import { describe, expect, it } from 'vitest';

import type { CanalCandidate } from './types';
import { rankCandidates } from './planner';

const candidates: CanalCandidate[] = [
  { uid: 1, artifact_revision: 'r1', coordinate: { lat: 1, lon: 1 }, straight_line_distance_m: 10, display_name: 'one' },
  { uid: 2, artifact_revision: 'r1', coordinate: { lat: 2, lon: 2 }, straight_line_distance_m: 20, display_name: 'two' },
  { uid: 3, artifact_revision: 'r1', coordinate: { lat: 3, lon: 3 }, straight_line_distance_m: 30, display_name: 'three' },
  { uid: 4, artifact_revision: 'r1', coordinate: { lat: 4, lon: 4 }, straight_line_distance_m: 40, display_name: 'four' },
];

describe('rankCandidates', () => {
  it('ranks reachable candidates by duration, distance, then geometric index', () => {
    const ranked = rankCandidates(candidates, [
      { available: true, durationSeconds: 20, distanceMeters: 100 },
      { available: false, reason: 'closed' },
      { available: true, durationSeconds: 10, distanceMeters: 200 },
      { available: true, durationSeconds: 10, distanceMeters: 200 },
    ]);

    expect(ranked.map(({ candidate }) => candidate.uid)).toEqual([3, 4, 1, 2]);
    expect(ranked.map(({ recommended }) => recommended)).toEqual([true, false, false, false]);
    expect(ranked[0]).toMatchObject({ available: true, durationSeconds: 10, distanceMeters: 200 });
    expect(ranked[3]).toMatchObject({ available: false, reason: 'closed' });
  });

  it('preserves all geometric candidates and treats missing matrix results as unavailable', () => {
    const ranked = rankCandidates(candidates, [{ available: true, durationSeconds: 5, distanceMeters: 8 }]);
    expect(ranked.map(({ candidate }) => candidate.uid)).toEqual([1, 2, 3, 4]);
    expect(ranked.slice(1).map((item) => item.available ? undefined : item.reason)).toEqual([
      'NO_RESULT', 'NO_RESULT', 'NO_RESULT',
    ]);
  });

  it('keeps unavailable candidates in geometric order and provisionally recommends the first', () => {
    const ranked = rankCandidates(candidates.slice(0, 3), [
      { available: false, reason: 'a' },
      { available: false, reason: 'b' },
      { available: false, reason: 'c' },
      { available: true, durationSeconds: 1, distanceMeters: 1 },
    ]);
    expect(ranked.map(({ candidate }) => candidate.uid)).toEqual([1, 2, 3]);
    expect(ranked.map(({ recommended }) => recommended)).toEqual([true, false, false]);
  });
});
