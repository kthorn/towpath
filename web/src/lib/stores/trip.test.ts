import { get } from 'svelte/store';
import { describe, expect, it, vi } from 'vitest';

import type { CanalCandidatesResponse, CanalRouteRequest, CanalRouteResponse, LatLon } from '../types';
import type { LandRoute, MapView, SelectedPlace, TransferResult, TransferRouter } from '../google/contracts';
import { createTripStore } from './trip';

const place = (name: string, lat = 51, lon = -1): SelectedPlace => ({ name, address: `${name} address`, coordinate: { lat, lon } });
const response = (revision: string, uids: number[]): CanalCandidatesResponse => ({
  artifact_revision: revision,
  candidates: uids.map((uid, index) => ({
    uid, artifact_revision: revision, coordinate: { lat: 52 + index, lon: -2 - index },
    straight_line_distance_m: 100 + index, display_name: `candidate ${uid}`,
  })),
});
const land: LandRoute = { path: [{ lat: 1, lon: 2 }], durationSeconds: 20, distanceMeters: 30 };
const canal: CanalRouteResponse = { route: { start: 'a', end: 'b', is_ring: false, legs: [], days: [], total_km: 1, total_locks: 0, total_minutes: 2, amenities: [], warnings: [], graph_source_date: 'today' }, geometry: { type: 'LineString', coordinates: [[-1, 51], [-2, 52]] } };

function setup(options: { matrices?: TransferResult[][]; routeError?: Error; map?: MapView } = {}) {
  const canalCandidates = vi.fn(async ({ lat }: LatLon) => lat < 52 ? response('r1', [1, 2]) : response('r1', [3, 4]));
  const canalRoute = vi.fn(async (_request: CanalRouteRequest) => canal);
  const matrices = options.matrices ?? [[
    { available: true, durationSeconds: 20, distanceMeters: 100 },
    { available: true, durationSeconds: 10, distanceMeters: 200 },
  ]];
  let matrixIndex = 0;
  const transferRouter: TransferRouter = {
    matrix: vi.fn(async () => matrices[Math.min(matrixIndex++, matrices.length - 1)]),
    route: vi.fn(async () => { if (options.routeError) throw options.routeError; return land; }),
  };
  const store = createTripStore({ poundApi: { canalCandidates, canalRoute }, transferRouter, mapView: options.map, transferMode: 'WALK' });
  return { store, canalCandidates, canalRoute, transferRouter };
}

