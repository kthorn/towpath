import { writable, type Readable } from 'svelte/store';

import type { PlaceTextSearch } from '../google/textSearch';
import type { LandRoute, TransferRouter } from '../google/contracts';
import type { CanalCandidate, LatLon } from '../types';
import {
	checkedWalkingRoutes,
	checkWalkingAccess,
	type WalkingAccess,
} from './walking';

const TASK_TIMEOUT_MS = 20_000;
const TASK_MARGIN_MS = 250;
const MAX_DETAILED_ROUTES = 20;

export interface PlaceChoice {
	option_ref: string;
	name: string;
	locality: string | null;
	address?: string;
	coordinate: LatLon;
	source: 'osm' | 'google' | 'manual';
}

export interface PlaceState {
	status: string;
	options: PlaceChoice[];
	selected: PlaceChoice | null;
	access: WalkingAccess[];
	error: string;
}

export interface PlaceController extends Readable<PlaceState> {
	search(query: string): Promise<void>;
	searchGoogle(): Promise<void>;
	select(optionRef: string): Promise<void>;
	selectManual(coordinate: LatLon): Promise<void>;
	cancel(): Promise<void>;
	destroy(): void;
	walkingRoutes(candidateId: string, confirmed: boolean): Promise<{
		outward: LandRoute;
		return: LandRoute;
	}>;
}

export interface PlaceControllerOptions {
	textSearch: PlaceTextSearch;
	transferRouter: TransferRouter;
	fetchFn?: typeof fetch;
}

interface Session {
	id: string;
	token: string;
	expiresIn: number;
}

interface Operation {
	generation: number;
	signal: AbortSignal;
}

interface BrowserTask {
	task_id: string;
	run_id: string;
	digest: string;
	timeout_ms?: number;
	kind: 'search' | 'walking';
	payload: {
		query?: string;
		bounds?: { south: number; west: number; north: number; east: number };
		option_ref?: string;
		candidates?: CanalCandidate[];
	};
}

interface SessionResponse {
	run_id: string;
	status: string;
	option_ref?: string;
	task?: BrowserTask;
	osm?: {
		status: string;
		options?: Array<{
			option_ref: string;
			name: string;
			locality?: string | null;
			coordinate: LatLon;
			source?: 'osm';
		}>;
	};
	option_refs?: string[];
	transfers?: unknown[];
}

class ControllerError extends Error {
	readonly code?: string;

	constructor(code?: string) {
		super(code ?? 'place_service_unavailable');
		this.code = code;
	}
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return Boolean(value) && typeof value === 'object';
}

function isFiniteCoordinate(value: unknown): value is LatLon {
	return (
		isRecord(value) &&
		typeof value.lat === 'number' &&
		Number.isFinite(value.lat) &&
		typeof value.lon === 'number' &&
		Number.isFinite(value.lon)
	);
}

function safeError(error: unknown): string {
	const code = error instanceof ControllerError ? error.code : undefined;
	if (code === 'session_budget') return 'Place lookup limit reached.';
	if (code === 'session_unavailable' || code === 'task_expired') {
		return 'Place lookup session expired.';
	}
	if (code === 'invalid_coordinate') return 'That place coordinate is unavailable.';
	return 'Place lookup is unavailable.';
}

function randomOptionRef(prefix: string): string {
	const randomUuid = typeof crypto !== 'undefined' ? crypto.randomUUID?.() : undefined;
	if (randomUuid) return `${prefix}-${randomUuid}`;
	return `${prefix}-${Math.random().toString(36).slice(2)}-${Date.now().toString(36)}`;
}

function abortError(): DOMException {
	return new DOMException('Place operation aborted', 'AbortError');
}

function throwIfAborted(signal: AbortSignal): void {
	if (signal.aborted) throw abortError();
}

