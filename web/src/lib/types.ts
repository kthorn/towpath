export interface LatLon {
  lat: number;
  lon: number;
}

export interface CanalCandidate {
  uid: number;
  artifact_revision: string;
  coordinate: LatLon;
  straight_line_distance_m: number;
  display_name: string;
}

export interface CanalCandidatesResponse {
  artifact_revision: string;
  candidates: CanalCandidate[];
}

export interface BoatHireBase {
  identity: string;
  operator: string;
  name: string;
  coordinate: LatLon;
}

export interface CanalNetworkRequest {
  days: number;
  hours_per_day: number;
  boat_length_m: number | null;
  boat_beam_m: number | null;
  boat_draft_m: number | null;
  boat_height_m: number | null;
  movable_bridge_delay_min: number | null;
}

export interface CanalNetworkResponse {
  artifact_revision: string;
  lines: GeoJSONLineString[];
  bases: BoatHireBase[];
}

export interface RouteLeg {
  from_place: string;
  to_place: string;
  distance_km: number;
  locks: number;
  est_minutes: number;
  flagged_unknown_dims: boolean;
}

export interface RouteAccessSegment {
  from_uid: number;
  to_uid: number;
  osm_way_id: number;
  kind: 'discouraged' | 'unknown';
  tag: 'boat' | 'access';
  value: string;
}

export interface DayPlan {
  day: number;
  legs: RouteLeg[];
  end_near: string | null;
  cruising_minutes: number;
}

export interface Amenity {
  kind: string;
  name: string | null;
  lat: number;
  lon: number;
  distance_m: number;
  source: string;
}

export interface RouteResult {
  start: string;
  end: string | null;
  is_ring: boolean;
  legs: RouteLeg[];
  days: DayPlan[];
  total_km: number;
  total_locks: number;
  total_minutes: number;
  amenities: Amenity[];
  warnings: string[];
  access_segments: RouteAccessSegment[];
  graph_source_date: string;
}

export interface GeoJSONLineString {
  type: 'LineString';
  coordinates: [number, number][];
}

export interface MapBounds {
  south: number;
  west: number;
  north: number;
  east: number;
}

export interface RoutePoi {
  identity: string;
  kind: string;
  name: string | null;
  coordinate: LatLon;
  distance_to_route_m: number;
}

export interface CatalogAddress {
  house_number: string | null;
  street: string | null;
  place: string | null;
  city: string | null;
  postcode: string | null;
}

export interface CatalogLink {
  label: string;
  url: string;
}

export interface CatalogMetadata {
  name: string | null;
  alt_name: string | null;
  brand: string | null;
  operator: string | null;
  address: CatalogAddress | null;
  opening_hours: string | null;
  access: string | null;
  fee: string | null;
  wheelchair: string | null;
  phone: string | null;
  email: string | null;
  description: string | null;
  links: CatalogLink[];
  kind_details: Record<string, string>;
}

export type PlacesPolicyBasis = 'route' | 'waterway' | 'none';

export interface PlacesQueryPolicy {
  basis: PlacesPolicyBasis;
  radius_m?: number | null;
}

export interface GeoJSONPoint {
  type: 'Point';
  coordinates: [number, number];
}

export interface NearbyTarget {
  id: string;
  geometry: GeoJSONPoint | GeoJSONLineString;
}

export interface ViewportPlacesRequest {
  mode: 'viewport';
  kinds: string[];
  bounds: MapBounds;
  text?: string | null;
  route_geometry?: GeoJSONLineString | null;
  day_geometry?: GeoJSONLineString | null;
  policy: PlacesQueryPolicy;
}

export interface NearbyPlacesRequest {
  mode: 'nearby';
  kinds: string[];
  text?: string | null;
  radius_m: number;
  targets: NearbyTarget[];
}

export type PlacesRequest = ViewportPlacesRequest | NearbyPlacesRequest;

export interface OsmProvenance {
  source: 'osm';
  osm_type: 'node' | 'way' | 'relation';
  osm_id: number;
  metadata: CatalogMetadata;
}

export interface BoatHireProvenance {
  source: 'boat_hire';
  provider_id: string;
  provider_name: string;
  location_id: string;
  location_name: string;
  provider_url: string | null;
  osm_url: string | null;
  evidence_url: string | null;
  booking_url: string | null;
}

export interface PlaceResponse {
  kind: string;
  name: string | null;
  coordinate: LatLon;
  target_id: string | null;
  distance_to_target_m: number | null;
  distance_to_full_route_m: number | null;
  distance_to_selected_geometry_m: number | null;
  waterway_distance_m: number | null;
  provenance: OsmProvenance | BoatHireProvenance;
}

export type Place = PlaceResponse;

export interface PlacesResponse {
  places: PlaceResponse[];
}

export interface HealthResponse {
  status: string;
  artifact_revision: string;
  places_status: 'available' | 'unavailable';
}

export interface RoutePoisRequest {
  artifact_revision: string;
  kinds: string[];
  bounds: MapBounds;
  route_geometry: GeoJSONLineString;
  day_geometry?: GeoJSONLineString;
  day?: number | null;
}

export interface RoutePoisResponse {
  pois: RoutePoi[];
  zoom_in_required: boolean;
  matching_count: number;
  day: number | null;
}

export interface RouteDayGeometry {
  day: number;
  geometry: GeoJSONLineString;
  start: LatLon;
  end: LatLon;
}

export interface RouteLock {
  coordinate: LatLon;
  name: string | null;
  day: number;
  approximate: boolean;
}

export interface CanalRouteResponse {
  route: RouteResult;
  geometry: GeoJSONLineString;
  day_geometries?: RouteDayGeometry[];
  locks?: RouteLock[];
}

export type CanalCandidatesRequest = LatLon;

export interface CanalRouteRequest {
  start_uid: number;
  end_uid: number;
  artifact_revision: string;
  days?: number | null;
  hours_per_day?: number;
  boat_length_m?: number | null;
  boat_beam_m?: number | null;
  boat_draft_m?: number | null;
  boat_height_m?: number | null;
  movable_bridge_delay_min?: number | null;
}

export interface PoundApiErrorDetail {
  code: string;
  message: string;
  fields: string[];
}