describe('trip store', () => {
  it('selects and draws the recommended reachable candidate for both symmetric endpoints', async () => {
    const marker = vi.fn(); const candidates = vi.fn(); const landDraw = vi.fn();
    const map = { marker, candidates, land: landDraw, canal: vi.fn(), onMapClick: vi.fn(), clearLand: vi.fn(), destroy: vi.fn() } as unknown as MapView;
    const { store } = setup({ map });
    await store.setEndpointCoordinate('origin', place('origin', 51));
    await store.setEndpointCoordinate('destination', { lat: 53, lon: -3 });
    const state = get(store);
    expect(state.origin.place?.name).toBe('origin');
    expect(state.destination.place?.coordinate).toEqual({ lat: 53, lon: -3 });
    expect(state.origin.selectedUid).toBe(2);
    expect(state.destination.selectedUid).toBe(4);
    expect(state.origin.landRoute).toEqual(land);
    expect(state.origin.requiresManualConfirmation).toBe(false);
    expect(marker).toHaveBeenCalledWith('origin', { lat: 51, lon: -1 });
    expect(candidates).toHaveBeenCalled();
    expect(landDraw).toHaveBeenCalled();
  });

  it('updates selection and land route on manual override', async () => {
    const { store, transferRouter } = setup();
    await store.setEndpointCoordinate('origin', place('origin'));
    await store.selectCandidate('origin', 1);
    expect(get(store).origin.selectedUid).toBe(1);
    expect(transferRouter.route).toHaveBeenLastCalledWith(place('origin').coordinate, { lat: 52, lon: -2 }, 'WALK');
  });

  it('requires confirmation for all-unavailable geometric fallback', async () => {
    const { store } = setup({ matrices: [[{ available: false, reason: 'none' }, { available: false, reason: 'none' }]] });
    await store.setEndpointCoordinate('origin', place('origin'));
    const endpoint = get(store).origin;
    expect(endpoint.selectedUid).toBe(1);
    expect(endpoint.transferWarning).toMatch(/could not verify/i);
    expect(endpoint.requiresManualConfirmation).toBe(true);
    expect(endpoint.confirmed).toBe(false);
    store.confirmGeometricFallback('origin');
    expect(get(store).origin.confirmed).toBe(true);
  });

  it('retains place and candidates when land routing fails', async () => {
    const clearLand = vi.fn();
    const map = { marker: vi.fn(), candidates: vi.fn(), land: vi.fn(), canal: vi.fn(), onMapClick: vi.fn(), clearLand, destroy: vi.fn() } as unknown as MapView;
    const { store } = setup({ routeError: new Error('land unavailable'), map });
    await store.setEndpointCoordinate('origin', place('origin'));
    expect(get(store).origin).toMatchObject({ selectedUid: 2, landRoute: null });
    expect(get(store).origin.transferWarning).toMatch(/land unavailable/);
    expect(clearLand).toHaveBeenCalledWith('origin');
  });

  it('constructs the exact canal request and draws the route', async () => {
    const drawCanal = vi.fn();
    const map = { marker: vi.fn(), candidates: vi.fn(), land: vi.fn(), canal: drawCanal, onMapClick: vi.fn(), clearLand: vi.fn(), destroy: vi.fn() } as unknown as MapView;
    const { store, canalRoute } = setup({ map });
    await store.setEndpointCoordinate('origin', place('origin', 51));
    await store.setEndpointCoordinate('destination', place('destination', 53));
    const constraints = { days: 4, hours_per_day: 7, boat_beam_m: 2.1, allow_derelict: true };
    await store.planCanalRoute(constraints);
    expect(canalRoute).toHaveBeenCalledWith({ start_uid: 2, end_uid: 4, artifact_revision: 'r1', ...constraints });
    expect(get(store).canalRoute).toEqual(canal);
    expect(drawCanal).toHaveBeenCalledWith(canal.geometry);
  });

  it('rejects mixed revisions before calling the backend', async () => {
    const { store, canalCandidates, canalRoute } = setup();
    canalCandidates.mockResolvedValueOnce(response('old', [1])).mockResolvedValueOnce(response('new', [2]));
    await store.setEndpointCoordinate('origin', place('origin', 51));
    await store.setEndpointCoordinate('destination', place('destination', 53));
    await expect(store.planCanalRoute({})).rejects.toThrow(/revision/i);
    expect(canalRoute).not.toHaveBeenCalled();
  });

  it.each(['canal network disconnected', 'boat constraint violated'])(
    'retains endpoints and records backend error: %s', async (errorText) => {
    const { store, canalRoute } = setup();
    canalRoute.mockRejectedValue(new Error(errorText));
    await store.setEndpointCoordinate('origin', place('origin', 51));
    await store.setEndpointCoordinate('destination', place('destination', 53));
    await expect(store.planCanalRoute({})).rejects.toThrow(errorText);
    expect(get(store).routeError).toContain(errorText);
    expect(get(store).origin.selectedUid).toBe(2);
    expect(get(store).destination.selectedUid).toBe(4);
  });

  it('blocks all-unavailable routing until explicit confirmation', async () => {
    const { store, canalRoute } = setup({ matrices: [
      [{ available: false, reason: 'none' }, { available: false, reason: 'none' }],
      [{ available: true, durationSeconds: 1, distanceMeters: 1 }, { available: false, reason: 'none' }],
    ] });
    await store.setEndpointCoordinate('origin', place('origin', 51));
    await store.setEndpointCoordinate('destination', place('destination', 53));
    await expect(store.planCanalRoute({})).rejects.toThrow(/confirm/i);
    expect(canalRoute).not.toHaveBeenCalled();
    store.confirmGeometricFallback('origin');
    await expect(store.planCanalRoute({})).resolves.toEqual(canal);
  });

  it('ignores stale candidate responses from an older coordinate request', async () => {
    let resolveOld!: (value: CanalCandidatesResponse) => void;
    const { store, canalCandidates } = setup();
    canalCandidates.mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }))
      .mockResolvedValueOnce(response('r1', [9]));
    const old = store.setEndpointCoordinate('origin', place('old', 51));
    const current = store.setEndpointCoordinate('origin', place('new', 52));
    await current;
    resolveOld(response('r1', [1]));
    await old;
    expect(get(store).origin.place?.name).toBe('new');
    expect(get(store).origin.selectedUid).toBe(9);
  });

  it('ignores stale destination candidate responses symmetrically', async () => {
    let resolveOld!: (value: CanalCandidatesResponse) => void;
    const { store, canalCandidates } = setup();
    canalCandidates.mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }))
      .mockResolvedValueOnce(response('r1', [8]));
    const old = store.setEndpointCoordinate('destination', place('old destination', 53));
    const current = store.setEndpointCoordinate('destination', place('new destination', 54));
    await current;
    resolveOld(response('r1', [3]));
    await old;
    expect(get(store).destination.place?.name).toBe('new destination');
    expect(get(store).destination.selectedUid).toBe(8);
  });

  it('ignores stale matrix and land-route responses', async () => {
    let resolveMatrix!: (value: TransferResult[]) => void;
    let resolveLand!: (value: LandRoute) => void;
    const { store, transferRouter } = setup();
    vi.mocked(transferRouter.matrix)
      .mockImplementationOnce(() => new Promise((resolve) => { resolveMatrix = resolve; }))
      .mockResolvedValueOnce([{ available: true, durationSeconds: 1, distanceMeters: 1 }, { available: false, reason: 'x' }]);
    const oldMatrix = store.setEndpointCoordinate('origin', place('old', 51));
    await vi.waitFor(() => expect(transferRouter.matrix).toHaveBeenCalledTimes(1));
    await store.setEndpointCoordinate('origin', place('new', 52));
    resolveMatrix([{ available: true, durationSeconds: 1, distanceMeters: 1 }]);
    await oldMatrix;
    expect(get(store).origin.place?.name).toBe('new');

    vi.mocked(transferRouter.route)
      .mockImplementationOnce(() => new Promise((resolve) => { resolveLand = resolve; }))
      .mockResolvedValueOnce({ ...land, distanceMeters: 999 });
    const oldLand = store.selectCandidate('origin', 3);
    await store.selectCandidate('origin', 4);
    resolveLand({ ...land, distanceMeters: 111 });
    await oldLand;
    expect(get(store).origin.selectedUid).toBe(4);
    expect(get(store).origin.landRoute?.distanceMeters).toBe(999);
  });

  it('swallows map failures while retaining usable state', async () => {
    const failing = () => { throw new Error('map failed'); };
    const map = { marker: failing, candidates: failing, land: failing, canal: failing, onMapClick: vi.fn(), clearLand: vi.fn(), destroy: vi.fn() } as unknown as MapView;
    const { store } = setup({ map });
    await expect(store.setEndpointCoordinate('origin', place('origin'))).resolves.toBeUndefined();
    expect(get(store).origin.selectedUid).toBe(2);
    expect(get(store).origin.transferWarning).toMatch(/map failed/);
  });

  it('lets the newest canal request win when responses arrive out of order', async () => {
    let resolveOld!: (value: CanalRouteResponse) => void;
    let resolveNew!: (value: CanalRouteResponse) => void;
    const draw = vi.fn();
    const map = { marker: vi.fn(), candidates: vi.fn(), land: vi.fn(), canal: draw, onMapClick: vi.fn(), clearLand: vi.fn(), destroy: vi.fn() } as unknown as MapView;
    const { store, canalRoute } = setup({ map });
    await store.setEndpointCoordinate('origin', place('origin', 51));
    await store.setEndpointCoordinate('destination', place('destination', 53));
    draw.mockClear();
    canalRoute
      .mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }))
      .mockImplementationOnce(() => new Promise((resolve) => { resolveNew = resolve; }));
    const oldPlan = store.planCanalRoute({ days: 1 });
    const newPlan = store.planCanalRoute({ days: 2 });
    const newer = { ...canal, route: { ...canal.route, total_km: 22 } };
    resolveNew(newer);
    await newPlan;
    resolveOld(canal);
    await oldPlan;
    expect(get(store).canalRoute).toEqual(newer);
    expect(draw).toHaveBeenCalledTimes(1);
    expect(draw).toHaveBeenCalledWith(newer.geometry);
  });

  it('invalidates an in-flight canal route when either endpoint changes', async () => {
    let resolveRoute!: (value: CanalRouteResponse) => void;
    const draw = vi.fn();
    const map = { marker: vi.fn(), candidates: vi.fn(), land: vi.fn(), canal: draw, onMapClick: vi.fn(), clearLand: vi.fn(), destroy: vi.fn() } as unknown as MapView;
    const { store, canalRoute } = setup({ map });
    await store.setEndpointCoordinate('origin', place('origin', 51));
    await store.setEndpointCoordinate('destination', place('destination', 53));
    draw.mockClear();
    canalRoute.mockImplementationOnce(() => new Promise((resolve) => { resolveRoute = resolve; }));
    const pending = store.planCanalRoute({});
    await store.setEndpointCoordinate('destination', place('new destination', 54));
    resolveRoute(canal);
    await pending;
    expect(get(store).canalRoute).toBeNull();
    expect(draw).toHaveBeenCalledTimes(1);
    expect(draw).toHaveBeenCalledWith(null);
  });

  it('initializes required selections as null and clears stale land for destination changes', async () => {
    const clearLand = vi.fn();
    const map = { marker: vi.fn(), candidates: vi.fn(), land: vi.fn(), canal: vi.fn(), onMapClick: vi.fn(), clearLand, destroy: vi.fn() } as unknown as MapView;
    const { store } = setup({ map });
    expect(get(store).origin.selectedUid).toBeNull();
    expect(get(store).destination.selectedUid).toBeNull();
    await store.setEndpointCoordinate('destination', place('destination', 53));
    await store.selectCandidate('destination', 3);
    expect(clearLand).toHaveBeenCalledWith('destination');
    expect(get(store).destination.selectedUid).toBe(3);
  });

  it('turns a land-overlay clear failure into a warning without losing endpoint state', async () => {
    const map = { marker: vi.fn(), candidates: vi.fn(), land: vi.fn(), canal: vi.fn(), onMapClick: vi.fn(), clearLand: () => { throw new Error('clear failed'); }, destroy: vi.fn() } as unknown as MapView;
    const { store } = setup({ map });
    await store.setEndpointCoordinate('destination', place('destination', 53));
    expect(get(store).destination.selectedUid).toBe(4);
    expect(get(store).destination.transferWarning).toMatch(/clear failed/);
  });
});
