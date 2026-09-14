import { Type } from 'typebox';
import { AgentError, type DomainTool, type Json, type ToolName } from './contracts.js';
import type { PoundCall } from './lab-tools.js';

type RecordJson = Record<string, Json>;

interface ApiToolDeps {
  tool: (
    name: ToolName,
    description: string,
    properties: Parameters<typeof Type.Object>[0],
    execute: (args: RecordJson, signal: AbortSignal) => Promise<Json>,
  ) => DomainTool;
  call: PoundCall;
  place: (ref: Json | undefined) => Json;
  rememberPlace: (id: string, coordinate: Json) => void;
  preview: (ref: Json | undefined) => { revision: string; journey: Json };
}

const CATALOG_KINDS = new Set([
  'pub', 'cafe', 'restaurant', 'supermarket', 'convenience', 'bakery', 'greengrocer',
  'butcher', 'deli', 'general', 'marina', 'mooring', 'fuel', 'water_point',
  'sanitary_disposal', 'museum', 'gallery', 'historic_site', 'garden',
  'wildlife_attraction', 'landmark', 'boat_hire',
]);
const RESOLVE_KIND_VALUES = [
  'pub', 'cafe', 'restaurant', 'supermarket', 'convenience', 'bakery', 'greengrocer',
  'butcher', 'deli', 'general', 'marina', 'mooring', 'fuel', 'water_point',
  'sanitary_disposal', 'museum', 'gallery', 'historic_site', 'garden',
  'wildlife_attraction', 'landmark',
] as const;
const SEARCH_KIND_VALUES = [...RESOLVE_KIND_VALUES, 'boat_hire'] as const;
const POI_KINDS = new Set([
  'water_point', 'sanitary_disposal', 'fuel', 'marina', 'mooring', 'pub', 'cafe',
  'restaurant', 'supermarket', 'convenience', 'bakery', 'greengrocer', 'butcher',
  'deli', 'general', 'rail_station', 'rail_halt', 'bus_stop', 'taxi_rank', 'entrance',
  'path_connection', 'pedestrian_bridge', 'steps', 'gate', 'stile', 'kissing_gate',
  'cycle_barrier',
]);

const refSchema = Type.String({ minLength: 1, maxLength: 256 });
export const resolveKindSchema = Type.Union(RESOLVE_KIND_VALUES.map(value => Type.Literal(value)));
export const catalogKindSchema = resolveKindSchema;
export const searchKindSchema = Type.Union(SEARCH_KIND_VALUES.map(value => Type.Literal(value)));
export const routePoiKindSchema = Type.Union([...POI_KINDS].map(value => Type.Literal(value)));
const boundsSchema = Type.Object({
  south: Type.Number({ minimum: -90, maximum: 90 }),
  west: Type.Number({ minimum: -180, maximum: 180 }),
  north: Type.Number({ minimum: -90, maximum: 90 }),
  east: Type.Number({ minimum: -180, maximum: 180 }),
});
const pagination = {
  offset: Type.Optional(Type.Integer({ minimum: 0, maximum: 10000 })),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 50 })),
};
const dimensions = {
  boat_length_m: Type.Optional(Type.Number({ exclusiveMinimum: 0 })),
  boat_beam_m: Type.Optional(Type.Number({ exclusiveMinimum: 0 })),
  boat_draft_m: Type.Optional(Type.Number({ exclusiveMinimum: 0 })),
  boat_height_m: Type.Optional(Type.Number({ exclusiveMinimum: 0 })),
};

function record(value: unknown): RecordJson {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new AgentError('tool_failed');
  }
  return value as RecordJson;
}

function array(value: Json | undefined): Json[] {
  if (!Array.isArray(value)) throw new AgentError('tool_failed');
  return value;
}

function stringArg(args: RecordJson, key: string): string {
  const value = args[key];
  if (typeof value !== 'string' || !value) throw new AgentError('invalid_tool_arguments');
  return value;
}

function finiteNumber(value: Json | undefined): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) throw new AgentError('invalid_tool_arguments');
  return value;
}

function kindsArg(args: RecordJson, allowed: Set<string>): string[] {
  const values = array(args.kinds);
  if (!values.length || values.length > 16) throw new AgentError('invalid_tool_arguments');
  const kinds = values.map(value => {
    if (typeof value !== 'string' || !allowed.has(value)) throw new AgentError('invalid_tool_arguments');
    return value;
  });
  if (new Set(kinds).size !== kinds.length) throw new AgentError('invalid_tool_arguments');
  return kinds;
}

