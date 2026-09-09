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
