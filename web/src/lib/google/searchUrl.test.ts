import { describe, expect, it } from 'vitest';

import { buildGoogleMapsSearchUrl } from './searchUrl';

function place(overrides: Record<string, unknown> = {}) {
  return {
    name: 'Canal Museum',
    coordinate: { lat: 51.234567, lon: -1.987654 },
    metadata: {
      address: {
        house_number: '1',
        street: "St. John's & Canal Road",
        place: null,
        city: 'Oxford',
        postcode: 'OX1 1AA',
      },
    },
    ...overrides,
  } as Parameters<typeof buildGoogleMapsSearchUrl>[0];
}

describe('Google Maps URL-only search helper', () => {
  it('encodes punctuation and uses non-empty normalized address fields', () => {
    const url = buildGoogleMapsSearchUrl(place({ name: "St. John's & Co." }));

    expect(url).toContain('https://www.google.com/maps/search/?api=1&query=');
    expect(url).toContain('%26');
    expect(url).toContain('%27');
    expect(new URL(url).searchParams.get('query')).toBe(
      "St. John's & Co., 1, St. John's & Canal Road, Oxford, OX1 1AA",
    );
  });

  it('falls back to coordinates when address and locality are missing', () => {
    const url = buildGoogleMapsSearchUrl(
      place({
        name: 'Rural Lockhouse',
        metadata: {
          address: {
            house_number: null,
            street: null,
            place: null,
            city: null,
            postcode: null,
          },
        },
      }),
    );

    expect(new URL(url).searchParams.get('query')).toBe('Rural Lockhouse, 51.234567,-1.987654');
  });

  it('uses coordinates when the catalog name is absent even if address fields exist', () => {
    const url = buildGoogleMapsSearchUrl(
      place({
        name: null,
        metadata: {
          name: null,
          address: {
            house_number: '1',
            street: 'Canal Road',
            place: null,
            city: 'Oxford',
            postcode: 'OX1',
          },
        },
      }),
    );

    expect(new URL(url).searchParams.get('query')).toBe('51.234567,-1.987654');
  });

  it('keeps the generated URL within the Maps 2,048-character limit', () => {
    const url = buildGoogleMapsSearchUrl(place({ name: 'x'.repeat(5000) }));

    expect(url.length).toBeLessThanOrEqual(2048);
    expect(() => decodeURIComponent(new URL(url).searchParams.get('query') ?? '')).not.toThrow();
  });
});
