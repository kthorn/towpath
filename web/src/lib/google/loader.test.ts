import { beforeEach, describe, expect, it, vi } from 'vitest';

import { createGoogleMapsLoader } from './loader';

describe('Google Maps loader', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('shares one concurrent SDK load and imports only required libraries', async () => {
    const importLibrary = vi.fn(async (name: string) => ({ name }));
    const loadScript = vi.fn(async () => ({ importLibrary }));
    const loader = createGoogleMapsLoader(loadScript);

    const [first, second] = await Promise.all([loader.load('test-key'), loader.load('test-key')]);

    expect(first).toBe(second);
    expect(loadScript).toHaveBeenCalledOnce();
    expect(loadScript).toHaveBeenCalledWith('test-key');
    expect(importLibrary.mock.calls.map(([name]) => name)).toEqual([
      'maps',
      'places',
      'routes',
      'marker',
    ]);
  });

  it('rejects clearly and permits a controlled retry after script failure', async () => {
    const importLibrary = vi.fn(async (name: string) => ({ name }));
    const loadScript = vi
      .fn()
      .mockRejectedValueOnce(new Error('blocked'))
      .mockResolvedValueOnce({ importLibrary });
    const loader = createGoogleMapsLoader(loadScript);

    await expect(loader.load('test-key')).rejects.toThrow('Failed to load Google Maps: blocked');
    await expect(loader.load('test-key')).resolves.toBeDefined();
    expect(loadScript).toHaveBeenCalledTimes(2);
  });

  it('rejects library import failures clearly', async () => {
    const loader = createGoogleMapsLoader(async () => ({
      importLibrary: async (name: string) => {
        if (name === 'routes') throw new Error('not enabled');
        return { name };
      },
    }));

    await expect(loader.load('test-key')).rejects.toThrow(
      'Failed to load Google Maps: routes library: not enabled',
    );
  });
});
