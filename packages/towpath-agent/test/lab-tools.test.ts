import assert from 'node:assert/strict';
import test from 'node:test';
import { createLabTools } from '../src/lab-tools.js';
import type { ToolContext, Json } from '../src/contracts.js';

const context = { signal: new AbortController().signal } as ToolContext;
test('lab maps issued place/candidate references to Pound handles and strips geometry', async () => {
  const requests: { path: string; body: unknown }[] = [];
  const toolset = createLabTools(async (path, body): Promise<Json> => {
    requests.push({ path, body });
    if (path === '/api/place-sessions') return { session_id: 'session', token: 'SECRET' };
    if (path.endsWith('/resolve')) return { osm: { status: 'resolved', options: [{
      option_ref: 'osm:1', name: 'Bletchley Park', coordinate: { lat: 52, lon: -1 },
    }] } };
    if (path === '/api/canal-candidates') return { artifact_revision: 'rev', candidates: [{
      candidate_id: 'candidate', handle: { edge: [1, 2], fraction: 0.5 },
      coordinate: { lat: 52, lon: -1 }, display_name: 'Canal', straight_line_distance_m: 100,
    }] };
    if (path === '/api/canal-route') return { route: {
      total_km: 10, total_locks: 2, total_minutes: 200, warnings: [],
    }, geometry: { coordinates: ['DO_NOT_SEND_TO_MODEL'] } };
    return {};
  }, () => {});
  const call = (name: string, args: unknown) => toolset.find(t => t.name === name)!.execute(args, context);
  await call('resolve_place', { query: 'Bletchley Park' });
  await call('get_canal_access_options', { place_ref: 'osm:1' });
  const result = await call('plan_canal_route', { start_ref: 'candidate', end_ref: 'candidate', days: 3, hours_per_day: 6 });
  assert.ok(!JSON.stringify(result).includes('DO_NOT_SEND_TO_MODEL'));
  assert.deepEqual(requests.find(r => r.path === '/api/canal-route')?.body, {
    artifact_revision: 'rev', start: { edge: [1, 2], fraction: 0.5 },
    end: { edge: [1, 2], fraction: 0.5 }, days: 3, hours_per_day: 6,
  });
  await assert.rejects(call('plan_canal_route', { start_ref: 'invented', end_ref: 'candidate' }));
});

test('lab exposes structured API failures without pretending they are route options', async () => {
  const events: Json[] = [];
  const tools = createLabTools(async () => ({ error: { status: 503, code: 'catalog_unavailable' } }), e => events.push(e));
  const result = await tools[0]!.execute({ query: 'Bletchley Park' }, context);
  assert.deepEqual(result, { error: { status: 503, code: 'catalog_unavailable' } });
  assert.equal((events.at(-1) as { type: string }).type, 'tool_result');
});

test('hire tools use published base anchors and compare real return routes via the attraction', async () => {
  const requests: { path: string; body: Json | undefined }[] = [];
  const tools = createLabTools(async (path, body): Promise<Json> => {
    requests.push({ path, body });
    if (path === '/api/place-sessions') return { session_id: 's', token: 'secret' };
    if (path.endsWith('/resolve')) return { osm: { options: [{ option_ref: 'osm:park', coordinate: { lat: 52, lon: -1 } }] } };
    if (path === '/api/canal-candidates') return { artifact_revision: 'rev', candidates: [{ candidate_id: 'visit', handle: { edge: [1, 2], fraction: 0.4 } }] };
    if (path === '/api/hire-bases') return { artifact_revision: 'rev', total_matches: 3, truncated: true, bases: [
      { base_ref: 'provider/base-a', name: 'Marina A', provider_name: 'Provider', provider_id: 'provider', coordinate: { lat: 52.1, lon: -1 }, handle: { edge: [3, 4], fraction: 0.2 }, straight_line_distance_m: 1000, snap_distance_m: 12, provider_url: 'https://example.com', evidence_url: 'https://example.com/base-a', booking_url: null },
      { base_ref: 'provider/base-b', name: 'Marina B', provider_name: 'Provider', coordinate: { lat: 52.2, lon: -1 }, handle: { edge: [5, 6], fraction: 0.3 }, straight_line_distance_m: 2000 },
    ] };
    if (path === '/api/turnaround-candidates') {
      const b = body as Record<string, Json>;
      if (JSON.stringify(b.start).includes('[5,6]')) return { error: { status: 422, code: 'no_feasible_turnaround' } };
      return { artifact_revision: 'rev', default_route_id: 'route-a', routes: [{ route_id: 'route-a', turnaround: { kind: 'winding_hole' }, budget: { available_minutes: 1200 }, journey: { route: { total_km: 42, total_locks: 8, total_minutes: 900, warnings: [] }, geometry: 'OMIT_GEOMETRY' } }] };
    }
    return {};
  }, () => {});
  const call = (name: string, args: unknown) => {
    const tool = tools.find(t => t.name === name);
    assert.ok(tool, `${name} must be available`);
    return tool.execute(args, context);
  };
  await call('resolve_place', { query: 'Bletchley Park' });
  await call('get_canal_access_options', { place_ref: 'osm:park' });
  const bases = await call('find_hire_bases', { place_ref: 'osm:park' }) as Record<string, Json>;
  assert.equal((bases.bases as Record<string, Json>[])[0]!.start_ref, 'hire:provider/base-a');
  assert.ok(!JSON.stringify(bases).includes('"handle"'));
  const result = await call('find_hire_trip_options', { place_ref: 'osm:park', waypoint_ref: 'visit', days: 5, hours_per_day: 4, boat_length_m: 20 }) as Record<string, Json>;
  const search = requests.filter(r => r.path === '/api/hire-bases').at(-1)!;
  assert.deepEqual(search.body, { lat: 52, lon: -1, limit: 6, offset: 0,
    target: { edge: [1, 2], fraction: 0.4 }, artifact_revision: 'rev',
    days: 5, hours_per_day: 4, boat_length_m: 20 });
  const request = requests.find(r => r.path === '/api/turnaround-candidates')!;
  assert.deepEqual(request.body, { artifact_revision: 'rev', start: { edge: [3, 4], fraction: 0.2 }, waypoint: { edge: [1, 2], fraction: 0.4 }, days: 5, hours_per_day: 4, boat_length_m: 20 });
  assert.equal((result.options as Json[]).length, 1);
  assert.equal((result.rejections as Json[]).length, 1);
  assert.equal(result.truncated, true);
  assert.ok(JSON.stringify(result).includes('https://example.com/base-a'));
  assert.ok(!JSON.stringify(result).includes('OMIT_GEOMETRY'));
  assert.equal(result.availability, 'not_checked');
  await assert.rejects(call('find_hire_bases', { place_ref: 'invented' }));
});

