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

export interface RouteLeg {
  from_place: string;
  to_place: string;
  distance_km: number;
  locks: number;
  est_minutes: number;
  flagged_unknown_dims: boolean;
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
}

export interface PoundApiErrorDetail {
  code: string;
  message: string;
  fields: string[];
}
