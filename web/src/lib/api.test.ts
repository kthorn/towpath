import { describe, expect, it, vi } from 'vitest';

import { createPoundApi, PoundApiError } from './api';
import type {
  CanalCandidatesResponse,
  CanalRouteResponse,
  CatalogPlacesRequest,
  CatalogPlacesResponse,
  HealthResponse,
  RoutePoisRequest,
  RoutePoisResponse,
} from './types';

const candidatesResponse: CanalCandidatesResponse = {
  artifact_revision: 'artifact-123',
  candidates: [
    {
      uid: 42,
      artifact_revision: 'artifact-123',
      coordinate: { lat: 51.997, lon: -0.742 },
      straight_line_distance_m: 125.5,
      display_name: 'Grand Union Canal',
    },
  ],
};

const routeResponse: CanalRouteResponse = {
  route: {
    start: 'A',
    end: 'B',
    is_ring: false,
    legs: [
      {
        from_place: 'A',
        to_place: 'B',
        distance_km: 3.2,
        locks: 1,
        est_minutes: 70,
        flagged_unknown_dims: false,
      },
    ],
    days: [
      {
        day: 1,
        legs: [],
        end_near: 'B',
        cruising_minutes: 70,
      },
    ],
    total_km: 3.2,
    total_locks: 1,
    total_minutes: 70,
    amenities: [
      {
        kind: 'pub',
        name: null,
        lat: 52.0,
        lon: -0.7,
        distance_m: 25,
        source: 'osm',
      },
    ],
    warnings: [],
    graph_source_date: '2026-07-11',
  },
  geometry: {
    type: 'LineString',
    coordinates: [
      [-0.742, 51.997],
      [-0.7, 52.0],
    ],
  },
};

