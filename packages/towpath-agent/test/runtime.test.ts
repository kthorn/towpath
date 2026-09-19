import assert from 'node:assert/strict';
import test from 'node:test';
import { Type } from 'typebox';
import { AgentRuntime } from '../src/runtime.js';
import type { BoundTool, DriverInput, RunEvent, SessionFactory, DomainTool } from '../src/contracts.js';

const args = Type.Object({ name: Type.String() }, { additionalProperties: false });
const tool = (execute: DomainTool['execute'] = async () => ({ place: 'fixture:bletchley' })): DomainTool => ({
  name: 'resolve_place', description: 'Find a sourced place', parameters: args, execute,
});
const deferred = () => {
  let resolve!: () => void;
  const promise = new Promise<void>(r => { resolve = r; });
  return { promise, resolve };
};
const driver = (fn: (input: DriverInput) => Promise<void>): SessionFactory => async input => ({
  prompt: async () => fn(input), abort: async () => {}, dispose() {},
});
const next = () => new Promise(resolve => setImmediate(resolve));

test('strict tool validation precedes execution and successful output stays application-owned', async () => {
  let calls = 0;
  const events: RunEvent[] = [];
  const runtime = new AgentRuntime({ tools: [tool(async (_args, ctx) => {
    calls++; ctx.publish('options', { ids: ['issued-option'] }); return { id: 'issued-option' };
  })], factory: driver(async ({ tools }) => {
    await assert.rejects(tools[0]!.execute({ name: 'Bletchley', extra: true }), { code: 'invalid_tool_arguments' });
    assert.deepEqual(await tools[0]!.execute({ name: 'Bletchley' }), { id: 'issued-option' });
  }) });
  const s = runtime.createSession('alice');
  const result = await runtime.run({ ...s, ownerId: 'alice', message: 'Visit', onEvent: e => events.push(e) });
  assert.equal(result.status, 'complete'); assert.equal(calls, 1);
  assert.deepEqual(events.map(e => e.type), ['started', 'options', 'complete']);
  assert.deepEqual(events.map(e => e.sequence), [1, 2, 3]);
  assert.ok(events.every(e => e.runId === result.runId && e.sessionId === s.sessionId));
});

test('owner, revision, deletion and expiry checks reject access without invoking a model', async () => {
  let now = 0, calls = 0;
  const runtime = new AgentRuntime({ tools: [], now: () => now, sessionTtlMs: 50,
    factory: driver(async () => { calls++; }) });
  const s = runtime.createSession('alice');
  const input = { ...s, ownerId: 'bob', message: 'hi', onEvent() {} };
  await assert.rejects(runtime.run(input), { code: 'not_found' });
  assert.throws(() => runtime.revise('bob', s.sessionId), { code: 'not_found' });
  assert.equal(runtime.revise('alice', s.sessionId), 1);
  await assert.rejects(runtime.run({ ...input, ownerId: 'alice' }), { code: 'stale_revision' });
  now = 51;
  await assert.rejects(runtime.run({ ...input, ownerId: 'alice', revision: 1 }), { code: 'not_found' });
  const second = runtime.createSession('alice');
  runtime.deleteSession('alice', second.sessionId);
  await assert.rejects(runtime.run({ ...input, ...second, ownerId: 'alice' }), { code: 'not_found' });
  assert.equal(calls, 0);
});

