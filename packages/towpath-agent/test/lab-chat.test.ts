import assert from 'node:assert/strict';
import test from 'node:test';
import { LabChat } from '../src/lab-chat.js';
import type { SessionFactory } from '../src/contracts.js';

test('lab retains bounded follow-up context and reset starts fresh', async () => {
  const prompts: string[] = [];
  const factory: SessionFactory = async ({ emit }) => ({
    async prompt(text) { prompts.push(text); emit({ type: 'text_delta', data: { delta: 'Reply.' } }); },
    async abort() {}, dispose() {},
  });
  const chat = new LabChat(factory, async () => ({}));
  await chat.send('Visit Bletchley Park', () => {});
  await chat.send('Make that five days', () => {});
  assert.match(prompts[1]!, /Visit Bletchley Park/);
  assert.match(prompts[1]!, /Reply\./);
  chat.reset();
  await chat.send('Start again', () => {});
  assert.ok(!prompts[2]!.includes('Visit Bletchley Park'));
});

test('reset recovers an expired runtime session', t => {
  t.mock.timers.enable({ apis: ['Date'], now: 1000 });
  const chat = new LabChat(async () => ({ async prompt() {}, async abort() {}, dispose() {} }), async () => ({}));
  t.mock.timers.tick(31 * 60_000);
  assert.doesNotThrow(() => chat.reset());
});

test('cancel stops a run and allows a fresh conversation', async () => {
  let started!: () => void;
  const ready = new Promise<void>(resolve => { started = resolve; });
  const chat = new LabChat(async ({ signal }) => ({
    async prompt() { started(); await new Promise<void>(resolve => signal.addEventListener('abort', () => resolve(), { once: true })); },
    async abort() {}, dispose() {},
  }), async () => ({}));
  const pending = chat.send('Hello', () => {});
  await ready;
  chat.cancel();
  assert.equal((await pending).code, 'cancelled');
  assert.doesNotThrow(() => chat.reset());
});
