import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { createLabLog } from '../src/lab-log.js';

test('local logs append parseable correlated events with private file permissions', () => {
  const root = mkdtempSync(join(tmpdir(), 'towpath-log-test-'));
  const path = join(root, 'logs/events.jsonl');
  try {
    const first = createLabLog(path);
    first.write({ turn_id: 'turn-a', event: { type: 'user_message', message: 'Bletchley\nPark' } });
    first.write({ turn_id: 'turn-a', event: { type: 'tool_result', tool: 'resolve_place', result: { status: 'not_found' } } });
    first.close();
    const second = createLabLog(path);
    second.write({ event: { type: 'lab_started' } });
    second.close();
    const records = readFileSync(path, 'utf8').trim().split('\n').map(line => JSON.parse(line));
    assert.equal(records.length, 3);
    assert.equal(records[0].turn_id, records[1].turn_id);
    assert.equal(records[0].lab_id, records[1].lab_id);
    assert.notEqual(records[0].lab_id, records[2].lab_id);
    assert.equal(records[0].event.message, 'Bletchley\nPark');
    assert.ok(Number.isFinite(Date.parse(records[0].timestamp)));
    assert.equal(statSync(path).mode & 0o777, 0o600);
  } finally { rmSync(root, { recursive: true, force: true }); }
});
