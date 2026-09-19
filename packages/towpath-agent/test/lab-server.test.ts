import assert from 'node:assert/strict';
import test from 'node:test';
import { request as httpRequest } from 'node:http';
import { createLabServer } from '../src/lab-server.js';
import type { Json } from '../src/contracts.js';
import { LabChat } from '../src/lab-chat.js';

test('local lab rejects foreign hosts/origins and missing tokens; chat streams', async () => {
  const chat = new LabChat(async ({ emit }) => ({
    async prompt() { emit({ type: 'text_delta', data: { delta: '<script>text only</script>' } }); },
    async abort() {}, dispose() {},
  }), async () => ({}));
  const logs: Json[] = [];
  const server = createLabServer(chat, '<html>__LAB_TOKEN__</html>', 'test-token', entry => logs.push(entry));
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  const { port } = server.address() as { port: number };
  const url = `http://127.0.0.1:${port}`;
  try {
    const status = await new Promise<number | undefined>((resolve, reject) => {
      const req = httpRequest(url, { headers: { host: 'evil.example' } }, res => {
        res.resume(); resolve(res.statusCode);
      });
      req.on('error', reject); req.end();
    });
    assert.equal(status, 403);
    assert.equal((await fetch(url + '/chat', { method: 'POST', body: '{}' })).status, 403);
    const headers = { 'content-type': 'application/json', 'x-lab-token': 'test-token' };
    assert.equal((await fetch(url + '/chat', { method: 'POST', headers: { ...headers, origin: 'https://evil.example' }, body: '{}' })).status, 403);
    const result = await fetch(url + '/chat', { method: 'POST', headers, body: JSON.stringify({ message: 'Hello' }) });
    assert.equal(result.status, 200);
    assert.match(await result.text(), /text_delta/);
    const records = logs as { turn_id: string; event: { type: string; message?: string } }[];
    const user = records.find(row => row.event.type === 'user_message')!;
    assert.equal(user.event.message, 'Hello');
    assert.ok(records.some(row => row.turn_id === user.turn_id && row.event.type === 'text_delta'));
    assert.ok(records.some(row => row.turn_id === user.turn_id && row.event.type === 'summary'));
    assert.ok(!JSON.stringify(logs).includes('test-token'));
    assert.ok(!JSON.stringify(logs).includes('evil.example'));
    assert.equal((await fetch(url + '/chat', { method: 'POST', headers, body: JSON.stringify({ message: 'x'.repeat(9000) }) })).status, 413);
  } finally { await new Promise<void>(resolve => server.close(() => resolve())); }
});
