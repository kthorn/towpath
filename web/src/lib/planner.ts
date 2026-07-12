import type { TransferResult } from './google/contracts';
import type { CanalCandidate } from './types';

export type RankedCandidate = (TransferResult & {
  candidate: CanalCandidate;
  recommended: boolean;
  geometricIndex: number;
});

export function rankCandidates(
  candidates: CanalCandidate[],
  matrix: TransferResult[],
): RankedCandidate[] {
  const ranked = candidates.map((candidate, geometricIndex): RankedCandidate => ({
    candidate,
    geometricIndex,
    recommended: false,
    ...(matrix[geometricIndex] ?? { available: false, reason: 'NO_RESULT' }),
  }));
  ranked.sort((left, right) => {
    if (left.available !== right.available) return left.available ? -1 : 1;
    if (!left.available || !right.available) return left.geometricIndex - right.geometricIndex;
    return (
      left.durationSeconds - right.durationSeconds ||
      left.distanceMeters - right.distanceMeters ||
      left.geometricIndex - right.geometricIndex
    );
  });
  if (ranked[0]) ranked[0].recommended = true;
  return ranked;
}
