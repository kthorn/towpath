import type { CatalogPlace } from '../types';

const GOOGLE_MAPS_SEARCH_BASE = 'https://www.google.com/maps/search/?api=1&query=';
const MAX_GOOGLE_MAPS_URL_LENGTH = 2_048;

function normalized(value: string | null | undefined): string | null {
  if (typeof value !== 'string') return null;
  const clean = value.trim().replace(/\s+/g, ' ');
  return clean || null;
}

function encodedQuery(query: string): string {
  return new URLSearchParams({ query }).toString().slice('query='.length);
}

export function buildGoogleMapsSearchUrl(place: CatalogPlace): string {
  const name = normalized(place.name) ?? normalized(place.metadata.name);
  const address = place.metadata.address
    ? [
        place.metadata.address.house_number,
        place.metadata.address.street,
        place.metadata.address.place,
        place.metadata.address.city,
        place.metadata.address.postcode,
      ]
        .map(normalized)
        .filter((value): value is string => value !== null)
        .join(', ')
    : '';
  const coordinate = `${place.coordinate.lat},${place.coordinate.lon}`;
  const query = (name && address ? [name, address] : [name, coordinate])
    .filter((value): value is string => value !== null && value !== '')
    .join(', ');
  let low = 0;
  let high = query.length;
  while (low < high) {
    const length = Math.ceil((low + high) / 2);
    const candidate = `${GOOGLE_MAPS_SEARCH_BASE}${encodedQuery(query.slice(0, length))}`;
    if (candidate.length <= MAX_GOOGLE_MAPS_URL_LENGTH) low = length;
    else high = length - 1;
  }
  return `${GOOGLE_MAPS_SEARCH_BASE}${encodedQuery(query.slice(0, low))}`;
}
