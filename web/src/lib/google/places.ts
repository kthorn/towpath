import type { PlaceSearch, SelectedPlace } from './contracts';

interface PlacePrediction {
  toPlace(): Place;
}

interface Place {
  displayName?: string;
  formattedAddress?: string;
  location?: {
    lat: number | (() => number);
    lng: number | (() => number);
  };
  fetchFields(options: { fields: string[] }): Promise<void>;
}

interface PlaceSelectEvent extends Event {
  placePrediction?: PlacePrediction;
}

interface PlaceAutocompleteElement extends HTMLElement {
  placeholder: string;
  addEventListener(event: 'gmp-select', listener: (event: PlaceSelectEvent) => void): void;
  addEventListener(event: 'gmp-error', listener: (event: Event) => void): void;
  removeEventListener(event: 'gmp-select', listener: (event: PlaceSelectEvent) => void): void;
  removeEventListener(event: 'gmp-error', listener: (event: Event) => void): void;
}

export interface PlacesFacade {
  createAutocomplete(): PlaceAutocompleteElement;
}

function valueOf(value: number | (() => number)): number {
  return typeof value === 'function' ? value() : value;
}

export function createGooglePlaceSearch(places: PlacesFacade): PlaceSearch {
  return {
    attach(container, onSelect, onUnavailable) {
      const fields = ['displayName', 'formattedAddress', 'location'];
      const autocomplete = places.createAutocomplete();
      const ariaLabel = container.getAttribute('aria-label');
      if (ariaLabel) autocomplete.setAttribute('aria-label', ariaLabel);
      autocomplete.placeholder = 'Search for a place';
      container.append(autocomplete);
      let disposed = false;
      let selectionToken = 0;
      const onError = (_event: Event) => {
        selectionToken += 1;
        if (!disposed) onUnavailable?.(new Error('Google Places autocomplete failed'));
      };
      const onSelectEvent = async ({ placePrediction }: PlaceSelectEvent) => {
        const token = ++selectionToken;
        if (!placePrediction || disposed) return;
        let selected: SelectedPlace;
        try {
          const place = placePrediction.toPlace();
          await place.fetchFields({ fields });
          const location = place.location;
          if (!location || disposed) return;
          selected = {
            name: place.displayName || place.formattedAddress || 'Selected place',
            address: place.formattedAddress ?? '',
            coordinate: { lat: valueOf(location.lat), lon: valueOf(location.lng) },
          };
        } catch (error) {
          if (!disposed && token === selectionToken) onUnavailable?.(error);
          return;
        }
        if (!disposed && token === selectionToken) onSelect(selected);
      };
      autocomplete.addEventListener('gmp-select', onSelectEvent);
      autocomplete.addEventListener('gmp-error', onError);
      return () => {
        disposed = true;
        autocomplete.removeEventListener('gmp-select', onSelectEvent);
        autocomplete.removeEventListener('gmp-error', onError);
        autocomplete.remove();
      };
    },
  };
}
