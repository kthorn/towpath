import { writable, type Readable } from 'svelte/store';

export const BOAT_SETTINGS_KEY = 'pound.boat-settings';

export interface BoatSettings {
  boat_length_m: number | null;
  boat_beam_m: number | null;
  boat_draft_m: number | null;
  boat_height_m: number | null;
}

export type SettingsSaveResult = 'persistent' | 'session-only';

export interface BoatSettingsStore extends Readable<BoatSettings> {
  save(settings: BoatSettings): SettingsSaveResult;
}

type SettingsStorage = Pick<Storage, 'getItem' | 'setItem'>;

const emptySettings = (): BoatSettings => ({
  boat_length_m: null,
  boat_beam_m: null,
  boat_draft_m: null,
  boat_height_m: null,
});

const fields = [
  'boat_length_m',
  'boat_beam_m',
  'boat_draft_m',
  'boat_height_m',
] as const;

function validateSettings(parsed: unknown): BoatSettings {
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    throw new Error('Invalid boat settings');
  }
  const record = parsed as Record<string, unknown>;
  const settings = emptySettings();
  for (const field of fields) {
    const candidate = record[field] ?? null;
    if (candidate !== null &&
        (typeof candidate !== 'number' || !Number.isFinite(candidate) || candidate <= 0)) {
      throw new Error('Invalid boat settings');
    }
    settings[field] = candidate;
  }
  return settings;
}

function parseSettings(value: string | null): BoatSettings {
  return value === null ? emptySettings() : validateSettings(JSON.parse(value));
}

export function createBoatSettingsStore(storage?: SettingsStorage): BoatSettingsStore {
  let initial = emptySettings();
  try {
    storage ??= globalThis.localStorage;
    initial = parseSettings(storage?.getItem(BOAT_SETTINGS_KEY) ?? null);
  } catch {
    initial = emptySettings();
  }
  const inner = writable(initial);

  return {
    subscribe: inner.subscribe,
    save(settings) {
      const validated = validateSettings(settings);
      inner.set(validated);
      if (!storage) return 'session-only';
      try {
        storage.setItem(BOAT_SETTINGS_KEY, JSON.stringify(validated));
        return 'persistent';
      } catch {
        return 'session-only';
      }
    },
  };
}
