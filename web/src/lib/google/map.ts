import type {
  BoatHireBase,
  BoatHireProvenance,
  CanalCandidate,
  GeoJSONLineString,
  OsmProvenance,
  PlaceResponse,
  LatLon,
  MapBounds,
  RouteDayGeometry,
  RouteLock,
  RoutePoi,
} from '../types';
import type { EndpointSlot, LandRoute, MapView } from './contracts';
import { geoJsonToGooglePath, toGoogleLatLng, type GoogleLatLngLiteral } from './routes';
import { buildGoogleMapsSearchUrl } from './searchUrl';

export interface RemovableListener {
  remove(): void;
}

export interface MapClickEvent {
  latLng?: { lat(): number; lng(): number };
}

export interface MarkerEvent {
  stopPropagation?: () => void;
  domEvent?: { stopPropagation?: () => void };
}

export type MarkerEventName = 'click' | 'mouseenter' | 'mouseleave';

export interface MapInstance {
  addListener(event: 'click', callback: (event: MapClickEvent) => void): RemovableListener;
  addListener(event: 'idle', callback: () => void): RemovableListener;
}

export interface MarkerInstance {
  map: MapInstance | null;
  title: string;
}

export interface PolylineInstance {
  setMap(map: MapInstance | null): void;
  setPath(path: GoogleLatLngLiteral[]): void;
}

export interface InfoWindowInstance {
  setContent(content: Node | string | null): void;
  open(options: { map: MapInstance; anchor?: MarkerInstance }): void;
  close(): void;
  addListener(event: 'closeclick', callback: () => void): RemovableListener;
}

export interface MapFacade {
  createMap(element: HTMLElement, options: Record<string, unknown>): MapInstance;
  createMarker(options: {
    map: MapInstance;
    position: GoogleLatLngLiteral;
    title?: string;
    content?: Node;
    anchorLeft?: string;
    anchorTop?: string;
    gmpClickable?: boolean;
    zIndex?: number;
  }): MarkerInstance;
  addMarkerListener(
    marker: MarkerInstance,
    event: MarkerEventName,
    callback: (event: MarkerEvent) => void,
  ): RemovableListener;
  createInfoWindow(): InfoWindowInstance;
  createPolyline(options: {
    map: MapInstance;
    path: GoogleLatLngLiteral[];
    strokeColor: string;
    strokeWeight: number;
    strokeOpacity?: number;
    zIndex?: number;
  }): PolylineInstance;
  fitBounds(map: MapInstance, points: GoogleLatLngLiteral[]): void;
  getBounds(map: MapInstance): MapBounds | undefined;
  getZoom(map: MapInstance): number | undefined;
}

const GROUP_STYLES = {
  attractions: { color: '#7c3aed' },
  hospitality: { color: '#d97706' },
  shops: { color: '#16a34a' },
  utilities: { color: '#2563eb' },
} as const;

const KIND_GROUPS: Record<string, keyof typeof GROUP_STYLES> = {
  museum: 'attractions',
  gallery: 'attractions',
  historic_site: 'attractions',
  garden: 'attractions',
  wildlife_attraction: 'attractions',
  landmark: 'attractions',
  pub: 'hospitality',
  cafe: 'hospitality',
  restaurant: 'hospitality',
  supermarket: 'shops',
  convenience: 'shops',
  bakery: 'shops',
  greengrocer: 'shops',
  butcher: 'shops',
  deli: 'shops',
  general: 'shops',
  marina: 'utilities',
  mooring: 'utilities',
  fuel: 'utilities',
  water_point: 'utilities',
  sanitary_disposal: 'utilities',
};

const KIND_GLYPHS: Record<string, string> = {
  museum: 'M',
  gallery: 'G',
  historic_site: 'H',
  garden: 'G',
  wildlife_attraction: 'W',
  landmark: 'L',
  pub: 'P',
  cafe: 'C',
  restaurant: 'R',
  supermarket: 'S',
  convenience: 'C',
  bakery: 'B',
  greengrocer: 'G',
  butcher: 'B',
  deli: 'D',
  general: 'G',
  marina: '⚓',
  mooring: '⚓',
  fuel: 'F',
  water_point: 'W',
  sanitary_disposal: 'S',
};

