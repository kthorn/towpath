import type { CanalCandidate, LatLon } from '../types';
import type { EndpointSlot, LandRoute, MapView } from './contracts';
import { geoJsonToGooglePath, toGoogleLatLng, type GoogleLatLngLiteral } from './routes';

interface RemovableListener {
  remove(): void;
}

interface MapInstance {
  addListener(event: 'click', callback: (event: { latLng?: { lat(): number; lng(): number } }) => void): RemovableListener;
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
  const clickListeners: RemovableListener[] = [];
  let canalRoute: PolylineInstance | undefined;

  const clearLandSlot = (slot: EndpointSlot) => {
    landRoutes[slot]?.setMap(null);
    delete landRoutes[slot];
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
        facade.fitBounds(map, path);
      }
    },
    canal(geometry) {
      canalRoute?.setMap(null);
      canalRoute = undefined;
      if (geometry) {
        const path = geoJsonToGooglePath(geometry);
        canalRoute = facade.createPolyline({
          map,
          path,
          strokeColor: '#0891b2',
          strokeWeight: 6,
        });
        facade.fitBounds(map, path);
      }
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
    clearLand(slot) {
      clearLandSlot(slot);
    },
    destroy() {
      for (const listener of clickListeners.splice(0)) listener.remove();
      for (const marker of Object.values(placeMarkers)) if (marker) marker.map = null;
      removeMarkers(candidateMarkers.origin);
      removeMarkers(candidateMarkers.destination);
      clearLandSlot('origin');
      clearLandSlot('destination');
      canalRoute?.setMap(null);
      canalRoute = undefined;
    },
  };
}
