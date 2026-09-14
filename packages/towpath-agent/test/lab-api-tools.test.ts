import assert from 'node:assert/strict';
import test from 'node:test';
import { Type } from 'typebox';
import { createApiTools } from '../src/lab-api-tools.js';
import type { DomainTool, Json, ToolName } from '../src/contracts.js';

const signal = new AbortController().signal;
const point = { lat: 51, lon: -1 } as Json;

function fixture(largeNetwork = false) {
  const requests: { path: string; body: Json | undefined; method?: string }[] = [];
  const places = new Map<string, Json>([['place', point]]);
  const previews = new Map<string, { revision: string; journey: Json }>();
  previews.set('trip', {
    revision: 'rev',
    journey: {
      geometry: { type: 'LineString', coordinates: [[-1.2, 51], [-1, 51.1]] },
      day_geometries: [{ day: 2, geometry: { type: 'LineString', coordinates: [[-1.1, 51], [-1, 51.1]] } }],
    },
  });
  const call = async (path: string, body: Json | undefined, _abort: AbortSignal,
    options?: { method?: string }): Promise<Json> => {
    requests.push({ path, body, method: options?.method });
    if (path === '/api/health') return { status: 'healthy', artifact_revision: 'rev', places_status: 'available' };
    if (path.startsWith('/api/places')) return { places: Array.from({ length: 3 }, (_, i) => ({ kind: 'pub', name: `Pub ${i}`, coordinate: point, target_id: 'target', provenance: { source: 'osm', osm_type: 'node', osm_id: i + 1, metadata: {} } })) };
    if (path === '/api/route-pois') return { pois: Array.from({ length: 3 }, (_, i) => ({ identity: `poi:${i}`, kind: 'pub', name: `Pub ${i}`, coordinate: point, distance_to_route_m: i })), matching_count: 3, zoom_in_required: false, day: null };
    if (path === '/api/canal-network') return { artifact_revision: 'rev', lines: [{ type: 'LineString', coordinates: largeNetwork ? Array.from({ length: 100_001 }, (_, i) => [-1 + i / 1_000_000, 51 + i / 1_000_000]) : [[-1.2, 51], [-1, 51.1]] }], highlight_lines: [], bases: [{ identity: 'base', operator: 'Operator', name: 'Base', coordinate: point }] };
    if (path.startsWith('/api/climate/locations?')) return { revision: 'climate', end_year: 2025, source: {}, week_id: 8, week_label: 'June', period_years: 25, metric: 'high', locations: [
      { id: 'oxford', name: 'Oxford', coordinate: point, distribution: { available: true, missing_years: [], start_year: 2000, end_year: 2025, n_days: 175, n_years: 25, p10: 10, median: 15, p90: 20 } },
      { id: 'bath', name: 'Bath', coordinate: { lat: 51.38, lon: -2.36 } as Json, distribution: { available: true, missing_years: [], start_year: 2000, end_year: 2025, n_days: 175, n_years: 25, p10: 10, median: 15, p90: 20 } },
    ] };
    if (path.startsWith('/api/climate/locations/')) return { revision: 'climate', location: { id: 'oxford' }, high: { '5': { samples: [1, 2], median: 1 } }, low: {} };
    if (path.startsWith('/api/climate/grid/cells/')) return { cell_id: 'cell-1', nested: { samples: [1, 2], value: 3 } };
    if (path.startsWith('/api/climate/grid')) return { revision: 'grid', end_year: 2025, source: {}, week_id: 8, week_label: 'June', period_years: 25, view: 'high_p90', threshold_c: null, unit: 'celsius', spacing_km: 10, mask: { type: 'Polygon', coordinates: [] }, cells: [
      { id: 'cell-1', coordinate: point, value: 30, n_days: 100 },
      { id: 'cell-2', coordinate: { lat: 52, lon: -1 } as Json, value: null, n_days: 0 },
    ] };
    return {};
  };
  const tool = (name: ToolName, description: string, properties: Parameters<typeof Type.Object>[0], execute: (args: Record<string, Json>, abort: AbortSignal) => Promise<Json>): DomainTool => ({
    name, description, parameters: Type.Object(properties), execute: (args, context) => execute(args as Record<string, Json>, context.signal),
  });
  const api = createApiTools({ tool, call, place: (ref: Json | undefined) => places.get(String(ref))!, rememberPlace: (id: string, coordinate: Json) => places.set(id, coordinate), preview: (ref: Json | undefined) => previews.get(String(ref)) ?? (() => { throw new Error('missing preview'); })() });
  return { api, requests, places, previews };
}