function removeMarkers(markers: MarkerInstance[]): void {
  for (const marker of markers) marker.map = null;
  markers.length = 0;
}

function removeListeners(listeners: RemovableListener[]): void {
  for (const listener of listeners) listener.remove();
  listeners.length = 0;
}

function markerContent(documentRef: Document, kind: string, label: string): HTMLElement {
  const group = KIND_GROUPS[kind] ?? 'attractions';
  const content = documentRef.createElement('span');
  content.className = 'pound-catalog-marker';
  content.dataset.group = group;
  content.dataset.kind = kind;
  content.setAttribute('role', 'img');
  content.setAttribute('aria-label', label);
  content.textContent = KIND_GLYPHS[kind] ?? kind.slice(0, 1).toUpperCase();
  content.style.backgroundColor = GROUP_STYLES[group].color;
  content.style.color = '#ffffff';
  content.style.display = 'grid';
  content.style.placeItems = 'center';
  content.style.borderRadius = '50%';
  content.style.width = '28px';
  content.style.height = '28px';
  content.style.fontWeight = '700';
  return content;
}

function lockContent(documentRef: Document, label: string): HTMLElement {
  const content = documentRef.createElement('span');
  content.className = 'pound-lock-marker';
  content.dataset.group = 'locks';
  content.setAttribute('role', 'img');
  content.setAttribute('aria-label', label);
  content.textContent = '⌄';
  content.style.color = '#4b5563';
  content.style.fontSize = '28px';
  content.style.fontWeight = '700';
  content.style.lineHeight = '28px';
  return content;
}

function hireBaseContent(documentRef: Document, label: string): HTMLElement {
  const content = documentRef.createElement('span');
  content.className = 'pound-hire-base-marker';
  content.setAttribute('role', 'img');
  content.setAttribute('aria-label', label);
  content.textContent = 'B';
  return content;
}

function addInfoField(documentRef: Document, root: HTMLElement, label: string, value: string): void {
  const row = documentRef.createElement('div');
  const name = documentRef.createElement('strong');
  name.textContent = `${label}: `;
  row.append(name, documentRef.createTextNode(value));
  root.append(row);
}

function hireBaseInfoContent(documentRef: Document, base: BoatHireBase, close: () => void): HTMLElement {
  const root = documentRef.createElement('article');
  root.className = 'pound-info-window';
  addCloseButton(documentRef, root, close);
  addInfoField(documentRef, root, 'Operator', base.operator);
  addInfoField(documentRef, root, 'Base', base.name);
  return root;
}

function distance(meters: number): string {
  return `${Math.round(meters)} m`;
}

function safeExternalUrl(value: string): URL | undefined {
  try {
    const url = new URL(value);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return undefined;
    return url;
  } catch {
    return undefined;
  }
}

function osmUrl(provenance: OsmProvenance): string | undefined {
  if (!Number.isSafeInteger(provenance.osm_id) || provenance.osm_id <= 0) return undefined;
  return `https://www.openstreetmap.org/${provenance.osm_type}/${provenance.osm_id}`;
}

function addCloseButton(documentRef: Document, root: HTMLElement, close: () => void): void {
  const button = documentRef.createElement('button');
  button.type = 'button';
  button.textContent = 'Close';
  button.addEventListener('click', close);
  root.prepend(button);
}

function appendLinks(
  documentRef: Document,
  root: HTMLElement,
  candidateLinks: Array<{ label: string; url: string | null | undefined }>,
): void {
  const links = documentRef.createElement('div');
  const seenUrls = new Set<string>();
  for (const link of candidateLinks) {
    if (!link.url) continue;
    const url = safeExternalUrl(link.url);
    if (!url || seenUrls.has(url.href)) continue;
    seenUrls.add(url.href);
    const anchor = documentRef.createElement('a');
    anchor.href = url.href;
    anchor.target = '_blank';
    anchor.rel = 'noopener noreferrer';
    anchor.textContent = link.label;
    links.append(anchor);
  }
  if (links.childElementCount) root.append(links);
}

