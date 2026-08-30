import { get } from 'svelte/store';
import { describe, expect, it, vi } from 'vitest';

import { PoundApiError } from '../api';
import type {
  BoatHireBase,
  CanalCandidatesResponse,
  CanalNetworkRequest,
  CanalNetworkResponse,
  CanalRouteRequest,
  CanalRouteResponse,
  HealthResponse,
  PlaceResponse,
  PlacesResponse,
  LatLon,
  MapBounds,
  RoutePoisResponse,
} from '../types';
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
const canal: CanalRouteResponse = { route: { start: 'a', end: 'b', is_ring: false, legs: [], days: [], total_km: 1, total_locks: 0, total_minutes: 2, amenities: [], warnings: [], access_segments: [], graph_source_date: 'today' }, geometry: { type: 'LineString', coordinates: [[-1, 51], [-2, 52]] } };
const networkRequest = (days = 7): CanalNetworkRequest => ({
  days, hours_per_day: 6,
  boat_length_m: null, boat_beam_m: null, boat_draft_m: null,
  boat_height_m: null, movable_bridge_delay_min: null,
});
const hireBase = (identity = 'base-one'): BoatHireBase => ({
  identity, operator: 'Canal Holidays', name: identity, coordinate: { lat: 51, lon: -1 },
});
const networkResponse = (identity = 'base-one', lines = [{
  type: 'LineString' as const, coordinates: [[-1, 51], [-2, 52]] as [number, number][],
}]): CanalNetworkResponse => ({ artifact_revision: 'r1', lines, bases: [hireBase(identity)] });
const placeResponse = (osmType: 'node' | 'way' | 'relation', osmId: number, kind: string): PlaceResponse => ({
  kind, name: kind, coordinate: { lat: 51.2, lon: -1.2 },
  target_id: null, distance_to_target_m: null,
  waterway_distance_m: 20, distance_to_full_route_m: 30, distance_to_selected_geometry_m: null,
  provenance: {
    source: 'osm', osm_type: osmType, osm_id: osmId,
    metadata: { name: kind, alt_name: null, brand: null, operator: null, address: null, opening_hours: null,
      access: null, fee: null, wheelchair: null, phone: null, email: null, description: null, links: [], kind_details: {} },
  },
});

const boatHirePlace = (providerId: string, locationId: string): PlaceResponse => ({
  kind: 'boat_hire', name: locationId, coordinate: { lat: 51.2, lon: -1.2 },
  target_id: null, distance_to_target_m: null,
  waterway_distance_m: 20, distance_to_full_route_m: 30, distance_to_selected_geometry_m: null,
  provenance: {
    source: 'boat_hire', provider_id: providerId, provider_name: providerId,
    location_id: locationId, location_name: locationId,
    provider_url: null, osm_url: null, evidence_url: null, booking_url: null,
  },
});

function viewportMap(setCallback: (callback: (bounds: MapBounds) => void) => void): MapView {
  return {
    marker: vi.fn(), candidates: vi.fn(), land: vi.fn(), canal: vi.fn(), network: vi.fn(), hireBases: vi.fn(), fitNetwork: vi.fn(), places: vi.fn(), pois: vi.fn(), locks: vi.fn(), day: vi.fn(),
    clearLand: vi.fn(), closeInfoWindow: vi.fn(), destroy: vi.fn(), onMapClick: vi.fn(() => vi.fn()),
    onViewportIdle: vi.fn((callback) => { setCallback(callback); return vi.fn(); }),
  };
}

function setup(options: {
  matrices?: TransferResult[][];
  routeError?: Error;
  map?: MapView;
  canalNetwork?: (request: CanalNetworkRequest) => Promise<CanalNetworkResponse>;
  routePois?: (request: unknown) => Promise<RoutePoisResponse>;
  places?: (request: unknown) => Promise<PlacesResponse>;
  placesHealth?: () => Promise<HealthResponse>;
} = {}) {
  const canalCandidates = vi.fn(async ({ lat }: LatLon) => lat < 52 ? response('r1', [1, 2]) : response('r1', [3, 4]));
  const canalNetwork = options.canalNetwork ?? vi.fn(async (_request: CanalNetworkRequest) => networkResponse());
  const canalRoute = vi.fn(async (_request: CanalRouteRequest) => canal);
  const routePois = options.routePois ?? vi.fn(async () => ({ pois: [], zoom_in_required: false, matching_count: 0, day: null }));
  const places = options.places ?? vi.fn(async () => ({ places: [] }));
  const placesHealth = options.placesHealth ?? vi.fn(async () => ({ status: 'healthy', artifact_revision: 'r1', places_status: 'available' as const }));
  const matrices = options.matrices ?? [[
    { available: true, durationSeconds: 20, distanceMeters: 100 },
    { available: true, durationSeconds: 10, distanceMeters: 200 },
  ]];
  let matrixIndex = 0;
  const transferRouter: TransferRouter = {
    matrix: vi.fn(async () => matrices[Math.min(matrixIndex++, matrices.length - 1)]),
    route: vi.fn(async () => { if (options.routeError) throw options.routeError; return land; }),
  };
  const store = createTripStore({ poundApi: { canalCandidates, canalNetwork, canalRoute, routePois, places, health: placesHealth }, transferRouter, mapView: options.map, transferMode: 'WALK' });
  return { store, canalCandidates, canalNetwork, canalRoute, transferRouter, places, placesHealth };
}