function coordinate(value: Json): { lat: number; lon: number } {
  const item = record(value);
  const lat = finiteNumber(item.lat);
  const lon = finiteNumber(item.lon);
  if (lat < -90 || lat > 90 || lon < -180 || lon > 180) {
    throw new AgentError('invalid_tool_arguments');
  }
  return { lat, lon };
}

function point(value: Json): RecordJson {
  const { lat, lon } = coordinate(value);
  return { type: 'Point', coordinates: [lon, lat] };
}

function line(value: Json | undefined): RecordJson | undefined {
  if (!value) return undefined;
  const geometry = record(value);
  if (geometry.type !== 'LineString' || !Array.isArray(geometry.coordinates)
    || geometry.coordinates.length < 2) throw new AgentError('invalid_tool_arguments');
  return geometry;
}

function routeResponse(value: Json): RecordJson {
  const current = record(value);
  if (current.geometry) return current;
  if (current.journey) return routeResponse(current.journey);
  throw new AgentError('tool_failed');
}

function dayGeometry(journey: Json, day: number | undefined): RecordJson | undefined {
  if (day === undefined) return undefined;
  const route = routeResponse(journey);
  const entries = Array.isArray(route.day_geometries) ? route.day_geometries : [];
  const match = entries.find(value => record(value).day === day);
  return match ? line(record(match).geometry) : undefined;
}

function geometryCoordinates(geometry: RecordJson): Array<[number, number]> {
  const values = array(geometry.coordinates);
  const coordinates: Array<[number, number]> = [];
  for (const value of values) {
    const pair = array(value);
    if (pair.length !== 2) throw new AgentError('invalid_tool_arguments');
    const lon = finiteNumber(pair[0]);
    const lat = finiteNumber(pair[1]);
    if (lon < -180 || lon > 180 || lat < -90 || lat > 90) {
      throw new AgentError('invalid_tool_arguments');
    }
    coordinates.push([lon, lat]);
  }
  return coordinates;
}

function geometryBounds(geometry: RecordJson): RecordJson {
  const coordinates = geometryCoordinates(geometry);
  if (!coordinates.length) throw new AgentError('invalid_tool_arguments');
  let west = coordinates[0]![0];
  let east = west;
  let south = coordinates[0]![1];
  let north = south;
  for (const [lon, lat] of coordinates.slice(1)) {
    west = Math.min(west, lon);
    east = Math.max(east, lon);
    south = Math.min(south, lat);
    north = Math.max(north, lat);
  }
  return {
    south, west, north, east,
  };
}

function paddedBounds(bounds: RecordJson, meters: number): RecordJson {
  const south = finiteNumber(bounds.south);
  const west = finiteNumber(bounds.west);
  const north = finiteNumber(bounds.north);
  const east = finiteNumber(bounds.east);
  const centerLat = Math.max(-89.999, Math.min(89.999, (south + north) / 2));
  const latPad = Math.max(meters / 111_320, 0.00001);
  const lonPad = Math.max(meters / (111_320 * Math.cos(centerLat * Math.PI / 180)), 0.00001);
  return {
    south: Math.max(-90, south - latPad), west: Math.max(-180, west - lonPad),
    north: Math.min(90, north + latPad), east: Math.min(180, east + lonPad),
  };
}

function issue(set: Set<string>, id: string): void {
  set.delete(id);
  while (set.size >= 1000) set.delete(set.values().next().value!);
  set.add(id);
}

function distanceSquared(left: { lat: number; lon: number }, right: { lat: number; lon: number }): number {
  const lat = (left.lat + right.lat) / 2 * Math.PI / 180;
  const dlat = left.lat - right.lat;
  const dlon = (left.lon - right.lon) * Math.cos(lat);
  return dlat * dlat + dlon * dlon;
}

function stripSamples(value: Json): Json {
  if (Array.isArray(value)) return value.map(stripSamples);
  if (!value || typeof value !== 'object') return value;
  return Object.fromEntries(Object.entries(value as RecordJson)
    .filter(([key]) => key !== 'samples')
    .map(([key, item]) => [key, stripSamples(item)])) as Json;
}

function paged(value: Json[], args: RecordJson): { values: Json[]; offset: number; limit: number; truncated: boolean } {
  const offset = args.offset === undefined ? 0 : finiteNumber(args.offset);
  const limit = args.limit === undefined ? 20 : finiteNumber(args.limit);
  return { values: value.slice(offset, offset + limit), offset, limit, truncated: offset + limit < value.length };
}