test('hire comparison rejects mixed artifact revisions before routing', async () => {
  let routed = false;
  const tools = createLabTools(async (path): Promise<Json> => {
    if (path === '/api/place-sessions') return { session_id: 's', token: 'secret' };
    if (path.endsWith('/resolve')) return { osm: { options: [{ option_ref: 'park', coordinate: { lat: 52, lon: -1 } }] } };
    if (path === '/api/canal-candidates') return { artifact_revision: 'old', candidates: [{ candidate_id: 'visit', handle: { edge: [1, 2], fraction: 0.4 } }] };
    if (path === '/api/hire-bases') return { artifact_revision: 'new', total_matches: 1, truncated: false, bases: [{ base_ref: 'base', name: 'Base', coordinate: { lat: 52, lon: -1 }, handle: { edge: [3, 4], fraction: 0.1 } }] };
    if (path === '/api/turnaround-candidates') routed = true;
    return {};
  }, () => {});
  const call = (name: string, args: unknown) => {
    const tool = tools.find(t => t.name === name); assert.ok(tool, `${name} must be available`);
    return tool.execute(args, context);
  };
  await call('resolve_place', { query: 'Park' });
  await call('get_canal_access_options', { place_ref: 'park' });
  await assert.rejects(call('find_hire_trip_options', { place_ref: 'park', waypoint_ref: 'visit', days: 3, hours_per_day: 6 }), /stale_revision/);
  assert.equal(routed, false);
});

test('exact trip inspection replays the stored selection and constraints without exposing geometry', async () => {
  const requests: { path: string; body: Json | undefined }[] = [];
  const journey = { route: { total_km: 12, total_minutes: 180, total_locks: 2, days: [{ day: 1, cruising_minutes: 180, end_near: 'Base', legs: [] }], legs: [], warnings: [] }, geometry: { type: 'LineString', coordinates: [[-1, 52], [-1.01, 52.01]] }, day_geometries: [] };
  const tools = createLabTools(async (path, body): Promise<Json> => {
    requests.push({ path, body });
    if (path === '/api/place-sessions') return { session_id: 's', token: 'secret' };
    if (path.endsWith('/resolve')) return { osm: { options: [{ option_ref: 'park', coordinate: { lat: 52, lon: -1 } }] } };
    if (path === '/api/canal-candidates') return { artifact_revision: 'rev', candidates: [{ candidate_id: 'c', handle: { edge: [1, 2], fraction: 0.3 } }] };
    const route = { artifact_revision: 'rev', request_id: 'request', route_id: 'route', turnaround: { kind: 'winding_hole' }, budget: { available_minutes: 360 }, journey };
    if (path === '/api/turnaround-candidates') return { artifact_revision: 'rev', request_id: 'request', default_route_id: 'route', routes: [route] };
    if (path === '/api/out-and-back-route') return route;
    return {};
  }, () => {});
  const call = (name: string, args: unknown) => { const tool = tools.find(t => t.name === name); assert.ok(tool); return tool.execute(args, context); };
  await call('resolve_place', { query: 'Park' });
  await call('get_canal_access_options', { place_ref: 'park' });
  const found = await call('plan_out_and_back', { start_ref: 'c', days: 1, hours_per_day: 6 }) as { routes: { preview_ref: string }[] };
  assert.ok(found.routes[0]!.preview_ref, 'previews must issue a stored reference');
  const result = await call('get_trip_option', { preview_ref: found.routes[0]!.preview_ref });
  assert.deepEqual(requests.at(-1), { path: '/api/out-and-back-route', body: { artifact_revision: 'rev', start: { edge: [1, 2], fraction: 0.3 }, days: 1, hours_per_day: 6, request_id: 'request', route_id: 'route' } });
  assert.ok(JSON.stringify(result).includes('cruising_minutes'));
  assert.ok(!JSON.stringify(result).includes('coordinates'));
  await assert.rejects(call('get_trip_option', { preview_ref: 'invented' }));
});

