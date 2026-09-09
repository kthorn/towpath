import type { CanalCandidate, LatLon } from '../types';
import type { LandRoute, TransferResult, TransferRouter } from '../google/contracts';

const MAX_CANDIDATES = 5;
const MAX_CONCURRENT_REVERSE_CHECKS = 2;
const DEFAULT_CALL_TIMEOUT_MS = 20_000;
const OVERALL_TIMEOUT_MS = 60_000;
const MAX_ROUTE_POINTS = 10_000;
const WALK_MODE = 'WALK' as const;

const UNAVAILABLE_REASON = 'UNAVAILABLE';
const INVALID_RESULT_REASON = 'INVALID_RESULT';
const TIMEOUT_REASON = 'TIMEOUT';

export interface WalkingAccess {
  candidate: CanalCandidate;
  /** The directed walk from the canal candidate to the attraction. */
  outward: TransferResult;
  /** The directed walk from the attraction back to the canal candidate. */
  return: TransferResult;
  complete: boolean;
}

export interface WalkingOptions {
  signal?: AbortSignal;
  timeoutMs?: number;
}

interface DeadlineOptions {
  signal?: AbortSignal;
  callTimeoutMs: number;
  deadline: number;
}

type CallOutcome<T> =
  | { kind: 'value'; value: T }
  | { kind: 'error' }
  | { kind: 'timeout' };

function isFiniteCoordinate(coordinate: LatLon): boolean {
  return (
    coordinate !== null &&
    typeof coordinate === 'object' &&
    Number.isFinite(coordinate.lat) &&
    Number.isFinite(coordinate.lon) &&
    Math.abs(coordinate.lat) <= 90 &&
    Math.abs(coordinate.lon) <= 180
  );
}

function validateTimeout(timeoutMs: number | undefined): number {
  const timeout = timeoutMs ?? DEFAULT_CALL_TIMEOUT_MS;
  if (!Number.isFinite(timeout) || timeout <= 0) {
    throw new TypeError('timeoutMs must be a finite number greater than zero');
  }
  return timeout;
}

function validateInputs(attraction: LatLon, candidates: CanalCandidate[]): void {
  if (!isFiniteCoordinate(attraction)) throw new TypeError('attraction coordinate is invalid');
  const identities = new Set<string>();
  for (const candidate of candidates) {
    if (!candidate || typeof candidate.candidate_id !== 'string') {
      throw new TypeError('candidate_id is invalid');
    }
    if (identities.has(candidate.candidate_id)) throw new TypeError('candidate_id values must be unique');
    identities.add(candidate.candidate_id);
    if (!isFiniteCoordinate(candidate.coordinate)) {
      throw new TypeError(`candidate ${candidate.candidate_id} coordinate is invalid`);
    }
  }
}

function abortError(): DOMException {
  return new DOMException('Walking request was aborted', 'AbortError');
}

function throwIfAborted(signal: AbortSignal | undefined): void {
  if (signal?.aborted) throw abortError();
}

function unavailable(reason = UNAVAILABLE_REASON): TransferResult {
  return { available: false, reason };
}

function validTransferResult(result: unknown): result is TransferResult {
  if (!result || typeof result !== 'object') return false;
  const value = result as Partial<TransferResult>;
  if (value.available === false) return true;
  return (
    value.available === true &&
    typeof value.durationSeconds === 'number' &&
    Number.isFinite(value.durationSeconds) &&
    value.durationSeconds >= 0 &&
    typeof value.distanceMeters === 'number' &&
    Number.isFinite(value.distanceMeters) &&
    value.distanceMeters >= 0
  );
}

function sanitizeTransferResult(result: unknown): TransferResult {
  if (!validTransferResult(result)) return unavailable(INVALID_RESULT_REASON);
  if (result.available === false) return unavailable();
  return {
    available: true,
    durationSeconds: result.durationSeconds,
    distanceMeters: result.distanceMeters,
  };
}

function callWithDeadline<T>(operation: () => Promise<T>, options: DeadlineOptions): Promise<CallOutcome<T>> {
  throwIfAborted(options.signal);
  const remaining = Math.min(options.callTimeoutMs, options.deadline - Date.now());
  if (remaining <= 0) return Promise.resolve({ kind: 'timeout' });

  return new Promise<CallOutcome<T>>((resolve, reject) => {
    let settled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const cleanup = () => {
      if (timer !== undefined) clearTimeout(timer);
      options.signal?.removeEventListener('abort', onAbort);
    };
    const finish = (outcome: CallOutcome<T>) => {
      if (settled) return;
      settled = true;
      cleanup();
      resolve(outcome);
    };
    const onAbort = () => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(abortError());
    };

    timer = setTimeout(() => finish({ kind: 'timeout' }), remaining);
    options.signal?.addEventListener('abort', onAbort, { once: true });
    Promise.resolve()
      .then(() => {
        if (settled) return undefined as T;
        throwIfAborted(options.signal);
        return operation();
      })
      .then(
        (value) => finish({ kind: 'value', value }),
        () => finish({ kind: 'error' }),
      );
  });
}