function addPlaceDistances(documentRef: Document, root: HTMLElement, place: PlaceResponse): void {
  if (place.distance_to_target_m !== null)
    addInfoField(documentRef, root, 'Distance to target', distance(place.distance_to_target_m));
  if (place.distance_to_full_route_m !== null)
    addInfoField(documentRef, root, 'Distance to route', distance(place.distance_to_full_route_m));
  if (place.distance_to_selected_geometry_m !== null)
    addInfoField(documentRef, root, 'Distance to selected day', distance(place.distance_to_selected_geometry_m));
  if (place.waterway_distance_m !== null)
    addInfoField(documentRef, root, 'Distance to waterway', distance(place.waterway_distance_m));
}

function osmInfoContent(documentRef: Document, place: PlaceResponse, provenance: OsmProvenance, close: () => void): HTMLElement {
  const root = documentRef.createElement('article');
  root.className = 'pound-info-window';
  addCloseButton(documentRef, root, close);
  const heading = documentRef.createElement('h3');
  heading.textContent = place.name ?? place.kind;
  root.append(heading);
  addInfoField(documentRef, root, 'Kind', place.kind);
  addPlaceDistances(documentRef, root, place);

  const metadata = provenance.metadata;
  if (metadata.alt_name) addInfoField(documentRef, root, 'Also known as', metadata.alt_name);
  if (metadata.brand) addInfoField(documentRef, root, 'Brand', metadata.brand);
  if (metadata.operator) addInfoField(documentRef, root, 'Operator', metadata.operator);
  if (metadata.address) {
    const address = [
      metadata.address.house_number,
      metadata.address.street,
      metadata.address.place,
      metadata.address.city,
      metadata.address.postcode,
    ].filter(Boolean).join(', ');
    if (address) addInfoField(documentRef, root, 'Address', address);
  }
  if (metadata.opening_hours) addInfoField(documentRef, root, 'Opening hours', metadata.opening_hours);
  if (metadata.access) addInfoField(documentRef, root, 'Access', metadata.access);
  if (metadata.fee) addInfoField(documentRef, root, 'Fee', metadata.fee);
  if (metadata.wheelchair) addInfoField(documentRef, root, 'Wheelchair access', metadata.wheelchair);
  if (metadata.phone) addInfoField(documentRef, root, 'Phone', metadata.phone);
  if (metadata.email) addInfoField(documentRef, root, 'Email', metadata.email);
  if (metadata.description) addInfoField(documentRef, root, 'Description', metadata.description);
  for (const [key, value] of Object.entries(metadata.kind_details)) addInfoField(documentRef, root, key, value);

  const derivedOsmUrl = osmUrl(provenance);
  appendLinks(documentRef, root, [
    { label: 'Search on Google Maps', url: buildGoogleMapsSearchUrl({ name: place.name, coordinate: place.coordinate, metadata }) },
    { label: 'OpenStreetMap', url: derivedOsmUrl },
    ...metadata.links,
  ]);
  addInfoField(documentRef, root, 'Source', '© OpenStreetMap contributors');
  return root;
}

function boatHireInfoContent(documentRef: Document, place: PlaceResponse, provenance: BoatHireProvenance, close: () => void): HTMLElement {
  const root = documentRef.createElement('article');
  root.className = 'pound-info-window';
  addCloseButton(documentRef, root, close);
  const heading = documentRef.createElement('h3');
  heading.textContent = place.name ?? provenance.location_name;
  root.append(heading);
  addInfoField(documentRef, root, 'Kind', place.kind);
  addPlaceDistances(documentRef, root, place);
  addInfoField(documentRef, root, 'Provider', `${provenance.provider_name} (${provenance.provider_id})`);
  addInfoField(documentRef, root, 'Location', `${provenance.location_name} (${provenance.location_id})`);
  appendLinks(documentRef, root, [
    { label: 'Provider', url: provenance.provider_url },
    { label: 'OpenStreetMap', url: provenance.osm_url },
    { label: 'Evidence', url: provenance.evidence_url },
    { label: 'Booking', url: provenance.booking_url },
  ]);
  return root;
}

