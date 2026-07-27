import { describe, expect, it, vi } from 'vitest';

import type { CanalCandidate, CatalogPlace, GeoJSONLineString } from '../types';
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
  const markers: Array<{
    map: typeof map | null;
    position: unknown;
    title?: string;
    content?: Node;
    anchorLeft?: string;
    anchorTop?: string;
  }> = [];
  const markerListeners: Array<{
    marker: (typeof markers)[number];
    event: string;
    callback: (event: never) => void;
    remove: ReturnType<typeof vi.fn>;
  }> = [];
  const infoWindowListeners: Array<{
    event: string;
    callback: () => void;
    remove: ReturnType<typeof vi.fn>;
  }> = [];
  const infoWindow = {
    setContent: vi.fn(),
    open: vi.fn(),
    close: vi.fn(),
    addListener: vi.fn((event, callback) => {
      const listener = { event, callback, remove: vi.fn() };
      infoWindowListeners.push(listener);
      return listener;
    }),
  };
  const polylines: Array<{ options: Record<string, unknown>; setMap: ReturnType<typeof vi.fn> }> = [];
  const facade: MapFacade = {
    createMap: vi.fn(() => map),
    createMarker: vi.fn((options) => {
      const marker = {
        map,
        position: options.position,
        title: options.title,
        content: options.content,
        anchorLeft: options.anchorLeft,
        anchorTop: options.anchorTop,
      };
      markers.push(marker);
      return marker;
    }),
    addMarkerListener: vi.fn((marker, event, callback) => {
      const listener = { marker, event, callback, remove: vi.fn() };
      markerListeners.push(listener);
      return listener;
    }),
    createInfoWindow: vi.fn(() => infoWindow),
    createPolyline: vi.fn((options) => {
      const polyline = { options, setMap: vi.fn() };
      polylines.push(polyline);
      return polyline;
    }),
    fitBounds: vi.fn(),
    getBounds: vi.fn(() => ({ south: 50, west: -2, north: 54, east: 0 })),
  };
  const element = document.createElement('div');
  return {
    view: createGoogleMapView(facade, element),
    element,
    facade,
    map,
    mapListeners,
    markers,
    markerListeners,
    infoWindow,
    infoWindowListeners,
    polylines,
  };
}

