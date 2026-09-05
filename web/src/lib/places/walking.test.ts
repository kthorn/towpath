import { describe, expect, it, vi } from 'vitest';

import type { LandRoute, TransferResult, TransferRouter } from '../google/contracts';
import type { CanalCandidate, LatLon } from '../types';
import { checkedWalkingRoutes, checkWalkingAccess } from './walking';

const attraction: LatLon = { lat: 52, lon: -1 };

function candidate(candidate_id: string, lat = 52.01): CanalCandidate {
  return {
    candidate_id,
    handle: { edge: [1, 2], fraction: 0.5 },
    coordinate: { lat, lon: -1.01 },
    straight_line_distance_m: 100,
    display_name: candidate_id,
  };
}

function available(durationSeconds: number, distanceMeters = durationSeconds * 10): TransferResult {
  return { available: true, durationSeconds, distanceMeters };
}

function unavailable(reason = 'UNAVAILABLE'): TransferResult {
  return { available: false, reason };
}

function router(overrides: Partial<TransferRouter> = {}): TransferRouter {
  return {
    matrix: vi.fn(async (_origin, destinations) => destinations.map(() => available(10))),
    route: vi.fn(async () => ({
      path: [attraction],
      durationSeconds: 10,
      distanceMeters: 100,
    })),
    ...overrides,
  };
}

