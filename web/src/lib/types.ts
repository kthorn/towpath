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
  selected_base_identity?: string | null;
}

export interface CanalNetworkResponse {
  artifact_revision: string;
  lines: GeoJSONLineString[];
  highlight_lines: GeoJSONLineString[];
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

export type CatalogPolicyBasis = 'route' | 'waterway' | 'segment' | 'none';

export interface CatalogQueryPolicy {
  basis: CatalogPolicyBasis;
  radius_m?: number;
}

export interface CatalogPlace {
  identity: string;
  kind: string;
  name: string | null;
  coordinate: LatLon;
  waterway_distance_m: number | null;
  distance_to_full_route_m: number | null;
  distance_to_selected_geometry_m: number | null;
  distance_to_segment_m: number | null;
  metadata: CatalogMetadata;
}

export interface CatalogPlacesRequest {
  catalog_revision: string;
  kinds: string[];
  bounds: MapBounds;
  text?: string | null;
  route_geometry?: GeoJSONLineString;
  day_geometry?: GeoJSONLineString;
  segment_geometry?: GeoJSONLineString;
  day?: number | null;
  policy: CatalogQueryPolicy;
}

export interface CatalogPlacesResponse {
  catalog_revision: string;
  places: CatalogPlace[];
  matching_count: number;
  over_cap: boolean;
  day: number | null;
}

export interface HealthResponse {
  status: string;
  artifact_revision: string;
  catalog_revision: string | null;
  catalog_status: 'available' | 'unavailable';
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