const run = (tools: DomainTool[], name: string, args: Record<string, Json>) => tools.find(tool => tool.name === name)!.execute(args, { signal } as never);

test('exposes all bounded server API wrappers and strips large geometry', async () => {
  const { api } = fixture();
  assert.deepEqual(api.map(tool => tool.name), [
    'get_api_status', 'search_places', 'get_route_pois', 'get_canal_network',
    'get_climate_locations', 'get_climate_location', 'get_climate_grid', 'get_climate_cell',
  ]);
  const network = await run(api, 'get_canal_network', { days: 3, hours_per_day: 6 });
  assert.equal(JSON.stringify(network).includes('coordinates'), false);
  const places = await run(api, 'search_places', { mode: 'nearby', place_ref: 'place', kinds: ['pub'], radius_m: 1000 });
  assert.equal((places as { places: Json[] }).places.length, 3);
  const pois = await run(api, 'get_route_pois', { preview_ref: 'trip', kinds: ['pub'], day: 2 });
  assert.equal((pois as { pois: Json[] }).pois.length, 3);
});

test('uses stored preview geometry and issued climate references', async () => {
  const { api, requests } = fixture();
  await run(api, 'search_places', { mode: 'viewport', preview_ref: 'trip', kinds: ['pub'], policy_basis: 'route', policy_radius_m: 2000, day: 2 });
  const placeRequest = requests.find(request => request.path === '/api/places')!;
  assert.equal((placeRequest.body as Record<string, Json>).day_geometry !== undefined, true);
  const locations = await run(api, 'get_climate_locations', { place_ref: 'place' });
  assert.equal((locations as Record<string, Json>).locations !== undefined, true);
  await run(api, 'get_climate_location', { location_id: 'oxford' });
  const grid = await run(api, 'get_climate_grid', {});
  assert.equal(JSON.stringify(grid).includes('mask'), false);
  const cell = await run(api, 'get_climate_cell', { cell_id: 'cell-1' });
  assert.equal(JSON.stringify(cell).includes('samples'), false);
});

test('uses exact day geometry for nearby preview searches and forwards text', async () => {
  const { api, requests } = fixture();
  await run(api, 'search_places', { mode: 'nearby', preview_ref: 'trip', kinds: ['pub'], day: 2, text: 'waterside' });
  const request = requests.find(item => item.path === '/api/places')!;
  const body = request.body as Record<string, Json>;
  assert.deepEqual((body.targets as Record<string, Json>[])[0]!.geometry, {
    type: 'LineString', coordinates: [[-1.1, 51], [-1, 51.1]],
  });
  assert.equal(body.text, 'waterside');
});

test('derives a bounded viewport around an issued place coordinate', async () => {
  const { api, requests } = fixture();
  await run(api, 'search_places', { mode: 'viewport', place_ref: 'place', kinds: ['pub'] });
  const body = requests.find(item => item.path === '/api/places')!.body as Record<string, Json>;
  assert.deepEqual(body.policy, { basis: 'none' });
  const derivedBounds = body.bounds as Record<string, Json>;
  assert.ok(Number(derivedBounds.south) < 51 && Number(derivedBounds.north) > 51);
  assert.ok(Number(derivedBounds.west) < -1 && Number(derivedBounds.east) > -1);
});

