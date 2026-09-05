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
import { PoundApiError } from '../api';
import { rankCandidates, type RankedCandidate } from '../planner';
import type {
  BoatHireBase,
  CanalCandidatesRequest,
  CanalCandidatesResponse,
  CanalNetworkRequest,
  CanalNetworkResponse,
  CanalRouteRequest,
  CanalRouteResponse,
  JourneyMode,
  PlaceResponse,
  PlacesRequest,
  PlacesResponse,
  PlacesQueryPolicy,
  GeoJSONLineString,
  HealthResponse,
  LatLon,
  MapBounds,
  RoutePoisRequest,
  RoutePoisResponse,
  TurnaroundCandidatesRequest,
  TurnaroundCandidatesResponse,
  OutAndBackRoute,
  TurnaroundRejection,
} from '../types';

interface PoundApi {
  canalCandidates(request: CanalCandidatesRequest): Promise<CanalCandidatesResponse>;
  canalNetwork(request: CanalNetworkRequest): Promise<CanalNetworkResponse>;
  canalRoute(request: CanalRouteRequest): Promise<CanalRouteResponse>;
  turnaroundCandidates?: (request: TurnaroundCandidatesRequest) => Promise<TurnaroundCandidatesResponse>;
  routePois(request: RoutePoisRequest): Promise<RoutePoisResponse>;
  health?: () => Promise<HealthResponse>;
  places?: (request: PlacesRequest) => Promise<PlacesResponse>;
}

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

export interface PlacesLayerState {
  enabledKinds: string[];
  places: PlaceResponse[];
  loading: boolean;
  error: string | null;
}

export interface TripState {
  origin: EndpointState;
  destination: EndpointState;
  canalRoute: CanalRouteResponse | null;
  routeError: string | null;
  networkError: string | null;
  hasNetworkOverlay: boolean;
  routing: boolean;
  selectedDay: number | null;
  enabledPoiKinds: string[];
  routePois: RoutePoisResponse | null;
  poiError: string | null;
  places: PlacesLayerState;
  placesStatus: HealthResponse['places_status'] | 'unknown';
  placesResultLimitExceeded: boolean;
  journeyMode?: JourneyMode;
  outAndBackRoutes?: OutAndBackRoute[];
  outAndBackRejections?: TurnaroundRejection[];
  outAndBackRequestId?: string | null;
  defaultOutAndBackRouteId?: string | null;
  selectedOutAndBackRouteId?: string | null;
}

export type CanalConstraints = Omit<CanalRouteRequest, 'start_uid' | 'end_uid' | 'artifact_revision'>;

type SuccessfulNetwork = {
  requestGeneration: number;
  lines: GeoJSONLineString[];
  bases: BoatHireBase[];
};

export interface TripStore extends Readable<TripState> {
  setEndpointCoordinate(slot: EndpointSlot, place: SelectedPlace | LatLon): Promise<void>;
  clearEndpoint(slot: EndpointSlot): void;
  selectCandidate(slot: EndpointSlot, uid: number): Promise<void>;
  confirmGeometricFallback(slot: EndpointSlot): void;
  planCanalRoute(constraints: CanalConstraints): Promise<CanalRouteResponse>;
  setJourneyMode: (mode: JourneyMode) => void;
  selectBranchRoute: (routeId: string) => void;
  togglePoiKind(kind: string): void;
  selectDay(day: number | null): void;
  refreshRoutePois(bounds: MapBounds): Promise<void>;
  togglePlaceKind(kind: string, policy?: PlacesQueryPolicy): void;
  togglePlaceKinds(kinds: string[], policy: PlacesQueryPolicy): void;
  refreshPlaces(bounds: MapBounds): Promise<void>;
  reset(): void;
  setNetworkRequest(request: CanalNetworkRequest | null): void;
  setMapView(mapView: MapView | undefined): void;
}

const emptyEndpoint = (): EndpointState => ({
  place: null, candidates: [], selectedUid: null, landRoute: null, transferWarning: null,
  requiresManualConfirmation: false, confirmed: false, loading: false, error: null,
});

const message = (error: unknown) => error instanceof Error ? error.message : String(error);
const isPlace = (value: SelectedPlace | LatLon): value is SelectedPlace => 'coordinate' in value;
const isPoundApiError = (value: unknown, status: number, code?: string): value is PoundApiError =>
  value instanceof PoundApiError && value.status === status && (code === undefined || value.code === code);
