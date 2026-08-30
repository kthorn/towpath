import { describe, expect, it } from 'vitest';

import type { CanalCandidate } from './types';
import { rankCandidates } from './planner';

const candidates: CanalCandidate[] = [
  { candidate_id: 'candidate-1', handle: { edge: [1, 2], fraction: 0.5 }, coordinate: { lat: 1, lon: 1 }, straight_line_distance_m: 10, display_name: 'one' },
  { candidate_id: 'candidate-2', handle: { edge: [2, 3], fraction: 0.5 }, coordinate: { lat: 2, lon: 2 }, straight_line_distance_m: 20, display_name: 'two' },
  { candidate_id: 'candidate-3', handle: { edge: [3, 4], fraction: 0.5 }, coordinate: { lat: 3, lon: 3 }, straight_line_distance_m: 30, display_name: 'three' },
  { candidate_id: 'candidate-4', handle: { edge: [4, 5], fraction: 0.5 }, coordinate: { lat: 4, lon: 4 }, straight_line_distance_m: 40, display_name: 'four' },
];

describe('rankCandidates', () => {
  it('ranks reachable candidates by duration, distance, then geometric index', () => {
    const ranked = rankCandidates(candidates, [
      { available: true, durationSeconds: 20, distanceMeters: 100 },
      { available: false, reason: 'closed' },
      { available: true, durationSeconds: 10, distanceMeters: 200 },
      { available: true, durationSeconds: 10, distanceMeters: 200 },
    ]);

    expect(ranked.map(({ candidate }) => candidate.candidate_id)).toEqual(['candidate-3', 'candidate-4', 'candidate-1', 'candidate-2']);
    expect(ranked.map(({ recommended }) => recommended)).toEqual([true, false, false, false]);
    expect(ranked[0]).toMatchObject({ available: true, durationSeconds: 10, distanceMeters: 200 });
    expect(ranked[3]).toMatchObject({ available: false, reason: 'closed' });
  });

  it('preserves all geometric candidates and treats missing matrix results as unavailable', () => {
    const ranked = rankCandidates(candidates, [{ available: true, durationSeconds: 5, distanceMeters: 8 }]);
    expect(ranked.map(({ candidate }) => candidate.candidate_id)).toEqual(['candidate-1', 'candidate-2', 'candidate-3', 'candidate-4']);
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
    expect(ranked.map(({ candidate }) => candidate.candidate_id)).toEqual(['candidate-1', 'candidate-2', 'candidate-3']);
    expect(ranked.map(({ recommended }) => recommended)).toEqual([true, false, false]);
  });
});