async function matrixResult(
  router: TransferRouter,
  origin: LatLon,
  destinations: LatLon[],
  options: DeadlineOptions,
): Promise<TransferResult[] | null> {
  const outcome = await callWithDeadline(() => router.matrix(origin, destinations, WALK_MODE), options);
  if (outcome.kind !== 'value' || !Array.isArray(outcome.value)) return null;
  return outcome.value;
}

function resultForMatrix(results: TransferResult[] | null, index: number): TransferResult {
  if (!results || index >= results.length) return unavailable();
  return sanitizeTransferResult(results[index]);
}

export async function checkWalkingAccess(
  attraction: LatLon,
  candidates: CanalCandidate[],
  router: TransferRouter,
  options: WalkingOptions = {},
): Promise<WalkingAccess[]> {
  const selected = candidates.slice(0, MAX_CANDIDATES);
  validateInputs(attraction, selected);
  const callTimeoutMs = validateTimeout(options.timeoutMs);
  throwIfAborted(options.signal);
  if (selected.length === 0) return [];

  const deadline = Date.now() + OVERALL_TIMEOUT_MS;
  const callOptions: DeadlineOptions = { signal: options.signal, callTimeoutMs, deadline };
  const inboundResults = await matrixResult(
    router,
    attraction,
    selected.map((candidate) => candidate.coordinate),
    callOptions,
  );
  throwIfAborted(options.signal);

  const outward = new Array<TransferResult>(selected.length);
  let nextIndex = 0;
  const checkNext = async (): Promise<void> => {
    while (true) {
      throwIfAborted(options.signal);
      const index = nextIndex++;
      if (index >= selected.length) return;
      if (Date.now() >= deadline) {
        outward[index] = unavailable(TIMEOUT_REASON);
        continue;
      }
      const candidate = selected[index];
      const outcome = await matrixResult(router, candidate.coordinate, [attraction], callOptions);
      outward[index] =
        outcome === null ? unavailable() : resultForMatrix(outcome, 0);
    }
  };

  await Promise.all(
    Array.from(
      { length: Math.min(MAX_CONCURRENT_REVERSE_CHECKS, selected.length) },
      () => checkNext(),
    ),
  );

  return selected
    .map((candidate, index) => {
      const outwardResult = outward[index] ?? unavailable(TIMEOUT_REASON);
      const returnResult = resultForMatrix(inboundResults, index);
      const complete = outwardResult.available && returnResult.available;
      return { candidate, outward: outwardResult, return: returnResult, complete };
    })
    .sort((left, right) => {
      if (left.complete !== right.complete) return left.complete ? -1 : 1;
      if (left.complete && right.complete) {
        const leftTotal = left.outward.available && left.return.available
          ? left.outward.durationSeconds + left.return.durationSeconds
          : 0;
        const rightTotal = right.outward.available && right.return.available
          ? right.outward.durationSeconds + right.return.durationSeconds
          : 0;
        const durationDifference = leftTotal - rightTotal;
        if (durationDifference !== 0) return durationDifference;
        if (left.candidate.candidate_id < right.candidate.candidate_id) return -1;
        if (left.candidate.candidate_id > right.candidate.candidate_id) return 1;
      }
      return 0;
    });
}

function validLandRoute(route: unknown): route is LandRoute {
  if (!route || typeof route !== 'object') return false;
  const value = route as Partial<LandRoute>;
  return (
    Array.isArray(value.path) &&
    value.path.length <= MAX_ROUTE_POINTS &&
    value.path.length > 0 &&
    value.path.every((point) => isFiniteCoordinate(point)) &&
    typeof value.durationSeconds === 'number' &&
    Number.isFinite(value.durationSeconds) &&
    value.durationSeconds >= 0 &&
    typeof value.distanceMeters === 'number' &&
    Number.isFinite(value.distanceMeters) &&
    value.distanceMeters >= 0
  );
}

async function detailedRoute(
  router: TransferRouter,
  origin: LatLon,
  destination: LatLon,
  options: DeadlineOptions,
): Promise<LandRoute> {
  const outcome = await callWithDeadline(() => router.route(origin, destination, WALK_MODE), options);
  if (outcome.kind !== 'value' || !validLandRoute(outcome.value)) {
    throw new Error('Walking route unavailable');
  }
  return outcome.value;
}

export async function checkedWalkingRoutes(
  attraction: LatLon,
  candidate: CanalCandidate,
  router: TransferRouter,
  options: WalkingOptions = {},
): Promise<{ outward: LandRoute; return: LandRoute }> {
  validateInputs(attraction, [candidate]);
  const callTimeoutMs = validateTimeout(options.timeoutMs);
  throwIfAborted(options.signal);
  const callOptions: DeadlineOptions = {
    signal: options.signal,
    callTimeoutMs,
    deadline: Date.now() + OVERALL_TIMEOUT_MS,
  };
  const [outward, inbound] = await Promise.all([
    detailedRoute(router, candidate.coordinate, attraction, callOptions),
    detailedRoute(router, attraction, candidate.coordinate, callOptions),
  ]);
  return { outward, return: inbound };
}
