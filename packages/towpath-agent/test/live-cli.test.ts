import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import test from 'node:test';

const exec = promisify(execFile);
const cli = new URL('../src/live-cli.js', import.meta.url).pathname;

test('live CLI explains OpenAI configuration and fails early without a key', async () => {
  const env: NodeJS.ProcessEnv = { ...process.env, OPENAI_API_KEY: '' };
  // Run an ordinary CLI child, not another Node test worker.
  delete env.NODE_TEST_CONTEXT;
  const help = await exec(process.execPath, [cli, '--help'], { env });
  assert.match(help.stdout, /OPENAI_API_KEY/);
  await assert.rejects(exec(process.execPath, [cli], { env }), (error: unknown) => {
    const failure = error as { code: number; stderr: string; stdout: string };
    assert.equal(failure.code, 1);
    assert.match(failure.stderr, /OPENAI_API_KEY is required/);
    assert.equal(failure.stdout, '');
    return true;
  });
});
