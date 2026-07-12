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

    const cleanup = search.attach(document.createElement('input'), onSelect);
    expect(() => select()).not.toThrow();
    expect(onSelect).not.toHaveBeenCalled();
    cleanup();
  });

  it('exposes legacy Google predictions semantically and restores owned attributes', async () => {
    const search = createGooglePlaceSearch({
      createAutocomplete() {
        return {
          addListener() { return { remove() {} }; },
          getPlace: () => ({}),
        };
      },
    });
    const input = document.createElement('input');
    input.setAttribute('role', 'searchbox');
    document.body.append(input);

    const cleanup = search.attach(input, vi.fn());
    expect(input).toHaveAttribute('role', 'combobox');
    expect(input).toHaveAttribute('aria-autocomplete', 'list');
    expect(input).toHaveAttribute('aria-expanded', 'false');

    const container = document.createElement('div');
    container.className = 'pac-container';
    const prediction = document.createElement('div');
    prediction.className = 'pac-item';
    container.append(prediction);
    document.body.append(container);
    await vi.waitFor(() => expect(prediction).toHaveAttribute('role', 'option'));

    expect(container).toHaveAttribute('role', 'listbox');
    expect(input).toHaveAttribute('aria-expanded', 'true');
    prediction.remove();
    await vi.waitFor(() => expect(input).toHaveAttribute('aria-expanded', 'false'));
    cleanup();

    expect(input).toHaveAttribute('role', 'searchbox');
    expect(input).not.toHaveAttribute('aria-autocomplete');
    expect(input).not.toHaveAttribute('aria-expanded');
    expect(container).not.toHaveAttribute('role');
    expect(prediction).not.toHaveAttribute('role');
    container.remove();
    input.remove();
  });
});
