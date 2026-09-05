import assert from 'node:assert/strict';
import test from 'node:test';
import { runSmoke } from '../src/live-smoke.js';

for (const callsTool of [true, false]) {
  test(`smoke ${callsTool ? 'passes with' : 'rejects missing'} tool execution`, async () => {
    const result = await runSmoke(async ({ tools, emit }) => ({
      async prompt() {
        if (callsTool) await tools[0]!.execute({ name: 'Bletchley Park' });
        emit({ type: 'text_delta', data: { text: 'Done.' } });
      },
      async abort() {}, dispose() {},
    }), () => {});
    assert.equal(result.passed, callsTool);
    assert.equal(result.toolCalls, callsTool ? 1 : 0);
  });
}

test('smoke fails when the model errors after executing a tool', async () => {
  const result = await runSmoke(async ({ tools }) => ({
    async prompt() {
      await tools[0]!.execute({ name: 'Bletchley Park' });
      throw new Error('provider failed');
    },
    async abort() {}, dispose() {},
  }), () => {});
  assert.equal(result.passed, false);
  assert.equal(result.status, 'error');
});
