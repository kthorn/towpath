import type { MapBounds } from '../types';
import type { MapView, PlaceSearch, TransferRouter } from './contracts';
import type { GoogleMapsModules } from './loader';
import { createGoogleMapView, type MapFacade, type MarkerEvent } from './map';
import { createGooglePlaceSearch, type PlacesFacade } from './places';
import { createGoogleTransferRouter, type RoutesFacade } from './routes';

type Constructor<T, A extends unknown[] = [Record<string, unknown>]> = new (...args: A) => T;

interface MapsModule {
  Map: Constructor<unknown, [HTMLElement, Record<string, unknown>]>;
  Polyline: Constructor<unknown>;
  InfoWindow: Constructor<unknown, []>;
}

interface RuntimeMap {
  fitBounds(bounds: { north: number; south: number; east: number; west: number }): void;
  getBounds(): { toJSON(): MapBounds } | undefined;
}

interface MarkerModule {
  AdvancedMarkerElement: Constructor<unknown>;
}

interface RuntimeMarker {
  addEventListener(event: string, callback: (event: unknown) => void): void;
  removeEventListener(event: string, callback: (event: unknown) => void): void;
}

interface RuntimeInfoWindow {
  setContent(content: Node | string | null): void;
  open(options: { map: unknown; anchor?: unknown }): void;
  close(): void;
}

interface PlacesModule {
  Autocomplete: Constructor<unknown, [HTMLInputElement, Record<string, unknown>]>;
}

interface RoutesModule {
  Route: {
    computeRoutes(request: Record<string, unknown>): Promise<{ routes?: unknown[] }>;
  };
  RouteMatrix: {
    computeRouteMatrix(request: Record<string, unknown>): Promise<{
      matrix: { rows: Array<{ items: unknown[] }> };
    }>;
  };
}

interface RuntimeModules extends GoogleMapsModules {
  maps: MapsModule;
  marker: MarkerModule;
  places: PlacesModule;
  routes: RoutesModule;
}

export interface GoogleAdapterOptions {
  mapId?: string;
  mapOptions?: Record<string, unknown>;
}

export interface GoogleAdapters {
  placeSearch: PlaceSearch;
  transferRouter: TransferRouter;
  createMapView(element: HTMLElement, options?: Record<string, unknown>): MapView;
}

function asRuntimeModules(modules: GoogleMapsModules): RuntimeModules {
  return modules as RuntimeModules;
}

function createRoutesFacade(modules: RuntimeModules): RoutesFacade {
  return {
    async computeRouteMatrix(request) {
      const { matrix } = await modules.routes.RouteMatrix.computeRouteMatrix(request);
      const items = matrix.rows[0]?.items ?? [];
      return items.map((item, destinationIndex) => ({
        ...(item as object),
        destinationIndex,
      }));
    },
    async computeRoutes(request) {
      const response = await modules.routes.Route.computeRoutes(request);
      return { routes: (response.routes ?? []) as never[] };
    },
  };
}

function createPlacesFacade(modules: RuntimeModules): PlacesFacade {
  return {
    createAutocomplete(input, options) {
      return new modules.places.Autocomplete(input, options) as ReturnType<PlacesFacade['createAutocomplete']>;
    },
  };
}

function createMapFacade(modules: RuntimeModules): MapFacade {
  return {
    createMap(element, options) {
      return new modules.maps.Map(element, options) as ReturnType<MapFacade['createMap']>;
    },
    createMarker(options) {
      return new modules.marker.AdvancedMarkerElement(options) as ReturnType<MapFacade['createMarker']>;
    },
    addMarkerListener(marker, event, callback) {
      const runtimeMarker = marker as unknown as RuntimeMarker;
      const runtimeEvent = event === 'click' ? 'gmp-click' : event;
      const runtimeCallback = (eventValue: unknown) => callback(eventValue as MarkerEvent);
      runtimeMarker.addEventListener(runtimeEvent, runtimeCallback);
      return {
        remove() {
          runtimeMarker.removeEventListener(runtimeEvent, runtimeCallback);
        },
      };
    },
    createInfoWindow() {
      return new modules.maps.InfoWindow() as ReturnType<MapFacade['createInfoWindow']>;
    },
    createPolyline(options) {
      return new modules.maps.Polyline(options) as ReturnType<MapFacade['createPolyline']>;
    },
    fitBounds(map, points) {
      if (!points.length) return;
      const latitudes = points.map(({ lat }) => lat);
      const longitudes = points.map(({ lng }) => lng);
      (map as unknown as RuntimeMap).fitBounds({
        north: Math.max(...latitudes),
        south: Math.min(...latitudes),
        east: Math.max(...longitudes),
        west: Math.min(...longitudes),
      });
    },
    getBounds(map) {
      const bounds = (map as unknown as RuntimeMap).getBounds();
      return bounds?.toJSON();
    },
  };
}

export function createGoogleAdapters(
  loadedModules: GoogleMapsModules,
  { mapId = 'DEMO_MAP_ID', mapOptions = {} }: GoogleAdapterOptions = {},
): GoogleAdapters {
  const modules = asRuntimeModules(loadedModules);
  const mapFacade = createMapFacade(modules);
  return {
    placeSearch: createGooglePlaceSearch(createPlacesFacade(modules)),
    transferRouter: createGoogleTransferRouter(createRoutesFacade(modules)),
    createMapView(element, options = {}) {
      return createGoogleMapView(mapFacade, element, {
        mapId,
        center: { lat: 52.7, lng: -1.5 },
        zoom: 6,
        ...mapOptions,
        ...options,
      });
    },
  };
}