test('per-session and global run gates remain held until cancelled work actually settles', async () => {
  const gate = deferred();
  let aborts = 0, disposals = 0;
  const runtime = new AgentRuntime({ tools: [], maxConcurrentRuns: 1, factory: async () => ({
    prompt: () => gate.promise, abort: async () => { aborts++; }, dispose() { disposals++; },
  }) });
  const s = runtime.createSession('alice'), other = runtime.createSession('bob');
  let runId = '';
  const input = { ...s, ownerId: 'alice', message: 'hi', onEvent(e: RunEvent) { runId = e.runId; } };
  const running = runtime.run(input);
  await next();
  await assert.rejects(runtime.run(input), { code: 'busy' });
  await assert.rejects(runtime.run({ ...input, ...other, ownerId: 'bob' }), { code: 'capacity' });
  assert.throws(() => runtime.cancel('bob', s.sessionId, runId), { code: 'not_found' });
  runtime.cancel('alice', s.sessionId, runId);
  assert.equal((await running).code, 'cancelled');
  await assert.rejects(runtime.run(input), { code: 'busy' });
  gate.resolve(); await next();
  assert.equal(aborts, 1); assert.equal(disposals, 1);
  assert.equal((await runtime.run(input)).status, 'complete');
});

test('deadline aborts tool work and late results cannot emit options or success', async () => {
  const gate = deferred();
  const events: RunEvent[] = [];
  let escaped: BoundTool | undefined;
  const runtime = new AgentRuntime({ limits: { deadlineMs: 25 }, tools: [tool(async (_args, ctx) => {
    await gate.promise; ctx.publish('options', { forged: true }); return {};
  })], factory: driver(async ({ tools }) => { escaped = tools[0]; await escaped!.execute({ name: 'Bletchley' }); }) });
  const s = runtime.createSession('alice');
  const result = await runtime.run({ ...s, ownerId: 'alice', message: 'hi', onEvent: e => events.push(e) });
  assert.equal(result.code, 'deadline_exceeded');
  gate.resolve(); await next();
  assert.deepEqual(events.map(e => e.type), ['started', 'error']);
  await assert.rejects(escaped!.execute({ name: 'late' }), { code: 'deadline_exceeded' });
});

test('revision change aborts current run and delayed factory is disposed without prompting', async () => {
  const gate = deferred();
  let prompts = 0, disposed = 0;
  const runtime = new AgentRuntime({ tools: [], factory: async () => {
    await gate.promise;
    return { prompt: async () => { prompts++; }, abort: async () => {}, dispose() { disposed++; } };
  } });
  const s = runtime.createSession('alice');
  const run = runtime.run({ ...s, ownerId: 'alice', message: 'hi', onEvent() {} });
  runtime.revise('alice', s.sessionId);
  assert.equal((await run).code, 'stale_revision');
  gate.resolve(); await next();
  assert.equal(prompts, 0); assert.equal(disposed, 1);
});

test('browser results are owner/run/revision bound, schema checked and single-use', async () => {
  const events: RunEvent[] = [];
  const runtime = new AgentRuntime({ tools: [tool(async (_args, ctx) => {
    const reply = await ctx.requestBrowserTask({ kind: 'fixture-transfer', targets: ['known-point'] },
      Type.Object({ available: Type.Boolean() }, { additionalProperties: false }));
    ctx.publish('clarification', { options: ['turn-a', 'turn-b'], transfer: reply });
    return { status: 'awaiting_selection' };
  })], factory: driver(async ({ tools }) => { await tools[0]!.execute({ name: 'Bletchley' }); }) });
  const s = runtime.createSession('alice');
  const run = runtime.run({ ...s, ownerId: 'alice', message: 'hi', onEvent: e => events.push(e) });
  await next();
  const event = events.find(e => e.type === 'browser_task')!;
  const taskId = (event.data as { taskId: string }).taskId;
  const reply = { ...s, runId: event.runId, taskId, ownerId: 'alice', result: { available: true } };
  assert.throws(() => runtime.submitBrowserResult({ ...reply, ownerId: 'bob' }), { code: 'not_found' });
  assert.throws(() => runtime.submitBrowserResult({ ...reply, revision: 1 }), { code: 'stale_result' });
  assert.throws(() => runtime.submitBrowserResult({ ...reply, result: { available: 'yes' } }), { code: 'invalid_request' });
  runtime.submitBrowserResult(reply);
  assert.throws(() => runtime.submitBrowserResult(reply), { code: 'stale_result' });
  assert.equal((await run).status, 'complete');
  assert.ok(events.some(e => e.type === 'clarification'));
  assert.throws(() => runtime.submitBrowserResult(reply), { code: 'stale_result' });
});

