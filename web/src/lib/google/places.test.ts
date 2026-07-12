import { describe, expect, it, vi } from 'vitest';

import { createGooglePlaceSearch } from './places';

describe('Google places adapter', () => {
  it('converts a selected place and removes its listener on cleanup', () => {
    let select!: () => void;
    const remove = vi.fn();
    const onSelect = vi.fn();
    const search = createGooglePlaceSearch({
      createAutocomplete(_input, options) {
        expect(options.fields).toEqual(['name', 'formatted_address', 'geometry.location']);
        return {
          addListener(_event, callback) {
            select = callback;
            return { remove };
          },
          getPlace: () => ({
            name: 'Bletchley Park',
            formatted_address: 'Sherwood Drive',
            geometry: { location: { lat: () => 51.997, lng: () => -0.74 } },
          }),
        };
      },
    });

    const cleanup = search.attach(document.createElement('input'), onSelect);
    select();
    cleanup();

    expect(onSelect).toHaveBeenCalledWith({
      name: 'Bletchley Park',
      address: 'Sherwood Drive',
      coordinate: { lat: 51.997, lon: -0.74 },
    });
    expect(remove).toHaveBeenCalledOnce();
  });

  it('ignores a place without geometry safely', () => {
    let select!: () => void;
    const onSelect = vi.fn();
    const search = createGooglePlaceSearch({
      createAutocomplete() {
        return {
          addListener(_event, callback) {
            select = callback;
            return { remove() {} };
          },
          getPlace: () => ({ name: 'Text-only result' }),
        };
      },
    });

    search.attach(document.createElement('input'), onSelect);
    expect(() => select()).not.toThrow();
    expect(onSelect).not.toHaveBeenCalled();
  });
});
