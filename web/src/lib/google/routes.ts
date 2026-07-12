import type { GeoJSONLineString, LatLon } from '../types';
import type { TransferMode } from '../config';
import type { LandRoute, TransferResult, TransferRouter } from './contracts';

export interface GoogleLatLngLiteral {
  lat: number;
  lng: number;
}

type RouteWaypoint = GoogleLatLngLiteral;

interface MatrixElement {
  destinationIndex?: number;
  status?: string;
  condition?: string;
  durationMillis?: number;
  distanceMeters?: number;
  error?: { message?: string } | Error;
}

interface GooglePathPoint {
  lat?: number | (() => number);
  lng?: number | (() => number);
  latitude?: number;
  longitude?: number;
}

interface GoogleRoute {
  path?: GooglePathPoint[];
  durationMillis?: number;
  distanceMeters?: number;
}

export interface RoutesFacade {
  computeRouteMatrix(request: {
    origins: RouteWaypoint[];
    destinations: RouteWaypoint[];
    travelMode: string;
    fields: string[];
  }): Promise<MatrixElement[]>;
  computeRoutes(request: {
    origin: RouteWaypoint;
    destination: RouteWaypoint;
    travelMode: string;
    fields: string[];
  }): Promise<{ routes: GoogleRoute[] }>;
}

function toGoogleTravelMode(mode: TransferMode): string {
  return { WALK: 'WALKING', DRIVE: 'DRIVING', TRANSIT: 'TRANSIT', BICYCLE: 'BICYCLING' }[mode];
}

export function toGoogleLatLng(coordinate: LatLon): GoogleLatLngLiteral {
  return { lat: coordinate.lat, lng: coordinate.lon };
}

function toWaypoint(coordinate: LatLon): RouteWaypoint {
  return toGoogleLatLng(coordinate);
}

function numberValue(value: number | (() => number) | undefined): number | undefined {
  return typeof value === 'function' ? value() : value;
}

function fromGooglePoint(point: GooglePathPoint): LatLon {
  const lat = numberValue(point.lat) ?? point.latitude;
  const lon = numberValue(point.lng) ?? point.longitude;
  if (lat === undefined || lon === undefined) throw new Error('Google route contained an invalid path point');
  return { lat, lon };
}

export function geoJsonToGooglePath(geometry: GeoJSONLineString): GoogleLatLngLiteral[] {
  return geometry.coordinates.map(([lon, lat]) => ({ lat, lng: lon }));
}

export function createGoogleTransferRouter(routes: RoutesFacade): TransferRouter {
  return {
    async matrix(origin, destinations, mode) {
      const elements = await routes.computeRouteMatrix({
        origins: [toWaypoint(origin)],
        destinations: destinations.map(toWaypoint),
        travelMode: toGoogleTravelMode(mode),
        fields: ['condition', 'durationMillis', 'distanceMeters', 'error'],
      });
      const results: TransferResult[] = destinations.map(() => ({
        available: false,
        reason: 'NO_RESULT',
      }));
      for (const element of elements) {
        const index = element.destinationIndex;
        if (index === undefined || index < 0 || index >= results.length) continue;
        const status = element.status ?? element.condition;
        if (
          (status === 'OK' || status === 'ROUTE_EXISTS') &&
          element.durationMillis !== undefined &&
          element.distanceMeters !== undefined
        ) {
          results[index] = {
            available: true,
            durationSeconds: element.durationMillis / 1000,
            distanceMeters: element.distanceMeters,
          };
        } else {
          results[index] = {
            available: false,
            reason: element.error?.message ?? status ?? 'UNKNOWN_ERROR',
          };
        }
      }
      return results;
    },

    async route(origin, destination, mode): Promise<LandRoute> {
      const response = await routes.computeRoutes({
        origin: toWaypoint(origin),
        destination: toWaypoint(destination),
        travelMode: toGoogleTravelMode(mode),
        fields: ['path', 'durationMillis', 'distanceMeters'],
      });
      const route = response.routes[0];
      if (!route?.path || route.durationMillis === undefined || route.distanceMeters === undefined) {
        throw new Error('Google returned no land route');
      }
      return {
        path: route.path.map(fromGooglePoint),
        durationSeconds: route.durationMillis / 1000,
        distanceMeters: route.distanceMeters,
      };
    },
  };
}
