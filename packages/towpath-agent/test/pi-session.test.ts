import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, rm, readdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fauxAssistantMessage, fauxToolCall } from '@earendil-works/pi-ai';
import { Type } from 'typebox';
import { fakeModel } from './fake-model.js';
import { createPiSessionFactory } from '../src/pi-session.js';
import type { EventData, Limits } from '../src/contracts.js';

export const limits: Limits = {
  deadlineMs: 5000, maxModelCalls: 8, maxToolCalls: 20, maxOutputTokens: 1024,
  maxPayloadBytes: 65536, maxEvents: 1000,
};

test('real Pi SDK exposes only domain tools, ignores ambient resources, and keeps sessions in memory', async () => {
  const root = await mkdtemp(join(tmpdir(), 'towpath-pi-'));
  try {
    await mkdir(join(root, '.pi', 'extensions'), { recursive: true });
    await writeFile(join(root, 'AGENTS.md'), 'AMBIENT_CONTEXT_MUST_NOT_LOAD');
    await writeFile(join(root, '.pi', 'extensions', 'bad.ts'), 'throw new Error("ambient extension loaded")');
    await writeFile(join(root, '.pi', 'settings.json'), '{"defaultTools":["bash"]}');
    const { faux, model, runtime } = fakeModel();
    const events: EventData[] = [];
    let executed = 0;
    faux.setResponses([
      (context, options) => {
        assert.deepEqual(context.tools?.map(t => t.name), ['resolve_place']);
        assert.ok(!context.systemPrompt?.includes('AMBIENT_CONTEXT'));
        assert.equal(options?.maxTokens, 1024);
        return fauxAssistantMessage(fauxToolCall('resolve_place', { name: 'Bletchley Park' }), { stopReason: 'toolUse' });
      },
      fauxAssistantMessage('I found the attraction.'),
    ]);
    const factory = createPiSessionFactory({ cwd: root, agentDir: join(root, 'agent'), model, modelRuntime: runtime });
    const driver = await factory({ tools: [{ name: 'resolve_place', description: 'Resolve a sourced place',
      parameters: Type.Object({ name: Type.String() }, { additionalProperties: false }),
      execute: async () => { executed++; return { placeId: 'fixture:bletchley' }; },
    }], limits, signal: new AbortController().signal, emit: e => events.push(e) });
    try { await driver.prompt('Visit Bletchley Park'); } finally { driver.dispose(); }
    assert.equal(executed, 1);
    assert.ok(events.some(e => e.type === 'text_delta'));
    assert.ok(events.some(e => e.type === 'tool_status'));
    assert.equal((await readdir(root)).includes('sessions'), false);
    // A fresh loader/session after disposal must remain usable.
    faux.setResponses([fauxAssistantMessage('Fresh session.')]);
    const next = await factory({ tools: [], limits, signal: new AbortController().signal, emit() {} });
    try { await next.prompt('Hello'); } finally { next.dispose(); }
  } finally { await rm(root, { recursive: true, force: true }); }
});

test('Pi model-call limit stops a continuing tool loop before another provider request', async () => {
  const root = await mkdtemp(join(tmpdir(), 'towpath-pi-limit-'));
  try {
    const { faux, model, runtime } = fakeModel();
    faux.setResponses([fauxAssistantMessage(fauxToolCall('resolve_place', {}), { stopReason: 'toolUse' }), fauxAssistantMessage('Must not run')]);
    const driver = await createPiSessionFactory({ cwd: root, agentDir: join(root, 'agent'), model, modelRuntime: runtime })({
      tools: [{ name: 'resolve_place', description: 'lookup', parameters: Type.Object({}), execute: async () => ({}) }],
      limits: { ...limits, maxModelCalls: 1 }, signal: new AbortController().signal, emit() {},
    });
    try { await assert.rejects(driver.prompt('Find it'), { code: 'limit_exceeded' }); }
    finally { driver.dispose(); }
    assert.equal(faux.state.callCount, 1);
  } finally { await rm(root, { recursive: true, force: true }); }
});

test('real Pi cannot recover a payload-budget violation into a successful run', async () => {
  const { AgentRuntime } = await import('../src/runtime.js');
  for (const where of ['arguments', 'result']) {
    const root = await mkdtemp(join(tmpdir(), 'towpath-pi-payload-'));
    try {
      const { faux, model, runtime: modelRuntime } = fakeModel();
      faux.setResponses([
        fauxAssistantMessage(fauxToolCall('resolve_place', { name: where === 'arguments' ? 'x'.repeat(2000) : 'Bletchley' }), { stopReason: 'toolUse' }),
        fauxAssistantMessage('Must not recover this budget failure.'),
      ]);
      const runtime = new AgentRuntime({ limits: { maxPayloadBytes: 1024 },
        factory: createPiSessionFactory({ cwd: root, agentDir: join(root, 'agent'), model, modelRuntime }),
        tools: [{ name: 'resolve_place', description: 'lookup',
          parameters: Type.Object({ name: Type.String() }, { additionalProperties: false }),
          execute: async () => 'x'.repeat(2000),
        }],
      });
      const result = await runtime.run({ ...runtime.createSession('a'), ownerId: 'a', message: 'lookup', onEvent() {} });
      assert.equal(result.code, 'limit_exceeded', where);
      assert.equal(result.status, 'error', where);
      assert.equal(faux.state.callCount, 1, where);
    } finally { await rm(root, { recursive: true, force: true }); }
  }
});
