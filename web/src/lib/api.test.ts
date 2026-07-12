import { describe, expect, it, vi } from 'vitest';

import { createPoundApi, PoundApiError } from './api';
import type { CanalCandidatesResponse, CanalRouteResponse } from './types';

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
      allow_derelict: false,
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
