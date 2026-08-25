import { get } from 'svelte/store';
import { beforeEach, describe, expect, it } from 'vitest';

import { BOAT_SETTINGS_KEY, createBoatSettingsStore, type SettingsSaveResult } from './boat-settings';

const emptySettings = {
  boat_length_m: null,
  boat_beam_m: null,
  boat_draft_m: null,
  boat_height_m: null,
  movable_bridge_delay_min: null,
};

describe('boat settings store', () => {
  beforeEach(() => localStorage.clear());

  it('starts with empty optional dimensions', () => {
    expect(get(createBoatSettingsStore(localStorage))).toEqual(emptySettings);
  });

  it('loads valid persisted dimensions', () => {
    localStorage.setItem('pound.boat-settings', JSON.stringify({
      boat_length_m: 18.3,
      boat_beam_m: 2.1,
      boat_draft_m: null,
      boat_height_m: 2.4,
      movable_bridge_delay_min: null,
    }));

    expect(get(createBoatSettingsStore(localStorage))).toEqual({
      boat_length_m: 18.3,
      boat_beam_m: 2.1,
      boat_draft_m: null,
      boat_height_m: 2.4,
      movable_bridge_delay_min: null,
    });
  });

  it('accepts and persists a zero bridge-delay override', () => {
    const store = createBoatSettingsStore(localStorage);
    const settings = { ...emptySettings, movable_bridge_delay_min: 0 };
    store.save(settings);
    expect(get(store)).toEqual(settings);
    expect(JSON.parse(localStorage.getItem(BOAT_SETTINGS_KEY)!)).toEqual(settings);
  });

  it('loads legacy dimensions without a bridge-delay field as null', () => {
    localStorage.setItem(BOAT_SETTINGS_KEY, JSON.stringify({ boat_length_m: 18 }));
    expect(get(createBoatSettingsStore(localStorage))).toEqual({
      boat_length_m: 18, boat_beam_m: null, boat_draft_m: null,
      boat_height_m: null, movable_bridge_delay_min: null,
    });
  });

  it.each([
    'not json',
    JSON.stringify({ boat_length_m: -1 }),
    JSON.stringify({ boat_beam_m: 'wide' }),
    JSON.stringify({ boat_height_m: Infinity }),
  ])('ignores malformed or invalid persisted settings %j', (stored) => {
    localStorage.setItem('pound.boat-settings', stored);
    expect(get(createBoatSettingsStore(localStorage))).toEqual(emptySettings);
  });

  it('updates the readable value and local storage together', () => {
    const store = createBoatSettingsStore(localStorage);
    const settings = {
      boat_length_m: 17.5,
      boat_beam_m: 2.05,
      boat_draft_m: 0.8,
      boat_height_m: null,
      movable_bridge_delay_min: null,
    };

    store.save(settings);

    expect(get(store)).toEqual(settings);
    expect(JSON.parse(localStorage.getItem('pound.boat-settings')!)).toEqual(settings);
  });

  it('reports a persistent save when browser storage accepts the write', () => {
    const store = createBoatSettingsStore(localStorage);
    const result: SettingsSaveResult = store.save({
      boat_length_m: 17.5,
      boat_beam_m: 2.05,
      boat_draft_m: 0.8,
      boat_height_m: null,
      movable_bridge_delay_min: null,
    });

    expect(result).toBe('persistent');
  });

  it('reports a session-only save when browser storage rejects the write', () => {
    const blocked = {
      getItem() { throw new DOMException('Blocked', 'SecurityError'); },
      setItem() { throw new DOMException('Blocked', 'SecurityError'); },
    };
    const store = createBoatSettingsStore(blocked);

    expect(store.save({
      boat_length_m: 18,
      boat_beam_m: null,
      boat_draft_m: null,
      boat_height_m: null,
      movable_bridge_delay_min: null,
    })).toBe('session-only');
  });

  it.each([Number.NaN, Number.POSITIVE_INFINITY])(
    'rejects non-finite values without changing current settings: %s',
    (invalid) => {
      const store = createBoatSettingsStore(localStorage);
      expect(() => store.save({ ...emptySettings, boat_beam_m: invalid })).toThrow(
        /invalid boat settings/i,
      );
      expect(get(store)).toEqual(emptySettings);
      expect(localStorage.getItem('pound.boat-settings')).toBeNull();
    },
  );

  it.each([-0.1, Number.NaN, Number.POSITIVE_INFINITY])(
    'rejects invalid bridge-delay overrides: %s',
    (invalid) => {
      const store = createBoatSettingsStore(localStorage);
      expect(() => store.save({ ...emptySettings, movable_bridge_delay_min: invalid })).toThrow(
        /invalid boat settings/i,
      );
      expect(get(store)).toEqual(emptySettings);
      expect(localStorage.getItem(BOAT_SETTINGS_KEY)).toBeNull();
    },
  );

  it('degrades safely when browser storage access throws', () => {
    const blocked = {
      getItem() { throw new DOMException('Blocked', 'SecurityError'); },
      setItem() { throw new DOMException('Blocked', 'SecurityError'); },
    };
    const store = createBoatSettingsStore(blocked);
    expect(get(store)).toEqual(emptySettings);
    expect(() => store.save({ ...emptySettings, boat_length_m: 18 })).not.toThrow();
    expect(get(store).boat_length_m).toBe(18);
  });
});