test('qualified place names retry once by name and preserve the unverified locality hint', async () => {
  const queries: Json[] = [];
  const tools = createLabTools(async (path, body): Promise<Json> => {
    if (path === '/api/place-sessions') return { session_id: 's', token: 'secret' };
    if (path.endsWith('/resolve')) {
      queries.push(body!);
      if ((body as Record<string, Json>).query !== 'Bletchley Park') return { osm: { status: 'not_found', reason: 'no_match', options: [] } };
      return { osm: { status: 'ambiguous', options: [{ option_ref: 'osm:park', name: 'Bletchley Park', coordinate: { lat: 52, lon: -1 } }] } };
    }
    return {};
  }, () => {});
  const result = await tools.find(t => t.name === 'resolve_place')!.execute({ query: 'Bletchley Park, Bletchley, Milton Keynes', kinds: ['museum'] }, context) as Record<string, Json>;
  assert.equal(result.status, 'ambiguous');
  assert.deepEqual(queries, [
    { query: 'Bletchley Park, Bletchley, Milton Keynes', kinds: ['museum'] },
    { query: 'Bletchley Park', kinds: ['museum'] },
  ]);
  assert.equal(result.lookup_query, 'Bletchley Park');
  assert.equal(result.locality_hint, 'Bletchley, Milton Keynes');
  assert.equal(result.locality_verified, false);
});

test('successful or unavailable qualified lookups are not broadened', async () => {
  for (const status of ['resolved', 'ambiguous', 'incomplete', 'unavailable']) {
    let lookups = 0;
    const tools = createLabTools(async (path): Promise<Json> => {
      if (path === '/api/place-sessions') return { session_id: 's', token: 'secret' };
      if (path.endsWith('/resolve')) { lookups++; return { osm: { status, options: [] } }; }
      return {};
    }, () => {});
    await tools[0]!.execute({ query: 'Museum, A Place' }, context);
    assert.equal(lookups, 1);
  }
});

test('reachable base discovery uses the half-trip network budget without requiring a turnaround preview', async () => {
  const requests: { path: string; body?: Json }[] = [];
  const tools = createLabTools(async (path, body): Promise<Json> => {
    requests.push({ path, body });
    if (path === '/api/place-sessions') return { session_id: 's', token: 'secret' };
    if (path.endsWith('/resolve')) return { osm: { options: [{ option_ref: 'park', coordinate: { lat: 52, lon: -1 } }] } };
    if (path === '/api/canal-candidates') return { artifact_revision: 'rev', candidates: [{ candidate_id: 'canal', handle: { edge: [1, 2], fraction: 0.5 } }] };
    if (path === '/api/hire-bases') return { artifact_revision: 'rev', budget_minutes: 2520, cutoff_minutes: 1260, ranking_basis: 'canal_travel_time', total_matches: 1, truncated: false, next_offset: null, bases: [{ base_ref: 'wyvern/leighton', name: 'Leighton Buzzard', provider_name: 'Wyvern', handle: { edge: [3, 4], fraction: 0.3 }, one_way_minutes: 201, return_minutes: 201 }] };
    assert.ok(!path.includes('turnaround') && !path.includes('out-and-back'), 'base lookup must not require a complete itinerary');
    return {};
  }, () => {});
  const call = async (name: string, args: Json) => {
    const tool = tools.find(t => t.name === name);
    assert.ok(tool, `${name} must be available`);
    return tool.execute(args, context) as Promise<Record<string, Json>>;
  };
  await call('resolve_place', { query: 'Bletchley Park' });
  await call('get_canal_access_options', { place_ref: 'park' });
  const result = await call('find_reachable_hire_bases', { place_ref: 'park', waypoint_ref: 'canal', days: 7, hours_per_day: 6, boat_beam_m: 2 });
  assert.deepEqual(requests.find(r => r.path === '/api/hire-bases')!.body, { lat: 52, lon: -1, limit: 6, offset: 0, target: { edge: [1, 2], fraction: 0.5 }, artifact_revision: 'rev', days: 7, hours_per_day: 6, boat_beam_m: 2 });
  assert.equal(result.itinerary, 'not_computed');
  assert.equal(result.turnaround, 'not_checked');
  assert.equal((result.bases as Record<string, Json>[])[0]!.one_way_minutes, 201);
  assert.equal(result.next_offset, null);
});
