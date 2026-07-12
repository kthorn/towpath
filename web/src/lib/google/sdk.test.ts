import { describe, expect, it, vi } from 'vitest';

import { createGoogleAdapters } from './sdk';

describe('Google SDK production bridge', () => {
  it('wires Maps, Places, and AdvancedMarkerElement constructors', () => {
    const MapCtor = vi.fn(function () { return { addListener: vi.fn(), fitBounds: vi.fn() }; });
    const PolylineCtor = vi.fn(function (options) { return { ...options, setMap: vi.fn() }; });
    const MarkerCtor = vi.fn(function (options) { return { ...options }; });
    const AutocompleteCtor = vi.fn(function () { return { addListener: vi.fn(), getPlace: vi.fn() }; });
    const adapters = createGoogleAdapters(
      { maps: { Map: MapCtor, Polyline: PolylineCtor }, marker: { AdvancedMarkerElement: MarkerCtor }, places: { Autocomplete: AutocompleteCtor }, routes: { Route: { computeRoutes: vi.fn() }, RouteMatrix: { computeRouteMatrix: vi.fn() } } },
      { mapId: 'pound-map' },
    );

    adapters.placeSearch.attach(document.createElement('input'), vi.fn());
    const view = adapters.createMapView(document.createElement('div'));
    view.marker('origin', { lat: 51, lon: -1 });
    view.land('origin', { path: [{ lat: 51, lon: -1 }], durationSeconds: 1, distanceMeters: 2 });

    expect(AutocompleteCtor).toHaveBeenCalledOnce();
    expect(MapCtor).toHaveBeenCalledWith(expect.any(HTMLElement), { mapId: 'pound-map', center: { lat: 52.7, lng: -1.5 }, zoom: 6 });
    expect(MarkerCtor).toHaveBeenCalledOnce();
    expect(PolylineCtor).toHaveBeenCalledOnce();
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
