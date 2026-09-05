import assert from 'node:assert/strict';
import test from 'node:test';
import { runTripFixture } from './fixture.js';

test('real Pi and fake tools resolve a visit, coordinate a transfer, offer sourced IDs and ask for explicit selection', async () => {
  const events = await runTripFixture();
  assert.equal(events.at(-1)?.type, 'complete');
  assert.equal(events.filter(e => e.type === 'browser_task').length, 1);
  const options = events.find(e => e.type === 'options');
  assert.deepEqual(options?.data, { optionIds: ['fixture:base-a:turn-1', 'fixture:base-b:turn-2'] });
  assert.deepEqual(events.find(e => e.type === 'clarification')?.data, {
    question: 'Which return trip would you like?', optionIds: ['fixture:base-a:turn-1', 'fixture:base-b:turn-2'],
  });
  const rejected = events.find(e => e.type === 'tool_status'
    && (e.data as { toolName?: string; status?: string }).toolName === 'bash'
    && (e.data as { status?: string }).status === 'completed');
  assert.equal((rejected?.data as { isError?: boolean })?.isError, true);
  assert.ok(!events.some(e => (e.type as string) === 'adopted'));
  assert.ok(!JSON.stringify(events).includes('ADVERSARIAL_DESCRIPTION'));
});
