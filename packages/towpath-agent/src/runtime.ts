import { randomUUID } from 'node:crypto';
import { Value } from 'typebox/value';
import type { TSchema } from 'typebox';
import {
  AgentError, TOOL_NAMES, type DomainTool, type SessionFactory, type Limits,
  type RunEvent, type Json, type Driver, type EventData, type BoundTool,
} from './contracts.js';

export interface RuntimeConfig {
  factory: SessionFactory; tools: DomainTool[]; limits?: Partial<Limits>;
  maxConcurrentRuns?: number; maxSessions?: number; sessionTtlMs?: number; now?: () => number;
}
export interface RunInput {
  /** Supplied by the authenticated host, never copied from a browser identity field. */
  ownerId: string; sessionId: string; revision: number; message: string;
  signal?: AbortSignal; onEvent(event: RunEvent): void;
}
export interface RunResult { runId: string; status: 'complete' | 'error'; code?: string }
export interface BrowserReply {
  ownerId: string; sessionId: string; runId: string; revision: number; taskId: string; result: Json;
}
interface PendingTask { schema: TSchema; resolve(data: Json): void; reject(error: unknown): void }
interface ActiveRun {
  id: string; revision: number; controller: AbortController; pending: Map<string, PendingTask>;
}
interface Session { ownerId: string; revision: number; expires: number; active?: ActiveRun }
export const DEFAULT_LIMITS: Readonly<Limits> = Object.freeze({
  deadlineMs: 60_000, maxModelCalls: 8, maxToolCalls: 20, maxOutputTokens: 2048,
  maxPayloadBytes: 65_536, maxEvents: 2000,
});
function positive(value: number): number {
  if (!Number.isSafeInteger(value) || value <= 0) throw new AgentError('invalid_request');
  return value;
}
function json(value: unknown, limit: number): Json {
  let serialized: string | undefined;
  try {
    serialized = JSON.stringify(value, (_key, item: unknown) => {
      if (item === undefined || typeof item === 'function' || typeof item === 'symbol'
        || typeof item === 'bigint' || (typeof item === 'number' && !Number.isFinite(item))) {
        throw new Error('Not JSON');
      }
      return item;
    });
  } catch { throw new AgentError('invalid_request'); }
  if (serialized === undefined) throw new AgentError('invalid_request');
  if (Buffer.byteLength(serialized) > limit) throw new AgentError('limit_exceeded');
  return JSON.parse(serialized) as Json;
}

/** In-memory application lifecycle; no credentials, graph state, or HTTP identity resolution. */
export class AgentRuntime {
  private readonly sessions = new Map<string, Session>();
  private running = 0;
  private readonly limits: Limits;
  private readonly maxConcurrent: number;
  private readonly maxSessions: number;
  private readonly ttl: number;
  private readonly now: () => number;
  private readonly tools: DomainTool[];

  constructor(private readonly config: RuntimeConfig) {
    this.limits = { ...DEFAULT_LIMITS, ...config.limits };
    Object.values(this.limits).forEach(positive);
    if (this.limits.deadlineMs > 2_147_483_647 || this.limits.maxEvents < 2) {
      throw new AgentError('invalid_request');
    }
    this.maxConcurrent = positive(config.maxConcurrentRuns ?? 2);
    this.maxSessions = positive(config.maxSessions ?? 100);
    this.ttl = positive(config.sessionTtlMs ?? 30 * 60_000);
    this.now = config.now ?? Date.now;
    const names = config.tools.map(t => t.name);
    if (new Set(names).size !== names.length || names.some(n => !TOOL_NAMES.includes(n))
      || config.tools.some(t => !('type' in t.parameters) || t.parameters.type !== 'object'
        || !('additionalProperties' in t.parameters) || t.parameters.additionalProperties !== false)) {
      throw new AgentError('invalid_tool_surface');
    }
    this.tools = config.tools.map(t => ({ ...t, parameters: structuredClone(t.parameters) }));
  }

