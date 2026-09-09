import { Type } from 'typebox';
import { AgentError, type DomainTool, type Json, type ToolName } from './contracts.js';

export type PoundCall = (path: string, body: Json | undefined, signal: AbortSignal,
  options?: { token?: string; method?: string }) => Promise<Json>;
export type Trace = (data: Json) => void;
const obj = (value: unknown): Record<string, Json> => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new AgentError('tool_failed');
  return value as Record<string, Json>;
};
const list = (value: Json | undefined): Json[] => Array.isArray(value) ? value : [];
const ref = Type.String({ minLength: 1, maxLength: 256 });
const schedule = {
  days: Type.Integer({ minimum: 1, maximum: 28 }),
  hours_per_day: Type.Number({ minimum: 1, maximum: 12 }),
  boat_length_m: Type.Optional(Type.Number({ exclusiveMinimum: 0 })),
  boat_beam_m: Type.Optional(Type.Number({ exclusiveMinimum: 0 })),
  boat_draft_m: Type.Optional(Type.Number({ exclusiveMinimum: 0 })),
  boat_height_m: Type.Optional(Type.Number({ exclusiveMinimum: 0 })),
};
function summary(value: Json | undefined): Json {
  const route = obj(value);
  return Object.fromEntries(['start', 'end', 'total_km', 'total_locks', 'total_minutes',
    'is_ring', 'warnings', 'graph_source_date'].filter(k => k in route).map(k => [k, route[k]!])) as Json;
}

