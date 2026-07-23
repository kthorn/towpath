import { describe, expect, it, vi } from 'vitest';

import { createGooglePlaceSearch, type PlacesFacade } from './places';

type PlacePrediction = { toPlace: () => unknown };
type SelectListener = (event: { placePrediction?: PlacePrediction }) => Promise<void>;

function createAutocompleteHarness() {
  const element = document.createElement('div') as unknown as ReturnType<PlacesFacade['createAutocomplete']>;
  let select!: SelectListener;
  let error!: (event: Event) => void;
  const addEventListener = vi.fn((event: string, listener: unknown) => {
    if (event === 'gmp-select') select = listener as SelectListener;
    if (event === 'gmp-error') error = listener as (event: Event) => void;
  });
  const removeEventListener = vi.fn();
  element.addEventListener = addEventListener as typeof element.addEventListener;
  element.removeEventListener = removeEventListener as typeof element.removeEventListener;
  element.remove = vi.fn();
  return {
    element,
    addEventListener,
    removeEventListener,
    remove: element.remove as ReturnType<typeof vi.fn>,
    select: (event: { placePrediction?: PlacePrediction }) => select(event),
    error: (event: Event) => error(event),
  };
}

const fields = ['displayName', 'formattedAddress', 'location'];

function createPlace(overrides: Record<string, unknown> = {}) {
  return {
    displayName: 'Bletchley Park',
    formattedAddress: 'Sherwood Drive',
    location: { lat: () => 51.997, lng: () => -0.74 },
    fetchFields: vi.fn(async ({ fields: requested }: { fields: string[] }) => {
      expect(requested).toEqual(fields);
    }),
    ...overrides,
  };
}

describe('Google places adapter', () => {
  it('fetches fields and converts a selected place with placeholder and label', async () => {
    const harness = createAutocompleteHarness();
    const place = createPlace();
    const prediction = { toPlace: vi.fn(() => place) };
    const onSelect = vi.fn();
    const onUnavailable = vi.fn();
    const search = createGooglePlaceSearch({ createAutocomplete: () => harness.element });
    const container = document.createElement('div');
    container.setAttribute('aria-label', 'Search for a place');

    const cleanup = search.attach(container, onSelect, onUnavailable);
    await harness.select({ placePrediction: prediction });

    expect(container.firstChild).toBe(harness.element);
    expect(harness.element.placeholder).toBe('Search for a place');
    expect(harness.element).toHaveAttribute('aria-label', 'Search for a place');
    expect(prediction.toPlace).toHaveBeenCalledOnce();
    expect(place.fetchFields).toHaveBeenCalledWith({ fields });
    expect(onSelect).toHaveBeenCalledWith({
      name: 'Bletchley Park',
      address: 'Sherwood Drive',
      coordinate: { lat: 51.997, lon: -0.74 },
    });
    expect(onUnavailable).not.toHaveBeenCalled();
    cleanup();
  });

  it('ignores selections without a prediction or location', async () => {
    const harness = createAutocompleteHarness();
    const place = createPlace({ location: undefined });
    const prediction = { toPlace: vi.fn(() => place) };
    const onSelect = vi.fn();
    const search = createGooglePlaceSearch({ createAutocomplete: () => harness.element });
    const cleanup = search.attach(document.createElement('div'), onSelect);

    await harness.select({});
    await harness.select({ placePrediction: prediction });

    expect(onSelect).not.toHaveBeenCalled();
    expect(place.fetchFields).toHaveBeenCalledWith({ fields });
    cleanup();
  });

  it('reports a failed field fetch as unavailable', async () => {
    const harness = createAutocompleteHarness();
    const failure = new Error('fetch failed');
    const place = createPlace({ fetchFields: vi.fn().mockRejectedValue(failure) });
    const onSelect = vi.fn();
    const onUnavailable = vi.fn();
    const search = createGooglePlaceSearch({ createAutocomplete: () => harness.element });
    const cleanup = search.attach(document.createElement('div'), onSelect, onUnavailable);

    await harness.select({ placePrediction: { toPlace: () => place } });

    expect(onUnavailable).toHaveBeenCalledWith(failure);
    expect(onSelect).not.toHaveBeenCalled();
    cleanup();
  });

  it('reports gmp-error as unavailable', () => {
    const harness = createAutocompleteHarness();
    const onUnavailable = vi.fn();
    const search = createGooglePlaceSearch({ createAutocomplete: () => harness.element });
    const cleanup = search.attach(document.createElement('div'), vi.fn(), onUnavailable);

    harness.error(new Event('gmp-error'));

    expect(onUnavailable).toHaveBeenCalledWith(new Error('Google Places autocomplete failed'));
    cleanup();
  });

  it('does not turn a consumer selection error into an unavailable error', async () => {
    const harness = createAutocompleteHarness();
    const place = createPlace();
    const callbackError = new Error('consumer failed');
    const onSelect = vi.fn(() => { throw callbackError; });
    const onUnavailable = vi.fn();
    const search = createGooglePlaceSearch({ createAutocomplete: () => harness.element });
    const cleanup = search.attach(document.createElement('div'), onSelect, onUnavailable);

    await expect(harness.select({ placePrediction: { toPlace: () => place } })).rejects.toThrow(callbackError);

    expect(onUnavailable).not.toHaveBeenCalled();
    cleanup();
  });

  it('removes both listeners and the element during cleanup', () => {
    const harness = createAutocompleteHarness();
    const search = createGooglePlaceSearch({ createAutocomplete: () => harness.element });
    const cleanup = search.attach(document.createElement('div'), vi.fn(), vi.fn());

    cleanup();

    expect(harness.removeEventListener).toHaveBeenNthCalledWith(1, 'gmp-select', expect.any(Function));
    expect(harness.removeEventListener).toHaveBeenNthCalledWith(2, 'gmp-error', expect.any(Function));
    expect(harness.remove).toHaveBeenCalledOnce();
  });

  it('ignores a pending selection after cleanup', async () => {
    const harness = createAutocompleteHarness();
    let resolveFields!: () => void;
    const place = createPlace({
      fetchFields: vi.fn(() => new Promise<void>((resolve) => { resolveFields = resolve; })),
    });
    const onSelect = vi.fn();
    const onUnavailable = vi.fn();
    const search = createGooglePlaceSearch({ createAutocomplete: () => harness.element });
    const cleanup = search.attach(document.createElement('div'), onSelect, onUnavailable);

    const pendingSelection = harness.select({ placePrediction: { toPlace: () => place } });
    cleanup();
    resolveFields();
    await pendingSelection;

    expect(onSelect).not.toHaveBeenCalled();
    expect(onUnavailable).not.toHaveBeenCalled();
  });
});
