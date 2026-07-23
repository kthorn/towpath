import { writable, type Readable } from 'svelte/store';

import type { TransferMode } from '../config';
import type {
  EndpointSlot,
  LandRoute,
  MapView,
  SelectedPlace,
  TransferResult,
  TransferRouter,
} from '../google/contracts';
import { rankCandidates, type RankedCandidate } from '../planner';
import type {
  CanalCandidatesRequest,
  CanalCandidatesResponse,
  CanalRouteRequest,
  CanalRouteResponse,
  CatalogPlace,
  CatalogPlacesRequest,
  CatalogPlacesResponse,
  CatalogQueryPolicy,
  HealthResponse,
  LatLon,
  MapBounds,
  RoutePoisRequest,
  RoutePoisResponse,
} from '../types';

interface PoundApi {
  canalCandidates(request: CanalCandidatesRequest): Promise<CanalCandidatesResponse>;
  canalRoute(request: CanalRouteRequest): Promise<CanalRouteResponse>;
  routePois(request: RoutePoisRequest): Promise<RoutePoisResponse>;
  health?: () => Promise<HealthResponse>;
  catalogPlaces?: (request: CatalogPlacesRequest) => Promise<CatalogPlacesResponse>;
}

type CatalogMapView = MapView & { catalogPlaces?: (places: CatalogPlace[]) => void };

export interface EndpointState {
  place: SelectedPlace | null;
  candidates: RankedCandidate[];
  selectedUid: number | null;
  artifactRevision?: string;
  landRoute: LandRoute | null;
  transferWarning: string | null;
  requiresManualConfirmation: boolean;
  confirmed: boolean;
  loading: boolean;
  error: string | null;
}

export interface CatalogLayerState {
  enabledKinds: string[];
  places: CatalogPlace[];
  loading: boolean;
  error: string | null;
}

export interface TripState {
  origin: EndpointState;
  destination: EndpointState;
  canalRoute: CanalRouteResponse | null;
  routeError: string | null;
  routing: boolean;
  selectedDay: number | null;
  enabledPoiKinds: string[];
  routePois: RoutePoisResponse | null;
  poiError: string | null;
  catalog: CatalogLayerState;
  catalogRevision: string | null;
  catalogStatus: HealthResponse['catalog_status'] | 'unknown';
  catalogMatchingCount: number;
  catalogOverCap: boolean;
}

export type CanalConstraints = Omit<CanalRouteRequest, 'start_uid' | 'end_uid' | 'artifact_revision'>;

export interface TripStore extends Readable<TripState> {
  setEndpointCoordinate(slot: EndpointSlot, place: SelectedPlace | LatLon): Promise<void>;
  selectCandidate(slot: EndpointSlot, uid: number): Promise<void>;
  confirmGeometricFallback(slot: EndpointSlot): void;
  planCanalRoute(constraints: CanalConstraints): Promise<CanalRouteResponse>;
  togglePoiKind(kind: string): void;
  selectDay(day: number | null): void;
  refreshRoutePois(bounds: MapBounds): Promise<void>;
  toggleCatalogKind(kind: string, policy?: CatalogQueryPolicy): void;
  toggleCatalogKinds(kinds: string[], policy: CatalogQueryPolicy): void;
  refreshCatalogPlaces(bounds: MapBounds): Promise<void>;
  setMapView(mapView: MapView | undefined): void;
}

const emptyEndpoint = (): EndpointState => ({
  place: null, candidates: [], selectedUid: null, landRoute: null, transferWarning: null,
  requiresManualConfirmation: false, confirmed: false, loading: false, error: null,
});

const message = (error: unknown) => error instanceof Error ? error.message : String(error);
const isPlace = (value: SelectedPlace | LatLon): value is SelectedPlace => 'coordinate' in value;