describe('trip store', () => {
  it('posts the current request and paints lines and bases when a map attaches', async () => {
    const request = networkRequest();
    const network = networkResponse();
    const map = viewportMap(() => {});
    const canalNetwork = vi.fn(async (_request: CanalNetworkRequest) => network);
    const { store } = setup({ canalNetwork });

    store.setNetworkRequest(request);
    expect(canalNetwork).not.toHaveBeenCalled();
    store.setMapView(map);

    await vi.waitFor(() => expect(map.network).toHaveBeenCalledWith(network.lines));
    expect(canalNetwork).toHaveBeenCalledOnce();
    expect(canalNetwork).toHaveBeenCalledWith(request);
    expect(map.hireBases).toHaveBeenCalledWith(network.bases);
    expect(map.fitNetwork).toHaveBeenCalledOnce();
    expect(get(store)).toMatchObject({ hasNetworkOverlay: true, networkError: null });
  });

  it('posts once per current generation and ignores older network responses', async () => {
    vi.useFakeTimers();
    try {
      let resolveOlder!: (value: CanalNetworkResponse) => void;
      let resolveNewer!: (value: CanalNetworkResponse) => void;
      const older = networkResponse('older');
      const newer = networkResponse('newer', [{
        type: 'LineString' as const, coordinates: [[-3, 53], [-4, 54]] as [number, number][],
      }]);
      const canalNetwork = vi.fn()
        .mockImplementationOnce(() => new Promise<CanalNetworkResponse>((resolve) => { resolveOlder = resolve; }))
        .mockImplementationOnce(() => new Promise<CanalNetworkResponse>((resolve) => { resolveNewer = resolve; }));
      const map = viewportMap(() => {});
      const { store } = setup({ canalNetwork });
      const first = networkRequest(7);
      const second = networkRequest(8);

      store.setMapView(map);
      store.setNetworkRequest(first);
      expect(canalNetwork).not.toHaveBeenCalled();
      await vi.advanceTimersByTimeAsync(100);
      expect(canalNetwork).toHaveBeenCalledOnce();
      store.setNetworkRequest(second);
      await vi.advanceTimersByTimeAsync(100);
      expect(canalNetwork).toHaveBeenCalledTimes(2);
      expect(canalNetwork).toHaveBeenNthCalledWith(1, first);
      expect(canalNetwork).toHaveBeenNthCalledWith(2, second);

      resolveNewer(newer);
      await vi.waitFor(() => expect(map.network).toHaveBeenLastCalledWith(newer.lines));
      resolveOlder(older);
      await Promise.resolve();

      expect(map.network).toHaveBeenCalledTimes(1);
      expect(map.hireBases).toHaveBeenLastCalledWith(newer.bases);
    } finally {
      vi.useRealTimers();
    }
  });

  it('does not draw to a detached map and replays a matching cached payload on attach', async () => {
    vi.useFakeTimers();
    try {
      let resolveNetwork!: (value: CanalNetworkResponse) => void;
      const network = networkResponse();
      const canalNetwork = vi.fn(() => new Promise<CanalNetworkResponse>((resolve) => { resolveNetwork = resolve; }));
      const firstMap = viewportMap(() => {});
      const secondMap = viewportMap(() => {});
      const { store } = setup({ canalNetwork });

      store.setMapView(firstMap);
      store.setNetworkRequest(networkRequest());
      await vi.advanceTimersByTimeAsync(100);
      expect(canalNetwork).toHaveBeenCalledOnce();
      store.setMapView(undefined);
      resolveNetwork(network);
      await Promise.resolve();

      expect(firstMap.network).not.toHaveBeenCalled();
      expect(firstMap.hireBases).not.toHaveBeenCalled();
      expect(firstMap.fitNetwork).not.toHaveBeenCalled();
      store.setMapView(secondMap);
      await vi.waitFor(() => expect(secondMap.network).toHaveBeenCalledWith(network.lines));
      expect(canalNetwork).toHaveBeenCalledOnce();
      expect(secondMap.hireBases).toHaveBeenCalledWith(network.bases);
      expect(secondMap.fitNetwork).toHaveBeenCalledOnce();
    } finally {
      vi.useRealTimers();
    }
  });

  it('fetches a changed request when a map attaches after being detached', async () => {
    const first = networkResponse('first');
    const second = networkResponse('second');
    const firstMap = viewportMap(() => {});
    const secondMap = viewportMap(() => {});
    const canalNetwork = vi.fn()
      .mockResolvedValueOnce(first)
      .mockResolvedValueOnce(second);
    const { store } = setup({ canalNetwork });

    store.setNetworkRequest(networkRequest(7));
    store.setMapView(firstMap);
    await vi.waitFor(() => expect(firstMap.network).toHaveBeenCalledWith(first.lines));
    store.setMapView(undefined);
    store.setNetworkRequest(networkRequest(8));
    expect(canalNetwork).toHaveBeenCalledOnce();
    store.setMapView(secondMap);

    await vi.waitFor(() => expect(secondMap.network).toHaveBeenCalledWith(second.lines));
    expect(canalNetwork).toHaveBeenNthCalledWith(2, networkRequest(8));
  });

  it('keeps the previous lines and bases when a refresh fails', async () => {
    vi.useFakeTimers();
    try {
      const network = networkResponse();
      const canalNetwork = vi.fn()
        .mockResolvedValueOnce(network)
        .mockRejectedValueOnce(new Error('network unavailable'));
      const map = viewportMap(() => {});
      const { store } = setup({ canalNetwork });

      store.setNetworkRequest(networkRequest());
      store.setMapView(map);
      await vi.waitFor(() => expect(map.network).toHaveBeenCalledWith(network.lines));
      const networkDraws = vi.mocked(map.network).mock.calls.length;
      const baseDraws = vi.mocked(map.hireBases).mock.calls.length;
      store.setNetworkRequest(networkRequest(8));
      await vi.advanceTimersByTimeAsync(100);
      await vi.waitFor(() => expect(get(store).networkError).toBe('network unavailable'));

      expect(get(store).hasNetworkOverlay).toBe(true);
      expect(map.network).toHaveBeenCalledTimes(networkDraws);
      expect(map.hireBases).toHaveBeenCalledTimes(baseDraws);
      expect(map.network).toHaveBeenLastCalledWith(network.lines);
      expect(map.hireBases).toHaveBeenLastCalledWith(network.bases);
    } finally {
      vi.useRealTimers();
    }
  });

  it('does not refit a cached overlay when replaying it over an active route', async () => {
    const network = networkResponse();
    const firstMap = viewportMap(() => {});
    const secondMap = viewportMap(() => {});
    const canalNetwork = vi.fn(async (_request: CanalNetworkRequest) => network);
    const { store } = setup({ canalNetwork });

    store.setNetworkRequest(networkRequest());
    store.setMapView(firstMap);
    await vi.waitFor(() => expect(firstMap.network).toHaveBeenCalledWith(network.lines));
    await store.setEndpointCoordinate('origin', place('origin'));
    await store.setEndpointCoordinate('destination', place('destination', 53));
    await store.planCanalRoute({});
    store.setMapView(undefined);
    store.setMapView(secondMap);

    expect(canalNetwork).toHaveBeenCalledOnce();
    expect(secondMap.network).toHaveBeenCalledWith(network.lines);
    expect(secondMap.hireBases).toHaveBeenCalledWith(network.bases);
    expect(secondMap.fitNetwork).not.toHaveBeenCalled();
  });

  it('fits a valid base-only response after the initial overlay paint', async () => {
    vi.useFakeTimers();
    try {
      const fullNetwork = networkResponse();
      const baseOnly = networkResponse('base-only', []);
      const canalNetwork = vi.fn()
        .mockResolvedValueOnce(fullNetwork)
        .mockResolvedValueOnce(baseOnly);
      const map = viewportMap(() => {});
      const { store } = setup({ canalNetwork });

      store.setNetworkRequest(networkRequest());
      store.setMapView(map);
      await vi.waitFor(() => expect(map.network).toHaveBeenCalledWith(fullNetwork.lines));
      store.setNetworkRequest(networkRequest(8));
      await vi.advanceTimersByTimeAsync(100);
      await vi.waitFor(() => expect(map.network).toHaveBeenLastCalledWith([]));

      expect(map.hireBases).toHaveBeenLastCalledWith(baseOnly.bases);
      expect(map.fitNetwork).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it('records a network error without blocking endpoint operations', async () => {
    const map = viewportMap(() => {});
    const { store } = setup({ canalNetwork: vi.fn(async (_request: CanalNetworkRequest) => { throw new Error('network unavailable'); }) });

    store.setNetworkRequest(networkRequest());
    store.setMapView(map);
    await vi.waitFor(() => expect(get(store).networkError).toBe('network unavailable'));
    await store.setEndpointCoordinate('origin', place('origin'));
    expect(get(store).origin.selectedUid).toBe(2);
  });

  it('resets trip state and fits the cached network', async () => {
    const map = viewportMap(() => {});
    const { store } = setup();
    store.setNetworkRequest(networkRequest());
    store.setMapView(map);
    await vi.waitFor(() => expect(map.network).toHaveBeenCalled());
    await store.setEndpointCoordinate('origin', place('origin'));
    await store.setEndpointCoordinate('destination', place('destination', 53));
    await store.planCanalRoute({});

    store.reset();

    expect(get(store).origin.place).toBeNull();
    expect(get(store).destination.place).toBeNull();
    expect(get(store).canalRoute).toBeNull();
    expect(get(store).routePois).toBeNull();
    expect(map.canal).toHaveBeenCalledWith(null);
    expect(map.fitNetwork).toHaveBeenCalledTimes(2);
  });

  it('ignores stale endpoint responses after reset', async () => {
    let resolveOld!: (value: CanalCandidatesResponse) => void;
    const { store, canalCandidates } = setup();
    canalCandidates.mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }));

    const pending = store.setEndpointCoordinate('origin', place('old'));
    store.reset();
    resolveOld(response('r1', [1]));
    await pending;

    expect(get(store).origin.place).toBeNull();
    expect(get(store).origin.candidates).toEqual([]);
  });

  it('ignores stale route responses after reset', async () => {
    let resolveRoute!: (value: CanalRouteResponse) => void;
    const { store, canalRoute } = setup();
    await store.setEndpointCoordinate('origin', place('origin'));
    await store.setEndpointCoordinate('destination', place('destination', 53));
    canalRoute.mockImplementationOnce(() => new Promise((resolve) => { resolveRoute = resolve; }));

    const pending = store.planCanalRoute({});
    store.reset();
    resolveRoute(canal);
    await pending;

    expect(get(store).origin.place).toBeNull();
    expect(get(store).destination.place).toBeNull();
    expect(get(store).canalRoute).toBeNull();
  });

  it('resets state even when map cleanup fails', async () => {
    const map = {
      ...viewportMap(() => {}),
      network: vi.fn(),
      fitNetwork: vi.fn(),
      clearLand: vi.fn(() => { throw new Error('clear failed'); }),
    } as unknown as MapView;
    const { store } = setup({ map });
    await store.setEndpointCoordinate('origin', place('origin'));

    expect(() => store.reset()).not.toThrow();
    expect(get(store).origin.place).toBeNull();
    expect(get(store).origin.transferWarning).toBeNull();
  });

  it('replays hydrated trip state when a map view attaches later', async () => {
    const { store } = setup();
    await store.setEndpointCoordinate('origin', place('origin', 51));
    await store.setEndpointCoordinate('destination', place('destination', 53));
    await store.planCanalRoute({});
    const map = { marker: vi.fn(), candidates: vi.fn(), land: vi.fn(), canal: vi.fn(), network: vi.fn(), fitNetwork: vi.fn(), onMapClick: vi.fn(), clearLand: vi.fn(), destroy: vi.fn() } as unknown as MapView;
    store.setMapView(map);
    expect(map.marker).toHaveBeenCalledWith('origin', { lat: 51, lon: -1 });
    expect(map.marker).toHaveBeenCalledWith('destination', { lat: 53, lon: -1 });
    expect(map.candidates).toHaveBeenCalledWith('origin', expect.any(Array), 2);
    expect(map.candidates).toHaveBeenCalledWith('destination', expect.any(Array), 4);
    expect(map.land).toHaveBeenCalledWith('origin', land);
    expect(map.land).toHaveBeenCalledWith('destination', land);
    expect(map.canal).toHaveBeenCalledWith(canal.geometry);
    expect(() => store.setMapView(undefined)).not.toThrow();
  });

  it('continues replaying map state when one delayed draw fails', async () => {
    const { store } = setup();
    await store.setEndpointCoordinate('origin', place('origin', 51));
    await store.setEndpointCoordinate('destination', place('destination', 53));
    const canalDraw = vi.fn();
    const map = { marker: vi.fn(() => { throw new Error('marker failed'); }), candidates: vi.fn(), land: vi.fn(), canal: canalDraw, network: vi.fn(), fitNetwork: vi.fn(), onMapClick: vi.fn(), clearLand: vi.fn(), destroy: vi.fn() } as unknown as MapView;
    store.setMapView(map);
    expect(map.candidates).toHaveBeenCalledTimes(2);
    expect(canalDraw).toHaveBeenCalledWith(null);
  });
  it('selects and draws the recommended reachable candidate for both symmetric endpoints', async () => {
    const marker = vi.fn(); const candidates = vi.fn(); const landDraw = vi.fn();
    const map = { marker, candidates, land: landDraw, canal: vi.fn(), network: vi.fn(), fitNetwork: vi.fn(), onMapClick: vi.fn(), clearLand: vi.fn(), destroy: vi.fn() } as unknown as MapView;
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
    const map = { marker: vi.fn(), candidates: vi.fn(), land: vi.fn(), canal: vi.fn(), network: vi.fn(), fitNetwork: vi.fn(), onMapClick: vi.fn(), clearLand, destroy: vi.fn() } as unknown as MapView;
    const { store } = setup({ routeError: new Error('land unavailable'), map });
    await store.setEndpointCoordinate('origin', place('origin'));
    expect(get(store).origin).toMatchObject({ selectedUid: 2, landRoute: null });
    expect(get(store).origin.transferWarning).toMatch(/land unavailable/);
    expect(clearLand).toHaveBeenCalledWith('origin');
  });

  it('constructs the exact canal request and draws the route', async () => {
    const drawCanal = vi.fn();
    const map = { marker: vi.fn(), candidates: vi.fn(), land: vi.fn(), canal: drawCanal, network: vi.fn(), fitNetwork: vi.fn(), onMapClick: vi.fn(), clearLand: vi.fn(), destroy: vi.fn() } as unknown as MapView;
    const { store, canalRoute } = setup({ map });
    await store.setEndpointCoordinate('origin', place('origin', 51));
    await store.setEndpointCoordinate('destination', place('destination', 53));
    const constraints = { days: 4, hours_per_day: 7, boat_beam_m: 2.1, movable_bridge_delay_min: 0 };
    await store.planCanalRoute(constraints);
    expect(canalRoute).toHaveBeenCalledWith({ start_uid: 2, end_uid: 4, artifact_revision: 'r1', ...constraints });
    expect(get(store).canalRoute).toEqual(canal);
    expect(drawCanal).toHaveBeenCalledWith(canal.geometry);
  });

  it('clears the old route and locks before a failed replan', async () => {
    const drawCanal = vi.fn();
    const drawLocks = vi.fn();
    const map = { marker: vi.fn(), candidates: vi.fn(), land: vi.fn(), canal: drawCanal, network: vi.fn(), fitNetwork: vi.fn(), pois: vi.fn(), locks: drawLocks, day: vi.fn(), onMapClick: vi.fn(), clearLand: vi.fn(), destroy: vi.fn() } as unknown as MapView;
    const { store, canalRoute } = setup({ map });
    const lockedRoute: CanalRouteResponse = {
      ...canal,
      locks: [{ coordinate: { lat: 51.5, lon: -1.5 }, name: 'Lock', day: 1, approximate: false }],
    };
    canalRoute.mockResolvedValueOnce(lockedRoute);
    await store.setEndpointCoordinate('origin', place('origin', 51));
    await store.setEndpointCoordinate('destination', place('destination', 53));
    await store.planCanalRoute({});
    expect(get(store).canalRoute).toEqual(lockedRoute);
    expect(drawLocks).toHaveBeenLastCalledWith(lockedRoute.locks);

    drawCanal.mockClear();
    drawLocks.mockClear();
    canalRoute.mockRejectedValueOnce(new Error('route unavailable'));
    await expect(store.planCanalRoute({})).rejects.toThrow('route unavailable');

    expect(get(store).canalRoute).toBeNull();
    expect(drawCanal).toHaveBeenCalledWith(null);
    expect(drawLocks).toHaveBeenCalledWith([]);
  });

  it('keeps POIs opt-in and refreshes selected route/day data', async () => {
    const routePois = vi.fn(async () => ({ pois: [], zoom_in_required: false, matching_count: 0, day: null }));
    const { store } = setup({ routePois });
    await store.setEndpointCoordinate('origin', place('origin', 51));
    await store.setEndpointCoordinate('destination', place('destination', 53));
    await store.planCanalRoute({});

    expect(routePois).not.toHaveBeenCalled();
    store.togglePoiKind('pub');
    await store.refreshRoutePois({ south: 50, west: -2, north: 54, east: 0 });

    expect(routePois).toHaveBeenCalledWith(expect.objectContaining({ kinds: ['pub'] }));
  });

  it('selects a day without replanning and sends its geometry to POI refreshes', async () => {
    const dayGeometry = {
      day: 2,
      geometry: { type: 'LineString' as const, coordinates: [[-1, 51], [-1.5, 52], [-2, 53]] as [number, number][] },
      start: { lat: 51, lon: -1 },
      end: { lat: 53, lon: -2 },
    };
    const routePois = vi.fn(async () => ({ pois: [], zoom_in_required: false, matching_count: 0, day: 2 }));
    const { store, canalRoute } = setup({ routePois });
    canalRoute.mockResolvedValue({ ...canal, day_geometries: [dayGeometry] });
    await store.setEndpointCoordinate('origin', place('origin', 51));
    await store.setEndpointCoordinate('destination', place('destination', 53));
    await store.planCanalRoute({});

    const bounds = { south: 50, west: -2, north: 54, east: 0 };
    store.togglePoiKind('pub');
    await store.refreshRoutePois(bounds);
    store.selectDay(2);
    await store.refreshRoutePois(bounds);

    expect(get(store).selectedDay).toBe(2);
    expect(canalRoute).toHaveBeenCalledTimes(1);
    expect(routePois).toHaveBeenLastCalledWith(expect.objectContaining({
      day: 2,
      day_geometry: dayGeometry.geometry,
    }));
  });

  it('clears prior POIs before a failed refresh for a newly selected day', async () => {
    const drawPois = vi.fn();
    const map = { marker: vi.fn(), candidates: vi.fn(), land: vi.fn(), canal: vi.fn(), network: vi.fn(), fitNetwork: vi.fn(), pois: drawPois, locks: vi.fn(), day: vi.fn(), onMapClick: vi.fn(), clearLand: vi.fn(), destroy: vi.fn() } as unknown as MapView;
    const fullRoutePois: RoutePoisResponse = {
      pois: [{ identity: 'node/1/pub', kind: 'pub', name: 'The Pub', coordinate: { lat: 51, lon: -1 }, distance_to_route_m: 10 }],
      zoom_in_required: false,
      matching_count: 1,
      day: null,
    };
    const routePois = vi.fn()
      .mockResolvedValueOnce(fullRoutePois)
      .mockRejectedValueOnce(new Error('POI refresh unavailable'));
    const { store, canalRoute } = setup({ map, routePois });
    canalRoute.mockResolvedValue({
      ...canal,
      day_geometries: [{
        day: 2,
        geometry: { type: 'LineString', coordinates: [[-1, 51], [-2, 53]] },
        start: { lat: 51, lon: -1 },
        end: { lat: 53, lon: -2 },
      }],
    });
    await store.setEndpointCoordinate('origin', place('origin', 51));
    await store.setEndpointCoordinate('destination', place('destination', 53));
    await store.planCanalRoute({});

    const bounds = { south: 50, west: -2, north: 54, east: 0 };
    store.togglePoiKind('pub');
    await store.refreshRoutePois(bounds);
    expect(get(store).routePois).toEqual(fullRoutePois);
    expect(drawPois).toHaveBeenLastCalledWith(fullRoutePois.pois);

    store.selectDay(2);
    expect(get(store).routePois).toBeNull();
    expect(drawPois).toHaveBeenLastCalledWith([]);
    await store.refreshRoutePois(bounds);

    expect(get(store).routePois).toBeNull();
    expect(get(store).poiError).toContain('POI refresh unavailable');
    expect(drawPois).toHaveBeenLastCalledWith([]);
  });

  it('coalesces grouped layer toggles and debounces rapid viewport refreshes', async () => {
    vi.useFakeTimers();
    try {
      const routePois = vi.fn(async () => ({ pois: [], zoom_in_required: false, matching_count: 0, day: null }));
      let onViewportIdle!: (bounds: MapBounds) => void;
      const map = viewportMap((callback) => { onViewportIdle = callback; });
      const { store } = setup({ routePois, map });
      await store.setEndpointCoordinate('origin', place('origin', 51));
      await store.setEndpointCoordinate('destination', place('destination', 53));
      await store.planCanalRoute({});
      store.setMapView(map);

      const firstBounds = { south: 50, west: -2, north: 54, east: 0 };
      onViewportIdle(firstBounds);
      store.togglePoiKind('pub');
      store.togglePoiKind('water_point');
      expect(routePois).not.toHaveBeenCalled();
      await vi.advanceTimersByTimeAsync(100);
      expect(routePois).toHaveBeenCalledTimes(1);
      expect(routePois).toHaveBeenCalledWith(expect.objectContaining({
        bounds: firstBounds,
        kinds: ['pub', 'water_point'],
      }));

      routePois.mockClear();
      const secondBounds = { south: 51, west: -1.5, north: 53, east: -0.5 };
      const latestBounds = { south: 51.5, west: -1.25, north: 52.5, east: -0.25 };
      onViewportIdle(secondBounds);
      onViewportIdle(latestBounds);
      await vi.advanceTimersByTimeAsync(100);
      expect(routePois).toHaveBeenCalledTimes(1);
      expect(routePois).toHaveBeenCalledWith(expect.objectContaining({ bounds: latestBounds }));
    } finally {
      vi.useRealTimers();
    }
  });

  it('keeps places opt-in and sends a revision-free viewport request', async () => {
    const { store, places } = setup();
    const bounds = { south: 50, west: -2, north: 54, east: 0 };
    await store.setEndpointCoordinate('origin', place('origin', 51));
    await store.setEndpointCoordinate('destination', place('destination', 53));
    await store.planCanalRoute({});

    await store.refreshPlaces(bounds);
    expect(places).not.toHaveBeenCalled();
    store.togglePlaceKinds(['museum'], { basis: 'waterway', radius_m: 2_000 });
    expect(get(store).places.enabledKinds).toEqual(['museum']);
    await store.refreshPlaces(bounds);

    expect(places).toHaveBeenCalledOnce();
    const request = vi.mocked(places).mock.calls[0][0] as Record<string, unknown>;
    expect(request).toMatchObject({ mode: 'viewport', kinds: ['museum'], bounds, policy: { basis: 'waterway', radius_m: 2_000 } });
    expect(request).not.toHaveProperty('catalog_revision');
    expect(request).not.toHaveProperty('day');
  });

  it('uses one standing health read and skips unavailable places queries', async () => {
    const places = vi.fn(async () => ({ places: [] }));
    const placesHealth = vi.fn(async (): Promise<HealthResponse> => ({ status: 'degraded', artifact_revision: 'r1', places_status: 'unavailable' }));
    const { store } = setup({ places, placesHealth });

    await vi.waitFor(() => expect(placesHealth).toHaveBeenCalledOnce());
    expect(get(store).placesStatus).toBe('unavailable');
    await store.refreshPlaces({ south: 50, west: -2, north: 54, east: 0 });

    expect(places).not.toHaveBeenCalled();
    expect(placesHealth).toHaveBeenCalledOnce();
  });

  it('does not retry a places 409 and records it as an actionable error', async () => {
    const places = vi.fn().mockRejectedValue(new PoundApiError(409, {
      code: 'places_revision_mismatch', message: 'Unexpected revision error.', fields: [],
    }));
    const { store } = setup({ places });
    await store.setEndpointCoordinate('origin', place('origin', 51));
    await store.setEndpointCoordinate('destination', place('destination', 53));
    await store.planCanalRoute({});
    store.togglePlaceKind('museum', { basis: 'route', radius_m: 2_000 });

    await store.refreshPlaces({ south: 50, west: -2, north: 54, east: 0 });

    expect(places).toHaveBeenCalledOnce();
    expect(get(store).places.error).toContain('Unexpected revision error.');
  });

  it('renders fulfilled groups and marks a result-limit group for zooming in', async () => {
    const firstPlace = placeResponse('node', 7, 'museum');
    const places = vi.fn()
      .mockResolvedValueOnce({ places: [firstPlace] })
      .mockRejectedValueOnce(new PoundApiError(413, {
        code: 'places_result_limit_exceeded', message: 'Narrow the places query.', fields: [],
      }));
    const draw = vi.fn();
    const map = { ...viewportMap(() => {}), places: draw } as unknown as MapView;
    const { store } = setup({ places, map });
    await store.setEndpointCoordinate('origin', place('origin', 51));
    await store.setEndpointCoordinate('destination', place('destination', 53));
    await store.planCanalRoute({});
    store.togglePlaceKinds(['museum'], { basis: 'route', radius_m: 2_000 });
    store.togglePlaceKinds(['marina'], { basis: 'waterway', radius_m: 500 });

    await store.refreshPlaces({ south: 50, west: -2, north: 54, east: 0 });

    expect(get(store).places.places).toEqual([firstPlace]);
    expect(get(store).placesResultLimitExceeded).toBe(true);
    expect(get(store).places.error).toBeNull();
    expect(draw).toHaveBeenLastCalledWith([firstPlace]);
  });

  it('keeps another 413 actionable instead of showing the zoom message', async () => {
    const places = vi.fn().mockRejectedValue(new PoundApiError(413, {
      code: 'places_query_budget_exceeded', message: 'Narrow the places query budget.', fields: ['radius_m'],
    }));
    const { store } = setup({ places });
    await store.setEndpointCoordinate('origin', place('origin', 51));
    await store.setEndpointCoordinate('destination', place('destination', 53));
    await store.planCanalRoute({});
    store.togglePlaceKind('museum', { basis: 'route', radius_m: 2_000 });

    await store.refreshPlaces({ south: 50, west: -2, north: 54, east: 0 });

    expect(get(store).placesResultLimitExceeded).toBe(false);
    expect(get(store).places.error).toContain('Narrow the places query budget.');
  });

  it('keeps OSM and boat-hire structured identities distinct when merging groups', async () => {
    const osm = placeResponse('node', 12, 'marina');
    const hire: PlaceResponse = {
      kind: 'boat_hire', name: 'Marina', coordinate: { lat: 51.2, lon: -1.2 },
      target_id: null, distance_to_target_m: null, distance_to_full_route_m: 30,
      distance_to_selected_geometry_m: null, waterway_distance_m: 20,
      provenance: {
        source: 'boat_hire', provider_id: 'node', provider_name: 'Node Hire', location_id: '12',
        location_name: 'Marina', provider_url: null, osm_url: null, evidence_url: null, booking_url: null,
      },
    };
    const places = vi.fn()
      .mockResolvedValueOnce({ places: [osm] })
      .mockResolvedValueOnce({ places: [hire] });
    const { store } = setup({ places });
    await store.setEndpointCoordinate('origin', place('origin', 51));
    await store.setEndpointCoordinate('destination', place('destination', 53));
    await store.planCanalRoute({});
    store.togglePlaceKind('museum', { basis: 'route', radius_m: 2_000 });
    store.togglePlaceKind('marina', { basis: 'waterway', radius_m: 500 });

    await store.refreshPlaces({ south: 50, west: -2, north: 54, east: 0 });

    expect(get(store).places.places).toEqual([osm, hire]);
  });

  it('keeps colon-containing boat-hire identities distinct when merging groups', async () => {
    const first = boatHirePlace('a:b', 'c');
    const second = boatHirePlace('a', 'b:c');
    const places = vi.fn()
      .mockResolvedValueOnce({ places: [first] })
      .mockResolvedValueOnce({ places: [second] });
    const { store } = setup({ places });
    await store.setEndpointCoordinate('origin', place('origin', 51));
    await store.setEndpointCoordinate('destination', place('destination', 53));
    await store.planCanalRoute({});
    store.togglePlaceKind('boat_hire', { basis: 'route', radius_m: 2_000 });
    store.togglePlaceKind('marina', { basis: 'waterway', radius_m: 500 });

    await store.refreshPlaces({ south: 50, west: -2, north: 54, east: 0 });

    expect(get(store).places.places).toEqual([first, second]);
  });

  it('does not let pending healthy health replace a runtime places outage', async () => {
    let resolveHealth!: (value: HealthResponse) => void;
    const placesHealth = vi.fn(() => new Promise<HealthResponse>((resolve) => { resolveHealth = resolve; }));
    const places = vi.fn().mockRejectedValue(new PoundApiError(503, {
      code: 'places_unavailable', message: 'Places are unavailable.', fields: [],
    }));
    const { store } = setup({ places, placesHealth });
    await vi.waitFor(() => expect(placesHealth).toHaveBeenCalledOnce());
    await store.setEndpointCoordinate('origin', place('origin', 51));
    await store.setEndpointCoordinate('destination', place('destination', 53));
    await store.planCanalRoute({});
    store.togglePlaceKind('museum', { basis: 'route', radius_m: 2_000 });
    const query = store.refreshPlaces({ south: 50, west: -2, north: 54, east: 0 });
    await vi.waitFor(() => expect(places).toHaveBeenCalledOnce());
    await query;

    expect(get(store).placesStatus).toBe('unavailable');
    expect(get(store).places.error).toBe('Places are unavailable.');
    resolveHealth({ status: 'healthy', artifact_revision: 'r1', places_status: 'available' });
    await Promise.resolve();
    expect(get(store).placesStatus).toBe('unavailable');
    expect(get(store).places.error).toBe('Places are unavailable.');
  });

  it('does not let pending unavailable health replace the runtime places error', async () => {
    let resolveHealth!: (value: HealthResponse) => void;
    const placesHealth = vi.fn(() => new Promise<HealthResponse>((resolve) => { resolveHealth = resolve; }));
    const places = vi.fn().mockRejectedValue(new PoundApiError(503, {
      code: 'places_unavailable', message: 'Runtime places outage.', fields: [],
    }));
    const { store } = setup({ places, placesHealth });
    await vi.waitFor(() => expect(placesHealth).toHaveBeenCalledOnce());
    await store.setEndpointCoordinate('origin', place('origin', 51));
    await store.setEndpointCoordinate('destination', place('destination', 53));
    await store.planCanalRoute({});
    store.togglePlaceKind('museum', { basis: 'route', radius_m: 2_000 });
    const query = store.refreshPlaces({ south: 50, west: -2, north: 54, east: 0 });
    await vi.waitFor(() => expect(places).toHaveBeenCalledOnce());
    await query;

    expect(get(store).placesStatus).toBe('unavailable');
    expect(get(store).places.error).toBe('Runtime places outage.');
    resolveHealth({ status: 'degraded', artifact_revision: 'r1', places_status: 'unavailable' });
    await Promise.resolve();
    expect(get(store).placesStatus).toBe('unavailable');
    expect(get(store).places.error).toBe('Runtime places outage.');
  });

  it('refreshes selected catalog layers after route creation and clears them on replacement', async () => {
    vi.useFakeTimers();
    try {
      const catalogDraw = vi.fn();
      const map = { ...viewportMap(() => {}), places: catalogDraw } as unknown as MapView;
      const { store, places } = setup({ map });
      await store.setEndpointCoordinate('origin', place('origin', 51));
      await store.setEndpointCoordinate('destination', place('destination', 53));
      store.togglePlaceKinds(['museum'], { basis: 'route', radius_m: 2_000 });
      let onIdle!: (bounds: MapBounds) => void;
      store.setMapView({ ...map, onViewportIdle: vi.fn((callback) => { onIdle = callback; return vi.fn(); }) });
      const bounds = { south: 50, west: -2, north: 54, east: 0 };
      onIdle(bounds);
      await store.planCanalRoute({});
      await vi.advanceTimersByTimeAsync(100);
      expect(places).toHaveBeenCalled();
      catalogDraw.mockClear();
      await store.planCanalRoute({});
      expect(catalogDraw).toHaveBeenCalledWith([]);
    } finally {
      vi.useRealTimers();
    }
  });

  it('keeps route overlays usable when catalog queries are unavailable', async () => {
    const locks = [{ coordinate: { lat: 51.5, lon: -1.5 }, name: 'Lock', day: 1, approximate: false }];
    const routeWithLocks = { ...canal, locks, day_geometries: [{ day: 1, geometry: canal.geometry, start: { lat: 51, lon: -1 }, end: { lat: 52, lon: -2 } }] };
    const places = vi.fn(async () => { throw new Error('Catalog unavailable'); });
    const { store, canalRoute } = setup({ places });
    canalRoute.mockResolvedValue(routeWithLocks);
    await store.setEndpointCoordinate('origin', place('origin', 51));
    await store.setEndpointCoordinate('destination', place('destination', 53));
    await store.planCanalRoute({});
    store.selectDay(1);
    store.togglePlaceKinds(['museum'], { basis: 'route', radius_m: 2_000 });
    await expect(store.refreshPlaces({ south: 50, west: -2, north: 54, east: 0 })).resolves.toBeUndefined();
    expect(get(store).canalRoute).toEqual(routeWithLocks);
    expect(get(store).selectedDay).toBe(1);
    expect(get(store).places.error).toContain('Catalog unavailable');
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
    const map = { marker: failing, candidates: failing, land: failing, canal: failing, network: failing, fitNetwork: failing, onMapClick: vi.fn(), clearLand: vi.fn(), destroy: vi.fn() } as unknown as MapView;
    const { store } = setup({ map });
    await expect(store.setEndpointCoordinate('origin', place('origin'))).resolves.toBeUndefined();
    expect(get(store).origin.selectedUid).toBe(2);
    expect(get(store).origin.transferWarning).toMatch(/map failed/);
  });

  it('lets the newest canal request win when responses arrive out of order', async () => {
    let resolveOld!: (value: CanalRouteResponse) => void;
    let resolveNew!: (value: CanalRouteResponse) => void;
    const draw = vi.fn();
    const map = { marker: vi.fn(), candidates: vi.fn(), land: vi.fn(), canal: draw, network: vi.fn(), fitNetwork: vi.fn(), onMapClick: vi.fn(), clearLand: vi.fn(), destroy: vi.fn() } as unknown as MapView;
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
    const map = { marker: vi.fn(), candidates: vi.fn(), land: vi.fn(), canal: draw, network: vi.fn(), fitNetwork: vi.fn(), onMapClick: vi.fn(), clearLand: vi.fn(), destroy: vi.fn() } as unknown as MapView;
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
    const map = { marker: vi.fn(), candidates: vi.fn(), land: vi.fn(), canal: vi.fn(), network: vi.fn(), fitNetwork: vi.fn(), onMapClick: vi.fn(), clearLand, destroy: vi.fn() } as unknown as MapView;
    const { store } = setup({ map });
    expect(get(store).origin.selectedUid).toBeNull();
    expect(get(store).destination.selectedUid).toBeNull();
    await store.setEndpointCoordinate('destination', place('destination', 53));
    await store.selectCandidate('destination', 3);
    expect(clearLand).toHaveBeenCalledWith('destination');
    expect(get(store).destination.selectedUid).toBe(3);
  });

  it('turns a land-overlay clear failure into a warning without losing endpoint state', async () => {
    const map = { marker: vi.fn(), candidates: vi.fn(), land: vi.fn(), canal: vi.fn(), network: vi.fn(), fitNetwork: vi.fn(), onMapClick: vi.fn(), clearLand: () => { throw new Error('clear failed'); }, destroy: vi.fn() } as unknown as MapView;
    const { store } = setup({ map });
    await store.setEndpointCoordinate('destination', place('destination', 53));
    expect(get(store).destination.selectedUid).toBe(4);
    expect(get(store).destination.transferWarning).toMatch(/clear failed/);
  });
});