function placeInfoContent(documentRef: Document, place: PlaceResponse, close: () => void): HTMLElement {
  return place.provenance.source === 'osm'
    ? osmInfoContent(documentRef, place, place.provenance, close)
    : boatHireInfoContent(documentRef, place, place.provenance, close);
}

function poiInfoContent(documentRef: Document, poi: RoutePoi, close: () => void): HTMLElement {
  const root = documentRef.createElement('article');
  root.className = 'pound-info-window';
  addCloseButton(documentRef, root, close);
  const heading = documentRef.createElement('h3');
  heading.textContent = poi.name ?? poi.kind;
  root.append(heading);
  addInfoField(documentRef, root, 'Kind', poi.kind);
  addInfoField(documentRef, root, 'Distance to route', distance(poi.distance_to_route_m));
  addInfoField(documentRef, root, 'Source', '© OpenStreetMap contributors');
  return root;
}

function lockInfoContent(documentRef: Document, lock: RouteLock, close: () => void): HTMLElement {
  const root = documentRef.createElement('article');
  root.className = 'pound-info-window';
  addCloseButton(documentRef, root, close);
  const heading = documentRef.createElement('h3');
  heading.textContent = lock.name ?? 'Lock';
  root.append(heading);
  addInfoField(documentRef, root, 'Kind', 'lock');
  addInfoField(documentRef, root, 'Route day', String(lock.day));
  if (lock.approximate) addInfoField(documentRef, root, 'Position', 'Approximate');
  return root;
}