export function createTripStore(dependencies: {
  poundApi: PoundApi;
  transferRouter: TransferRouter;
  mapView?: MapView;
  transferMode: TransferMode;
}): TripStore {
  const { poundApi, transferRouter, transferMode } = dependencies;
  let mapView = dependencies.mapView;
  const initial: TripState = {
    origin: emptyEndpoint(), destination: emptyEndpoint(), canalRoute: null, routeError: null, routing: false,
    selectedDay: null, enabledPoiKinds: [], routePois: null, poiError: null,
    catalog: { enabledKinds: [], places: [], loading: false, error: null },
    catalogRevision: null, catalogStatus: 'unknown', catalogMatchingCount: 0, catalogOverCap: false,
  };
  const inner = writable(initial);
  let state = initial;
  inner.subscribe((value) => { state = value; });
  const generations: Record<EndpointSlot, number> = { origin: 0, destination: 0 };
  let routeGeneration = 0;
  let routeRequest = 0;
  let poiRequest = 0;
  let catalogRequest = 0;
  let viewportUnsubscribe: (() => void) | undefined;
  let lastViewportBounds: MapBounds | undefined;
  let poiRefreshTimer: ReturnType<typeof setTimeout> | undefined;
  let catalogRefreshTimer: ReturnType<typeof setTimeout> | undefined;
  let catalogHealthPromise: Promise<HealthResponse> | undefined;
  const catalogPolicies = new Map<string, CatalogQueryPolicy>();

  const cancelScheduledPoiRefresh = () => {
    if (poiRefreshTimer === undefined) return;
    clearTimeout(poiRefreshTimer);
    poiRefreshTimer = undefined;
  };
  const schedulePoiRefresh = (bounds: MapBounds) => {
    lastViewportBounds = bounds;
    cancelScheduledPoiRefresh();
    if (!state.enabledPoiKinds.length) return;
    poiRefreshTimer = setTimeout(() => {
      poiRefreshTimer = undefined;
      void refreshRoutePois(bounds);
    }, 100);
  };
  const cancelScheduledCatalogRefresh = () => {
    if (catalogRefreshTimer === undefined) return;
    clearTimeout(catalogRefreshTimer);
    catalogRefreshTimer = undefined;
  };
  const scheduleCatalogRefresh = (bounds: MapBounds) => {
    lastViewportBounds = bounds;
    cancelScheduledCatalogRefresh();
    if (!state.catalog.enabledKinds.length) return;
    catalogRefreshTimer = setTimeout(() => {
      catalogRefreshTimer = undefined;
      void refreshCatalogPlaces(bounds);
    }, 100);
  };

  const updateEndpoint = (slot: EndpointSlot, patch: Partial<EndpointState>) => {
    inner.update((current) => ({ ...current, [slot]: { ...current[slot], ...patch } }));
  };
  const warn = (slot: EndpointSlot, warning: string) => {
    const existing = state[slot].transferWarning;
    updateEndpoint(slot, { transferWarning: existing ? `${existing} ${warning}` : warning });
  };
  const mapCall = (slot: EndpointSlot, operation: (() => void) | undefined) => {
    if (!operation) return;
    try { operation(); } catch (error) { warn(slot, `Map display failed: ${message(error)}`); }
  };
  const clearCatalogPlaces = () => {
    cancelScheduledCatalogRefresh();
    catalogRequest += 1;
    inner.update((current) => ({
      ...current,
      catalog: { ...current.catalog, places: [], loading: false, error: null },
      catalogMatchingCount: 0,
      catalogOverCap: false,
    }));
    mapCall('origin', () => (mapView as CatalogMapView | undefined)?.catalogPlaces?.([]));
  };
  const clearRouteOverlays = () => {
    cancelScheduledPoiRefresh();
    poiRequest += 1;
    clearCatalogPlaces();
    inner.update((current) => ({
      ...current,
      selectedDay: null,
      routePois: null,
      poiError: null,
    }));
    mapCall('origin', () => mapView?.pois?.([]));
    mapCall('origin', () => mapView?.locks?.([]));
    mapCall('origin', () => mapView?.day?.(null));
  };
  const invalidateCanalRoute = (slot: EndpointSlot) => {
    routeGeneration += 1;
    inner.update((current) => ({ ...current, canalRoute: null, routeError: null, routing: false }));
    clearRouteOverlays();
    mapCall(slot, () => mapView?.canal(null));
  };
  const clearLand = (slot: EndpointSlot) => {
    mapCall(slot, () => mapView?.clearLand(slot));
  };

  async function loadLandRoute(slot: EndpointSlot, generation: number): Promise<void> {
    const endpoint = state[slot];
    const selected = endpoint.candidates.find(({ candidate }) => candidate.uid === endpoint.selectedUid);
    if (!endpoint.place || !selected) return;
    try {
      const route = await transferRouter.route(endpoint.place.coordinate, selected.candidate.coordinate, transferMode);
      if (generation !== generations[slot] || state[slot].selectedUid !== selected.candidate.uid) return;
      updateEndpoint(slot, { landRoute: route });
      mapCall(slot, () => mapView?.land(slot, route));
    } catch (error) {
      if (generation !== generations[slot]) return;
      updateEndpoint(slot, { landRoute: null });
      clearLand(slot);
      warn(slot, `Land route unavailable: ${message(error)}`);
    }
  }

  async function setEndpointCoordinate(slot: EndpointSlot, input: SelectedPlace | LatLon): Promise<void> {
    const generation = ++generations[slot];
    const place: SelectedPlace = isPlace(input)
      ? input
      : { name: 'Selected point', address: '', coordinate: input };
    updateEndpoint(slot, { ...emptyEndpoint(), place, loading: true });
    invalidateCanalRoute(slot);
    clearLand(slot);
    mapCall(slot, () => mapView?.marker(slot, place.coordinate));
    let candidateResponse: CanalCandidatesResponse;
    try {
      candidateResponse = await poundApi.canalCandidates(place.coordinate);
    } catch (error) {
      if (generation === generations[slot]) updateEndpoint(slot, { loading: false, error: message(error) });
      return;
    }
    if (generation !== generations[slot]) return;

    let matrix: TransferResult[];
    let matrixWarning: string | null = null;
    try {
      matrix = await transferRouter.matrix(
        place.coordinate,
        candidateResponse.candidates.map(({ coordinate }) => coordinate),
        transferMode,
      );
    } catch (error) {
      matrix = [];
      matrixWarning = `Transfer routing failed: ${message(error)}`;
    }
    if (generation !== generations[slot]) return;
    const ranked = rankCandidates(candidateResponse.candidates, matrix);
    const allUnavailable = ranked.length > 0 && ranked.every(({ available }) => !available);
    const selectedUid = ranked[0]?.candidate.uid ?? null;
    const priorWarning = state[slot].transferWarning;
    const fallbackWarning = allUnavailable
      ? 'Could not verify a land transfer. Confirm the geometric fallback before canal routing.'
      : null;
    const transferWarning = [priorWarning, fallbackWarning, matrixWarning].filter(Boolean).join(' ') || null;
    updateEndpoint(slot, {
      candidates: ranked, selectedUid, artifactRevision: candidateResponse.artifact_revision,
      requiresManualConfirmation: allUnavailable, confirmed: !allUnavailable,
      transferWarning,
      loading: false, error: null,
    });
    mapCall(slot, () => mapView?.candidates(slot, candidateResponse.candidates, selectedUid ?? undefined));
    if (selectedUid !== null) await loadLandRoute(slot, generation);
  }

  async function selectCandidate(slot: EndpointSlot, uid: number): Promise<void> {
    if (!state[slot].candidates.some(({ candidate }) => candidate.uid === uid)) {
      throw new Error(`Unknown ${slot} candidate UID ${uid}`);
    }
    const generation = ++generations[slot];
    invalidateCanalRoute(slot);
    clearLand(slot);
    updateEndpoint(slot, {
      selectedUid: uid,
      landRoute: null,
      confirmed: state[slot].requiresManualConfirmation ? false : state[slot].confirmed,
    });
    mapCall(slot, () => mapView?.candidates(
      slot, state[slot].candidates.map(({ candidate }) => candidate), uid,
    ));
    await loadLandRoute(slot, generation);
  }

  function confirmGeometricFallback(slot: EndpointSlot): void {
    if (state[slot].requiresManualConfirmation) updateEndpoint(slot, { confirmed: true });
  }

  async function planCanalRoute(constraints: CanalConstraints): Promise<CanalRouteResponse> {
    const { origin, destination } = state;
    if (origin.selectedUid === null || destination.selectedUid === null) {
      throw new Error('Select both canal endpoints before routing');
    }
    if ((origin.requiresManualConfirmation && !origin.confirmed) ||
        (destination.requiresManualConfirmation && !destination.confirmed)) {
      throw new Error('Confirm geometric fallback candidates before canal routing');
    }
    if (!origin.artifactRevision || origin.artifactRevision !== destination.artifactRevision) {
      throw new Error('Endpoint artifact revisions do not match');
    }
    const request: CanalRouteRequest = {
      start_uid: origin.selectedUid,
      end_uid: destination.selectedUid,
      artifact_revision: origin.artifactRevision,
      ...constraints,
    };
    const endpointGeneration = routeGeneration;
    const requestSequence = ++routeRequest;
    const hadCanalRoute = state.canalRoute !== null;
    clearRouteOverlays();
    inner.update((current) => ({ ...current, canalRoute: null, routing: true, routeError: null }));
    if (hadCanalRoute) mapCall('origin', () => mapView?.canal(null));
    try {
      const result = await poundApi.canalRoute(request);
      if (endpointGeneration === routeGeneration && requestSequence === routeRequest) {
        inner.update((current) => ({ ...current, routing: false, canalRoute: result }));
        mapCall('origin', () => mapView?.canal(result.geometry));
        mapCall('origin', () => mapView?.locks?.(result.locks ?? []));
        if (state.catalog.enabledKinds.length && lastViewportBounds) scheduleCatalogRefresh(lastViewportBounds);
      }
      return result;
    } catch (error) {
      if (endpointGeneration === routeGeneration && requestSequence === routeRequest) {
        inner.update((current) => ({ ...current, routing: false, routeError: message(error) }));
      }
      throw error;
    }
  }

  function selectedDayGeometry(day: number | null) {
    return state.canalRoute?.day_geometries?.find((geometry) => geometry.day === day) ?? null;
  }

  async function catalogHealth(): Promise<HealthResponse> {
    if (!catalogHealthPromise) {
      catalogHealthPromise = poundApi.health
        ? poundApi.health()
        : Promise.reject(new Error('Catalog health unavailable'));
    }
    try {
      const health = await catalogHealthPromise;
      inner.update((current) => ({
        ...current,
        catalogRevision: health.catalog_revision,
        catalogStatus: health.catalog_status,
      }));
      return health;
    } catch (error) {
      catalogHealthPromise = undefined;
      inner.update((current) => ({
        ...current,
        catalogStatus: 'unavailable',
        catalog: { ...current.catalog, loading: false, error: message(error) },
      }));
      throw error;
    }
  }

  async function refreshCatalogPlaces(bounds: MapBounds): Promise<void> {
    cancelScheduledCatalogRefresh();
    lastViewportBounds = bounds;
    const route = state.canalRoute;
    const kinds = [...state.catalog.enabledKinds];
    if (!route || !kinds.length || !poundApi.catalogPlaces) return;

    const requestSequence = ++catalogRequest;
    const routeGeometry = route.geometry;
    inner.update((current) => ({
      ...current,
      catalog: { ...current.catalog, places: [], loading: true, error: null },
      catalogMatchingCount: 0,
      catalogOverCap: false,
    }));
    mapCall('origin', () => (mapView as CatalogMapView | undefined)?.catalogPlaces?.([]));

    let health: HealthResponse;
    try {
      health = await catalogHealth();
    } catch {
      if (requestSequence === catalogRequest && route === state.canalRoute) {
        inner.update((current) => ({ ...current, catalog: { ...current.catalog, loading: false } }));
      }
      return;
    }
    if (requestSequence !== catalogRequest || route !== state.canalRoute) return;
    if (health.catalog_status !== 'available' || !health.catalog_revision) {
      inner.update((current) => ({
        ...current,
        catalog: { ...current.catalog, loading: false, error: 'Catalog unavailable' },
      }));
      return;
    }

    const day = state.selectedDay;
    const dayGeometry = selectedDayGeometry(day);
    const groups = new Map<string, { kinds: string[]; policy: CatalogQueryPolicy }>();
    for (const kind of kinds) {
      const policy = catalogPolicies.get(kind) ?? { basis: 'route', radius_m: 2_000 };
      const key = JSON.stringify(policy);
      const group = groups.get(key);
      if (group) group.kinds.push(kind);
      else groups.set(key, { kinds: [kind], policy });
    }

    async function queryCatalog(health: HealthResponse, canRetry: boolean): Promise<void> {
      if (requestSequence !== catalogRequest || route !== state.canalRoute) return;
      if (health.catalog_status !== 'available' || !health.catalog_revision) {
        inner.update((current) => ({
          ...current,
          catalog: { ...current.catalog, loading: false, error: 'Catalog unavailable' },
        }));
        return;
      }
      const requests = [...groups.values()].map(({ kinds: groupKinds, policy }) => ({
        catalog_revision: health.catalog_revision!,
        kinds: groupKinds,
        bounds,
        route_geometry: routeGeometry,
        ...(dayGeometry ? { day_geometry: dayGeometry.geometry } : {}),
        day,
        policy,
      } satisfies CatalogPlacesRequest));
      const responses = await Promise.allSettled(requests.map((request) => poundApi.catalogPlaces!(request)));
      if (requestSequence !== catalogRequest || route !== state.canalRoute) return;

      const failures = responses.filter((result): result is PromiseRejectedResult => result.status === 'rejected');
      const revisionMismatch = canRetry && failures.some(({ reason }) => {
        if (typeof reason !== 'object' || reason === null) return false;
        const error = reason as { status?: unknown; code?: unknown };
        return error.status === 409 && error.code === 'catalog_revision_mismatch';
      });
      if (revisionMismatch) {
        catalogHealthPromise = undefined;
        inner.update((current) => ({ ...current, catalogRevision: null, catalogStatus: 'unknown' }));
        try {
          await queryCatalog(await catalogHealth(), false);
        } catch {
          if (requestSequence === catalogRequest && route === state.canalRoute) {
            inner.update((current) => ({ ...current, catalog: { ...current.catalog, loading: false } }));
          }
        }
        return;
      }

      const placesByIdentity = new Map<string, CatalogPlace>();
      let matchingCount = 0;
      let overCap = false;
      for (const result of responses) {
        if (result.status !== 'fulfilled') continue;
        matchingCount += result.value.matching_count;
        overCap ||= result.value.over_cap;
        for (const place of result.value.places) placesByIdentity.set(place.identity, place);
      }
      const error = failures.length ? message(failures[0].reason) : null;
      const places = [...placesByIdentity.values()];
      inner.update((current) => ({
        ...current,
        catalog: { ...current.catalog, places, loading: false, error },
        catalogMatchingCount: matchingCount,
        catalogOverCap: overCap,
      }));
      mapCall('origin', () => (mapView as CatalogMapView | undefined)?.catalogPlaces?.(places));
    }

    await queryCatalog(health, true);
  }

  async function refreshRoutePois(bounds: MapBounds): Promise<void> {
    cancelScheduledPoiRefresh();
    const route = state.canalRoute;
    const kinds = [...state.enabledPoiKinds];
    const artifactRevision = state.origin.artifactRevision ?? state.destination.artifactRevision;
    if (!route || !kinds.length || !artifactRevision) return;

    const selectedDay = state.selectedDay;
    const dayGeometry = selectedDayGeometry(selectedDay);
    const request: RoutePoisRequest = {
      artifact_revision: artifactRevision,
      kinds,
      bounds,
      route_geometry: route.geometry,
      ...(dayGeometry ? { day_geometry: dayGeometry.geometry } : {}),
      day: selectedDay,
    };
    const requestSequence = ++poiRequest;
    try {
      const result = await poundApi.routePois(request);
      if (requestSequence !== poiRequest || route !== state.canalRoute) return;
      inner.update((current) => ({ ...current, routePois: result, poiError: null }));
      mapCall('origin', () => mapView?.pois?.(result.pois));
    } catch (error) {
      if (requestSequence !== poiRequest || route !== state.canalRoute) return;
      inner.update((current) => ({ ...current, poiError: message(error) }));
    }
  }

  function togglePoiKind(kind: string): void {
    cancelScheduledPoiRefresh();
    const enabled = state.enabledPoiKinds.includes(kind);
    const kinds = enabled
      ? state.enabledPoiKinds.filter((value) => value !== kind)
      : [...state.enabledPoiKinds, kind];
    poiRequest += 1;
    inner.update((current) => ({ ...current, enabledPoiKinds: kinds, routePois: null, poiError: null }));
    mapCall('origin', () => mapView?.pois?.([]));
    if (kinds.length && lastViewportBounds) schedulePoiRefresh(lastViewportBounds);
  }

  function toggleCatalogKinds(kinds: string[], policy: CatalogQueryPolicy): void {
    cancelScheduledCatalogRefresh();
    const allEnabled = kinds.every((kind) => state.catalog.enabledKinds.includes(kind));
    const enabledKinds = allEnabled
      ? state.catalog.enabledKinds.filter((kind) => !kinds.includes(kind))
      : [...state.catalog.enabledKinds, ...kinds.filter((kind) => !state.catalog.enabledKinds.includes(kind))];
    for (const kind of kinds) {
      if (allEnabled) catalogPolicies.delete(kind);
      else catalogPolicies.set(kind, policy);
    }
    catalogRequest += 1;
    inner.update((current) => ({
      ...current,
      catalog: { ...current.catalog, enabledKinds },
      catalogMatchingCount: 0,
      catalogOverCap: false,
    }));
    clearCatalogPlaces();
    if (enabledKinds.length && lastViewportBounds) scheduleCatalogRefresh(lastViewportBounds);
  }

  function toggleCatalogKind(kind: string, policy: CatalogQueryPolicy = { basis: 'route', radius_m: 2_000 }): void {
    toggleCatalogKinds([kind], policy);
  }

  function selectDay(day: number | null): void {
    cancelScheduledPoiRefresh();
    cancelScheduledCatalogRefresh();
    poiRequest += 1;
    inner.update((current) => ({ ...current, selectedDay: day, routePois: null, poiError: null }));
    clearCatalogPlaces();
    mapCall('origin', () => mapView?.pois?.([]));
    mapCall('origin', () => mapView?.day?.(selectedDayGeometry(day)));
    if (state.enabledPoiKinds.length && lastViewportBounds) schedulePoiRefresh(lastViewportBounds);
    if (state.catalog.enabledKinds.length && lastViewportBounds) scheduleCatalogRefresh(lastViewportBounds);
  }

  if (poundApi.health) void catalogHealth().catch(() => {});

  return {
    subscribe: inner.subscribe, setEndpointCoordinate, selectCandidate, confirmGeometricFallback,
    planCanalRoute, togglePoiKind, toggleCatalogKind, toggleCatalogKinds, selectDay, refreshRoutePois, refreshCatalogPlaces,
    setMapView(value) {
      cancelScheduledPoiRefresh();
      viewportUnsubscribe?.();
      viewportUnsubscribe = undefined;
      lastViewportBounds = undefined;
      mapView = value;
      if (!mapView) return;
      for (const slot of ['origin', 'destination'] as const) {
        const endpoint = state[slot];
        if (endpoint.place) mapCall(slot, () => mapView?.marker(slot, endpoint.place!.coordinate));
        mapCall(slot, () => mapView?.candidates(
          slot, endpoint.candidates.map(({ candidate }) => candidate), endpoint.selectedUid ?? undefined,
        ));
        if (endpoint.landRoute) mapCall(slot, () => mapView?.land(slot, endpoint.landRoute));
      }
      mapCall('origin', () => mapView?.canal(state.canalRoute?.geometry ?? null));
      mapCall('origin', () => mapView?.locks?.(state.canalRoute?.locks ?? []));
      mapCall('origin', () => mapView?.day?.(selectedDayGeometry(state.selectedDay)));
      mapCall('origin', () => mapView?.pois?.(state.routePois?.pois ?? []));
      mapCall('origin', () => (mapView as CatalogMapView | undefined)?.catalogPlaces?.(state.catalog.places));
      try {
        viewportUnsubscribe = mapView.onViewportIdle?.((bounds) => {
          if (state.enabledPoiKinds.length) schedulePoiRefresh(bounds);
          if (state.catalog.enabledKinds.length) scheduleCatalogRefresh(bounds);
          if (!state.enabledPoiKinds.length && !state.catalog.enabledKinds.length) lastViewportBounds = bounds;
        });
      } catch (error) {
        warn('origin', `Map display failed: ${message(error)}`);
      }
    },
  };
}
