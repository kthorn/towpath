import { describe, expect, it, vi } from 'vitest';

import { createGoogleAdapters } from './sdk';

describe('Google SDK production bridge', () => {
  it('wires Maps, Places, and AdvancedMarkerElement constructors', () => {
    const MapCtor = vi.fn(() => ({ addListener: vi.fn(), fitBounds: vi.fn() }));
    const PolylineCtor = vi.fn((options) => ({ ...options, setMap: vi.fn() }));
    const InfoWindowCtor = vi.fn(() => ({
      setContent: vi.fn(),
      open: vi.fn(),
      close: vi.fn(),
      addListener: vi.fn(() => ({ remove: vi.fn() })),
    }));
    const MarkerCtor = vi.fn((options) => ({ ...options, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
    const AutocompleteCtor = vi.fn(() => ({ addListener: vi.fn(), getPlace: vi.fn() }));
    const adapters = createGoogleAdapters(
      { maps: { Map: MapCtor, Polyline: PolylineCtor, InfoWindow: InfoWindowCtor }, marker: { AdvancedMarkerElement: MarkerCtor }, places: { Autocomplete: AutocompleteCtor }, routes: { Route: { computeRoutes: vi.fn() }, RouteMatrix: { computeRouteMatrix: vi.fn() } } },
      { mapId: 'pound-map' },
    );

    adapters.placeSearch.attach(document.createElement('input'), vi.fn());
    const view = adapters.createMapView(document.createElement('div'));
    view.marker('origin', { lat: 51, lon: -1 });
    view.land('origin', { path: [{ lat: 51, lon: -1 }], durationSeconds: 1, distanceMeters: 2 });

    expect(AutocompleteCtor).toHaveBeenCalledOnce();
    expect(MapCtor).toHaveBeenCalledWith(expect.any(HTMLElement), { mapId: 'pound-map', center: { lat: 52.7, lng: -1.5 }, zoom: 6 });
    expect(MarkerCtor).toHaveBeenCalledOnce();
    expect(InfoWindowCtor).toHaveBeenCalledOnce();
    expect(PolylineCtor).toHaveBeenCalledOnce();
  });

  it('bridges Advanced Marker events and centered lock content to Maps primitives', () => {
    const markerEvents: Array<[string, unknown]> = [];
    const addEventListener = vi.fn((event, callback) => markerEvents.push([event, callback]));
    const removeEventListener = vi.fn();
    const MapCtor = vi.fn(() => ({ addListener: vi.fn(), fitBounds: vi.fn() }));
    const MarkerCtor = vi.fn((options) => ({ ...options, addEventListener, removeEventListener }));
    const infoWindowEvents: Array<[string, unknown]> = [];
    const addInfoWindowListener = vi.fn((event, callback) => {
      infoWindowEvents.push([event, callback]);
      return { remove: vi.fn() };
    });
    const InfoWindowCtor = vi.fn(() => ({
      setContent: vi.fn(),
      open: vi.fn(),
      close: vi.fn(),
      addListener: addInfoWindowListener,
    }));
    const adapters = createGoogleAdapters({
      maps: { Map: MapCtor, Polyline: vi.fn(), InfoWindow: InfoWindowCtor },
      marker: { AdvancedMarkerElement: MarkerCtor },
      places: {},
      routes: {},
    });

    adapters.createMapView(document.createElement('div')).locks([
      { coordinate: { lat: 51, lon: -1 }, name: 'Lock', day: 1, approximate: false },
    ]);

    expect(MarkerCtor).toHaveBeenCalledWith(expect.objectContaining({
      anchorLeft: '-50%',
      anchorTop: '-50%',
      gmpClickable: true,
    }));
    expect(markerEvents.map(([event]) => event)).toContain('gmp-click');
    expect(markerEvents.map(([event]) => event)).toContain('mouseenter');
    expect(infoWindowEvents.map(([event]) => event)).toContain('closeclick');
  });

  it('uses the Maps JavaScript Routes static APIs with field masks', async () => {
    const computeRouteMatrix = vi.fn().mockResolvedValue({ matrix: { rows: [{ items: [{ condition: 'ROUTE_EXISTS', durationMillis: 2500, distanceMeters: 4 }] }] } });
    const computeRoutes = vi.fn().mockResolvedValue({ routes: [{ distanceMeters: 8, durationMillis: 3000, path: [{ lat: 51, lng: -1 }, { lat: 52, lng: -2 }] }] });
    const adapters = createGoogleAdapters(
      { maps: {}, marker: {}, places: {}, routes: { Route: { computeRoutes }, RouteMatrix: { computeRouteMatrix } } },
      { mapId: 'pound-map' },
    );

    await expect(adapters.transferRouter.matrix({ lat: 51, lon: -1 }, [{ lat: 52, lon: -2 }], 'WALK')).resolves.toEqual([{ available: true, durationSeconds: 2.5, distanceMeters: 4 }]);
    await expect(adapters.transferRouter.route({ lat: 51, lon: -1 }, { lat: 52, lon: -2 }, 'DRIVE')).resolves.toEqual({ path: [{ lat: 51, lon: -1 }, { lat: 52, lon: -2 }], durationSeconds: 3, distanceMeters: 8 });

    expect(computeRouteMatrix).toHaveBeenCalledWith(expect.objectContaining({ fields: ['condition', 'durationMillis', 'distanceMeters', 'error'] }));
    expect(computeRoutes).toHaveBeenCalledWith(expect.objectContaining({ fields: ['path', 'durationMillis', 'distanceMeters'] }));
  });
});