function bounded<T>(operation: () => Promise<T>, signal: AbortSignal, timeoutMs = TASK_TIMEOUT_MS): Promise<T> {
	throwIfAborted(signal);
	const timeout = Math.max(1, Math.min(TASK_TIMEOUT_MS, timeoutMs) - TASK_MARGIN_MS);
	return new Promise<T>((resolve, reject) => {
		let settled = false;
		const timer = setTimeout(() => finishReject(new ControllerError('task_expired')), timeout);
		const onAbort = () => finishReject(abortError());
		const cleanup = () => {
			clearTimeout(timer);
			signal.removeEventListener('abort', onAbort);
		};
		const finishResolve = (value: T) => {
			if (settled) return;
			settled = true;
			cleanup();
			resolve(value);
		};
		const finishReject = (error: unknown) => {
			if (settled) return;
			settled = true;
			cleanup();
			reject(error);
		};
		signal.addEventListener('abort', onAbort, { once: true });
		Promise.resolve().then(operation).then(finishResolve, finishReject);
	});
}

export function createPlaceController({
	textSearch,
	transferRouter,
	fetchFn = fetch,
}: PlaceControllerOptions): PlaceController {
	const initial: PlaceState = {
		status: 'idle',
		options: [],
		selected: null,
		access: [],
		error: '',
	};
	const store = writable<PlaceState>(initial);
	const choices = new Map<string, PlaceChoice>();
	let googleDetails = new Map<string, { id: string; address: string }>();
	let session: Session | undefined;
	let sessionPromise: Promise<Session> | undefined;
	let expiryTimer: ReturnType<typeof setTimeout> | undefined;
	let activeController: AbortController | undefined;
	let generation = 0;
	let destroyed = false;
	let cancelRequested = false;
	let detailedRoutesUsed = 0;
	let currentRunId = '';

	function update(patch: Partial<PlaceState>): void {
		store.update((current) => ({ ...current, ...patch }));
	}

	function clearProviderState(status: string, error = ''): void {
		choices.clear();
		googleDetails = new Map();
		update({ status, options: [], selected: null, access: [], error });
	}

	function isCurrent(operation: Operation): boolean {
		return !destroyed && operation.generation === generation;
	}

	function begin(status: string): Operation {
		activeController?.abort();
		activeController = new AbortController();
		generation += 1;
		update({ status, error: '' });
		return { generation, signal: activeController.signal };
	}

	async function jsonRequest<T>(
		path: string,
		init: RequestInit = {},
		signal?: AbortSignal,
	): Promise<T> {
		const headers = new Headers(init.headers);
		if (!headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
		if (session && !headers.has('Authorization')) headers.set('Authorization', `Bearer ${session.token}`);
		const requestController = new AbortController();
		const relayAbort = () => requestController.abort();
		signal?.addEventListener('abort', relayAbort, { once: true });
		let timer: ReturnType<typeof setTimeout> | undefined;
		const timeout = new Promise<never>((_, reject) => {
			timer = setTimeout(() => {
				requestController.abort();
				reject(new ControllerError());
			}, TASK_TIMEOUT_MS);
		});
		try {
			let response: Response;
			try {
				response = await Promise.race([
					fetchFn(path, { ...init, headers, signal: requestController.signal }),
					timeout,
				]);
			} catch (error) {
				if (signal?.aborted) throw abortError();
				throw error instanceof ControllerError ? error : new ControllerError();
			}
			if (!response.ok) {
				let code: string | undefined;
				try {
					const value = await Promise.race([
						response.json() as Promise<{ detail?: { code?: unknown } }>,
						timeout,
					]);
					if (typeof value.detail?.code === 'string') code = value.detail.code;
				} catch {
					// Keep provider and server payloads out of browser state.
				}
				throw new ControllerError(code);
			}
			return await Promise.race([response.json() as Promise<T>, timeout]);
		} catch (error) {
			if (signal?.aborted) throw abortError();
			throw error instanceof ControllerError ? error : new ControllerError();
		} finally {
			if (timer) clearTimeout(timer);
			signal?.removeEventListener('abort', relayAbort);
		}
	}

	async function deleteSession(value: Session): Promise<void> {
		try {
			await fetchFn(`/api/place-sessions/${value.id}`, {
				method: 'DELETE',
				headers: { Authorization: `Bearer ${value.token}` },
			});
		} catch {
			// Cancellation is local even when cleanup reaches an unavailable server.
		}
	}

	function scheduleExpiry(value: Session): void {
		if (expiryTimer) clearTimeout(expiryTimer);
		expiryTimer = setTimeout(() => {
			generation += 1;
			activeController?.abort();
			clearProviderState('expired', 'Place lookup session expired.');
			const expired = session;
			session = undefined;
			currentRunId = '';
			detailedRoutesUsed = 0;
			if (expired) void deleteSession(expired);
		}, Math.max(0, value.expiresIn * 1000));
	}

	function ensureSession(): Promise<Session> {
		if (session) return Promise.resolve(session);
		if (sessionPromise) return sessionPromise;
		sessionPromise = jsonRequest<{ session_id: string; token: string; expires_in: number }>(
			'/api/place-sessions',
			{ method: 'POST', body: '{}' },
		).then((value) => {
			if (
				!isRecord(value) ||
				typeof value.session_id !== 'string' ||
				typeof value.token !== 'string' ||
				typeof value.expires_in !== 'number' ||
				!Number.isFinite(value.expires_in)
			) {
				throw new ControllerError();
			}
			const created = { id: value.session_id, token: value.token, expiresIn: value.expires_in };
			session = created;
			detailedRoutesUsed = 0;
			scheduleExpiry(created);
			if (cancelRequested || destroyed) {
				session = undefined;
				void deleteSession(created);
			}
			return created;
		}).finally(() => {
			sessionPromise = undefined;
		});
		return sessionPromise;
	}

	function choicesFromOsm(value: SessionResponse['osm']): PlaceChoice[] {
		if (!value?.options) return [];
		return value.options.flatMap((option) => {
			if (
				typeof option.option_ref !== 'string' ||
				typeof option.name !== 'string' ||
				!isFiniteCoordinate(option.coordinate)
			) return [];
			const choice: PlaceChoice = {
				option_ref: option.option_ref,
				name: option.name,
				locality: option.locality ?? null,
				coordinate: option.coordinate,
				source: 'osm',
			};
			choices.set(choice.option_ref, choice);
			return [choice];
		});
	}

	function setOptions(options: PlaceChoice[]): void {
		update({ options, selected: null, access: [] });
	}

	async function postSearchTask(
		operation: Operation,
		task: BrowserTask,
		query: string,
		bounds: { south: number; west: number; north: number; east: number },
	): Promise<void> {
		let result: Awaited<ReturnType<PlaceTextSearch['search']>>;
		try {
			result = await bounded(() => textSearch.search(query, bounds), operation.signal, task.timeout_ms);
		} catch (error) {
			if (error instanceof DOMException && error.name === 'AbortError') throw error;
			result = { status: error instanceof ControllerError && error.code === 'task_expired' ? 'incomplete' : 'unavailable', places: [] };
		}
		if (!isCurrent(operation)) return;
		const refs: string[] = [];
		if (result.status === 'matches' || result.status === 'incomplete') {
			for (const place of result.places) {
				let ref = randomOptionRef('google');
				while (choices.has(ref)) ref = randomOptionRef('google');
				const choice: PlaceChoice = {
					option_ref: ref,
					name: place.name,
					locality: null,
					address: place.address,
					coordinate: place.coordinate,
					source: 'google',
				};
				choices.set(ref, choice);
				googleDetails.set(ref, { id: place.id, address: place.address });
				refs.push(ref);
			}
		}
		const response = await jsonRequest<SessionResponse>(
			`/api/place-sessions/${session?.id}/tasks/${task.task_id}/result`,
			{
				method: 'POST',
				body: JSON.stringify({ run_id: task.run_id, digest: task.digest, status: result.status, option_refs: refs }),
			},
			operation.signal,
		);
		if (!isCurrent(operation)) return;
		const options = refs.flatMap((ref) => {
			const choice = choices.get(ref);
			return choice ? [choice] : [];
		});
		setOptions(options);
		const status = response.status === 'ambiguous' ? 'ambiguous' : response.status || result.status;
		update({ status, error: status === 'unavailable' ? 'Place lookup is unavailable.' : '' });
	}

	async function processTask(operation: Operation, task: BrowserTask): Promise<void> {
		if (task.kind === 'search') {
			const query = task.payload.query;
			const bounds = task.payload.bounds;
			if (!query || !bounds) throw new ControllerError();
			await postSearchTask(operation, task, query, bounds);
			return;
		}
		await processWalkingTask(operation, task);
	}

	async function processWalkingTask(operation: Operation, task: BrowserTask): Promise<void> {
		const selected = task.payload.option_ref ? choices.get(task.payload.option_ref) : undefined;
		const candidates = task.payload.candidates;
		if (!selected || !candidates || !candidates.length) throw new ControllerError();
		let access: WalkingAccess[];
		let timedOut = false;
		const walkingController = new AbortController();
		const abortWalking = () => walkingController.abort();
		operation.signal.addEventListener('abort', abortWalking, { once: true });
		try {
			access = await bounded(
				() => checkWalkingAccess(selected.coordinate, candidates, transferRouter, { signal: walkingController.signal }),
				operation.signal,
				task.timeout_ms,
			);
		} catch (error) {
			if (error instanceof DOMException && error.name === 'AbortError') throw error;
			timedOut = error instanceof ControllerError && error.code === 'task_expired';
			walkingController.abort();
			access = [];
		} finally {
			operation.signal.removeEventListener('abort', abortWalking);
		}
		if (!isCurrent(operation)) return;
		const transfers = access.map((item) => ({
			candidate_id: item.candidate.candidate_id,
			outward: item.outward.available ? 'available' : 'unavailable',
			return: item.return.available ? 'available' : 'unavailable',
		}));
		const status = timedOut ? 'incomplete' : access.length ? 'complete' : 'unavailable';
		const response = await jsonRequest<SessionResponse>(
			`/api/place-sessions/${session?.id}/tasks/${task.task_id}/result`,
			{
				method: 'POST',
				body: JSON.stringify({ run_id: task.run_id, digest: task.digest, status, transfers }),
			},
			operation.signal,
		);
		if (!isCurrent(operation)) return;
		update({ access, status: response.status === 'complete' ? 'ready' : response.status || status });
	}

	async function selectWithOperation(operation: Operation, optionRef: string, coordinate?: LatLon): Promise<void> {
		const choice = choices.get(optionRef);
		if (!choice) throw new ControllerError('unknown_option');
		const body: { run_id: string; option_ref: string; coordinate?: LatLon } = {
			run_id: currentRunId,
			option_ref: optionRef,
		};
		if (choice.source === 'google' || choice.source === 'manual') body.coordinate = coordinate ?? choice.coordinate;
		const response = await jsonRequest<SessionResponse>(
			`/api/place-sessions/${session?.id}/select`,
			{ method: 'POST', body: JSON.stringify(body) },
			operation.signal,
		);
		if (!isCurrent(operation)) return;
		update({ selected: choice, access: [], status: response.task ? 'walking' : response.status });
		if (response.task) await processTask(operation, response.task);
	}

	async function search(query: string): Promise<void> {
		const operation = begin('searching');
		cancelRequested = false;
		clearProviderState('searching');
		try {
			await ensureSession();
			if (!isCurrent(operation) || !session) return;
			const response = await jsonRequest<SessionResponse>(
				`/api/place-sessions/${session.id}/resolve`,
				{ method: 'POST', body: JSON.stringify({ query }) },
				operation.signal,
			);
			if (!isCurrent(operation)) return;
			currentRunId = response.run_id;
			const options = choicesFromOsm(response.osm);
			if (response.status === 'resolved' && options.length === 1) {
				await selectWithOperation(operation, options[0].option_ref);
				return;
			}
			setOptions(options);
			if (response.task) {
				await processTask(operation, response.task);
				return;
			}
			update({ status: response.status });
		} catch (error) {
			if (isCurrent(operation) && !(error instanceof DOMException && error.name === 'AbortError')) {
				update({ status: 'error', error: safeError(error) });
			}
		}
	}

	async function searchGoogle(): Promise<void> {
		const operation = begin('searching');
		clearProviderState('searching');
		try {
			await ensureSession();
			if (!isCurrent(operation) || !session || !currentRunId) return;
			const response = await jsonRequest<SessionResponse>(
				`/api/place-sessions/${session.id}/google`,
				{ method: 'POST', body: JSON.stringify({ run_id: currentRunId }) },
				operation.signal,
			);
			if (!isCurrent(operation)) return;
			if (response.task) await processTask(operation, response.task);
		} catch (error) {
			if (isCurrent(operation) && !(error instanceof DOMException && error.name === 'AbortError')) {
				update({ status: 'error', error: safeError(error) });
			}
		}
	}

	async function select(optionRef: string): Promise<void> {
		const operation = begin('selecting');
		try {
			if (!session || !currentRunId) await ensureSession();
			if (!isCurrent(operation) || !session) return;
			await selectWithOperation(operation, optionRef);
		} catch (error) {
			if (isCurrent(operation) && !(error instanceof DOMException && error.name === 'AbortError')) {
				update({ status: 'error', error: safeError(error) });
			}
		}
	}

	async function selectManual(coordinate: LatLon): Promise<void> {
		const operation = begin('selecting');
		try {
			await ensureSession();
			if (!isCurrent(operation) || !session || !isFiniteCoordinate(coordinate)) return;
			const optionRef = randomOptionRef('manual');
			const manualBody: { coordinate: LatLon; run_id?: string } = { coordinate };
			if (currentRunId) manualBody.run_id = currentRunId;
			const response = await jsonRequest<SessionResponse>(
				`/api/place-sessions/${session.id}/manual`,
				{ method: 'POST', body: JSON.stringify(manualBody) },
				operation.signal,
			);
			if (!isCurrent(operation)) return;
			currentRunId = response.run_id;
			const serverOptionRef = response.option_ref ?? response.task?.payload.option_ref ?? optionRef;
			const choice: PlaceChoice = {
				option_ref: serverOptionRef,
				name: 'Selected coordinates',
				locality: null,
				coordinate,
				source: 'manual',
			};
			choices.set(serverOptionRef, choice);
			update({ selected: choice, options: [choice], access: [], status: response.task ? 'walking' : response.status });
			if (response.task) await processTask(operation, response.task);
		} catch (error) {
			if (isCurrent(operation) && !(error instanceof DOMException && error.name === 'AbortError')) {
				update({ status: 'error', error: safeError(error) });
			}
		}
	}

	async function cancel(): Promise<void> {
		cancelRequested = true;
		generation += 1;
		activeController?.abort();
		if (expiryTimer) clearTimeout(expiryTimer);
		const value = session;
		session = undefined;
		currentRunId = '';
		detailedRoutesUsed = 0;
		clearProviderState('cancelled');
		if (value) await deleteSession(value);
	}

	function destroy(): void {
		destroyed = true;
		void cancel();
		store.set({ status: 'cancelled', options: [], selected: null, access: [], error: '' });
	}

	async function walkingRoutes(candidateId: string, confirmed: boolean): Promise<{ outward: LandRoute; return: LandRoute }> {
		if (!confirmed) throw new Error('Walking access requires confirmation.');
		if (detailedRoutesUsed + 2 > MAX_DETAILED_ROUTES) throw new Error('Walking route limit reached.');
		const routeGeneration = generation;
		const routeSignal = activeController?.signal ?? new AbortController().signal;
		const selected = getSelected();
		const item = getAccess(candidateId);
		if (!selected || !item?.complete) throw new Error('A checked walking candidate is required.');
		detailedRoutesUsed += 2;
		try {
			const result = await checkedWalkingRoutes(selected.coordinate, item.candidate, transferRouter, { signal: routeSignal });
			if (destroyed || routeGeneration !== generation || routeSignal.aborted) throw abortError();
			return result;
		} catch (error) {
			if (error instanceof DOMException && error.name === 'AbortError') throw error;
			throw new Error('Walking route unavailable.');
		}
	}

	function getSelected(): PlaceChoice | null {
		let selected: PlaceChoice | null = null;
		const unsubscribe = store.subscribe((value) => { selected = value.selected; });
		unsubscribe();
		return selected;
	}

	function getAccess(candidateId: string): WalkingAccess | undefined {
		let result: WalkingAccess | undefined;
		const unsubscribe = store.subscribe((value) => { result = value.access.find((item) => item.candidate.candidate_id === candidateId); });
		unsubscribe();
		return result;
	}

	return Object.assign(store, {
		search,
		searchGoogle,
		select,
		selectManual,
		cancel,
		destroy,
		walkingRoutes,
	});
}