  createSession(ownerId: string): { sessionId: string; revision: number } {
    if (typeof ownerId !== 'string' || !ownerId.trim() || ownerId.length > 256) {
      throw new AgentError('invalid_request');
    }
    for (const [id, s] of this.sessions) if (s.expires <= this.now()) this.remove(id, s);
    if (this.sessions.size >= this.maxSessions) throw new AgentError('capacity');
    const sessionId = randomUUID();
    this.sessions.set(sessionId, { ownerId, revision: 0, expires: this.now() + this.ttl });
    return { sessionId, revision: 0 };
  }

  private get(ownerId: string, id: string): Session {
    const s = this.sessions.get(id);
    if (s?.expires !== undefined && s.expires <= this.now()) this.remove(id, s);
    if (!s || s.ownerId !== ownerId || s.expires <= this.now()) throw new AgentError('not_found');
    return s;
  }

  private remove(id: string, s: Session): void {
    this.sessions.delete(id);
    s.active?.controller.abort(new AgentError('cancelled'));
  }

  deleteSession(ownerId: string, sessionId: string): void {
    this.remove(sessionId, this.get(ownerId, sessionId));
  }

  revise(ownerId: string, sessionId: string): number {
    const s = this.get(ownerId, sessionId);
    s.revision++;
    s.active?.controller.abort(new AgentError('stale_revision'));
    return s.revision;
  }

  cancel(ownerId: string, sessionId: string, runId: string): void {
    const s = this.get(ownerId, sessionId);
    if (s.active?.id !== runId) throw new AgentError('stale_result');
    s.active.controller.abort(new AgentError('cancelled'));
  }

  submitBrowserResult(reply: BrowserReply): void {
    const s = this.get(reply.ownerId, reply.sessionId);
    const run = s.active;
    if (!run || run.id !== reply.runId || run.revision !== reply.revision
      || s.revision !== reply.revision || run.controller.signal.aborted) {
      throw new AgentError('stale_result');
    }
    const task = run.pending.get(reply.taskId);
    if (!task) throw new AgentError('stale_result');
    const result = json(reply.result, this.limits.maxPayloadBytes);
    if (!Value.Check(task.schema, result)) throw new AgentError('invalid_request');
    run.pending.delete(reply.taskId);
    task.resolve(result);
  }