test('pads flat auto-derived route bounds for spatial queries', async () => {
  const { api, requests, previews } = fixture();
  previews.set('flat', { revision: 'rev', journey: { geometry: { type: 'LineString', coordinates: [[-1.2, 51], [-1, 51]] } } });
  await run(api, 'search_places', { mode: 'viewport', preview_ref: 'flat', kinds: ['pub'], policy_basis: 'none' });
  const placesBody = requests.find(item => item.path === '/api/places')!.body as Record<string, Json>;
  const bounds = placesBody.bounds as Record<string, Json>;
  assert.ok(Number(bounds.south) < 51 && Number(bounds.north) > 51);
  const { api: poiApi, requests: poiRequests } = fixture();
  await run(poiApi, 'get_route_pois', { preview_ref: 'trip', kinds: ['pub'] });
  const poiBounds = poiRequests.find(item => item.path === '/api/route-pois')!.body as Record<string, Json>;
  assert.ok(Number((poiBounds.bounds as Record<string, Json>).south) < 51);
});

test('rejects unknown issued references before making HTTP calls', async () => {
  const { api, requests } = fixture();
  await assert.rejects(run(api, 'search_places', { mode: 'nearby', place_ref: 'unknown', kinds: ['pub'], radius_m: 100 }));
  await assert.rejects(run(api, 'get_route_pois', { preview_ref: 'unknown', kinds: ['pub'] }));
  await assert.rejects(run(api, 'get_climate_location', { location_id: 'oxford' }));
  await assert.rejects(run(api, 'get_climate_cell', { cell_id: 'cell-1' }));
  assert.equal(requests.length, 0);
});

test('caps place and POI results with offset while preserving truncation', async () => {
  const { api } = fixture();
  const result = await run(api, 'search_places', { mode: 'nearby', place_ref: 'place', kinds: ['pub'], radius_m: 1000, offset: 1, limit: 1 }) as Record<string, Json>;
  assert.equal((result.places as Json[]).length, 1);
  assert.equal(result.truncated, true);
  const pois = await run(api, 'get_route_pois', { preview_ref: 'trip', kinds: ['pub'], offset: 1, limit: 1 }) as Record<string, Json>;
  assert.equal((pois.pois as Json[]).length, 1);
  assert.equal(pois.truncated, true);
});

test('only issues paged place and climate references', async () => {
  const { api } = fixture();
  await run(api, 'search_places', { mode: 'nearby', place_ref: 'place', kinds: ['pub'], radius_m: 1000, offset: 2, limit: 1 });
  await assert.rejects(run(api, 'search_places', { mode: 'nearby', place_ref: 'osm:node:1', kinds: ['pub'], radius_m: 100 }));
  await run(api, 'get_climate_locations', { offset: 1, limit: 1 });
  await assert.rejects(run(api, 'get_climate_location', { location_id: 'oxford' }));
  await run(api, 'get_climate_location', { location_id: 'bath' });
});

test('rejects stale preview geometry before calling places', async () => {
  const { api, requests, previews } = fixture();
  previews.set('trip', { ...previews.get('trip')!, revision: 'old-rev' });
  await assert.rejects(run(api, 'search_places', { mode: 'nearby', preview_ref: 'trip', kinds: ['pub'] }), /stale_revision/);
  assert.equal(requests.some(request => request.path === '/api/places'), false);
});

test('summarizes large network geometry without spread call-stack failure', async () => {
  const { api } = fixture(true);
  const result = await run(api, 'get_canal_network', { days: 3, hours_per_day: 6 }) as Record<string, Json>;
  assert.equal(result.vertex_count, 100001);
});

test('viewport day queries retain full route geometry under every policy', async () => {
  for (const policy_basis of ['route', 'waterway', 'none']) {
    const { api, requests } = fixture();
    await run(api, 'search_places', { mode: 'viewport', preview_ref: 'trip', kinds: ['pub'], day: 2, policy_basis });
    const body = requests.find(request => request.path === '/api/places')!.body as Record<string, Json>;
    assert.deepEqual(body.route_geometry, { type: 'LineString', coordinates: [[-1.2, 51], [-1, 51.1]] });
    assert.deepEqual(body.day_geometry, { type: 'LineString', coordinates: [[-1.1, 51], [-1, 51.1]] });
  }
});