describe('createPoundApi', () => {
  it('posts coordinates and parses canal candidates', async () => {
    const fetchFn = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify(candidatesResponse), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const result = await createPoundApi(fetchFn).canalCandidates({ lat: 51.997, lon: -0.742 });

    expect(result).toEqual(candidatesResponse);
    expect(fetchFn).toHaveBeenCalledWith('/api/canal-candidates', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ lat: 51.997, lon: -0.742 }),
    });
  });

  it('posts route constraints and parses the complete route response', async () => {
    const request = {
      start_uid: 42,
      end_uid: 84,
      artifact_revision: 'artifact-123',
      days: 2,
      hours_per_day: 6,
      boat_length_m: 17.5,
      boat_beam_m: null,
      boat_draft_m: null,
      boat_height_m: null,
    };
    const fetchFn = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify(routeResponse), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const result = await createPoundApi(fetchFn).canalRoute(request);

    expect(result).toEqual(routeResponse);
    expect(fetchFn).toHaveBeenCalledWith('/api/canal-route', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    });
  });

  it('preserves structured Pound API errors', async () => {
    const fetchFn = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: {
            code: 'artifact_revision_mismatch',
            message: 'Refresh candidates.',
            fields: ['artifact_revision'],
          },
        }),
        { status: 409, headers: { 'Content-Type': 'application/json' } },
      ),
    );

    const promise = createPoundApi(fetchFn).canalCandidates({ lat: 0, lon: 0 });

    await expect(promise).rejects.toMatchObject({
      status: 409,
      code: 'artifact_revision_mismatch',
      message: 'Refresh candidates.',
      fields: ['artifact_revision'],
    });
    await expect(promise).rejects.toBeInstanceOf(PoundApiError);
  });

  it('posts route POI queries and returns the typed response', async () => {
    const response: RoutePoisResponse = {
      pois: [],
      zoom_in_required: false,
      matching_count: 0,
      day: null,
    };
    const request: RoutePoisRequest = {
      artifact_revision: 'rev',
      kinds: ['pub'],
      bounds: { south: 50, west: -2, north: 52, east: 0 },
      route_geometry: { type: 'LineString', coordinates: [[-1, 51], [-1.1, 51.1]] },
    };
    const fetchFn = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify(response), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const result = await createPoundApi(fetchFn).routePois(request);

    expect(result).toEqual(response);
    expect(fetchFn).toHaveBeenCalledWith('/api/route-pois', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    });
  });

  it('posts catalog queries with revision, policy, bounds, and rich metadata', async () => {
    const response: CatalogPlacesResponse = {
      catalog_revision: 'catalog-456',
      places: [{
        identity: 'node/123',
        kind: 'museum',
        name: 'Canal Museum',
        coordinate: { lat: 51.5, lon: -1.2 },
        waterway_distance_m: 45,
        distance_to_full_route_m: 100,
        distance_to_selected_geometry_m: null,
        metadata: {
          name: 'Canal Museum', alt_name: null, brand: null, operator: 'Canal Trust',
          address: { house_number: '1', street: 'Towpath', place: null, city: 'Oxford', postcode: 'OX1' },
          opening_hours: 'Mo-Su 10:00-17:00', access: null, fee: 'yes', wheelchair: 'yes',
          phone: null, email: null, description: 'A museum',
          links: [{ label: 'Website', url: 'https://example.test/museum' }], kind_details: { tourism: 'museum' },
        },
      }],
      matching_count: 1,
      over_cap: false,
      day: null,
    };
    const request: CatalogPlacesRequest = {
      catalog_revision: 'catalog-456',
      kinds: ['museum'],
      bounds: { south: 51, west: -2, north: 52, east: 0 },
      route_geometry: { type: 'LineString', coordinates: [[-1, 51], [-1.2, 51.5]] },
      policy: { basis: 'waterway', radius_m: 2_000 },
    };
    const fetchFn = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify(response), { status: 200, headers: { 'Content-Type': 'application/json' } }),
    );

    const result = await createPoundApi(fetchFn).catalogPlaces(request);

    expect(result).toEqual(response);
    expect(fetchFn).toHaveBeenCalledWith('/api/catalog-places', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(request),
    });
  });

  it('gets independent artifact and catalog health status', async () => {
    const response: HealthResponse = {
      status: 'degraded', artifact_revision: 'artifact-123', catalog_revision: 'catalog-456', catalog_status: 'available',
    };
    const fetchFn = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify(response), { status: 200, headers: { 'Content-Type': 'application/json' } }),
    );

    await expect(createPoundApi(fetchFn).health()).resolves.toEqual(response);
    expect(fetchFn).toHaveBeenCalledWith('/api/health', { method: 'GET' });
  });

  it('preserves structured catalog unavailable and revision mismatch errors', async () => {
    const request: CatalogPlacesRequest = {
      catalog_revision: 'catalog-456', kinds: ['pub'],
      bounds: { south: 51, west: -2, north: 52, east: 0 }, policy: { basis: 'none' },
    };
    const unavailable = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify({
      detail: { code: 'catalog_unavailable', message: 'Catalog is not loaded.', fields: [] },
    }), { status: 503, headers: { 'Content-Type': 'application/json' } }));
    await expect(createPoundApi(unavailable).catalogPlaces(request)).rejects.toMatchObject({
      status: 503, code: 'catalog_unavailable', message: 'Catalog is not loaded.', fields: [],
    });

    const mismatch = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify({
      detail: { code: 'catalog_revision_mismatch', message: 'Refresh catalog health.', fields: ['catalog_revision'] },
    }), { status: 409, headers: { 'Content-Type': 'application/json' } }));
    await expect(createPoundApi(mismatch).catalogPlaces(request)).rejects.toMatchObject({
      status: 409, code: 'catalog_revision_mismatch', fields: ['catalog_revision'],
    });
  });

  it('uses a safe fallback for non-JSON errors', async () => {
    const fetchFn = vi.fn<typeof fetch>().mockResolvedValue(
      new Response('<html>Bad gateway</html>', {
        status: 502,
        statusText: 'Bad Gateway',
        headers: { 'Content-Type': 'text/html' },
      }),
    );

    await expect(
      createPoundApi(fetchFn).canalCandidates({ lat: 0, lon: 0 }),
    ).rejects.toMatchObject({
      status: 502,
      code: 'http_error',
      message: 'Bad Gateway',
      fields: [],
    });
  });
});