test('limits stop tool loops, oversized results and excessive events; raw errors are redacted', async () => {
  for (const scenario of ['tools', 'payload', 'events', 'error']) {
    const events: RunEvent[] = [];
    const runtime = new AgentRuntime({ tools: [tool(async () => {
      if (scenario === 'error') throw new Error('secret credential');
      return scenario === 'payload' ? 'x'.repeat(2000) : {};
    })], limits: { maxToolCalls: 1, maxPayloadBytes: 1024, maxEvents: 4 },
    factory: driver(async ({ tools, emit }) => {
      await tools[0]!.execute({ name: 'x' });
      if (scenario === 'tools') await tools[0]!.execute({ name: 'x' });
      if (scenario === 'events') for (let i = 0; i < 10; i++) emit({ type: 'text_delta', data: 'hello' });
    }) });
    const result = await runtime.run({ ...runtime.createSession('a'), ownerId: 'a', message: 'hi', onEvent: e => events.push(e) });
    assert.equal(result.status, 'error', scenario);
    assert.equal(result.code, scenario === 'error' ? 'tool_failed' : 'limit_exceeded');
    assert.ok(!JSON.stringify(events).includes('secret credential'));
  }
});

test('browser task rejected while publishing at the event limit leaves no orphan rejection', async () => {
  const runtime = new AgentRuntime({ limits: { maxEvents: 2 }, tools: [tool(async (_args, ctx) => {
    return await ctx.requestBrowserTask({}, Type.Object({}));
  })], factory: driver(async ({ tools }) => { await tools[0]!.execute({ name: 'Bletchley' }); }) });
  const result = await runtime.run({ ...runtime.createSession('a'), ownerId: 'a', message: 'hi', onEvent() {} });
  assert.equal(result.code, 'limit_exceeded');
  await next(); // Node's test runner reports any unhandled task rejection here.
});

test('pre-aborted requests do not construct a Pi session; session caps expire independently', async () => {
  let calls = 0, now = 0;
  const runtime = new AgentRuntime({ tools: [], maxSessions: 1, sessionTtlMs: 10, now: () => now,
    factory: driver(async () => { calls++; }) });
  const s = runtime.createSession('alice');
  assert.throws(() => runtime.createSession('bob'), { code: 'capacity' });
  const controller = new AbortController(); controller.abort();
  const result = await runtime.run({ ...s, ownerId: 'alice', message: 'hi', signal: controller.signal, onEvent() {} });
  assert.equal(result.code, 'cancelled'); assert.equal(calls, 0);
  now = 11;
  assert.ok(runtime.createSession('bob').sessionId);
});

test('tool handlers receive authenticated run identity and simultaneous sessions remain separate', async () => {
  const gate = deferred();
  const seen: unknown[] = [];
  const runtime = new AgentRuntime({ tools: [tool(async (_args, ctx) => {
    // These fields must come from the host run, never model arguments.
    seen.push([ctx.ownerId, ctx.sessionId, ctx.revision]);
    await gate.promise; return {};
  })], factory: driver(async ({ tools }) => { await tools[0]!.execute({ name: 'x' }); }) });
  const a = runtime.createSession('alice'), b = runtime.createSession('bob');
  const one = runtime.run({ ...a, ownerId: 'alice', message: 'a', onEvent() {} });
  const two = runtime.run({ ...b, ownerId: 'bob', message: 'b', onEvent() {} });
  await next(); gate.resolve();
  assert.deepEqual((await Promise.all([one, two])).map(r => r.status), ['complete', 'complete']);
  assert.deepEqual(seen, [['alice', a.sessionId, 0], ['bob', b.sessionId, 0]]);
});