/** Conversation-local references. No arbitrary coordinates, graph handles, or URLs from the model. */
class PoundApiError extends Error {
  constructor(readonly result: Json) { super('pound_api_error'); }
}
export function createLabTools(request: PoundCall, trace: Trace): DomainTool[] {
  const call: PoundCall = async (...args) => {
    if (args[0] !== '/api/place-sessions' && args[3]?.method !== 'DELETE') {
      trace({ type: 'api_request', path: args[0], body: args[1] ?? null });
    }
    const result = await request(...args);
    if (obj(result).error) throw new PoundApiError(result);
    return result;
  };
  const places = new Map<string, Json>();
  const candidates = new Map<string, { revision: string; handle: Json }>();
  function remember<T>(map: Map<string, T>, key: string, value: T) {
    if (!map.has(key) && map.size >= 200) throw new AgentError('limit_exceeded');
    map.set(key, value);
  }
  function candidate(key: Json | undefined) {
    const found = typeof key === 'string' && candidates.get(key);
    if (!found) throw new AgentError('invalid_tool_arguments');
    return found;
  }
  function tool(name: ToolName, description: string, properties: Parameters<typeof Type.Object>[0],
    execute: (args: Record<string, Json>, signal: AbortSignal) => Promise<Json>): DomainTool {
    return { name, description, parameters: Type.Object(properties, { additionalProperties: false }),
      async execute(args, ctx) {
        trace({ type: 'tool_request', tool: name, arguments: args as Json });
        let result: Json;
        try { result = await execute(obj(args), ctx.signal); }
        catch (error) {
          if (!(error instanceof PoundApiError)) {
            trace({ type: 'tool_error', tool: name, code: error instanceof AgentError ? error.code : 'pound_unavailable' });
            throw error;
          }
          result = error.result;
        }
        ctx.signal.throwIfAborted();
        trace({ type: 'tool_result', tool: name, result });
        return result;
      } };
  }
  return [
    tool('resolve_place', 'Search the real OSM catalog by name. Returns sourced place refs; '
      + 'ask the user to choose when ambiguous. No Google fallback in this lab.',
    { query: Type.String({ minLength: 1, maxLength: 200 }) }, async (args, signal) => {
      const session = obj(await call('/api/place-sessions', {}, signal));
      const path = `/api/place-sessions/${encodeURIComponent(String(session.session_id))}`;
      const token = String(session.token);
      try {
        const result = obj(await call(`${path}/resolve`, args, signal, { token }));
        signal.throwIfAborted();
        const osm = obj(result.osm);
        for (const item of list(osm.options)) {
          const place = obj(item);
          remember(places, String(place.option_ref), place.coordinate!);
        }
        return osm;
      } finally {
        await call(path, undefined, AbortSignal.timeout(3000), { token, method: 'DELETE' }).catch(() => {});
      }
    }),
    tool('get_canal_access_options', 'Get geometric canal candidates for a resolved place_ref. '
      + 'These are unverified access points, not checked walking routes or moorings. '
      + 'Use an option_ref from resolve_place; ask the user to choose material alternatives.',
    { place_ref: ref }, async (args, signal) => {
      const coordinate = places.get(String(args.place_ref));
      if (!coordinate) throw new AgentError('invalid_tool_arguments');
      const result = obj(await call('/api/canal-candidates', coordinate, signal));
      signal.throwIfAborted();
      for (const value of list(result.candidates)) {
        const item = obj(value);
        remember(candidates, String(item.candidate_id), {
          revision: String(result.artifact_revision), handle: item.handle!,
        });
      }
      return { ...result, access_basis: 'geometric_unconfirmed', walking: 'not_checked' };
    }),
    ...(['plan_canal_route', 'plan_out_and_back'] as const).map(name => tool(name,
      name === 'plan_canal_route'
        ? 'Preview a point-to-point route using two issued candidate refs and explicit schedule. '
          + 'Never adopt a route; missing boat dimensions stay unknown.'
        : 'Preview out-and-back alternatives from one issued start candidate, optionally visiting '
          + 'a waypoint candidate. This does not compare hire bases or find rings. '
          + 'Ask for schedule and candidate choices first. Results may be a bounded shortlist.',
      { start_ref: ref, ...(name === 'plan_canal_route' ? { end_ref: ref }
        : { waypoint_ref: Type.Optional(ref) }), ...schedule }, async (args, signal): Promise<Json> => {
        const start = candidate(args.start_ref);
        const body: Record<string, Json> = { artifact_revision: start.revision, start: start.handle };
        for (const key of Object.keys(schedule)) if (args[key] !== undefined) body[key] = args[key]!;
        for (const key of ['end', 'waypoint']) if (args[`${key}_ref`] !== undefined) {
          const other = candidate(args[`${key}_ref`]);
          if (other.revision !== start.revision) throw new AgentError('stale_revision');
          body[key] = other.handle;
        }
        const path = name === 'plan_canal_route' ? '/api/canal-route' : '/api/turnaround-candidates';
        const result = obj(await call(path, body, signal));
        if (name === 'plan_canal_route') return { preview_only: true, route: summary(result.route) };
        const routes = list(result.routes);
        return { preview_only: true, artifact_revision: result.artifact_revision!,
          default_route_id: result.default_route_id!, total_options: routes.length,
          shown_options: Math.min(routes.length, 5), truncated: routes.length > 5,
          routes: routes.slice(0, 5).map(value => {
            const route = obj(value);
            return { route_id: route.route_id!, turnaround: route.turnaround!, budget: route.budget!,
              route: summary(obj(route.journey).route) };
          }), rejections: list(result.rejections).slice(0, 5) };
      })),
  ];
}

export function createPoundClient(base: string): PoundCall {
  const url = new URL(base);
  if (url.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)
    || url.username || url.password || url.pathname !== '/' || url.search || url.hash) {
    throw new Error('POUND_API_URL must be a loopback HTTP origin, for example http://127.0.0.1:8000');
  }
  return async (path, body, signal, options = {}) => {
    const target = new URL(path, url);
    if (target.origin !== url.origin) throw new AgentError('invalid_request');
    const response = await fetch(target, {
      method: options.method ?? 'POST', redirect: 'error',
      headers: { 'content-type': 'application/json',
        ...(options.token ? { authorization: `Bearer ${options.token}` } : {}) },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.any([signal, AbortSignal.timeout(30_000)]),
    });
    const reader = response.body!.getReader();
    let text = '';
    let bytes = 0;
    const decoder = new TextDecoder();
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        bytes += value.byteLength;
        if (bytes > 8 * 1024 * 1024) throw new AgentError('limit_exceeded');
        text += decoder.decode(value, { stream: true });
      }
      text += decoder.decode();
    } finally { await reader.cancel(); }
    if (!response.ok) {
      // Keep API status/code observable without leaking arbitrary response bodies into logs.
      let code = 'pound_error';
      try { code = String(obj(obj(JSON.parse(text)).detail).code ?? code); } catch {}
      return { error: { status: response.status, code }, path };
    }
    return text ? JSON.parse(text) as Json : {};
  };
}
