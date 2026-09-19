import { fauxProvider } from '@earendil-works/pi-ai';
import type { ModelRuntime } from '@earendil-works/pi-coding-agent';
export function fakeModel() {
  const faux = fauxProvider({ provider: 'towpath-test', tokensPerSecond: 100000 });
  const model = faux.getModel();
  const runtime = {
    getModel: () => model, getAvailableSnapshot: () => [model], hasConfiguredAuth: () => true,
    isUsingOAuth: () => false, getAuth: async () => ({ auth: { apiKey: 'synthetic' } }),
    streamSimple: faux.provider.streamSimple.bind(faux.provider),
  } as unknown as ModelRuntime;
  return { faux, model, runtime };
}

