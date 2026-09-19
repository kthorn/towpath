import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';
import { join, resolve } from 'node:path';
import { randomBytes } from 'node:crypto';
import { parseArgs } from 'node:util';
import { InMemoryCredentialStore } from '@earendil-works/pi-ai';
import { ModelRuntime } from '@earendil-works/pi-coding-agent';
import { createPiSessionFactory } from './pi-session.js';
import { createPoundClient } from './lab-tools.js';
import { LabChat } from './lab-chat.js';
import { createLabServer } from './lab-server.js';
import { createLabLog } from './lab-log.js';

async function main() {
  const { values } = parseArgs({ options: { help: { type: 'boolean', short: 'h' },
    port: { type: 'string', default: '8787' }, 'prompt-file': { type: 'string' }, 'log-file': { type: 'string' } } });
  if (values.help) {
    console.log('Usage: npm run chat:lab -- [--port 8787] [--prompt-file path] [--log-file path]\n'
      + 'Requires OPENAI_API_KEY and a local Pound server (POUND_API_URL, default http://127.0.0.1:8000).\n'
      + 'Local-only chat with real APIs and GPT 5.6 Luna; model calls are billed to OpenAI.');
    return;
  }
  if (!process.env.OPENAI_API_KEY?.trim()) throw new Error('OPENAI_API_KEY is required.');
  const port = Number(values.port);
  if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('Invalid port.');
  const pound = createPoundClient(process.env.POUND_API_URL ?? 'http://127.0.0.1:8000');
  const prompt = values['prompt-file'] ? await readFile(values['prompt-file'], 'utf8') : '';
  if (Buffer.byteLength(prompt) > 4000) throw new Error('Prompt file must be at most 4000 bytes.');
  const logPath = resolve(values['log-file'] ?? fileURLToPath(new URL('../../.local/chat-lab/events.jsonl', import.meta.url)));
  const log = createLabLog(logPath);
  const root = await mkdtemp(join(tmpdir(), 'towpath-chat-lab-'));
  try {
    const modelRuntime = await ModelRuntime.create({ credentials: new InMemoryCredentialStore(),
      modelsPath: null, modelsStorePath: join(root, 'models.json'),
      refreshOnCreate: false, allowModelNetwork: false });
    const model = modelRuntime.getModel('openai', 'gpt-5.6-luna');
    if (!model) throw new Error('Installed Pi catalog is missing OpenAI Luna.');
    const factory = createPiSessionFactory({ cwd: root, agentDir: join(root, 'agent'), model, modelRuntime });
    const chat = new LabChat(factory, pound, prompt);
    const page = await readFile(new URL('../../lab/index.html', import.meta.url), 'utf8');
    const server = createLabServer(chat, page, randomBytes(32).toString('hex'), log.write);
    await new Promise<void>((resolve, reject) => {
      server.once('error', reject);
      server.listen(port, '127.0.0.1', resolve);
    });
    log.write({ event: { type: 'lab_started', model: 'openai/gpt-5.6-luna', pound_url: process.env.POUND_API_URL ?? 'http://127.0.0.1:8000' } });
    console.log(`Log: ${logPath}\nChat lab: http://127.0.0.1:${port}\nModel: openai/gpt-5.6-luna\nPound: ${process.env.POUND_API_URL ?? 'http://127.0.0.1:8000'}`);
    const stop = () => { chat.cancel(); server.close(); server.closeAllConnections(); };
    process.once('SIGINT', stop);
    process.once('SIGTERM', stop);
    await new Promise<void>(resolve => server.once('close', resolve));
    process.removeListener('SIGINT', stop);
    process.removeListener('SIGTERM', stop);
  } finally { log.write({ event: { type: 'lab_stopped' } }); log.close(); await rm(root, { recursive: true, force: true }); }
}
main().catch(error => { console.error(error instanceof Error ? error.message : 'Chat lab failed'); process.exitCode = 1; });
