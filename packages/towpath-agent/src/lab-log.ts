import { randomUUID } from 'node:crypto';
import { closeSync, fchmodSync, mkdirSync, openSync, writeSync } from 'node:fs';
import { dirname } from 'node:path';
import type { Json } from './contracts.js';

/** Local diagnostic events only; callers never pass HTTP headers or credentials. */
export function createLabLog(path: string) {
  mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
  const fd = openSync(path, 'a', 0o600);
  fchmodSync(fd, 0o600);
  const labId = randomUUID();
  let closed = false;
  return {
    write(entry: Json) {
      if (closed) return;
      writeSync(fd, JSON.stringify({ timestamp: new Date().toISOString(), lab_id: labId,
        ...(entry as Record<string, Json>) }) + '\n');
    },
    close() { if (!closed) { closed = true; closeSync(fd); } },
  };
}
