import { runTripFixture } from './fixture.js';
console.log('Synthetic offline fixture; no real route, provider, or model calls.');
for (const event of await runTripFixture()) {
  if (event.type !== 'text_delta') console.log(JSON.stringify({ type: event.type, data: event.data }));
}
