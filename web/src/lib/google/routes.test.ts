import { describe, expect, it } from 'vitest';

import { createGoogleTransferRouter, geoJsonToGooglePath, toGoogleLatLng } from './routes';

describe('Google routes adapter', () => {
  it('preserves matrix destination order and maps every status', async () => {
    const calls: unknown[] = [];
    const router = createGoogleTransferRouter({
      async computeRouteMatrix(request) {
        calls.push(request);
        return [
          { destinationIndex: 2, status: 'INTERNAL' },
          {
            destinationIndex: 0,
            status: 'OK',
            durationMillis: 125_000,
            distanceMeters: 900,
          },
          { destinationIndex: 1, status: 'ZERO_RESULTS' },
        ];
      },
      async computeRoutes() {
        throw new Error('unused');
      },
    });

    const result = await router.matrix(
      { lat: 51.5, lon: -0.1 },
      [
        { lat: 51.6, lon: -0.2 },
        { lat: 51.7, lon: -0.3 },
        { lat: 51.8, lon: -0.4 },
        { lat: 51.9, lon: -0.5 },
      ],
      'WALK',
    );

    expect(result).toEqual([
      { available: true, durationSeconds: 125, distanceMeters: 900 },
      { available: false, reason: 'ZERO_RESULTS' },
      { available: false, reason: 'INTERNAL' },
      { available: false, reason: 'NO_RESULT' },
    ]);
    expect(calls).toEqual([
      {
        origins: [{ lat: 51.5, lng: -0.1 }],
        destinations: [
          { lat: 51.6, lng: -0.2 },
          { lat: 51.7, lng: -0.3 },
          { lat: 51.8, lng: -0.4 },
          { lat: 51.9, lng: -0.5 },
        ],
        travelMode: 'WALKING',
        fields: ['condition', 'durationMillis', 'distanceMeters', 'error'],
      },
    ]);
  });

  it('returns a provider-neutral route with explicit fields', async () => {
    const router = createGoogleTransferRouter({
      async computeRouteMatrix() {
        return [];
      },
      async computeRoutes(request) {
        expect(request).toMatchObject({
          origin: { lat: 52, lng: -1 },
          destination: { lat: 53, lng: -2 },
          travelMode: 'DRIVING',
          fields: ['path', 'durationMillis', 'distanceMeters'],
        });
        return {
          routes: [
            {
              path: [
                { lat: 52, lng: -1 },
                { latitude: 53, longitude: -2 },
              ],
              durationMillis: 90_500,
              distanceMeters: 12_345,
            },
          ],
        };
      },
    });

    await expect(router.route({ lat: 52, lon: -1 }, { lat: 53, lon: -2 }, 'DRIVE')).resolves.toEqual({
      path: [
        { lat: 52, lon: -1 },
        { lat: 53, lon: -2 },
      ],
      durationSeconds: 90.5,
      distanceMeters: 12_345,
    });
  });

  it('converts domain and GeoJSON coordinate orders explicitly', () => {
    expect(toGoogleLatLng({ lat: 50.5, lon: -1.25 })).toEqual({ lat: 50.5, lng: -1.25 });
    expect(
      geoJsonToGooglePath({
        type: 'LineString',
        coordinates: [
          [-1.25, 50.5],
          [-1.5, 50.75],
        ],
      }),
    ).toEqual([
      { lat: 50.5, lng: -1.25 },
      { lat: 50.75, lng: -1.5 },
    ]);
  });
});