const placeKey = (place: PlaceResponse): string => {
  const provenance = place.provenance;
  return provenance.source === 'osm'
    ? JSON.stringify(['osm', provenance.osm_type, provenance.osm_id])
    : JSON.stringify(['boat_hire', provenance.provider_id, provenance.location_id]);
};

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
    selectedDay: null, enabledPoiKinds: [], routePois: null, poiError: null, networkError: null, hasNetworkOverlay: false,
    places: { enabledKinds: [], places: [], loading: false, error: null },
    placesStatus: 'unknown', placesResultLimitExceeded: false,
    journeyMode: 'point_to_point', outAndBackRoutes: [], outAndBackRejections: [],
    outAndBackRequestId: null, defaultOutAndBackRouteId: null, selectedOutAndBackRouteId: null,
  };
  const inner = writable(initial);
  let state = initial;
  inner.subscribe((value) => { state = value; });
  const generations: Record<EndpointSlot, number> = { origin: 0, destination: 0 };
  let routeGeneration = 0;
  let routeRequest = 0;
  let poiRequest = 0;
  let placesRequest = 0;
  let desiredNetworkRequest: CanalNetworkRequest | undefined;
  let networkRequestKey: string | undefined;
  let desiredNetworkGeneration = 0;
  let mapAttachmentGeneration = mapView ? 1 : 0;
  let networkPaintedAttachmentGeneration: number | undefined;
  let successfulNetwork: SuccessfulNetwork | undefined;
  let networkRefreshTimer: ReturnType<typeof setTimeout> | undefined;
  let networkRequest: { generation: number; promise: Promise<void> } | undefined;
  let viewportUnsubscribe: (() => void) | undefined;
  let lastViewportBounds: MapBounds | undefined;
  let poiRefreshTimer: ReturnType<typeof setTimeout> | undefined;
  let placesRefreshTimer: ReturnType<typeof setTimeout> | undefined;
  let placesHealthPromise: Promise<HealthResponse> | undefined;
  let placesAvailabilityGeneration = 0;
  const placesPolicies = new Map<string, PlacesQueryPolicy>();

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
  const cancelScheduledPlacesRefresh = () => {
    if (placesRefreshTimer === undefined) return;
    clearTimeout(placesRefreshTimer);
    placesRefreshTimer = undefined;
  };
  const schedulePlacesRefresh = (bounds: MapBounds) => {
    lastViewportBounds = bounds;
    cancelScheduledPlacesRefresh();
    if (!state.places.enabledKinds.length) return;
    placesRefreshTimer = setTimeout(() => {
      placesRefreshTimer = undefined;
      void refreshPlaces(bounds);
    }, 100);
  };

  const updateEndpoint = (slot: EndpointSlot, patch: Partial<EndpointState>) => {
    inner.update((current) => ({ ...current, [slot]: { ...current[slot], ...patch } }));
  };
  const warn = (slot: EndpointSlot, warning: string) => {
    const existing = state[slot].transferWarning;
    updateEndpoint(slot, { transferWarning: existing ? `${existing} ${warning}` : warning });
  };
  const mapCall = (slot: EndpointSlot, operation: (() => void) | undefined, reportFailure = true) => {
    if (!operation) return;
    try { operation(); } catch (error) {
      if (reportFailure) warn(slot, `Map display failed: ${message(error)}`);
    }
  };
  const isCurrentMapAttachment = (view: MapView, attachmentGeneration: number) =>
    mapView === view && mapAttachmentGeneration === attachmentGeneration;
  const drawNetwork = (view: MapView, attachmentGeneration: number, network: SuccessfulNetwork) => {
    if (network.requestGeneration !== desiredNetworkGeneration ||
        !isCurrentMapAttachment(view, attachmentGeneration)) return;
    mapCall('origin', () => view.network(network.lines));
    if (!isCurrentMapAttachment(view, attachmentGeneration)) return;
    mapCall('origin', () => view.hireBases(network.bases));
    if (!isCurrentMapAttachment(view, attachmentGeneration)) return;
    const shouldFit = networkPaintedAttachmentGeneration !== attachmentGeneration || network.lines.length === 0;
    networkPaintedAttachmentGeneration = attachmentGeneration;
    if (shouldFit && !state.canalRoute && isCurrentMapAttachment(view, attachmentGeneration)) {
      mapCall('origin', () => view.fitNetwork());
    }
  };
  const loadNetwork = () => {
    const request = desiredNetworkRequest;
    const generation = desiredNetworkGeneration;
    if (!mapView || !request || networkRequest?.generation === generation) return;
    const promise = Promise.resolve()
      .then(() => poundApi.canalNetwork(request))
      .then(({ lines, bases }) => {
        if (generation !== desiredNetworkGeneration) return;
        const network = { requestGeneration: generation, lines, bases };
        successfulNetwork = network;
        inner.update((current) => ({ ...current, networkError: null, hasNetworkOverlay: true }));
        const view = mapView;
        if (view) drawNetwork(view, mapAttachmentGeneration, network);
      })
      .catch((error) => {
        if (generation !== desiredNetworkGeneration) return;
        inner.update((current) => ({ ...current, networkError: message(error) }));
      })
      .finally(() => {
        if (networkRequest?.generation === generation) networkRequest = undefined;
      });
    networkRequest = { generation, promise };
  };
  const cancelScheduledNetworkRefresh = () => {
    if (networkRefreshTimer === undefined) return;
    clearTimeout(networkRefreshTimer);
    networkRefreshTimer = undefined;
  };
  const scheduleNetworkRefresh = () => {
    cancelScheduledNetworkRefresh();
    if (!mapView || !desiredNetworkRequest) return;
    const generation = desiredNetworkGeneration;
    networkRefreshTimer = setTimeout(() => {
      networkRefreshTimer = undefined;
      if (!mapView || generation !== desiredNetworkGeneration) return;
      loadNetwork();
    }, 100);
  };
  const setNetworkRequest = (request: CanalNetworkRequest | null) => {
    const nextKey = request === null ? 'invalid' : JSON.stringify([
      request.days, request.hours_per_day, request.boat_length_m, request.boat_beam_m,
      request.boat_draft_m, request.boat_height_m, request.movable_bridge_delay_min,
    ]);
    if (nextKey === networkRequestKey) return;
    networkRequestKey = nextKey;
    if (request === null) {
      invalidateCanalRoute('origin');
      return;
    }
    desiredNetworkRequest = request;
    desiredNetworkGeneration += 1;
    invalidateCanalRoute('origin');
    scheduleNetworkRefresh();
  };
  const clearPlaces = () => {
    cancelScheduledPlacesRefresh();
    placesRequest += 1;
    inner.update((current) => ({
      ...current,
      places: { ...current.places, places: [], loading: false, error: null },
      placesResultLimitExceeded: false,
    }));
    mapCall('origin', () => mapView?.places([]));
  };
  const clearRouteOverlays = () => {
    cancelScheduledPoiRefresh();
    poiRequest += 1;
    clearPlaces();
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
    inner.update((current) => ({
      ...current, canalRoute: null, routeError: null, routing: false,
      outAndBackRoutes: [], outAndBackRejections: [], outAndBackRequestId: null,
      defaultOutAndBackRouteId: null, selectedOutAndBackRouteId: null,
    }));
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

  function clearEndpoint(slot: EndpointSlot): void {
    generations[slot] += 1;
    invalidateCanalRoute(slot);
    clearLand(slot);
    updateEndpoint(slot, emptyEndpoint());
    mapCall(slot, () => mapView?.marker(slot, null));
    mapCall(slot, () => mapView?.candidates(slot, []));
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

  async function planOutAndBack(constraints: CanalConstraints): Promise<CanalRouteResponse> {
    const { origin, destination } = state;
    if (origin.selectedUid === null) throw new Error('Select an origin canal endpoint before routing');
    if (origin.requiresManualConfirmation && !origin.confirmed) {
      throw new Error('Confirm geometric fallback candidates before canal routing');
    }
    if (destination.place && destination.selectedUid === null) {
      throw new Error('Select a canal waypoint or clear the optional visit-on-the-way field');
    }
    if (destination.selectedUid !== null &&
        (destination.requiresManualConfirmation && !destination.confirmed)) {
      throw new Error('Confirm geometric fallback candidates before canal routing');
    }
    if (!origin.artifactRevision ||
        (destination.selectedUid !== null && origin.artifactRevision !== destination.artifactRevision)) {
      throw new Error('Endpoint artifact revisions do not match');
    }
    if (!poundApi.turnaroundCandidates) throw new Error('Out-and-back routing is unavailable');
    if (typeof constraints.days !== 'number' || !Number.isInteger(constraints.days) || constraints.days < 1) {
      throw new Error('Days must be a whole number from 1 through 365.');
    }
    const hoursPerDay = constraints.hours_per_day ?? 6;
    if (typeof hoursPerDay !== 'number' || !Number.isFinite(hoursPerDay) || hoursPerDay <= 0) {
      throw new Error('Hours per day must be greater than 0.');
    }
    const request: TurnaroundCandidatesRequest = {
      artifact_revision: origin.artifactRevision,
      start_uid: origin.selectedUid,
      waypoint_uid: destination.selectedUid,
      ...constraints,
      days: constraints.days,
      hours_per_day: hoursPerDay,
    };
    const endpointGeneration = routeGeneration;
    const requestSequence = ++routeRequest;
    const hadCanalRoute = state.canalRoute !== null;
    clearRouteOverlays();
    inner.update((current) => ({
      ...current, canalRoute: null, routing: true, routeError: null,
      outAndBackRoutes: [], outAndBackRejections: [], outAndBackRequestId: null,
      defaultOutAndBackRouteId: null, selectedOutAndBackRouteId: null,
    }));
    if (hadCanalRoute) mapCall('origin', () => mapView?.canal(null));
    try {
      const result = await poundApi.turnaroundCandidates(request);
      if (endpointGeneration === routeGeneration && requestSequence === routeRequest) {
        const selected = result.routes.find(({ route_id }) => route_id === result.default_route_id) ?? result.routes[0];
        const defaultRouteId = result.default_route_id ?? selected?.route_id ?? null;
        inner.update((current) => ({
          ...current,
          routing: false,
          canalRoute: selected?.journey ?? null,
          outAndBackRoutes: result.routes,
          outAndBackRejections: result.rejections,
          outAndBackRequestId: result.request_id,
          defaultOutAndBackRouteId: defaultRouteId,
          selectedOutAndBackRouteId: selected?.route_id ?? null,
          routeError: selected || result.rejections.length === 0 ? null : result.rejections[0].message,
        }));
        if (selected) {
          mapCall('origin', () => mapView?.canal(selected.journey.geometry));
          mapCall('origin', () => mapView?.locks?.(selected.journey.locks ?? []));
          if (state.enabledPoiKinds.length && lastViewportBounds) schedulePoiRefresh(lastViewportBounds);
          if (state.places.enabledKinds.length && lastViewportBounds) schedulePlacesRefresh(lastViewportBounds);
        }
      }
      const selected = result.routes.find(({ route_id }) => route_id === result.default_route_id) ?? result.routes[0];
      if (!selected) throw new Error(result.rejections[0]?.message ?? 'No feasible out-and-back route found');
      return selected.journey;
    } catch (error) {
      if (endpointGeneration === routeGeneration && requestSequence === routeRequest) {
        const rejections = error instanceof PoundApiError ? error.rejections : [];
        const detail = rejections.length
          ? `${message(error)} ${rejections.map(({ message: rejectionMessage, fields }) => `${rejectionMessage}${fields.length ? ` (${fields.join(', ')})` : ''}`).join(' ')}`
          : message(error);
        inner.update((current) => ({ ...current, routing: false, routeError: detail, outAndBackRejections: rejections }));
      }
      throw error;
    }
  }

  async function planCanalRoute(constraints: CanalConstraints): Promise<CanalRouteResponse> {
    if (state.journeyMode === 'out_and_back') return planOutAndBack(constraints);
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
        if (state.places.enabledKinds.length && lastViewportBounds) schedulePlacesRefresh(lastViewportBounds);
      }
      return result;
    } catch (error) {
      if (endpointGeneration === routeGeneration && requestSequence === routeRequest) {
        inner.update((current) => ({ ...current, routing: false, routeError: message(error) }));
      }
      throw error;
    }
  }

  function setJourneyMode(mode: JourneyMode): void {
    if (state.journeyMode === mode) return;
    invalidateCanalRoute('origin');
    inner.update((current) => ({ ...current, journeyMode: mode }));
  }

  function selectBranchRoute(routeId: string): void {
    const selected = (state.outAndBackRoutes ?? []).find(({ route_id }) => route_id === routeId);
    if (!selected) throw new Error(`Unknown out-and-back route ${routeId}`);
    clearRouteOverlays();
    inner.update((current) => ({ ...current, canalRoute: selected.journey, selectedOutAndBackRouteId: routeId, routeError: null }));
    mapCall('origin', () => mapView?.canal(selected.journey.geometry));
    mapCall('origin', () => mapView?.locks?.(selected.journey.locks ?? []));
    if (state.enabledPoiKinds.length && lastViewportBounds) schedulePoiRefresh(lastViewportBounds);
    if (state.places.enabledKinds.length && lastViewportBounds) schedulePlacesRefresh(lastViewportBounds);
  }

  function selectedDayGeometry(day: number | null) {
    return state.canalRoute?.day_geometries?.find((geometry) => geometry.day === day) ?? null;
  }

  async function placesHealth(): Promise<HealthResponse> {
    if (!placesHealthPromise) {
      placesHealthPromise = poundApi.health
        ? poundApi.health()
        : Promise.reject(new Error('Places health unavailable'));
    }
    const healthGeneration = placesAvailabilityGeneration;
    try {
      const health = await placesHealthPromise;
      if (healthGeneration !== placesAvailabilityGeneration) return health;
      inner.update((current) => ({
        ...current,
        placesStatus: health.places_status,
      }));
      return health;
    } catch (error) {
      placesHealthPromise = undefined;
      if (healthGeneration !== placesAvailabilityGeneration) throw error;
      inner.update((current) => ({
        ...current,
        placesStatus: 'unavailable',
        places: { ...current.places, loading: false, error: current.places.error ?? message(error) },
      }));
      throw error;
    }
  }

  async function refreshPlaces(bounds: MapBounds): Promise<void> {
    cancelScheduledPlacesRefresh();
    lastViewportBounds = bounds;
    const route = state.canalRoute;
    const kinds = [...state.places.enabledKinds];
    if (!route || !kinds.length || !poundApi.places || state.placesStatus === 'unavailable') return;

    const requestSequence = ++placesRequest;
    const routeGeometry = route.geometry;
    inner.update((current) => ({
      ...current,
      places: { ...current.places, places: [], loading: true, error: null },
      placesResultLimitExceeded: false,
    }));
    mapCall('origin', () => mapView?.places([]));

    const day = state.selectedDay;
    const dayGeometry = selectedDayGeometry(day);
    const groups = new Map<string, { kinds: string[]; policy: PlacesQueryPolicy }>();
    for (const kind of kinds) {
      const policy = placesPolicies.get(kind) ?? { basis: 'route', radius_m: 2_000 };
      const key = JSON.stringify(policy);
      const group = groups.get(key);
      if (group) group.kinds.push(kind);
      else groups.set(key, { kinds: [kind], policy });
    }

    const requests = [...groups.values()].map(({ kinds: groupKinds, policy }) => ({
      mode: 'viewport' as const,
      kinds: groupKinds,
      bounds,
      route_geometry: routeGeometry,
      ...(dayGeometry ? { day_geometry: dayGeometry.geometry } : {}),
      policy,
    } satisfies PlacesRequest));
    const responses = await Promise.allSettled(requests.map((request) => poundApi.places!(request)));
    if (requestSequence !== placesRequest || route !== state.canalRoute) return;

    const placesByKey = new Map<string, PlaceResponse>();
    let resultLimited = false;
    let firstError: unknown = null;
    let runtimeUnavailable = false;
    for (const result of responses) {
      if (result.status === 'fulfilled') {
        for (const place of result.value.places) placesByKey.set(placeKey(place), place);
      } else if (isPoundApiError(result.reason, 413, 'places_result_limit_exceeded')) {
        resultLimited = true;
      } else {
        if (isPoundApiError(result.reason, 503)) runtimeUnavailable = true;
        if (firstError === null) firstError = result.reason;
      }
    }
    const places = [...placesByKey.values()];
    if (runtimeUnavailable) placesAvailabilityGeneration += 1;
    inner.update((current) => ({
      ...current,
      placesStatus: runtimeUnavailable ? 'unavailable' : current.placesStatus,
      places: { ...current.places, places, loading: false, error: firstError === null ? null : message(firstError) },
      placesResultLimitExceeded: resultLimited,
    }));
    mapCall('origin', () => mapView?.places(places));
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

  function togglePlaceKinds(kinds: string[], policy: PlacesQueryPolicy): void {
    cancelScheduledPlacesRefresh();
    const allEnabled = kinds.every((kind) => state.places.enabledKinds.includes(kind));
    const enabledKinds = allEnabled
      ? state.places.enabledKinds.filter((kind) => !kinds.includes(kind))
      : [...state.places.enabledKinds, ...kinds.filter((kind) => !state.places.enabledKinds.includes(kind))];
    for (const kind of kinds) {
      if (allEnabled) placesPolicies.delete(kind);
      else placesPolicies.set(kind, policy);
    }
    placesRequest += 1;
    inner.update((current) => ({
      ...current,
      places: { ...current.places, enabledKinds },
      placesResultLimitExceeded: false,
    }));
    clearPlaces();
    if (enabledKinds.length && lastViewportBounds) schedulePlacesRefresh(lastViewportBounds);
  }

  function togglePlaceKind(kind: string, policy: PlacesQueryPolicy = { basis: 'route', radius_m: 2_000 }): void {
    togglePlaceKinds([kind], policy);
  }

  function selectDay(day: number | null): void {
    cancelScheduledPoiRefresh();
    cancelScheduledPlacesRefresh();
    poiRequest += 1;
    inner.update((current) => ({ ...current, selectedDay: day, routePois: null, poiError: null }));
    clearPlaces();
    mapCall('origin', () => mapView?.pois?.([]));
    mapCall('origin', () => mapView?.day?.(selectedDayGeometry(day)));
    if (state.enabledPoiKinds.length && lastViewportBounds) schedulePoiRefresh(lastViewportBounds);
    if (state.places.enabledKinds.length && lastViewportBounds) schedulePlacesRefresh(lastViewportBounds);
  }

  function reset(): void {
    generations.origin += 1;
    generations.destination += 1;
    routeGeneration += 1;
    routeRequest += 1;
    poiRequest += 1;
    placesRequest += 1;
    cancelScheduledPoiRefresh();
    cancelScheduledPlacesRefresh();
    placesPolicies.clear();
    const networkError = state.networkError;
    const hasNetworkOverlay = state.hasNetworkOverlay;
    inner.set({
      ...initial,
      origin: emptyEndpoint(),
      destination: emptyEndpoint(),
      places: { ...initial.places },
      networkError,
      hasNetworkOverlay,
    });
    for (const slot of ['origin', 'destination'] as const) {
      mapCall(slot, () => mapView?.marker(slot, null), false);
      mapCall(slot, () => mapView?.candidates(slot, []), false);
      mapCall(slot, () => mapView?.clearLand(slot), false);
    }
    mapCall('origin', () => mapView?.canal(null), false);
    mapCall('origin', () => mapView?.day?.(null), false);
    mapCall('origin', () => mapView?.locks?.([]), false);
    mapCall('origin', () => mapView?.pois?.([]), false);
    mapCall('origin', () => mapView?.places([]), false);
    const view = mapView;
    const attachmentGeneration = mapAttachmentGeneration;
    if (successfulNetwork && view && isCurrentMapAttachment(view, attachmentGeneration)) {
      mapCall('origin', () => view.fitNetwork(), false);
    }
  }

  if (poundApi.health) void placesHealth().catch(() => {});

  return {
    subscribe: inner.subscribe, setEndpointCoordinate, clearEndpoint, selectCandidate, confirmGeometricFallback,
    planCanalRoute, togglePoiKind, togglePlaceKind, togglePlaceKinds, selectDay, refreshRoutePois, refreshPlaces,
    reset, setNetworkRequest, setJourneyMode, selectBranchRoute,
    setMapView(value) {
      cancelScheduledPoiRefresh();
      viewportUnsubscribe?.();
      viewportUnsubscribe = undefined;
      lastViewportBounds = undefined;
      cancelScheduledNetworkRefresh();
      mapAttachmentGeneration += 1;
      const attachmentGeneration = mapAttachmentGeneration;
      mapView = value;
      if (!mapView) return;
      const network = successfulNetwork;
      if (network?.requestGeneration === desiredNetworkGeneration) {
        drawNetwork(mapView, attachmentGeneration, network);
      } else {
        loadNetwork();
      }
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
      mapCall('origin', () => mapView?.places(state.places.places));
      try {
        viewportUnsubscribe = mapView.onViewportIdle?.((bounds) => {
          if (state.enabledPoiKinds.length) schedulePoiRefresh(bounds);
          if (state.places.enabledKinds.length) schedulePlacesRefresh(bounds);
          if (!state.enabledPoiKinds.length && !state.places.enabledKinds.length) lastViewportBounds = bounds;
        });
      } catch (error) {
        warn('origin', `Map display failed: ${message(error)}`);
      }
    },
  };
}