  async run(input: RunInput): Promise<RunResult> {
    const { ownerId, sessionId, revision, message, onEvent, signal: callerSignal } = input;
    const s = this.get(ownerId, sessionId);
    if (!Number.isSafeInteger(revision) || revision !== s.revision) throw new AgentError('stale_revision');
    if (typeof message !== 'string' || !message.trim()) throw new AgentError('invalid_request');
    json(message, this.limits.maxPayloadBytes);
    if (s.active) throw new AgentError('busy');
    if (this.running >= this.maxConcurrent) throw new AgentError('capacity');
    const run: ActiveRun = {
      id: randomUUID(), revision, controller: new AbortController(), pending: new Map(),
    };
    const { signal } = run.controller;
    s.active = run;
    this.running++;
    let sequence = 0, toolCalls = 0, outputBytes = 0;
    let driver: Driver | undefined;
    let abortStarted = false;
    const live = () => {
      signal.throwIfAborted();
      if (s.revision !== revision || this.sessions.get(sessionId) !== s) throw new AgentError('stale_result');
    };
    const bounded = (value: unknown): Json => {
      try { return json(value, this.limits.maxPayloadBytes); }
      catch (error) {
        if (error instanceof AgentError && error.code === 'limit_exceeded') run.controller.abort(error);
        throw error;
      }
    };
    const emit = (event: EventData, terminal = false) => {
      if (!terminal) {
        live();
        if (sequence >= this.limits.maxEvents - 1) {
          run.controller.abort(new AgentError('limit_exceeded'));
          signal.throwIfAborted();
        }
      }
      const data = bounded(event.data);
      if (!terminal) {
        outputBytes += Buffer.byteLength(JSON.stringify(data));
        if (outputBytes > this.limits.maxPayloadBytes) {
          run.controller.abort(new AgentError('limit_exceeded'));
          signal.throwIfAborted();
        }
      }
      onEvent({ ...event, data, sessionId, runId: run.id, revision, sequence: ++sequence });
    };
    const requestAbort = () => {
      if (driver && !abortStarted) {
        abortStarted = true;
        void driver.abort().catch(() => {});
      }
    };
    let rejectAbort!: (error: unknown) => void;
    const aborted = new Promise<never>((_resolve, reject) => { rejectAbort = reject; });
    const onAbort = () => {
      requestAbort();
      for (const task of run.pending.values()) task.reject(signal.reason);
      run.pending.clear();
      rejectAbort(signal.reason);
    };
    signal.addEventListener('abort', onAbort, { once: true });
    const callerAbort = () => run.controller.abort(new AgentError('cancelled'));
    callerSignal?.addEventListener('abort', callerAbort, { once: true });
    if (callerSignal?.aborted) callerAbort();
    const timer = setTimeout(() => run.controller.abort(new AgentError('deadline_exceeded')),
      Math.min(this.limits.deadlineMs, Math.max(1, s.expires - this.now())));

    const boundTools: BoundTool[] = this.tools.map(tool => ({
      name: tool.name, description: tool.description, parameters: tool.parameters,
      execute: async args => {
        live();
        if (++toolCalls > this.limits.maxToolCalls) {
          run.controller.abort(new AgentError('limit_exceeded'));
          signal.throwIfAborted();
        }
        const validated = bounded(args);
        if (!Value.Check(tool.parameters, validated)) throw new AgentError('invalid_tool_arguments');
        try {
          const data = await tool.execute(validated, {
            ownerId, sessionId, runId: run.id, revision, signal,
            publish: (type, data) => emit({ type, data }),
            requestBrowserTask: (task, responseSchema) => {
              live();
              const data = bounded(task);
              const taskId = randomUUID();
              const promise = new Promise<Json>((resolve, reject) => {
                run.pending.set(taskId, { schema: structuredClone(responseSchema), resolve, reject });
              });
              // Emission can abort and reject this promise before it is returned to the tool.
              void promise.catch(() => {});
              // Catch synchronously failing sinks without leaving an orphan promise.
              try { emit({ type: 'browser_task', data: { taskId, task: data } }); }
              catch (error) { run.pending.delete(taskId); throw error; }
              return promise;
            },
          });
          live();
          return bounded(data);
        } catch (error) {
          if (error instanceof AgentError) throw error;
          if (signal.aborted) throw signal.reason;
          throw new AgentError('tool_failed');
        }
      },
    }));
    // Keep capacity reserved until actual work settles, even when the caller has timed out.
    const work = (async () => {
      try {
        live();
        emit({ type: 'started', data: {} });
        driver = await this.config.factory({ tools: boundTools, limits: { ...this.limits }, signal,
          emit: event => {
            try { emit(event); }
            catch (error) { run.controller.abort(error instanceof AgentError ? error : new AgentError('internal_error')); }
          },
        });
        if (signal.aborted) requestAbort();
        live();
        await driver.prompt(message);
        live();
      } finally {
        try { driver?.dispose(); }
        finally {
          driver = undefined;
          if (s.active === run) s.active = undefined;
          this.running--;
        }
      }
    })();
    try {
      await Promise.race([work, aborted]);
      emit({ type: 'complete', data: {} }, true);
      return { runId: run.id, status: 'complete' };
    } catch (error) {
      const code = error instanceof AgentError ? error.code : 'internal_error';
      try { emit({ type: 'error', data: { code } }, true); } catch { /* disconnected sink */ }
      return { runId: run.id, status: 'error', code };
    } finally {
      clearTimeout(timer);
      callerSignal?.removeEventListener('abort', callerAbort);
      // Revoke captured tool contexts after any terminal outcome, including normal completion.
      run.controller.abort(new AgentError('stale_result'));
      signal.removeEventListener('abort', onAbort);
    }
  }
}
