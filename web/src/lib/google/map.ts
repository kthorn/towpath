import type {
  CanalCandidate,
  LatLon,
  MapBounds,
  RouteDayGeometry,
  RouteLock,
  RoutePoi,
} from '../types';
import type { EndpointSlot, LandRoute, MapView } from './contracts';
import { geoJsonToGooglePath, toGoogleLatLng, type GoogleLatLngLiteral } from './routes';

export interface RemovableListener {
  remove(): void;
}

interface MapInstance {
  addListener(event: 'click', callback: (event: { latLng?: { lat(): number; lng(): number } }) => void): RemovableListener;
  addListener(event: 'idle', callback: () => void): RemovableListener;
}

interface MarkerInstance {
  map: MapInstance | null;
}

interface PolylineInstance {
  setMap(map: MapInstance | null): void;
}

export interface MapFacade {
  createMap(element: HTMLElement, options: Record<string, unknown>): MapInstance;
  createMarker(options: { map: MapInstance; position: GoogleLatLngLiteral; title?: string }): MarkerInstance;
  createPolyline(options: {
    map: MapInstance;
    path: GoogleLatLngLiteral[];
    strokeColor: string;
    strokeWeight: number;
  }): PolylineInstance;
  fitBounds(map: MapInstance, points: GoogleLatLngLiteral[]): void;
  getBounds(map: MapInstance): MapBounds;
}

function removeMarkers(markers: MarkerInstance[]): void {
  for (const marker of markers) marker.map = null;
  markers.length = 0;
}

export function createGoogleMapView(
  facade: MapFacade,
  element: HTMLElement,
  options: Record<string, unknown> = {},
): MapView {
  const map = facade.createMap(element, options);
  const placeMarkers: Partial<Record<EndpointSlot, MarkerInstance>> = {};
  const candidateMarkers: Record<EndpointSlot, MarkerInstance[]> = { origin: [], destination: [] };
  const landRoutes: Partial<Record<EndpointSlot, PolylineInstance>> = {};
  const poiMarkers: MarkerInstance[] = [];
  const lockMarkers: MarkerInstance[] = [];
  const dayWaypointMarkers: MarkerInstance[] = [];
  const clickListeners: RemovableListener[] = [];
  const viewportListeners: RemovableListener[] = [];
  let canalRoute: PolylineInstance | undefined;
  let highlightedDay: PolylineInstance | undefined;

  const clearDay = () => {
    highlightedDay?.setMap(null);
    highlightedDay = undefined;
    removeMarkers(dayWaypointMarkers);
  };

  const clearLandSlot = (slot: EndpointSlot) => {
    landRoutes[slot]?.setMap(null);
    delete landRoutes[slot];
    element.removeAttribute(`data-${slot}-land-overlay`);
  };

  return {
    marker(slot, coordinate) {
      if (placeMarkers[slot]) placeMarkers[slot]!.map = null;
      delete placeMarkers[slot];
      if (coordinate) {
        placeMarkers[slot] = facade.createMarker({ map, position: toGoogleLatLng(coordinate), title: slot });
        facade.fitBounds(map, [toGoogleLatLng(coordinate)]);
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
      if (candidates.length) facade.fitBounds(map, candidates.map(({ coordinate }) => toGoogleLatLng(coordinate)));
    },
    land(slot, route: LandRoute | null) {
      clearLandSlot(slot);
      if (route) {
        const path = route.path.map(toGoogleLatLng);
        landRoutes[slot] = facade.createPolyline({
          map,
          path,
          strokeColor: '#2563eb',
          strokeWeight: 5,
        });
        element.setAttribute(`data-${slot}-land-overlay`, 'visible');
        facade.fitBounds(map, path);
      }
    },
    canal(geometry) {
      canalRoute?.setMap(null);
      canalRoute = undefined;
      element.removeAttribute('data-canal-overlay');
      if (geometry) {
        const path = geoJsonToGooglePath(geometry);
        canalRoute = facade.createPolyline({
          map,
          path,
          strokeColor: '#0891b2',
          strokeWeight: 6,
        });
        element.setAttribute('data-canal-overlay', 'visible');
        facade.fitBounds(map, path);
      }
    },
    pois(pois: RoutePoi[]) {
      removeMarkers(poiMarkers);
      for (const poi of pois) {
        poiMarkers.push(
          facade.createMarker({
            map,
            position: toGoogleLatLng(poi.coordinate),
            title: poi.name ?? poi.kind,
          }),
        );
      }
    },
    locks(locks: RouteLock[]) {
      removeMarkers(lockMarkers);
      for (const lock of locks) {
        const approximation = lock.approximate ? ' (approximate)' : '';
        lockMarkers.push(
          facade.createMarker({
            map,
            position: toGoogleLatLng(lock.coordinate),
            title: `${lock.name ?? 'Lock'}${approximation} — day ${lock.day}`,
          }),
        );
      }
    },
    day(dayGeometry: RouteDayGeometry | null) {
      clearDay();
      if (!dayGeometry) return;

      const path = geoJsonToGooglePath(dayGeometry.geometry);
      highlightedDay = facade.createPolyline({
        map,
        path,
        strokeColor: '#0891b2',
        strokeWeight: 8,
      });
      const points = [toGoogleLatLng(dayGeometry.start), toGoogleLatLng(dayGeometry.end)];
      dayWaypointMarkers.push(
        facade.createMarker({ map, position: points[0], title: `Day ${dayGeometry.day} start` }),
        facade.createMarker({ map, position: points[1], title: `Day ${dayGeometry.day} end` }),
      );
      facade.fitBounds(map, points);
    },
    onMapClick(callback: (coordinate: LatLon) => void) {
      const listener = map.addListener('click', (event) => {
        if (event.latLng) callback({ lat: event.latLng.lat(), lon: event.latLng.lng() });
      });
      clickListeners.push(listener);
      return () => {
        listener.remove();
        const index = clickListeners.indexOf(listener);
        if (index >= 0) clickListeners.splice(index, 1);
      };
    },
    onViewportIdle(callback) {
      const listener = map.addListener('idle', () => callback(facade.getBounds(map)));
      viewportListeners.push(listener);
      callback(facade.getBounds(map));
      return () => {
        listener.remove();
        const index = viewportListeners.indexOf(listener);
        if (index >= 0) viewportListeners.splice(index, 1);
      };
    },
    clearLand(slot) {
      clearLandSlot(slot);
    },
    destroy() {
      for (const listener of clickListeners.splice(0)) listener.remove();
      for (const listener of viewportListeners.splice(0)) listener.remove();
      for (const marker of Object.values(placeMarkers)) if (marker) marker.map = null;
      removeMarkers(candidateMarkers.origin);
      removeMarkers(candidateMarkers.destination);
      removeMarkers(poiMarkers);
      removeMarkers(lockMarkers);
      clearDay();
      clearLandSlot('origin');
      clearLandSlot('destination');
      canalRoute?.setMap(null);
      canalRoute = undefined;
    },
  };
}
