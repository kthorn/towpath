import { Type } from 'typebox';
import { resolveKindSchema, createApiTools } from './lab-api-tools.js';
import { AgentError, type DomainTool, type Json, type ToolName } from './contracts.js';

export type PoundCall = (path: string, body: Json | undefined, signal: AbortSignal,
  options?: { token?: string; method?: string }) => Promise<Json>;
export type Trace = (data: Json) => void;
const obj = (value: unknown): Record<string, Json> => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new AgentError('tool_failed');
  return value as Record<string, Json>;
};
const list = (value: Json | undefined): Json[] => Array.isArray(value) ? value : [];
const ref = Type.String({ minLength: 1, maxLength: 256,
  description: 'An issued canal candidate_id or hire start_ref, never an OSM place option_ref.' });
const placeRef = Type.String({ minLength: 1, maxLength: 256,
  description: 'An OSM option_ref returned by resolve_place.' });
const hireSearch = {
  place_ref: placeRef,
  offset: Type.Optional(Type.Integer({ minimum: 0, maximum: 1000, description: 'Use next_offset from an earlier result to inspect more bases.' })),
  radius_km: Type.Optional(Type.Number({ minimum: 1, maximum: 250,
    description: 'Straight-line search radius, default 100 km; proximity is not route feasibility.' })),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 6,
    description: 'Maximum nearby bases to inspect, default 6. This is a shortlist, not exhaustive.' })),
};
const schedule = {
  days: Type.Integer({ minimum: 1, maximum: 28 }),
  hours_per_day: Type.Number({ minimum: 1, maximum: 12 }),
  movable_bridge_delay_min: Type.Optional(Type.Number({ minimum: 0, maximum: 60 })),
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
  const previews = new Map<string, { revision: string; journey: Json; path: string; body: Json }>();
  let nextPreview = 0;
  function preview(key: Json | undefined) {
    const found = typeof key === 'string' && previews.get(key);
    if (!found) throw new AgentError('invalid_tool_arguments');
    return found;
  }
  function storePreview(journey: Json, revision: string, path: string, body: Json) {
    // Bound geometry retained outside model context; older preview refs expire explicitly.
    const key = `preview:${++nextPreview}`;
    previews.set(key, { revision, journey, path, body });
    while (previews.size > 12 || Buffer.byteLength(JSON.stringify([...previews])) > 64 * 1024 * 1024) {
      previews.delete(previews.keys().next().value!);
    }
    if (!previews.has(key)) throw new AgentError('limit_exceeded');
    return key;
  }
  function roundTripPreview(route: Record<string, Json>, revision: string,
    body: Record<string, Json>, requestId: Json | undefined) {
    return storePreview(route.journey!, revision, '/api/out-and-back-route', {
      ...body, request_id: requestId ?? route.request_id ?? null, route_id: route.route_id!,
    });
  }
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
  async function hireBases(args: Record<string, Json>, signal: AbortSignal,
    target?: { revision: string; handle: Json }) {
    const coordinate = places.get(String(args.place_ref));
    if (!coordinate) throw new AgentError('invalid_tool_arguments');
    const radius = args.radius_km ?? 100;
    const body: Record<string, Json> = { ...obj(coordinate), limit: args.limit ?? 6,
      offset: args.offset ?? 0 };
    if (target) {
      body.target = target.handle;
      body.artifact_revision = target.revision;
      for (const key of Object.keys(schedule)) if (args[key] !== undefined) body[key] = args[key]!;
    } else body.radius_km = radius;
    const result = obj(await call('/api/hire-bases', body, signal));
    const revision = String(result.artifact_revision);
    const bases = list(result.bases).map(value => {
      const { handle, ...base } = obj(value);
      if (!handle || typeof base.base_ref !== 'string') throw new AgentError('tool_failed');
      const startRef = `hire:${base.base_ref}`;
      remember(candidates, startRef, { revision, handle });
      return { ...base, start_ref: startRef };
    });
    return { artifact_revision: revision, radius_km: target ? null : radius,
      budget_minutes: result.budget_minutes ?? null, cutoff_minutes: result.cutoff_minutes ?? null,
      search_basis: result.ranking_basis ?? (target ? 'canal_travel_time' : 'straight_line_distance'),
      next_offset: result.next_offset ?? null,
      total_matches: result.total_matches ?? bases.length, truncated: result.truncated ?? false,
      bases, source: 'curated_published_hire_bases', availability: 'not_checked', prices: 'not_checked',
      operator_basis: 'published_source_provider_not_verified_operating_company' };
  }
  return [
    tool('resolve_place', 'Search OSM attraction/amenity names, not addresses or cities. Use the place name alone '
      + '(e.g. Bletchley Park), without appending town/county. Failed comma-qualified queries retry the name once, retaining the locality as an unverified hint. Returns sourced place refs; choose among nearby same-attraction matches. City-name matches may be attractions, not the city itself. No Google fallback.',
    { query: Type.String({ minLength: 1, maxLength: 200 }),
      kinds: Type.Optional(Type.Array(resolveKindSchema,
        { minItems: 1, maxItems: 16, description: 'Optional catalog kinds such as museum, historic_site, pub, marina. Defaults to attractions.' })) }, async (args, signal) => {
      const session = obj(await call('/api/place-sessions', {}, signal));
      const path = `/api/place-sessions/${encodeURIComponent(String(session.session_id))}`;
      const token = String(session.token);
      try {
        const result = obj(await call(`${path}/resolve`, args, signal, { token }));
        signal.throwIfAborted();
        let osm = obj(result.osm);
        const query = String(args.query);
        const comma = query.indexOf(',');
        const name = comma > 0 ? query.slice(0, comma).trim() : '';
        if (osm.status === 'not_found' && osm.reason === 'no_match' && name) {
          const retried = obj(await call(`${path}/resolve`, { ...args, query: name }, signal, { token }));
          osm = { ...obj(retried.osm), requested_query: query, lookup_query: name,
            locality_hint: query.slice(comma + 1).trim(), locality_verified: false };
        }
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
      + 'Use an option_ref from resolve_place; choose a suitable nearby named canal candidate for a provisional preview.',
    { place_ref: Type.String({ minLength: 1, maxLength: 256,
      description: 'An OSM option_ref returned by resolve_place.' }) }, async (args, signal) => {
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
    tool('find_hire_bases', 'Find published boat-hire bases and their source providers near a resolved '
      + 'attraction. Returns source links and issued start_ref values from the API validated base '
      + 'anchors, ordered by straight-line proximity. It does not establish canal reachability, '
      + 'prices, availability or the actual operating rental company. Use find_hire_trip_options '
      + 'for complete itineraries, or find_reachable_hire_bases for budgeted departure-base searches.', hireSearch, hireBases),
    tool('find_reachable_hire_bases', 'Find departure bases that can reach an attraction canal waypoint '
      + 'and return within the cruising budget. Use this for questions about where to hire/depart '
      + 'from, including week-long trips. Searches all published base anchors by canal travel time, '
      + 'allowing half the full budget in each direction, with no geographic-radius prefilter. '
      + 'Returns base/provider names, source links and directional travel times. This answers base '
      + 'reachability without computing a full itinerary or verifying a turnaround. Stop and '
      + 'present these results when the user asks for bases; do not automatically try trip previews. '
      + 'Use next_offset only when non-null. Prices, availability and walking access are unknown.',
    { place_ref: placeRef, waypoint_ref: ref, limit: hireSearch.limit, offset: hireSearch.offset, ...schedule },
    async (args, signal): Promise<Json> => {
      const waypoint = candidate(args.waypoint_ref);
      const search = await hireBases(args, signal, waypoint);
      if (search.artifact_revision !== waypoint.revision) throw new AgentError('stale_revision');
      return { ...search, itinerary: 'not_computed', turnaround: 'not_checked',
        walking: 'not_checked', boat_fit: 'not_verified' };
    }),
    tool('find_hire_trip_options', 'Compare out-and-back trip previews from up to six reachable published '
      + 'hire bases via the attraction canal waypoint. Supply place_ref from resolve_place and '
      + 'waypoint_ref from get_canal_access_options for that attraction. Uses real base anchors and '
      + 'routing. Searches all published bases on the connected canal network, keeps those within '
      + 'half the full cruising budget in each direction, then checks full out-and-back previews. '
      + 'No geographical-radius prefilter. Use next_offset to inspect more reachable bases. '
      + 'Compares each base API-recommended turnaround, not every possible '
      + 'trip or operator. Use 3 days at 6 hours/day when schedule is unspecified. Returns source '
      + 'links, route facts and rejection reasons; prices and availability are unknown. For base-only '
      + 'questions use find_reachable_hire_bases. A rejection already includes the underlying '
      + 'out-and-back check: do not retry plan_out_and_back with the same base, waypoint and constraints.',
    { place_ref: placeRef, limit: hireSearch.limit, offset: hireSearch.offset, waypoint_ref: ref, ...schedule }, async (args, signal): Promise<Json> => {
      const waypoint = candidate(args.waypoint_ref);
      const search = await hireBases(args, signal, waypoint);
      if (search.artifact_revision !== waypoint.revision) throw new AgentError('stale_revision');
      const options: Record<string, Json>[] = [];
      const rejections: Json[] = [];
      for (const base of search.bases) {
        signal.throwIfAborted();
        const start = candidate(base.start_ref);
        const body: Record<string, Json> = { artifact_revision: start.revision,
          start: start.handle, waypoint: waypoint.handle };
        for (const key of Object.keys(schedule)) if (args[key] !== undefined) body[key] = args[key]!;
        let result: Record<string, Json>;
        try { result = obj(await call('/api/turnaround-candidates', body, signal)); }
        catch (error) {
          if (!(error instanceof PoundApiError)) throw error;
          rejections.push({ base, error: obj(error.result).error ?? error.result });
          continue;
        }
        const routes = list(result.routes).map(obj);
        const chosen = routes.find(route => route.route_id === result.default_route_id);
        if (!chosen) {
          rejections.push({ base, code: 'no_route_returned', rejections: list(result.rejections).slice(0, 3) });
          continue;
        }
        if (result.artifact_revision !== waypoint.revision) throw new AgentError('stale_revision');
        const previewRef = roundTripPreview(chosen, waypoint.revision, body, result.request_id);
        options.push({ base, preview_ref: previewRef, start_ref: base.start_ref, waypoint_ref: args.waypoint_ref!,
          route_id: chosen.route_id!, turnaround: chosen.turnaround!, budget: chosen.budget!,
          route: summary(obj(chosen.journey).route) });
      }
      options.sort((a, b) => Number(obj(b.route).total_km) - Number(obj(a.route).total_km));
      return { ...search, bases: search.bases, tested_bases: search.bases.length,
        preview_only: true, options, rejections, walking: 'not_checked', boat_fit: 'not_verified',
        ranking_basis: 'distance_descending_among_api_recommended_routes_for_checked_bases' };
    }),
    tool('get_trip_option', 'Inspect a previously issued preview_ref. Replays its exact stored route '
      + 'selection and constraints against the current API, returning daily plans and route details '
      + 'without geometry. This is still a preview, not route adoption. Changed schedules must use '
      + 'a planning tool, not this inspection tool.',
    { preview_ref: Type.String({ minLength: 1, maxLength: 256 }) }, async (args, signal): Promise<Json> => {
      const stored = preview(args.preview_ref);
      if (stored.path === '/api/out-and-back-route' && !obj(stored.body).request_id) {
        throw new AgentError('invalid_tool_arguments');
      }
      const result = obj(await call(stored.path, stored.body, signal));
      const journey = stored.path === '/api/out-and-back-route' ? obj(result.journey) : result;
      stored.journey = journey;
      previews.delete(String(args.preview_ref));
      previews.set(String(args.preview_ref), stored);
      while (Buffer.byteLength(JSON.stringify([...previews])) > 64 * 1024 * 1024) {
        previews.delete(previews.keys().next().value!);
      }
      const route = obj(journey.route);
      const days = list(route.days);
      const legs = list(route.legs);
      return { preview_ref: args.preview_ref!, preview_only: true, artifact_revision: stored.revision,
        route: summary(route),
        days: days.slice(0, 28).map(value => {
          const day = obj(value);
          return { day: day.day!, cruising_minutes: day.cruising_minutes!, end_near: day.end_near ?? null,
            leg_count: list(day.legs).length };
        }), legs: legs.slice(0, 50), total_legs: legs.length, truncated: days.length > 28 || legs.length > 50,
        ...(result.turnaround ? { turnaround: result.turnaround, budget: result.budget! } : {}) };
    }),
    ...createApiTools({ tool, call, preview,
      place: key => {
        const coordinate = typeof key === 'string' && places.get(key);
        if (!coordinate) throw new AgentError('invalid_tool_arguments');
        return coordinate;
      },
      rememberPlace: (id, coordinate) => remember(places, id, coordinate),
    }),
    ...(['plan_canal_route', 'plan_out_and_back'] as const).map(name => tool(name,
      name === 'plan_canal_route'
        ? 'Preview a point-to-point route using two issued candidate refs and a schedule (default 3 days, 6 hours/day if unspecified). '
          + 'Never adopt a route; missing boat dimensions stay unknown.'
        : 'Preview out-and-back alternatives from one issued start candidate, optionally visiting '
          + 'a waypoint candidate. Omit waypoint_ref when exploring from the attraction-adjacent start; '
          + 'only include it for a separate canal location to visit. All route refs are candidate_id values, '
          + 'not OSM option_ref values. Use find_hire_trip_options to compare hire bases; this single-start tool does not find rings. '
          + 'Choose a plausible issued candidate and use 3 days at 6 hours/day unless the user supplied a schedule. Results may be a bounded shortlist.',
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
        if (name === 'plan_canal_route') return { preview_only: true,
          preview_ref: storePreview(result, start.revision, path, body), route: summary(result.route) };
        const routes = list(result.routes);
        return { preview_only: true, artifact_revision: result.artifact_revision!,
          default_route_id: result.default_route_id!, total_options: routes.length,
          shown_options: Math.min(routes.length, 5), truncated: routes.length > 5,
          routes: routes.slice(0, 5).map(value => {
            const route = obj(value);
            return { preview_ref: roundTripPreview(route, start.revision, body, result.request_id),
              route_id: route.route_id!, turnaround: route.turnaround!, budget: route.budget!,
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
