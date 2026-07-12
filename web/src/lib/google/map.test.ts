import { describe, expect, it, vi } from 'vitest';

import type { CanalCandidate } from '../types';
import { createGoogleMapView, type MapFacade } from './map';

function candidate(uid: number): CanalCandidate {
  return {
    uid,
    artifact_revision: 'rev',
    coordinate: { lat: 52 + uid, lon: -1 - uid },
    straight_line_distance_m: 10,
    display_name: `Candidate ${uid}`,
  };
}

function setup() {
  const mapListeners: Array<{ callback: (event: never) => void; remove: ReturnType<typeof vi.fn> }> = [];
  const map = {
    addListener: vi.fn((_event, callback) => {
      const listener = { callback, remove: vi.fn() };
      mapListeners.push(listener);
      return listener;
    }),
  };
  const markers: Array<{ map: typeof map | null; position: unknown; title?: string }> = [];
  const polylines: Array<{ options: Record<string, unknown>; setMap: ReturnType<typeof vi.fn> }> = [];
  const facade: MapFacade = {
    createMap: vi.fn(() => map),
    createMarker: vi.fn((options) => {
      const marker = { map, position: options.position, title: options.title };
      markers.push(marker);
      return marker;
    }),
    createPolyline: vi.fn((options) => {
      const polyline = { options, setMap: vi.fn() };
      polylines.push(polyline);
      return polyline;
    }),
    fitBounds: vi.fn(),
  };
  return { view: createGoogleMapView(facade, document.createElement('div')), facade, map, mapListeners, markers, polylines };
}

describe('Google map adapter', () => {
  it('replaces endpoint and candidate markers without disturbing other marker groups', () => {
    const { view, facade, markers } = setup();
    view.marker('origin', { lat: 51, lon: -1 });
    view.marker('origin', { lat: 52, lon: -2 });
    view.candidates('origin', [candidate(1), candidate(2)]);
    view.candidates('origin', [candidate(3)]);

    expect(markers[0].map).toBeNull();
    expect(markers[1].map).not.toBeNull();
    expect(markers[2].map).toBeNull();
    expect(markers[3].map).toBeNull();
    expect(markers[4].map).not.toBeNull();
    expect(facade.fitBounds).toHaveBeenCalledWith(expect.anything(), [{ lat: 52, lng: -2 }]);
    expect(facade.fitBounds).toHaveBeenCalledWith(expect.anything(), [
      { lat: 53, lng: -2 },
      { lat: 54, lng: -3 },
    ]);
  });

  it('owns land and canal overlays independently and converts GeoJSON while drawing', () => {
    const { view, facade, markers, polylines } = setup();
    view.marker('origin', { lat: 51, lon: -1 });
    view.land('origin', { path: [{ lat: 51, lon: -1 }], durationSeconds: 3, distanceMeters: 4 });
    view.canal({ type: 'LineString', coordinates: [[-1.5, 52.5], [-1.6, 52.6]] });
    view.clearLand('origin');

    expect(polylines[0].setMap).toHaveBeenCalledWith(null);
    expect(polylines[1].setMap).not.toHaveBeenCalled();
    expect(markers[0].map).not.toBeNull();
    expect(facade.fitBounds).toHaveBeenCalledWith(expect.anything(), [{ lat: 51, lng: -1 }]);
    expect(polylines[1].options.path).toEqual([{ lat: 52.5, lng: -1.5 }, { lat: 52.6, lng: -1.6 }]);
    expect(facade.fitBounds).toHaveBeenCalledWith(expect.anything(), [{ lat: 52.5, lng: -1.5 }, { lat: 52.6, lng: -1.6 }]);

    view.canal(null);
    expect(polylines[1].setMap).toHaveBeenCalledWith(null);
  });

  it('converts map clicks and cleans up unsubscribe and destroy listeners', () => {
    const { view, mapListeners } = setup();
    const first = vi.fn();
    const second = vi.fn();
    const unsubscribe = view.onMapClick(first);
    view.onMapClick(second);
    mapListeners[0].callback({ latLng: { lat: () => 53, lng: () => -2 } } as never);
    unsubscribe();
    view.destroy();

    expect(first).toHaveBeenCalledWith({ lat: 53, lon: -2 });
    expect(mapListeners[0].remove).toHaveBeenCalledOnce();
    expect(mapListeners[1].remove).toHaveBeenCalledOnce();
  });
});
