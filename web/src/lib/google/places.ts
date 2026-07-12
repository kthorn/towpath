import type { PlaceSearch, SelectedPlace } from './contracts';

interface PlaceLike {
  name?: string;
  formatted_address?: string;
  geometry?: {
    location?: {
      lat: number | (() => number);
      lng: number | (() => number);
    };
  };
}

interface Listener {
  remove(): void;
}

interface Autocomplete {
  addListener(event: 'place_changed', callback: () => void): Listener;
  getPlace(): PlaceLike;
}

export interface PlacesFacade {
  createAutocomplete(input: HTMLInputElement, options: { fields: string[] }): Autocomplete;
}

interface AttributeClaim {
  count: number;
  original: string | null;
}

const claims = new WeakMap<Element, Map<string, AttributeClaim>>();

function claimAttribute(element: Element, name: string, value: string): () => void {
  let attributes = claims.get(element);
  if (!attributes) {
    attributes = new Map();
    claims.set(element, attributes);
  }
  let claim = attributes.get(name);
  if (!claim) {
    claim = { count: 0, original: element.getAttribute(name) };
    attributes.set(name, claim);
  }
  claim.count += 1;
  element.setAttribute(name, value);
  return () => {
    claim!.count -= 1;
    if (claim!.count > 0) return;
    if (claim!.original === null) element.removeAttribute(name);
    else element.setAttribute(name, claim!.original);
    attributes!.delete(name);
    if (attributes!.size === 0) claims.delete(element);
  };
}

function valueOf(value: number | (() => number)): number {
  return typeof value === 'function' ? value() : value;
}

export function createGooglePlaceSearch(places: PlacesFacade): PlaceSearch {
  return {
    attach(input, onSelect) {
      const autocomplete = places.createAutocomplete(input, {
        fields: ['name', 'formatted_address', 'geometry.location'],
      });
      const inputAttributes = ['role', 'aria-autocomplete', 'aria-expanded'] as const;
      const previousInputAttributes = new Map(
        inputAttributes.map((name) => [name, input.getAttribute(name)]),
      );
      input.setAttribute('role', 'combobox');
      input.setAttribute('aria-autocomplete', 'list');
      input.setAttribute('aria-expanded', 'false');

      const releases: Array<() => void> = [];
      const decorated = new Set<Element>();
      const decoratePredictions = () => {
        const containers = [...document.querySelectorAll('.pac-container')];
        for (const container of containers) {
          if (!decorated.has(container)) {
            decorated.add(container);
            releases.push(claimAttribute(container, 'role', 'listbox'));
          }
          for (const item of container.querySelectorAll('.pac-item')) {
            if (!decorated.has(item)) {
              decorated.add(item);
              releases.push(claimAttribute(item, 'role', 'option'));
            }
          }
        }
        const expanded = containers.some((container) => {
          const html = container as HTMLElement;
          return container.querySelector('.pac-item') !== null
            && !html.hidden
            && html.style.display !== 'none'
            && container.getAttribute('aria-hidden') !== 'true';
        });
        const expandedValue = String(expanded);
        if (input.getAttribute('aria-expanded') !== expandedValue) {
          input.setAttribute('aria-expanded', expandedValue);
        }
      };
      const observer = new MutationObserver(decoratePredictions);
      observer.observe(document.body, { childList: true, subtree: true, attributes: true });
      decoratePredictions();
      const listener = autocomplete.addListener('place_changed', () => {
        const place = autocomplete.getPlace();
        const location = place.geometry?.location;
        if (!location) return;
        const selected: SelectedPlace = {
          name: place.name || place.formatted_address || 'Selected place',
          address: place.formatted_address ?? '',
          coordinate: { lat: valueOf(location.lat), lon: valueOf(location.lng) },
        };
        onSelect(selected);
      });
      return () => {
        listener.remove();
        observer.disconnect();
        for (const release of releases.reverse()) release();
        for (const name of inputAttributes) {
          const previous = previousInputAttributes.get(name);
          if (previous === null || previous === undefined) input.removeAttribute(name);
          else input.setAttribute(name, previous);
        }
      };
    },
  };
}