describe('walking access', () => {
  it('checks both directed walks and sorts complete candidates by total duration', async () => {
    const c1 = candidate('c1', 52.01);
    const c2 = candidate('c2', 52.02);
    const c3 = candidate('c3', 52.03);
    const matrix = vi.fn(async (origin: LatLon, destinations: LatLon[]) => {
      if (origin === attraction) return [available(40), unavailable('matrix-missing'), available(10)];
      const duration = destinations[0] === attraction ? ({ 52.01: 20, 52.02: 3, 52.03: 6 } as Record<number, number>)[origin.lat] : 99;
      return [available(duration)];
    });
    const transferRouter = router({ matrix });

    const result = await checkWalkingAccess(attraction, [c1, c2, c3], transferRouter);

    expect(matrix).toHaveBeenCalledTimes(4);
    expect(matrix).toHaveBeenNthCalledWith(1, attraction, [c1.coordinate, c2.coordinate, c3.coordinate], 'WALK');
    expect(matrix).toHaveBeenCalledWith(c1.coordinate, [attraction], 'WALK');
    expect(matrix).toHaveBeenCalledWith(c2.coordinate, [attraction], 'WALK');
    expect(matrix).toHaveBeenCalledWith(c3.coordinate, [attraction], 'WALK');
    expect(result.map(({ candidate: item, outward, return: inbound, complete }) => ({
      id: item.candidate_id,
      outward,
      return: inbound,
      complete,
    }))).toEqual([
      { id: 'c3', outward: available(6), return: available(10), complete: true },
      { id: 'c1', outward: available(20), return: available(40), complete: true },
      { id: 'c2', outward: available(3), return: unavailable(), complete: false },
    ]);
  });

  it('caps work at five candidates while preserving missing and failed directions', async () => {
    const candidates = Array.from({ length: 7 }, (_, index) => candidate(`c${index + 1}`, 52 + index / 100));
    const matrix = vi.fn(async (origin: LatLon, destinations: LatLon[]) => {
      if (origin === attraction) return [available(1), available(2), available(3), available(4), available(5)];
      if (origin === candidates[1].coordinate) throw new Error('provider details');
      return destinations.length ? [available(1)] : [];
    });
    const transferRouter = router({ matrix });

    const result = await checkWalkingAccess(attraction, candidates, transferRouter);

    expect(result).toHaveLength(5);
    expect(result.map(({ candidate: item }) => item.candidate_id)).toEqual(['c1', 'c3', 'c4', 'c5', 'c2']);
    expect(result.find(({ candidate: item }) => item.candidate_id === 'c2')?.outward).toEqual(
      unavailable(),
    );
    expect(matrix).toHaveBeenCalledTimes(6);
  });

  it('rejects invalid coordinates and duplicate candidate identities', async () => {
    const transferRouter = router();

    await expect(checkWalkingAccess({ lat: Number.NaN, lon: 0 }, [], transferRouter)).rejects.toThrow(/coordinate/i);
    await expect(
      checkWalkingAccess(attraction, [candidate('same'), candidate('same', 52.02)], transferRouter),
    ).rejects.toThrow(/candidate_id/i);
    expect(transferRouter.matrix).not.toHaveBeenCalled();
  });

  it('accepts legal coordinate bounds and rejects out-of-range latitude or longitude', async () => {
    const transferRouter = router();
    const bounded = [
      { ...candidate('north-east'), coordinate: { lat: 90, lon: 180 } },
      { ...candidate('south-west'), coordinate: { lat: -90, lon: -180 } },
    ];

    await expect(checkWalkingAccess({ lat: 0, lon: 0 }, bounded, transferRouter)).resolves.toHaveLength(2);
    await expect(checkWalkingAccess({ lat: 90.001, lon: 0 }, [], transferRouter)).rejects.toThrow(/coordinate/i);
    await expect(checkWalkingAccess({ lat: 0, lon: -180.001 }, [], transferRouter)).rejects.toThrow(/coordinate/i);
    await expect(
      checkWalkingAccess(attraction, [{ ...candidate('bad-lat'), coordinate: { lat: -90.001, lon: 0 } }], transferRouter),
    ).rejects.toThrow(/coordinate/i);
    await expect(
      checkWalkingAccess(attraction, [{ ...candidate('bad-lon'), coordinate: { lat: 0, lon: 180.001 } }], transferRouter),
    ).rejects.toThrow(/coordinate/i);
  });

  it('turns malformed numeric results into generic unavailable outcomes', async () => {
    const c1 = candidate('c1');
    const matrix = vi.fn(async (origin: LatLon): Promise<TransferResult[]> => {
      if (origin === attraction) {
        return [
          { available: true, durationSeconds: Number.NaN, distanceMeters: 10 },
        ];
      }
      return [{ available: true, durationSeconds: 4, distanceMeters: Number.POSITIVE_INFINITY }];
    });
    const result = await checkWalkingAccess(attraction, [c1], router({ matrix }));

    expect(result[0]?.return).toEqual(unavailable('INVALID_RESULT'));
    expect(result[0]?.outward).toEqual(unavailable('INVALID_RESULT'));
    expect(JSON.stringify(result)).not.toContain('NaN');
  });

  it('bounds each provider call and returns unavailable results after timeout', async () => {
    vi.useFakeTimers();
    try {
      const c1 = candidate('c1');
      const matrix = vi.fn(async (): Promise<TransferResult[]> => new Promise(() => undefined));
      const pending = checkWalkingAccess(attraction, [c1], router({ matrix }), { timeoutMs: 5 });
      await vi.advanceTimersByTimeAsync(15);

      await expect(pending).resolves.toEqual([
        { candidate: c1, outward: unavailable(), return: unavailable(), complete: false },
      ]);
      expect(matrix).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it('does not launch queued reverse checks after cancellation', async () => {
    const controller = new AbortController();
    const candidates = Array.from({ length: 5 }, (_, index) => candidate(`c${index + 1}`, 52 + index / 100));
    let releaseFirst!: () => void;
    let releaseSecond!: () => void;
    let calls = 0;
    const matrix = vi.fn(async (origin: LatLon, destinations: LatLon[]) => {
      if (origin === attraction) return destinations.map(() => available(1));
      calls += 1;
      await new Promise<void>((resolve) => {
        if (calls === 1) releaseFirst = resolve;
        else releaseSecond = resolve;
      });
      return [available(1)];
    });
    const pending = checkWalkingAccess(attraction, candidates, router({ matrix }), { signal: controller.signal });
    await vi.waitFor(() => expect(matrix).toHaveBeenCalledTimes(3));
    controller.abort();
    releaseFirst();
    releaseSecond();

    await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
    expect(matrix).toHaveBeenCalledTimes(3);
  });

  it('checks detailed routes in both directions and validates paths', async () => {
    const c1 = candidate('c1');
    const outward: LandRoute = {
      path: [c1.coordinate, attraction],
      durationSeconds: 20,
      distanceMeters: 200,
    };
    const inbound: LandRoute = {
      path: [attraction, c1.coordinate],
      durationSeconds: 30,
      distanceMeters: 300,
    };
    const route = vi.fn(async (origin: LatLon, destination: LatLon) => origin === c1.coordinate ? outward : inbound);
    const transferRouter = router({ route });

    await expect(checkedWalkingRoutes(attraction, c1, transferRouter)).resolves.toEqual({
      outward,
      return: inbound,
    });
    expect(route).toHaveBeenNthCalledWith(1, c1.coordinate, attraction, 'WALK');
    expect(route).toHaveBeenNthCalledWith(2, attraction, c1.coordinate, 'WALK');

    await expect(checkedWalkingRoutes(attraction, c1, router({
      route: vi.fn(async () => ({ ...outward, path: [{ lat: Number.NaN, lon: 0 }] })),
    }))).rejects.toThrow(/route/i);

    await expect(checkedWalkingRoutes(attraction, c1, router({
      route: vi.fn(async () => ({ ...outward, durationSeconds: -1 })),
    }))).rejects.toThrow(/route/i);
    await expect(checkedWalkingRoutes(attraction, c1, router({
      route: vi.fn(async () => ({ ...outward, path: Array.from({ length: 10_001 }, () => attraction) })),
    }))).rejects.toThrow(/route/i);
    await expect(checkedWalkingRoutes(attraction, c1, router({
      route: vi.fn(async () => ({ ...outward, path: Array.from({ length: 10_000 }, () => attraction) })),
    }))).resolves.toBeTruthy();
  });
});
