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

function valueOf(value: number | (() => number)): number {
  return typeof value === 'function' ? value() : value;
}

export function createGooglePlaceSearch(places: PlacesFacade): PlaceSearch {
  return {
    attach(input, onSelect) {
      const autocomplete = places.createAutocomplete(input, {
        fields: ['name', 'formatted_address', 'geometry.location'],
      });
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
      return () => listener.remove();
    },
  };
}
