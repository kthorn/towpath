import type {
  CanalCandidate,
  BoatHireBase,
  CatalogPlace,
  GeoJSONLineString,
  LatLon,
  MapBounds,
  RouteDayGeometry,
  RouteLock,
  RoutePoi,
} from '../types';
import type { TransferMode } from '../config';

export type EndpointSlot = 'origin' | 'destination';

export interface SelectedPlace {
  name: string;
  address: string;
  coordinate: LatLon;
}

export interface AvailableTransferResult {
  available: true;
  durationSeconds: number;
  distanceMeters: number;
}

export interface UnavailableTransferResult {
  available: false;
  reason: string;
}

export type TransferResult = AvailableTransferResult | UnavailableTransferResult;

export interface LandRoute {
  path: LatLon[];
  durationSeconds: number;
  distanceMeters: number;
}

export interface PlaceSearch {
  attach(container: HTMLElement, onSelect: (place: SelectedPlace) => void, onUnavailable?: (error: unknown) => void): () => void;
}

export interface TransferRouter {
  matrix(origin: LatLon, destinations: LatLon[], mode: TransferMode): Promise<TransferResult[]>;
  route(origin: LatLon, destination: LatLon, mode: TransferMode): Promise<LandRoute>;
}

export interface MapView {
  marker(slot: EndpointSlot, coordinate: LatLon | null): void;
  candidates(slot: EndpointSlot, candidates: CanalCandidate[], selectedUid?: number): void;
  land(slot: EndpointSlot, route: LandRoute | null): void;
  canal(geometry: GeoJSONLineString | null): void;
  network(lines: GeoJSONLineString[]): void;
  hireBases(bases: BoatHireBase[]): void;
  fitNetwork(): void;
  catalogPlaces(places: CatalogPlace[]): void;
  pois(pois: RoutePoi[]): void;
  locks(locks: RouteLock[]): void;
  day(dayGeometry: RouteDayGeometry | null): void;
  closeInfoWindow(): void;
  onMapClick(callback: (coordinate: LatLon) => void): () => void;
  onViewportIdle(callback: (bounds: MapBounds) => void): () => void;
  clearLand(slot: EndpointSlot): void;
  destroy(): void;
}