function catalogPlace(overrides: Partial<CatalogPlace> = {}): CatalogPlace {
  return {
    identity: 'node/1/museum',
    kind: 'museum',
    name: 'Canal Museum',
    coordinate: { lat: 51, lon: -1 },
    waterway_distance_m: 120,
    distance_to_full_route_m: 450,
    distance_to_selected_geometry_m: null,
    metadata: {
      name: 'Canal Museum',
      alt_name: null,
      brand: null,
      operator: null,
      address: { house_number: '1', street: 'Canal Road', place: null, city: 'Oxford', postcode: 'OX1' },
      opening_hours: 'Mo-Su 10:00-17:00',
      access: null,
      fee: 'yes',
      wheelchair: 'yes',
      phone: null,
      email: null,
      description: 'A museum beside the water.',
      links: [
        { label: 'OpenStreetMap', url: 'https://www.openstreetmap.org/node/1' },
        { label: 'Website', url: 'https://example.test/museum' },
        { label: 'Unsafe', url: 'javascript:alert(1)' },
      ],
      kind_details: {},
    },
    ...overrides,
  };
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
    expect(facade.fitBounds).not.toHaveBeenCalled();
  });

  it('owns land and canal overlays independently and converts GeoJSON while drawing', () => {
    const { view, element, facade, markers, polylines } = setup();
    view.marker('origin', { lat: 51, lon: -1 });
    view.land('origin', { path: [{ lat: 51, lon: -1 }], durationSeconds: 3, distanceMeters: 4 });
    expect(element).toHaveAttribute('data-origin-land-overlay', 'visible');
    expect(markers[0].map).not.toBeNull();
    expect(facade.fitBounds).not.toHaveBeenCalled();

    view.canal({ type: 'LineString', coordinates: [[-1.5, 52.5], [-1.6, 52.6]] });
    expect(element).toHaveAttribute('data-canal-overlay', 'visible');
    view.clearLand('origin');
    expect(element).not.toHaveAttribute('data-origin-land-overlay');

    expect(polylines[0].setMap).toHaveBeenCalledWith(null);
    expect(polylines[1].setMap).not.toHaveBeenCalled();
    expect(polylines[1].options.path).toEqual([{ lat: 52.5, lng: -1.5 }, { lat: 52.6, lng: -1.6 }]);
    expect(facade.fitBounds).toHaveBeenCalledWith(expect.anything(), [{ lat: 52.5, lng: -1.5 }, { lat: 52.6, lng: -1.6 }]);

    view.canal(null);
    expect(element).not.toHaveAttribute('data-canal-overlay');
    expect(polylines[1].setMap).toHaveBeenCalledWith(null);
  });

  it('draws, replaces, fits, and destroys full network polylines', () => {
    const { view, facade, polylines } = setup();
    const lines: GeoJSONLineString[] = [
      { type: 'LineString', coordinates: [[-1, 51], [-1.1, 51.1]] },
      { type: 'LineString', coordinates: [[-1.2, 51.2], [-1.3, 51.3]] },
    ];
    const replacement: GeoJSONLineString[] = [
      { type: 'LineString', coordinates: [[-2, 52], [-2.1, 52.1]] },
    ];

    view.network(lines);
    expect(facade.createPolyline).toHaveBeenCalledTimes(2);
    expect(polylines[0].options).toMatchObject({ strokeColor: '#0e7490', strokeWeight: 3, strokeOpacity: 0.55 });
    expect(polylines[1].options).toMatchObject({ strokeColor: '#0e7490', strokeWeight: 3, strokeOpacity: 0.55 });

    view.network(replacement);
    expect(polylines[0].setMap).toHaveBeenCalledWith(null);
    expect(polylines[1].setMap).toHaveBeenCalledWith(null);
    expect(facade.createPolyline).toHaveBeenCalledTimes(3);

    view.fitNetwork();
    expect(facade.fitBounds).toHaveBeenCalledWith(expect.anything(), [
      { lat: 52, lng: -2 },
      { lat: 52.1, lng: -2.1 },
    ]);

    view.destroy();
    expect(polylines[2].setMap).toHaveBeenCalledWith(null);
  });

  it('does not fit an empty network', () => {
    const { view, facade } = setup();
    view.network([]);
    view.fitNetwork();
    expect(facade.fitBounds).not.toHaveBeenCalled();
  });

  it('replaces POI and lock markers and highlights a selected day', () => {
    const { view, markers, polylines, facade } = setup();
    view.pois([
      {
        identity: 'node/1/pub',
        kind: 'pub',
        name: 'The Pub',
        coordinate: { lat: 51, lon: -1 },
        distance_to_route_m: 12,
      },
    ]);
    view.locks([
      { coordinate: { lat: 51.1, lon: -1.1 }, name: null, day: 1, approximate: true },
    ]);
    view.day({
      day: 1,
      geometry: { type: 'LineString', coordinates: [[-1, 51], [-1.1, 51.1]] },
      start: { lat: 51, lon: -1 },
      end: { lat: 51.1, lon: -1.1 },
    });

    expect(markers.some((marker) => marker.title === 'The Pub')).toBe(true);
    expect(markers.some((marker) => marker.title === 'Lock (approximate) — day 1')).toBe(true);
    expect(polylines.at(-1)?.options.strokeWeight).toBe(8);
    expect(facade.fitBounds).toHaveBeenCalled();
  });

  it('fits curved day geometry and restores the full route when deselected', () => {
    const { view, facade, polylines } = setup();
    const fullRoute = { type: 'LineString' as const, coordinates: [[-1, 51], [-1.5, 51.5], [-2, 52]] as [number, number][] };
    const dayGeometry = {
      day: 1,
      geometry: { type: 'LineString' as const, coordinates: [[-1, 51], [-1.25, 54], [-1.75, 50], [-2, 52]] as [number, number][] },
      start: { lat: 51, lon: -1 },
      end: { lat: 52, lon: -2 },
    };

    view.canal(fullRoute);
    vi.mocked(facade.fitBounds).mockClear();
    view.day(dayGeometry);
    expect(facade.fitBounds).toHaveBeenLastCalledWith(expect.anything(), [
      { lat: 51, lng: -1 },
      { lat: 54, lng: -1.25 },
      { lat: 50, lng: -1.75 },
      { lat: 52, lng: -2 },
    ]);

    view.day(null);
    expect(polylines.at(-1)?.setMap).toHaveBeenCalledWith(null);
    expect(facade.fitBounds).toHaveBeenLastCalledWith(expect.anything(), [
      { lat: 51, lng: -1 },
      { lat: 51.5, lng: -1.5 },
      { lat: 52, lng: -2 },
    ]);
  });

  it('ignores undefined initial bounds and delivers first usable idle bounds', () => {
    const { view, facade, mapListeners } = setup();
    // First getBounds returns undefined (pre-idle), then returns real bounds
    facade.getBounds = vi.fn()
      .mockReturnValueOnce(undefined)
      .mockReturnValue({ south: 50, west: -2, north: 54, east: 0 });
    const callback = vi.fn();
    view.onViewportIdle(callback);

    // Immediate invocation: bounds undefined, callback should NOT fire
    expect(callback).not.toHaveBeenCalled();

    // Simulate map idle — bounds now available
    mapListeners[0].callback(undefined as never);
    expect(callback).toHaveBeenCalledTimes(1);
    expect(callback).toHaveBeenCalledWith({ south: 50, west: -2, north: 54, east: 0 });
  });

  it('reports viewport bounds immediately and when the map becomes idle', () => {
    const { view, facade, mapListeners } = setup();
    const callback = vi.fn();
    const unsubscribe = view.onViewportIdle(callback);

    expect(callback).toHaveBeenCalledWith({ south: 50, west: -2, north: 54, east: 0 });
    mapListeners[0].callback(undefined as never);
    expect(callback).toHaveBeenCalledTimes(2);
    unsubscribe();
    expect(mapListeners[0].remove).toHaveBeenCalledOnce();
    expect(facade.getBounds).toHaveBeenCalledTimes(2);
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

  it('assigns grouped catalog glyphs, titles, and name/kind hover tooltips', () => {
    const { view, element, facade, markerListeners } = setup();
    view.catalogPlaces!([
      catalogPlace(),
      catalogPlace({ identity: 'node/2/pub', kind: 'pub', name: 'The Navigation' }),
      catalogPlace({ identity: 'node/3/supermarket', kind: 'supermarket', name: 'Market' }),
      catalogPlace({ identity: 'node/4/marina', kind: 'marina', name: 'Marina' }),
    ]);

    const markerCalls = vi.mocked(facade.createMarker).mock.calls;
    expect(markerCalls[0][0].title).toBe('Canal Museum — museum');
    expect(markerCalls[0][0].content?.textContent).toBe('M');
    expect(markerCalls[0][0].content).toHaveAttribute('data-group', 'attractions');
    expect(markerCalls[1][0].content?.textContent).toBe('P');
    expect(markerCalls[1][0].content).toHaveAttribute('data-group', 'hospitality');
    expect(markerCalls[2][0].content?.textContent).toBe('S');
    expect(markerCalls[2][0].content).toHaveAttribute('data-group', 'shops');
    expect(markerCalls[3][0].content?.textContent).toBe('⚓');
    expect(markerCalls[3][0].content).toHaveAttribute('data-group', 'utilities');

    const enter = markerListeners.find(({ event }) => event === 'mouseenter');
    enter?.callback({} as never);
    expect(element).toHaveTextContent('Canal Museum — museum');
    expect(element).not.toHaveTextContent('Opening hours');
    const leave = markerListeners.find(({ event }) => event === 'mouseleave');
    leave?.callback({} as never);
    expect(element.querySelector('[role="tooltip"]')).toBeNull();
  });

  it('opens safe catalog metadata links in the shared info window and stops marker clicks', () => {
    const { view, facade, markerListeners, infoWindow } = setup();
    view.catalogPlaces!([catalogPlace()]);
    const click = markerListeners.find(({ event }) => event === 'click');
    const stopPropagation = vi.fn();
    click?.callback({ stopPropagation } as never);

    const content = vi.mocked(infoWindow.setContent).mock.calls.find(([value]) => value !== null)?.[0] as HTMLElement;
    expect(stopPropagation).toHaveBeenCalledOnce();
    expect(content).toHaveTextContent('Canal Museum');
    expect(content).toHaveTextContent('museum');
    expect(content).toHaveTextContent('Opening hours: Mo-Su 10:00-17:00');
    expect(content).toHaveTextContent('Distance to route: 450 m');
    expect(content.querySelector('a[href^="https://www.google.com/maps/search/?api=1&query="]')).toHaveTextContent('Search on Google Maps');
    expect(content.querySelector('a[href^="https://www.google.com/maps/search/?api=1&query="]')).toHaveAttribute('target', '_blank');
    expect(content.querySelector('a[href^="https://www.google.com/maps/search/?api=1&query="]')).toHaveAttribute('rel', 'noopener noreferrer');
    expect(content.querySelector('a[href="https://example.test/museum"]')).toHaveAttribute('target', '_blank');
    expect(content.querySelectorAll('a[href="https://www.openstreetmap.org/node/1"]')).toHaveLength(1);
    expect(content.querySelector('a[href^="javascript:"]')).toBeNull();
    expect(infoWindow.open).toHaveBeenCalledWith(expect.objectContaining({ anchor: markersAt(facade, 0) }));
  });

  it('switches POI and lock content through one info window and centers lock chevrons', () => {
    const { view, facade, markerListeners, infoWindow } = setup();
    view.pois([{ identity: 'node/1/pub', kind: 'pub', name: 'The Pub', coordinate: { lat: 51, lon: -1 }, distance_to_route_m: 12 }]);
    let click = markerListeners.find(({ event }) => event === 'click');
    click?.callback({} as never);
    expect((vi.mocked(infoWindow.setContent).mock.calls.at(-1)?.[0] as HTMLElement)).toHaveTextContent('The Pub');

    view.locks([
      { coordinate: { lat: 51, lon: -1 }, name: 'Town Lock', day: 2, approximate: true },
      { coordinate: { lat: 51.1, lon: -1.1 }, name: 'Source Lock', day: 3, approximate: false },
    ]);
    const lockCalls = vi.mocked(facade.createMarker).mock.calls.slice(-2);
    expect(lockCalls[0][0].anchorLeft).toBe('-50%');
    expect(lockCalls[0][0].anchorTop).toBe('-100%');
    expect(lockCalls[0][0].title).toContain('(approximate)');
    expect(lockCalls[1][0].title).not.toContain('approximate');
    click = markerListeners.filter(({ event }) => event === 'click').at(-1);
    click?.callback({} as never);
    expect((vi.mocked(infoWindow.setContent).mock.calls.at(-1)?.[0] as HTMLElement)).toHaveTextContent('Route day: 3');
    expect((vi.mocked(infoWindow.setContent).mock.calls.at(-1)?.[0] as HTMLElement)).not.toHaveTextContent('approximate');
  });

  it('lets the next background click select an endpoint after native InfoWindow close', () => {
    const { view, mapListeners, markerListeners, infoWindowListeners } = setup();
    const endpointClick = vi.fn();
    view.onMapClick(endpointClick);
    view.catalogPlaces!([catalogPlace()]);
    markerListeners.find(({ event }) => event === 'click')?.callback({} as never);

    const closeClick = infoWindowListeners.find(({ event }) => event === 'closeclick');
    expect(closeClick).toBeDefined();
    closeClick?.callback();
    mapListeners[0].callback({ latLng: { lat: () => 53, lng: () => -2 } } as never);

    expect(endpointClick).toHaveBeenCalledWith({ lat: 53, lon: -2 });
  });

  it('cleans replaced marker listeners and popup state, consumes the first background click, and closes on escape', () => {
    const { view, element, mapListeners, markerListeners, markers, infoWindow } = setup();
    const endpointClick = vi.fn();
    view.onMapClick(endpointClick);
    view.catalogPlaces!([catalogPlace()]);
    const oldMarker = markers[0];
    const oldListener = markerListeners[0];
    markerListeners.find(({ event }) => event === 'click')?.callback({} as never);
    view.catalogPlaces!([catalogPlace({ identity: 'node/2/pub', kind: 'pub', name: 'Pub' })]);
    expect(oldMarker.map).toBeNull();
    expect(oldListener.remove).toHaveBeenCalled();
    expect(infoWindow.close).toHaveBeenCalled();
    infoWindow.close.mockClear();

    markerListeners.filter(({ event }) => event === 'click').at(-1)?.callback({} as never);
    mapListeners[0].callback({} as never);
    expect(infoWindow.close).toHaveBeenCalledTimes(1);
    expect(endpointClick).not.toHaveBeenCalled();
    mapListeners[0].callback({ latLng: { lat: () => 53, lng: () => -2 } } as never);
    expect(endpointClick).toHaveBeenCalledWith({ lat: 53, lon: -2 });

    markerListeners.filter(({ event }) => event === 'click').at(-1)?.callback({} as never);
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    expect(infoWindow.close).toHaveBeenCalledTimes(2);
    view.closeInfoWindow!();
    view.destroy();
    expect(infoWindow.close).toHaveBeenCalledTimes(4);
    expect(element.querySelector('[role="tooltip"]')).toBeNull();
    expect(markers.every(({ map }) => map === null)).toBe(true);
  });
});

function markersAt(facade: MapFacade, index: number) {
  return vi.mocked(facade.createMarker).mock.results[index]?.value;
}