export function createGoogleMapView(
  facade: MapFacade,
  element: HTMLElement,
  options: Record<string, unknown> = {},
): MapView {
  const map = facade.createMap(element, options);
  const documentRef = element.ownerDocument;
  const placeMarkers: Partial<Record<EndpointSlot, MarkerInstance>> = {};
  const candidateMarkers: Record<EndpointSlot, MarkerInstance[]> = { origin: [], destination: [] };
  const landRoutes: Partial<Record<EndpointSlot, PolylineInstance>> = {};
  let networkGeometries: GeoJSONLineString[] = [];
  const hireBaseMarkers: MarkerInstance[] = [];
  const hireBaseMarkerListeners: RemovableListener[] = [];
  const hireBaseCoordinates: GoogleLatLngLiteral[] = [];
  const hireBaseSelectionSubscribers = new Set<(identity: string | null) => void>();
  let hireBaseRecords: BoatHireBase[] = [];
  let hireBaseSelectedIdentity: string | null = null;
  const hireBaseContents: HTMLElement[] = [];
  const catalogMarkers: MarkerInstance[] = [];
  const poiMarkers: MarkerInstance[] = [];
  const lockMarkers: MarkerInstance[] = [];
  const dayWaypointMarkers: MarkerInstance[] = [];
  const markerListeners: RemovableListener[] = [];
  const catalogMarkerListeners: RemovableListener[] = [];
  const poiMarkerListeners: RemovableListener[] = [];
  const lockMarkerListeners: RemovableListener[] = [];
  const tooltipElements: HTMLElement[] = [];
  const clickListeners: RemovableListener[] = [];
  const viewportListeners: RemovableListener[] = [];
  const infoWindowListeners: RemovableListener[] = [];
  const infoWindow = facade.createInfoWindow();
  let infoWindowOpen = false;
  infoWindowListeners.push(infoWindow.addListener('closeclick', () => {
    infoWindowOpen = false;
  }));
  const canalRoute: PolylineInstance[] = [];
  let canalPath: GoogleLatLngLiteral[] = [];
  const highlightedDay: PolylineInstance[] = [];

  const removePolylines = (lines: PolylineInstance[]) => {
    for (const line of lines.splice(0)) line.setMap(null);
  };
  interface CasedPair {
    casing: PolylineInstance;
    center: PolylineInstance;
  }
  const networkLines: CasedPair[] = [];
  const focusedNetworkLines: CasedPair[] = [];
  // ponytail: casing polylines are invisible below CASING_MIN_ZOOM but kept alive;
  // setMap toggling on idle is cheaper than rebuilding thousands of objects.
  const CASING_MIN_ZOOM = 11;
  const casingListeners: RemovableListener[] = [];
  const removeCasedPairs = (pairs: CasedPair[]) => {
    for (const pair of pairs.splice(0)) {
      pair.casing.setMap(null);
      pair.center.setMap(null);
    }
  };
  let casingVisible = (facade.getZoom(map) ?? Infinity) >= CASING_MIN_ZOOM;
  const applyCasingVisibility = (pairs: CasedPair[]) => {
    for (const pair of pairs) pair.casing.setMap(casingVisible ? map : null);
  };
  casingListeners.push(
    map.addListener('idle', () => {
      const zoom = facade.getZoom(map);
      if (zoom === undefined) return;
      const visible = zoom >= CASING_MIN_ZOOM;
      if (visible === casingVisible) return;
      casingVisible = visible;
      applyCasingVisibility(networkLines);
      applyCasingVisibility(focusedNetworkLines);
    }),
  );
  const makeCasedPair = (
    path: GoogleLatLngLiteral[],
    color: string,
    weight: number,
    zIndex: number,
  ): CasedPair => {
    const casing = facade.createPolyline({
      map, path, strokeColor: '#e0f2fe', strokeWeight: weight + 4, zIndex,
    });
    const center = facade.createPolyline({ map, path, strokeColor: color, strokeWeight: weight, zIndex: zIndex + 1 });
    if (!casingVisible) casing.setMap(null);
    return { casing, center };
  };
  const casedLine = (
    path: GoogleLatLngLiteral[],
    color: string,
    weight: number,
    zIndex: number,
  ) => Object.values(makeCasedPair(path, color, weight, zIndex));
  const paintCasedLines = (
    pairs: CasedPair[],
    lines: GeoJSONLineString[],
    color: string,
    weight: number,
    zIndex: number,
  ) => {
    const keep = Math.min(pairs.length, lines.length);
    for (let index = 0; index < keep; index += 1) {
      const path = geoJsonToGooglePath(lines[index]);
      pairs[index].casing.setPath(path);
      pairs[index].center.setPath(path);
    }
    removeCasedPairs(pairs.splice(keep));
    for (let index = keep; index < lines.length; index += 1) {
      pairs.push(makeCasedPair(geoJsonToGooglePath(lines[index]), color, weight, zIndex));
    }
  };

  const removeTooltip = (tooltip: HTMLElement) => {
    tooltip.remove();
    const index = tooltipElements.indexOf(tooltip);
    if (index >= 0) tooltipElements.splice(index, 1);
  };
  const removeTooltips = () => {
    for (const tooltip of tooltipElements.splice(0)) tooltip.remove();
  };
  const showTooltip = (label: string) => {
    removeTooltips();
    const tooltip = documentRef.createElement('div');
    tooltip.className = 'pound-marker-tooltip';
    tooltip.setAttribute('role', 'tooltip');
    tooltip.textContent = label;
    tooltip.style.position = 'absolute';
    tooltip.style.zIndex = '1';
    element.append(tooltip);
    tooltipElements.push(tooltip);
    return tooltip;
  };
  const closeInfoWindow = () => {
    infoWindow.close();
    infoWindow.setContent(null);
    infoWindowOpen = false;
  };
  const openInfoWindow = (content: HTMLElement, marker: MarkerInstance) => {
    infoWindow.setContent(content);
    infoWindow.open({ map, anchor: marker });
    infoWindowOpen = true;
  };
  const stopMarkerPropagation = (event: MarkerEvent) => {
    if (event.stopPropagation) event.stopPropagation();
    else event.domEvent?.stopPropagation?.();
  };
  const bindMarker = (
    marker: MarkerInstance,
    label: string,
    content: () => HTMLElement,
    listeners: RemovableListener[],
  ) => {
    const enter = facade.addMarkerListener(marker, 'mouseenter', () => { showTooltip(label); });
    const leave = facade.addMarkerListener(marker, 'mouseleave', () => {
      const tooltip = tooltipElements.at(-1);
      if (tooltip) removeTooltip(tooltip);
    });
    const click = facade.addMarkerListener(marker, 'click', (event) => {
      stopMarkerPropagation(event);
      openInfoWindow(content(), marker);
    });
    listeners.push(enter, leave, click);
    markerListeners.push(enter, leave, click);
  };
  const updateHireBaseSelectionStyles = () => {
    for (let index = 0; index < hireBaseMarkers.length; index += 1) {
      const base = hireBaseRecords[index];
      const content = hireBaseContents[index];
      if (!base || !content) continue;
      const label = `${base.operator} — ${base.name}`;
      const selected = base.identity === hireBaseSelectedIdentity;
      const accessibleLabel = selected ? `${label} (selected)` : label;
      content.classList.toggle('selected', selected);
      content.setAttribute('aria-label', accessibleLabel);
      hireBaseMarkers[index]!.title = accessibleLabel;
    }
  };
  const bindHireBaseMarker = (marker: MarkerInstance, base: BoatHireBase) => {
    const label = `${base.operator} — ${base.name}`;
    const enter = facade.addMarkerListener(marker, 'mouseenter', () => { showTooltip(label); });
    const leave = facade.addMarkerListener(marker, 'mouseleave', () => {
      const tooltip = tooltipElements.at(-1);
      if (tooltip) removeTooltip(tooltip);
    });
    const click = facade.addMarkerListener(marker, 'click', (event) => {
      stopMarkerPropagation(event);
      hireBaseSelectedIdentity = base.identity;
      updateHireBaseSelectionStyles();
      for (const subscriber of hireBaseSelectionSubscribers) subscriber(base.identity);
      openInfoWindow(hireBaseInfoContent(documentRef, base, closeInfoWindow), marker);
    });
    hireBaseMarkerListeners.push(enter, leave, click);
    markerListeners.push(enter, leave, click);
  };
  const removeMarkerGroup = (
    markers: MarkerInstance[],
    listeners: RemovableListener[],
  ) => {
    for (const listener of listeners) {
      listener.remove();
      const index = markerListeners.indexOf(listener);
      if (index >= 0) markerListeners.splice(index, 1);
    }
    listeners.length = 0;
    removeMarkers(markers);
    removeTooltips();
  };
  const clearDay = () => {
    removePolylines(highlightedDay);
    removeMarkers(dayWaypointMarkers);
  };
  const clearLandSlot = (slot: EndpointSlot) => {
    landRoutes[slot]?.setMap(null);
    delete landRoutes[slot];
    element.removeAttribute(`data-${slot}-land-overlay`);
  };
  const escapeListener = (event: KeyboardEvent) => {
    if (event.key === 'Escape' && infoWindowOpen) closeInfoWindow();
  };
  documentRef.addEventListener('keydown', escapeListener);

  return {
    marker(slot, coordinate) {
      if (placeMarkers[slot]) placeMarkers[slot]!.map = null;
      delete placeMarkers[slot];
      if (coordinate) {
        placeMarkers[slot] = facade.createMarker({ map, position: toGoogleLatLng(coordinate), title: slot, zIndex: 5 });
      }
    },
    candidates(slot, candidates: CanalCandidate[], selectedUid?: number) {
      removeMarkers(candidateMarkers[slot]);
      for (const candidate of candidates) {
        candidateMarkers[slot].push(
          facade.createMarker({
            map,
            position: toGoogleLatLng(candidate.coordinate),
            title: candidate.uid === selectedUid ? `${candidate.display_name} (selected)` : candidate.display_name,
          }),
        );
      }
    },
    land(slot, route: LandRoute | null) {
      clearLandSlot(slot);
      if (route) {
        const path = route.path.map(toGoogleLatLng);
        landRoutes[slot] = facade.createPolyline({ map, path, strokeColor: '#2563eb', strokeWeight: 5, zIndex: 9 });
        element.setAttribute(`data-${slot}-land-overlay`, 'visible');
      }
    },
    canal(geometry) {
      removePolylines(canalRoute);
      canalPath = [];
      element.removeAttribute('data-canal-overlay');
      if (geometry) {
        canalPath = geoJsonToGooglePath(geometry);
        canalRoute.push(...casedLine(canalPath, '#0369a1', 7, 5));
        element.setAttribute('data-canal-overlay', 'visible');
        facade.fitBounds(map, canalPath);
      }
    },
    network(lines) {
      networkGeometries = lines;
      paintCasedLines(networkLines, lines, '#0284c7', 4, 1);
    },
    focusedNetwork(lines) {
      paintCasedLines(focusedNetworkLines, lines, '#00324d', 6, 3);
    },
    hireBases(bases, selectedIdentity) {
      const recordsChanged = hireBaseRecords.length !== bases.length || hireBaseRecords.some((base, index) => {
        const next = bases[index];
        return !next || base.identity !== next.identity || base.operator !== next.operator || base.name !== next.name
          || base.coordinate.lat !== next.coordinate.lat || base.coordinate.lon !== next.coordinate.lon;
      });
      hireBaseSelectedIdentity = selectedIdentity !== null && bases.some((base) => base.identity === selectedIdentity)
        ? selectedIdentity
        : null;
      if (!recordsChanged) {
        updateHireBaseSelectionStyles();
        return;
      }
      closeInfoWindow();
      removeMarkerGroup(hireBaseMarkers, hireBaseMarkerListeners);
      hireBaseRecords = bases.map((base) => ({ identity: base.identity, operator: base.operator, name: base.name, coordinate: { lat: base.coordinate.lat, lon: base.coordinate.lon } }));
      hireBaseContents.length = 0;
      hireBaseCoordinates.length = 0;
      for (const base of hireBaseRecords) {
        const label = `${base.operator} — ${base.name}`;
        const coordinate = toGoogleLatLng(base.coordinate);
        const content = hireBaseContent(documentRef, label);
        hireBaseCoordinates.push(coordinate);
        hireBaseContents.push(content);
        const marker = facade.createMarker({
          map,
          position: coordinate,
          title: label,
          content,
          gmpClickable: true,
        });
        hireBaseMarkers.push(marker);
        bindHireBaseMarker(marker, base);
      }
      updateHireBaseSelectionStyles();
    },
    fitNetwork() {
      const points = [
        ...hireBaseCoordinates,
        ...networkGeometries.flatMap((line) =>
          line.coordinates.map(([lon, lat]) => toGoogleLatLng({ lat, lon })),
        ),
      ];
      if (points.length) facade.fitBounds(map, points);
    },
    places(places: PlaceResponse[]) {
      closeInfoWindow();
      removeMarkerGroup(catalogMarkers, catalogMarkerListeners);
      for (const place of places) {
        const label = `${place.name ?? place.kind} — ${place.kind}`;
        const marker = facade.createMarker({
          map,
          position: toGoogleLatLng(place.coordinate),
          title: label,
          content: markerContent(documentRef, place.kind, label),
          gmpClickable: true,
        });
        catalogMarkers.push(marker);
        bindMarker(marker, label, () => placeInfoContent(documentRef, place, closeInfoWindow), catalogMarkerListeners);
      }
    },
    pois(pois: RoutePoi[]) {
      closeInfoWindow();
      removeMarkerGroup(poiMarkers, poiMarkerListeners);
      for (const poi of pois) {
        const label = `${poi.name ?? poi.kind} — ${poi.kind}`;
        const marker = facade.createMarker({ map, position: toGoogleLatLng(poi.coordinate), title: poi.name ?? poi.kind, gmpClickable: true });
        poiMarkers.push(marker);
        bindMarker(marker, label, () => poiInfoContent(documentRef, poi, closeInfoWindow), poiMarkerListeners);
      }
    },
    locks(locks: RouteLock[]) {
      closeInfoWindow();
      removeMarkerGroup(lockMarkers, lockMarkerListeners);
      for (const lock of locks) {
        const approximation = lock.approximate ? ' (approximate)' : '';
        const title = `${lock.name ?? 'Lock'}${approximation} — day ${lock.day}`;
        const marker = facade.createMarker({
          map,
          position: toGoogleLatLng(lock.coordinate),
          title,
          content: lockContent(documentRef, title),
          anchorLeft: '-50%',
          anchorTop: '-100%',
          gmpClickable: true,
        });
        lockMarkers.push(marker);
        bindMarker(marker, `${lock.name ?? 'Lock'} — lock`, () => lockInfoContent(documentRef, lock, closeInfoWindow), lockMarkerListeners);
      }
    },
    day(dayGeometry: RouteDayGeometry | null) {
      clearDay();
      if (!dayGeometry) {
        if (canalPath.length) facade.fitBounds(map, canalPath);
        return;
      }
      const path = geoJsonToGooglePath(dayGeometry.geometry);
      highlightedDay.push(...casedLine(path, '#0ea5e9', 9, 7));
      const points = [toGoogleLatLng(dayGeometry.start), toGoogleLatLng(dayGeometry.end)];
      dayWaypointMarkers.push(
        facade.createMarker({ map, position: points[0], title: `Day ${dayGeometry.day} start`, zIndex: 7 }),
        facade.createMarker({ map, position: points[1], title: `Day ${dayGeometry.day} end`, zIndex: 7 }),
      );
      facade.fitBounds(map, path);
    },
    onMapClick(callback: (coordinate: LatLon) => void) {
      const listener = map.addListener('click', (event) => {
        if (infoWindowOpen || hireBaseSelectedIdentity !== null) {
          closeInfoWindow();
          hireBaseSelectedIdentity = null;
          updateHireBaseSelectionStyles();
          for (const subscriber of hireBaseSelectionSubscribers) subscriber(null);
          return;
        }
        if (event.latLng) callback({ lat: event.latLng.lat(), lon: event.latLng.lng() });
      });
      clickListeners.push(listener);
      return () => {
        listener.remove();
        const index = clickListeners.indexOf(listener);
        if (index >= 0) clickListeners.splice(index, 1);
      };
    },
    onHireBaseSelect(callback) {
      hireBaseSelectionSubscribers.add(callback);
      return () => hireBaseSelectionSubscribers.delete(callback);
    },
    onViewportIdle(callback) {
      const listener = map.addListener('idle', () => {
        const bounds = facade.getBounds(map);
        if (bounds) callback(bounds);
      });
      viewportListeners.push(listener);
      const bounds = facade.getBounds(map);
      if (bounds) callback(bounds);
      return () => {
        listener.remove();
        const index = viewportListeners.indexOf(listener);
        if (index >= 0) viewportListeners.splice(index, 1);
      };
    },
    clearLand(slot) {
      clearLandSlot(slot);
    },
    closeInfoWindow,
    destroy() {
      for (const listener of clickListeners.splice(0)) listener.remove();
      for (const listener of viewportListeners.splice(0)) listener.remove();
      documentRef.removeEventListener('keydown', escapeListener);
      removeListeners(markerListeners);
      catalogMarkerListeners.length = 0;
      poiMarkerListeners.length = 0;
      lockMarkerListeners.length = 0;
      hireBaseMarkerListeners.length = 0;
      hireBaseSelectionSubscribers.clear();
      removeListeners(infoWindowListeners);
      closeInfoWindow();
      removeTooltips();
      for (const marker of Object.values(placeMarkers)) if (marker) marker.map = null;
      removeMarkers(candidateMarkers.origin);
      removeMarkers(candidateMarkers.destination);
      removeMarkerGroup(catalogMarkers, []);
      removeMarkerGroup(poiMarkers, []);
      removeMarkerGroup(lockMarkers, []);
      removeMarkerGroup(hireBaseMarkers, []);
      hireBaseCoordinates.length = 0;
      hireBaseContents.length = 0;
      hireBaseRecords = [];
      hireBaseSelectedIdentity = null;
      clearDay();
      clearLandSlot('origin');
      clearLandSlot('destination');
      removeCasedPairs(networkLines);
      removeCasedPairs(focusedNetworkLines);
      networkGeometries = [];
      removePolylines(canalRoute);
      canalPath = [];
      for (const listener of casingListeners.splice(0)) listener.remove();
    },
  };
}
