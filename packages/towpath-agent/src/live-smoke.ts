import { Type } from 'typebox';
import { AgentRuntime } from './runtime.js';
import type { RunEvent, SessionFactory } from './contracts.js';

export const SMOKE_PROMPT = 'Call resolve_place for Bletchley Park, then briefly acknowledge '
  + 'the returned synthetic fixture. This is a tool-connectivity smoke test, not route planning.';

export async function runSmoke(
  factory: SessionFactory,
  trace: (event: RunEvent) => void,
  message = SMOKE_PROMPT,
) {
  let toolCalls = 0;
  let textReceived = false;
  const runtime = new AgentRuntime({ factory, limits: {
    deadlineMs: 60_000, maxModelCalls: 3, maxToolCalls: 2, maxOutputTokens: 1024,
  }, tools: [{
    name: 'resolve_place',
    description: 'Return a synthetic place fixture for a connectivity smoke test. No real lookup.',
    parameters: Type.Object({ name: Type.String() }, { additionalProperties: false }),
    async execute() {
      toolCalls++;
      return { placeId: 'fixture:bletchley', name: 'Bletchley Park', synthetic: true };
    },
  }] });
  const ownerId = 'local-smoke';
  const session = runtime.createSession(ownerId);
  const started = performance.now();
  try {
    const result = await runtime.run({ ownerId, ...session, message, onEvent(event) {
      if (event.type === 'text_delta') textReceived = true;
      trace(event);
    } });
    return { passed: result.status === 'complete' && toolCalls > 0 && textReceived,
      toolCalls, textReceived, status: result.status, code: result.code,
      elapsedMs: Math.round(performance.now() - started) };
  } finally { runtime.deleteSession(ownerId, session.sessionId); }
}
