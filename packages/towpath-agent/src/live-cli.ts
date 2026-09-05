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
      + 'Calls GPT 5.6 Luna on Amazon Bedrock (us.openai.gpt-5.6-luna).\n'
      + 'Uses AWS_PROFILE (default: default) and AWS_REGION / AWS profile region.\n'
      + 'Makes up to 3 billed model calls; requires a tool call and a text reply to pass.');
    return;
  }
  // Pi detects profile-based auth explicitly; AWS SDK resolves the actual credentials.
  const ambientAuth = process.env.AWS_BEARER_TOKEN_BEDROCK
    || (process.env.AWS_ACCESS_KEY_ID && process.env.AWS_SECRET_ACCESS_KEY)
    || process.env.AWS_CONTAINER_CREDENTIALS_RELATIVE_URI
    || process.env.AWS_CONTAINER_CREDENTIALS_FULL_URI
    || process.env.AWS_WEB_IDENTITY_TOKEN_FILE;
  if (!ambientAuth) process.env.AWS_PROFILE ||= 'default';
  const root = await mkdtemp(join(tmpdir(), 'towpath-live-'));
  try {
    const modelRuntime = await ModelRuntime.create({
      credentials: new InMemoryCredentialStore(), modelsPath: null,
      modelsStorePath: join(root, 'models-cache.json'), refreshOnCreate: false,
      allowModelNetwork: false,
    });
    const base = modelRuntime.getModel('amazon-bedrock', 'openai.gpt-5.6-luna');
    if (!base) throw new Error('Installed Pi catalog is missing Bedrock GPT 5.6 Luna.');
    // Bedrock Converse requires the geographic inference ID, not the base catalog ID.
    const model = { ...base, id: 'us.openai.gpt-5.6-luna' };
    modelRuntime.registerProvider('amazon-bedrock', { models: [model] });
    console.log(JSON.stringify({ provider: model.provider, model: model.id,
      profile: process.env.AWS_PROFILE,
      region: process.env.AWS_REGION ?? process.env.AWS_DEFAULT_REGION ?? 'AWS profile region' }));
    const result = await runSmoke(createPiSessionFactory({
      cwd: root, agentDir: join(root, 'agent'), model, modelRuntime,
    }), event => console.log(JSON.stringify(event)), values.prompt);
    console.log(JSON.stringify(result));
    if (!result.passed) {
      console.error('Smoke failed. Check AWS credentials, region, and Bedrock model access.');
      process.exitCode = 1;
    }
  } finally { await rm(root, { recursive: true, force: true }); }
}
main().catch(error => {
  console.error(error instanceof Error ? error.message : 'Live smoke failed');
  process.exitCode = 1;
});