function addPlaceRef(value: Json, rememberPlace: ApiToolDeps['rememberPlace']): Json {
  const place = record(value);
  const provenance = record(place.provenance);
  if (provenance.source !== 'osm') return place;
  const id = `osm:${String(provenance.osm_type)}:${String(provenance.osm_id)}`;
  rememberPlace(id, place.coordinate!);
  return { ...place, place_ref: id };
}

function toolName(name: string): ToolName {
  return name as ToolName;
}

export function createApiTools(deps: ApiToolDeps): DomainTool[] {
  const climateLocationIds = new Set<string>();
  const climateCellIds = new Set<string>();
  const make = (name: string, description: string, properties: Parameters<typeof Type.Object>[0], execute: (args: RecordJson, signal: AbortSignal) => Promise<Json>) =>
    deps.tool(toolName(name), description, properties, execute);

  const climateLocationList = make('get_climate_locations', 'Read bounded historical climate summaries, optionally nearest to an issued place reference.', {
    week_id: Type.Optional(Type.Integer({ minimum: 0, maximum: 17 })),
    period_years: Type.Optional(Type.Union([Type.Literal(5), Type.Literal(25)])),
    metric: Type.Optional(Type.Union([Type.Literal('high'), Type.Literal('low')])),
    place_ref: Type.Optional(refSchema),
    ...pagination,
  }, async (args, signal) => {
    const query = new URLSearchParams();
    query.set('week_id', String(args.week_id ?? 8));
    query.set('period_years', String(args.period_years ?? 25));
    query.set('metric', String(args.metric ?? 'high'));
    const result = record(await deps.call(`/api/climate/locations?${query}`, undefined, signal, { method: 'GET' }));
    const values = array(result.locations);
    const target = args.place_ref === undefined ? undefined : coordinate(deps.place(args.place_ref));
    const sorted = target ? [...values].sort((a, b) => distanceSquared(coordinate(record(a).coordinate!), target) - distanceSquared(coordinate(record(b).coordinate!), target)) : values;
    const page = paged(sorted, args);
    for (const value of page.values) {
      const id = record(value).id;
      if (typeof id === 'string') issue(climateLocationIds, id);
    }
    return { ...result, locations: page.values, total_locations: values.length, offset: page.offset, limit: page.limit, truncated: page.truncated };
  });

  const climateGrid = make('get_climate_grid', 'Read a bounded climate surface summary without returning its mask or full cell payload.', {
    week_id: Type.Optional(Type.Integer({ minimum: 0, maximum: 17 })),
    period_years: Type.Optional(Type.Union([Type.Literal(5), Type.Literal(25)])),
    view: Type.Optional(Type.Union([Type.Literal('high_median'), Type.Literal('high_p90'), Type.Literal('low_median'), Type.Literal('low_p10'), Type.Literal('high_exceedance')])),
    threshold_c: Type.Optional(Type.Number({ minimum: -20, maximum: 50 })),
    place_ref: Type.Optional(refSchema),
    ...pagination,
  }, async (args, signal) => {
    const query = new URLSearchParams({ week_id: String(args.week_id ?? 8), period_years: String(args.period_years ?? 25), view: String(args.view ?? 'high_p90') });
    if (args.threshold_c !== undefined) query.set('threshold_c', String(args.threshold_c));
    const result = record(await deps.call(`/api/climate/grid?${query}`, undefined, signal, { method: 'GET' }));
    const cells = array(result.cells);
    const target = args.place_ref === undefined ? undefined : coordinate(deps.place(args.place_ref));
    const sorted = target ? [...cells].sort((a, b) => distanceSquared(coordinate(record(a).coordinate!), target) - distanceSquared(coordinate(record(b).coordinate!), target)) : cells;
    const page = paged(sorted, args);
    for (const value of page.values) {
      const id = record(value).id;
      if (typeof id === 'string') issue(climateCellIds, id);
    }
    return {
      ...Object.fromEntries(Object.entries(result).filter(([key]) => key !== 'mask' && key !== 'cells')),
      total_cells: cells.length,
      available_cells: cells.filter(value => record(value).value !== null).length,
      cells: page.values,
      offset: page.offset,
      limit: page.limit,
      truncated: page.truncated,
    } as Json;
  });

  return [
    make('get_api_status', 'Check the loaded Pound API and artifact status.', {}, async (_args, signal) =>
      deps.call('/api/health', undefined, signal, { method: 'GET' })),
    make('search_places', 'Search bounded OSM and curated places near an issued place or preview, or within explicit viewport bounds.', {
      mode: Type.Union([Type.Literal('nearby'), Type.Literal('viewport')]),
      kinds: Type.Array(searchKindSchema, { minItems: 1, maxItems: 16 }),
      place_ref: Type.Optional(refSchema),
      preview_ref: Type.Optional(refSchema),
      text: Type.Optional(Type.String({ maxLength: 256 })),
      radius_m: Type.Optional(Type.Number({ minimum: 0, maximum: 2000 })),
      policy_basis: Type.Optional(Type.Union([Type.Literal('route'), Type.Literal('waterway'), Type.Literal('none')])),
      policy_radius_m: Type.Optional(Type.Number({ minimum: 0, maximum: 2000 })),
      bounds: Type.Optional(boundsSchema),
      day: Type.Optional(Type.Integer({ minimum: 1 })),
      ...pagination,
    }, async (args, signal) => {
      const kinds = kindsArg(args, CATALOG_KINDS);
      const mode = stringArg(args, 'mode');
      if (args.place_ref !== undefined && args.preview_ref !== undefined) throw new AgentError('invalid_tool_arguments');
      let geometry: RecordJson | undefined;
      let revision: string | undefined;
      let routeGeometry: RecordJson | undefined;
      if (args.place_ref !== undefined) geometry = point(deps.place(args.place_ref));
      if (args.preview_ref !== undefined) {
        const preview = deps.preview(args.preview_ref);
        revision = preview.revision;
        const route = routeResponse(preview.journey);
        routeGeometry = line(route.geometry);
        if (args.day !== undefined) {
          geometry = dayGeometry(preview.journey, finiteNumber(args.day));
          if (!geometry) throw new AgentError('invalid_tool_arguments');
        } else {
          geometry = routeGeometry;
        }
        if (!geometry) throw new AgentError('tool_failed');
        const health = record(await deps.call('/api/health', undefined, signal, { method: 'GET' }));
        if (health.artifact_revision !== revision) throw new AgentError('stale_revision');
      }
      if (mode === 'nearby') {
        if (!geometry) throw new AgentError('invalid_tool_arguments');
        const body: RecordJson = { mode, kinds, radius_m: args.radius_m ?? 1000, targets: [{ id: 'target', geometry }] };
        if (args.text !== undefined) body.text = args.text;
        const result = record(await deps.call('/api/places', body, signal));
        const values = array(result.places);
        const page = paged(values, args);
        return { places: page.values.map(value => addPlaceRef(value, deps.rememberPlace)), offset: page.offset, limit: page.limit, total_places: values.length, truncated: page.truncated } as Json;
      }
      const basis = String(args.policy_basis ?? (geometry && geometry.type === 'LineString' ? 'route' : 'none'));
      const explicitBounds = args.bounds ? record(args.bounds) : undefined;
      const radius = args.policy_radius_m === undefined ? 2000 : finiteNumber(args.policy_radius_m);
      const bounds = explicitBounds ?? (geometry?.type === 'Point' ? paddedBounds(geometryBounds({ type: 'LineString', coordinates: [geometry!.coordinates!, geometry!.coordinates!] }), radius) : geometry ? paddedBounds(geometryBounds(geometry), basis === 'none' ? 0 : radius) : undefined);
      if (!bounds) throw new AgentError('invalid_tool_arguments');
      if (Number(bounds.south) > Number(bounds.north) || Number(bounds.west) > Number(bounds.east)) throw new AgentError('invalid_tool_arguments');
      if (basis === 'route' && !routeGeometry) throw new AgentError('invalid_tool_arguments');
      const body: RecordJson = { mode, kinds, bounds, policy: { basis } };
      if (basis !== 'none') body.policy = { basis, radius_m: args.policy_radius_m ?? 2000 };
      if (args.text !== undefined) body.text = args.text;
      if (routeGeometry && (basis === 'route' || args.day !== undefined)) body.route_geometry = routeGeometry;
      if (args.day !== undefined) {
        if (args.preview_ref === undefined) throw new AgentError('invalid_tool_arguments');
        const day = dayGeometry(deps.preview(args.preview_ref), finiteNumber(args.day));
        if (day) body.day_geometry = day;
      }
      const result = record(await deps.call('/api/places', body, signal));
      const values = array(result.places);
      const page = paged(values, args);
      return { places: page.values.map(value => addPlaceRef(value, deps.rememberPlace)), offset: page.offset, limit: page.limit, total_places: values.length, truncated: page.truncated, artifact_revision: revision ?? null } as Json;
    }),
    make('get_route_pois', 'Search retained POIs along an issued route preview, optionally for one stored day geometry.', {
      preview_ref: refSchema,
      kinds: Type.Array(routePoiKindSchema, { minItems: 1, maxItems: 16 }),
      day: Type.Optional(Type.Integer({ minimum: 1 })),
      ...pagination,
    }, async (args, signal) => {
      const kinds = kindsArg(args, POI_KINDS);
      const preview = deps.preview(args.preview_ref);
      const route = routeResponse(preview.journey);
      const routeGeometry = line(route.geometry);
      if (!routeGeometry) throw new AgentError('tool_failed');
      const body: RecordJson = { artifact_revision: preview.revision, kinds, bounds: paddedBounds(geometryBounds(routeGeometry), 1000), route_geometry: routeGeometry };
      if (args.day !== undefined) {
        const day = dayGeometry(preview.journey, finiteNumber(args.day));
        if (!day) throw new AgentError('invalid_tool_arguments');
        body.day = args.day;
        body.day_geometry = day;
      }
      const result = record(await deps.call('/api/route-pois', body, signal));
      const values = array(result.pois);
      const page = paged(values, args);
      return { ...result, pois: page.values, offset: page.offset, limit: page.limit, truncated: page.truncated };
    }),
    make('get_canal_network', 'Summarize the bounded hire-base reachable canal network without returning network geometry.', {
      days: Type.Integer({ minimum: 1, maximum: 365 }),
      hours_per_day: Type.Number({ exclusiveMinimum: 0, maximum: 24 }),
      movable_bridge_delay_min: Type.Optional(Type.Number({ minimum: 0 })),
      selected_base_identity: Type.Optional(Type.String({ minLength: 1 })),
      ...dimensions,
    }, async (args, signal) => {
      const body: RecordJson = { days: finiteNumber(args.days), hours_per_day: finiteNumber(args.hours_per_day) };
      for (const key of ['movable_bridge_delay_min', 'selected_base_identity', ...Object.keys(dimensions)]) {
        if (args[key] !== undefined) body[key] = args[key]!;
      }
      const result = record(await deps.call('/api/canal-network', body, signal));
      const lines = array(result.lines);
      const highlights = array(result.highlight_lines);
      const allCoordinates = [...lines, ...highlights].flatMap(value => geometryCoordinates(record(value)));
      const bounds = allCoordinates.length ? geometryBounds({ type: 'LineString', coordinates: allCoordinates.map(([lon, lat]) => [lon, lat]) }) : null;
      return { artifact_revision: result.artifact_revision!, bases: result.bases ?? [], line_count: lines.length, highlight_line_count: highlights.length, vertex_count: allCoordinates.length, bounds };
    }),
    climateLocationList,
    make('get_climate_location', 'Read one climate location previously issued by get_climate_locations, with sample arrays removed.', {
      location_id: refSchema,
      week_id: Type.Optional(Type.Integer({ minimum: 0, maximum: 17 })),
    }, async (args, signal) => {
      const id = stringArg(args, 'location_id');
      if (!climateLocationIds.has(id)) throw new AgentError('invalid_tool_arguments');
      const query = new URLSearchParams({ week_id: String(args.week_id ?? 8) });
      return stripSamples(await deps.call(`/api/climate/locations/${encodeURIComponent(id)}?${query}`, undefined, signal, { method: 'GET' }));
    }),
    climateGrid,
    make('get_climate_cell', 'Read one climate grid cell previously issued by get_climate_grid, with sample arrays removed.', {
      cell_id: refSchema,
      week_id: Type.Optional(Type.Integer({ minimum: 0, maximum: 17 })),
    }, async (args, signal) => {
      const id = stringArg(args, 'cell_id');
      if (!climateCellIds.has(id)) throw new AgentError('invalid_tool_arguments');
      const query = new URLSearchParams({ week_id: String(args.week_id ?? 8) });
      return stripSamples(await deps.call(`/api/climate/grid/cells/${encodeURIComponent(id)}?${query}`, undefined, signal, { method: 'GET' }));
    }),
  ];
}
