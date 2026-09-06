import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { parseArgs } from 'node:util';
import { InMemoryCredentialStore } from '@earendil-works/pi-ai';
import { ModelRuntime } from '@earendil-works/pi-coding-agent';
import { createPiSessionFactory } from './pi-session.js';
import { runSmoke } from './live-smoke.js';

async function main() {
  const { values } = parseArgs({ options: {
    help: { type: 'boolean', short: 'h' }, prompt: { type: 'string' },
  } });
  if (values.help) {
    console.log('Usage: npm run smoke:live -- [--prompt "..."]\n'
      + 'Calls GPT 5.6 Luna through the OpenAI Responses API (gpt-5.6-luna).\n'
      + 'Requires OPENAI_API_KEY; it can be supplied from AWS Secrets Manager.\n'
      + 'Makes up to 3 billed model calls; requires a tool call and a text reply to pass.');
    return;
  }
  if (!process.env.OPENAI_API_KEY?.trim()) {
    throw new Error('OPENAI_API_KEY is required. Supply it directly or from AWS Secrets Manager.');
  }
  const root = await mkdtemp(join(tmpdir(), 'towpath-live-'));
  try {
    const modelRuntime = await ModelRuntime.create({
      credentials: new InMemoryCredentialStore(), modelsPath: null,
      modelsStorePath: join(root, 'models-cache.json'), refreshOnCreate: false,
      allowModelNetwork: false,
    });
    const model = modelRuntime.getModel('openai', 'gpt-5.6-luna');
    if (!model) throw new Error('Installed Pi catalog is missing OpenAI GPT 5.6 Luna.');
    console.log(JSON.stringify({ provider: model.provider, model: model.id }));
    const result = await runSmoke(createPiSessionFactory({
      cwd: root, agentDir: join(root, 'agent'), model, modelRuntime,
    }), event => console.log(JSON.stringify(event)), values.prompt);
    console.log(JSON.stringify(result));
    if (!result.passed) {
      console.error('Smoke failed. Check the OpenAI API key, billing, and model access.');
      process.exitCode = 1;
    }
  } finally { await rm(root, { recursive: true, force: true }); }
}
main().catch(error => {
  console.error(error instanceof Error ? error.message : 'Live smoke failed');
  process.exitCode = 1;
});
