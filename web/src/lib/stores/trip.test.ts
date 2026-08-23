import { get } from 'svelte/store';
import { describe, expect, it, vi } from 'vitest';

import { PoundApiError } from '../api';
import type {
  CanalCandidatesResponse,
  CanalNetworkResponse,
  CanalRouteRequest,
  CanalRouteResponse,
  CatalogPlacesResponse,
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
const catalogPlace = (identity: string, kind: string) => ({
  identity, kind, name: kind, coordinate: { lat: 51.2, lon: -1.2 },
  waterway_distance_m: 20, distance_to_full_route_m: 30, distance_to_selected_geometry_m: null, distance_to_segment_m: null,
  metadata: { name: kind, alt_name: null, brand: null, operator: null, address: null, opening_hours: null,
    access: null, fee: null, wheelchair: null, phone: null, email: null, description: null, links: [], kind_details: {} },
});

function viewportMap(setCallback: (callback: (bounds: MapBounds) => void) => void): MapView {
  return {
    marker: vi.fn(), candidates: vi.fn(), land: vi.fn(), canal: vi.fn(), network: vi.fn(), fitNetwork: vi.fn(), catalogPlaces: vi.fn(), pois: vi.fn(), locks: vi.fn(), day: vi.fn(),
    clearLand: vi.fn(), closeInfoWindow: vi.fn(), destroy: vi.fn(), onMapClick: vi.fn(() => vi.fn()),
    onViewportIdle: vi.fn((callback) => { setCallback(callback); return vi.fn(); }),
  };
}

function setup(options: {
  matrices?: TransferResult[][];
  routeError?: Error;
  map?: MapView;
  canalNetwork?: () => Promise<CanalNetworkResponse>;
  routePois?: (request: unknown) => Promise<RoutePoisResponse>;
  catalogPlaces?: (request: unknown) => Promise<CatalogPlacesResponse>;
  catalogHealth?: () => Promise<{ status: string; artifact_revision: string; catalog_revision: string | null; catalog_status: 'available' | 'unavailable' }>;
} = {}) {
  const canalCandidates = vi.fn(async ({ lat }: LatLon) => lat < 52 ? response('r1', [1, 2]) : response('r1', [3, 4]));
  const canalNetwork = options.canalNetwork ?? vi.fn(async () => ({
    artifact_revision: 'r1',
    lines: [{ type: 'LineString' as const, coordinates: [[-1, 51], [-2, 52]] as [number, number][] }],
  }));
  const canalRoute = vi.fn(async (_request: CanalRouteRequest) => canal);
  const routePois = options.routePois ?? vi.fn(async () => ({ pois: [], zoom_in_required: false, matching_count: 0, day: null }));
  const catalogPlaces = options.catalogPlaces ?? vi.fn(async () => ({ catalog_revision: 'c1', places: [], matching_count: 0, over_cap: false, day: null }));
  const catalogHealth = options.catalogHealth ?? vi.fn(async () => ({ status: 'healthy', artifact_revision: 'r1', catalog_revision: 'c1', catalog_status: 'available' as const }));
  const matrices = options.matrices ?? [[
    { available: true, durationSeconds: 20, distanceMeters: 100 },
    { available: true, durationSeconds: 10, distanceMeters: 200 },
  ]];
  let matrixIndex = 0;
  const transferRouter: TransferRouter = {
    matrix: vi.fn(async () => matrices[Math.min(matrixIndex++, matrices.length - 1)]),
    route: vi.fn(async () => { if (options.routeError) throw options.routeError; return land; }),
  };
  const store = createTripStore({ poundApi: { canalCandidates, canalNetwork, canalRoute, routePois, catalogPlaces, health: catalogHealth }, transferRouter, mapView: options.map, transferMode: 'WALK' });
  return { store, canalCandidates, canalNetwork, canalRoute, transferRouter, catalogPlaces, catalogHealth };
}

describe('trip store', () => {
  it('loads and fits the network once when a map attaches', async () => {
    const network = { artifact_revision: 'r1', lines: [{ type: 'LineString' as const, coordinates: [[-1, 51], [-2, 52]] as [number, number][] }] };
    const map = { ...viewportMap(() => {}), network: vi.fn(), fitNetwork: vi.fn() } as unknown as MapView;
    const { store } = setup({ map, canalNetwork: vi.fn(async () => network) });

    store.setMapView(map);
    await vi.waitFor(() => expect(map.network).toHaveBeenCalledWith(network.lines));
    expect(map.fitNetwork).toHaveBeenCalledOnce();
  });

  it('draws deferred network lines without refitting after a route fits the map', async () => {
    let resolveNetwork!: (network: CanalNetworkResponse) => void;
    const network = { artifact_revision: 'r1', lines: [{ type: 'LineString' as const, coordinates: [[-1, 51], [-2, 52]] as [number, number][] }] };
    const map = { ...viewportMap(() => {}), network: vi.fn(), fitNetwork: vi.fn(), canal: vi.fn() } as unknown as MapView;
    const canalNetwork = vi.fn(() => new Promise<CanalNetworkResponse>((resolve) => { resolveNetwork = resolve; }));
    const { store } = setup({ map, canalNetwork });

    store.setMapView(map);
    await vi.waitFor(() => expect(canalNetwork).toHaveBeenCalledOnce());
    await store.setEndpointCoordinate('origin', place('origin'));
    await store.setEndpointCoordinate('destination', place('destination', 53));
    await store.planCanalRoute({});
    expect(map.canal).toHaveBeenCalledWith(canal.geometry);

    resolveNetwork(network);
    await vi.waitFor(() => expect(map.network).toHaveBeenCalledWith(network.lines));
    expect(map.fitNetwork).not.toHaveBeenCalled();
  });

  it('replays cached network lines without a second API call', async () => {
    const network = { artifact_revision: 'r1', lines: [{ type: 'LineString' as const, coordinates: [[-1, 51], [-2, 52]] as [number, number][] }] };
    const canalNetwork = vi.fn(async () => network);
    const firstMap = { ...viewportMap(() => {}), network: vi.fn(), fitNetwork: vi.fn() } as unknown as MapView;
    const secondMap = { ...viewportMap(() => {}), network: vi.fn(), fitNetwork: vi.fn() } as unknown as MapView;
    const { store } = setup({ canalNetwork });

    store.setMapView(firstMap);
    await vi.waitFor(() => expect(firstMap.network).toHaveBeenCalledWith(network.lines));
    store.setMapView(secondMap);
    expect(canalNetwork).toHaveBeenCalledOnce();
    expect(secondMap.network).toHaveBeenCalledWith(network.lines);
    expect(secondMap.fitNetwork).toHaveBeenCalledOnce();
  });

  it('records a network error without blocking endpoint operations', async () => {
    const map = { ...viewportMap(() => {}), network: vi.fn(), fitNetwork: vi.fn() } as unknown as MapView;
    const { store } = setup({ map, canalNetwork: vi.fn(async () => { throw new Error('network unavailable'); }) });

    store.setMapView(map);
    await vi.waitFor(() => expect(get(store).networkError).toBe('network unavailable'));
    await store.setEndpointCoordinate('origin', place('origin'));
    expect(get(store).origin.selectedUid).toBe(2);
  });

  it('resets trip state and fits the cached network', async () => {
    const map = { ...viewportMap(() => {}), network: vi.fn(), fitNetwork: vi.fn() } as unknown as MapView;
    const { store } = setup({ map });
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
    expect(map.fitNetwork).toHaveBeenCalled();
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

  it('keeps catalog queries opt-in and sends no request for empty selections', async () => {
    const { store, catalogPlaces } = setup();
    const bounds = { south: 50, west: -2, north: 54, east: 0 };
    await store.setEndpointCoordinate('origin', place('origin', 51));
    await store.setEndpointCoordinate('destination', place('destination', 53));
    await store.planCanalRoute({});

    await store.refreshCatalogPlaces(bounds);
    expect(catalogPlaces).not.toHaveBeenCalled();
    store.toggleCatalogKinds(['museum'], { basis: 'waterway', radius_m: 2_000 });
    expect(get(store).catalog.enabledKinds).toEqual(['museum']);
    await store.refreshCatalogPlaces(bounds);
    expect(catalogPlaces).toHaveBeenCalledWith(expect.objectContaining({ kinds: ['museum'], catalog_revision: 'c1' }));
  });

  it('issues separate catalog requests for destination and utility policies', async () => {
    const { store, catalogPlaces } = setup();
    await store.setEndpointCoordinate('origin', place('origin', 51));
    await store.setEndpointCoordinate('destination', place('destination', 53));
    await store.planCanalRoute({});
    store.toggleCatalogKinds(['museum'], { basis: 'route', radius_m: 2_000 });
    store.toggleCatalogKinds(['marina'], { basis: 'waterway', radius_m: 500 });
    await store.refreshCatalogPlaces({ south: 50, west: -2, north: 54, east: 0 });

    expect(catalogPlaces).toHaveBeenCalledTimes(2);
    expect(catalogPlaces).toHaveBeenCalledWith(expect.objectContaining({ kinds: ['museum'], policy: { basis: 'route', radius_m: 2_000 } }));
    expect(catalogPlaces).toHaveBeenCalledWith(expect.objectContaining({ kinds: ['marina'], policy: { basis: 'waterway', radius_m: 500 } }));
  });

  it('consumes initial catalog health failures without an unhandled rejection', async () => {
    const healthError = new PoundApiError(503, {
      code: 'catalog_unavailable',
      message: 'Catalog is unavailable.',
      fields: [],
    });
    const catalogHealth = vi.fn().mockRejectedValue(healthError);
    const unhandledRejections: unknown[] = [];
    const onUnhandledRejection = (reason: unknown) => {
      unhandledRejections.push(reason);
    };
    process.on('unhandledRejection', onUnhandledRejection);
    try {
      const { store } = setup({ catalogHealth });
      await vi.waitFor(() => expect(catalogHealth).toHaveBeenCalledTimes(1));
      await new Promise((resolve) => setTimeout(resolve, 0));
      expect(get(store).catalogStatus).toBe('unavailable');
      expect(get(store).catalog.error).toContain('Catalog is unavailable.');
      expect(unhandledRejections).toEqual([]);
    } finally {
      process.off('unhandledRejection', onUnhandledRejection);
    }
  });

  it('refetches catalog health and retries once after a revision mismatch', async () => {
    const catalogPlaces = vi.fn()
      .mockRejectedValueOnce(new PoundApiError(409, {
        code: 'catalog_revision_mismatch', message: 'Refresh catalog health.', fields: ['catalog_revision'],
      }))
      .mockResolvedValue({ catalog_revision: 'c2', places: [], matching_count: 0, over_cap: false, day: null });
    const catalogHealth = vi.fn()
      .mockResolvedValueOnce({ status: 'healthy', artifact_revision: 'r1', catalog_revision: 'c1', catalog_status: 'available' as const })
      .mockResolvedValueOnce({ status: 'healthy', artifact_revision: 'r1', catalog_revision: 'c2', catalog_status: 'available' as const });
    const { store } = setup({ catalogPlaces, catalogHealth });
    await vi.waitFor(() => expect(catalogHealth).toHaveBeenCalledTimes(1));
    await store.setEndpointCoordinate('origin', place('origin', 51));
    await store.setEndpointCoordinate('destination', place('destination', 53));
    await store.planCanalRoute({});
    store.toggleCatalogKind('museum', { basis: 'route', radius_m: 2_000 });

    await store.refreshCatalogPlaces({ south: 50, west: -2, north: 54, east: 0 });

    expect(catalogHealth).toHaveBeenCalledTimes(2);
    expect(catalogPlaces).toHaveBeenCalledTimes(2);
    expect(catalogPlaces).toHaveBeenNthCalledWith(1, expect.objectContaining({ catalog_revision: 'c1' }));
    expect(catalogPlaces).toHaveBeenNthCalledWith(2, expect.objectContaining({ catalog_revision: 'c2' }));
    expect(get(store).catalogRevision).toBe('c2');
  });

  it('merges catalog groups once and ignores stale responses', async () => {
    let resolveOld!: (value: CatalogPlacesResponse) => void;
    let resolveNew!: (value: CatalogPlacesResponse) => void;
    const catalogPlaces = vi.fn()
      .mockImplementationOnce(() => new Promise<CatalogPlacesResponse>((resolve) => { resolveOld = resolve; }))
      .mockImplementationOnce(() => new Promise<CatalogPlacesResponse>((resolve) => { resolveNew = resolve; }));
    const catalogDraw = vi.fn();
    const map = { marker: vi.fn(), candidates: vi.fn(), land: vi.fn(), canal: vi.fn(), network: vi.fn(), fitNetwork: vi.fn(), catalogPlaces: catalogDraw, onMapClick: vi.fn(), clearLand: vi.fn(), destroy: vi.fn() } as unknown as MapView;
    const { store } = setup({ catalogPlaces, map });
    await store.setEndpointCoordinate('origin', place('origin', 51));
    await store.setEndpointCoordinate('destination', place('destination', 53));
    await store.planCanalRoute({});
    store.toggleCatalogKinds(['museum'], { basis: 'route', radius_m: 2_000 });
    const first = store.refreshCatalogPlaces({ south: 50, west: -2, north: 54, east: 0 });
    await vi.waitFor(() => expect(catalogPlaces).toHaveBeenCalledTimes(1));
    const second = store.refreshCatalogPlaces({ south: 51, west: -1.5, north: 53, east: -0.5 });
    await vi.waitFor(() => expect(catalogPlaces).toHaveBeenCalledTimes(2));
    resolveNew({ catalog_revision: 'c1', places: [catalogPlace('node/2', 'pub')], matching_count: 1, over_cap: false, day: null });
    await vi.waitFor(() => expect(get(store).catalog.places).toHaveLength(1));
    resolveOld({ catalog_revision: 'c1', places: [catalogPlace('node/1', 'museum')], matching_count: 1, over_cap: false, day: null });
    await Promise.all([first, second]);
    expect(get(store).catalog.places.map(({ identity }) => identity)).toEqual(['node/2']);
    expect(catalogDraw).toHaveBeenLastCalledWith([expect.objectContaining({ identity: 'node/2' })]);
  });

  it('refreshes selected catalog layers after route creation and clears them on replacement', async () => {
    vi.useFakeTimers();
    try {
      const catalogDraw = vi.fn();
      const map = { ...viewportMap(() => {}), catalogPlaces: catalogDraw } as unknown as MapView;
      const { store, catalogPlaces } = setup({ map });
      await store.setEndpointCoordinate('origin', place('origin', 51));
      await store.setEndpointCoordinate('destination', place('destination', 53));
      store.toggleCatalogKinds(['museum'], { basis: 'route', radius_m: 2_000 });
      let onIdle!: (bounds: MapBounds) => void;
      store.setMapView({ ...map, onViewportIdle: vi.fn((callback) => { onIdle = callback; return vi.fn(); }) });
      const bounds = { south: 50, west: -2, north: 54, east: 0 };
      onIdle(bounds);
      await store.planCanalRoute({});
      await vi.advanceTimersByTimeAsync(100);
      expect(catalogPlaces).toHaveBeenCalled();
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
    const catalogPlaces = vi.fn(async () => { throw new Error('Catalog unavailable'); });
    const { store, canalRoute } = setup({ catalogPlaces });
    canalRoute.mockResolvedValue(routeWithLocks);
    await store.setEndpointCoordinate('origin', place('origin', 51));
    await store.setEndpointCoordinate('destination', place('destination', 53));
    await store.planCanalRoute({});
    store.selectDay(1);
    store.toggleCatalogKinds(['museum'], { basis: 'route', radius_m: 2_000 });
    await expect(store.refreshCatalogPlaces({ south: 50, west: -2, north: 54, east: 0 })).resolves.toBeUndefined();
    expect(get(store).canalRoute).toEqual(routeWithLocks);
    expect(get(store).selectedDay).toBe(1);
    expect(get(store).catalog.error).toContain('Catalog unavailable');
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
