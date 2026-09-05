import type { LatLon } from './types';
import { PoundApiError } from './api';

export type ClimateMetric = 'high' | 'low';
export type ClimatePeriodYears = 5 | 25;

export interface ClimateSource {
  name: string;
  url: string;
  attribution: string;
  timezone: string;
  model: string;
}

export interface ClimateSummaryDistribution {
  available: boolean;
  missing_years: number[];
  start_year: number | null;
  end_year: number | null;
  n_days: number;
  n_years: number;
  p10: number | null;
  median: number | null;
  p90: number | null;
  samples?: number[];
}

export interface ClimateLocationSummary {
  id: string;
  name: string;
  coordinate: LatLon;
  distribution: ClimateSummaryDistribution;
}

export interface ClimateLocationsResponse {
  revision: string;
  end_year: number;
  source: ClimateSource;
  week_id: number;
  week_label: string;
  period_years: ClimatePeriodYears;
  metric: ClimateMetric;
  locations: ClimateLocationSummary[];
}

export interface ClimateLocationDetail {
  id: string;
  name: string;
  coordinate: LatLon;
  source_coordinate: LatLon | null;
  elevation: number | null;
}

export interface ClimateLocationResponse {
  revision: string;
  end_year: number;
  source: ClimateSource;
  week_id: number;
  week_label: string;
  location: ClimateLocationDetail;
  high: Record<`${ClimatePeriodYears}`, ClimateSummaryDistribution>;
  low: Record<`${ClimatePeriodYears}`, ClimateSummaryDistribution>;
}

export interface ClimateLocationsRequest {
  week_id: number;
  period_years: ClimatePeriodYears;
  metric: ClimateMetric;
}

export interface ClimateLocationRequest {
  week_id: number;
}

export interface ClimateApi {
  locations(request: ClimateLocationsRequest): Promise<ClimateLocationsResponse>;
  location(id: string, request: ClimateLocationRequest): Promise<ClimateLocationResponse>;
}

export class ClimateApiError extends PoundApiError {
  constructor(status: number, detail: { code: string; message: string; fields?: string[] }) {
    super(status, { code: detail.code, message: detail.message, fields: detail.fields ?? [] });
    this.name = 'ClimateApiError';
  }
}

function isErrorDetail(value: unknown): value is { code: string; message: string; fields?: string[] } {
  if (typeof value !== 'object' || value === null) return false;
  const detail = value as Record<string, unknown>;
  return (
    typeof detail.code === 'string' &&
    typeof detail.message === 'string' &&
    (detail.fields === undefined || (
      Array.isArray(detail.fields) && detail.fields.every((field) => typeof field === 'string')
    ))
  );
}

async function errorFromResponse(response: Response): Promise<ClimateApiError> {
  try {
    const body: unknown = await response.json();
    if (typeof body === 'object' && body !== null && isErrorDetail((body as { detail?: unknown }).detail)) {
      return new ClimateApiError(response.status, (body as { detail: { code: string; message: string; fields?: string[] } }).detail);
    }
  } catch {
    // The fallback below intentionally does not expose response bodies.
  }

  return new ClimateApiError(response.status, {
    code: 'http_error',
    message: response.statusText || `Request failed with status ${response.status}`,
  });
}

async function getJson<T>(fetchFn: typeof fetch, url: string): Promise<T> {
  const response = await fetchFn(url, { method: 'GET' });
  if (!response.ok) throw await errorFromResponse(response);
  return (await response.json()) as T;
}

export function createClimateApi(fetchFn: typeof fetch = fetch): ClimateApi {
  return {
    locations(request) {
      const query = new URLSearchParams({
        week_id: String(request.week_id),
        period_years: String(request.period_years),
        metric: request.metric,
      });
      return getJson(fetchFn, `/api/climate/locations?${query.toString()}`);
    },
    location(id, request) {
      const query = new URLSearchParams({ week_id: String(request.week_id) });
      return getJson(fetchFn, `/api/climate/locations/${encodeURIComponent(id)}?${query.toString()}`);
    },
  };
}

export interface ClimateWeek {
  id: number;
  label: string;
}

export const CLIMATE_WEEKS: readonly ClimateWeek[] = [
  'May 1–7',
  'May 8–14',
  'May 15–21',
  'May 22–28',
  'May 29–June 4',
  'June 5–11',
  'June 12–18',
  'June 19–25',
  'June 26–July 2',
  'July 3–9',
  'July 10–16',
  'July 17–23',
  'July 24–30',
  'July 31–August 6',
  'August 7–13',
  'August 14–20',
  'August 21–27',
  'August 28–September 3',
].map((label, id) => ({ id, label }));

export const DEFAULT_CLIMATE_WEEK_ID = 8;
export const DEFAULT_CLIMATE_PERIOD_YEARS: ClimatePeriodYears = 25;
export const DEFAULT_CLIMATE_METRIC: ClimateMetric = 'high';

export const CLIMATE_COLOR_LIMITS: Record<ClimateMetric, { min: number; max: number }> = {
  high: { min: 0, max: 35 },
  low: { min: -5, max: 25 },
};

export function climateColorPosition(metric: ClimateMetric, value: number): number {
  const limits = CLIMATE_COLOR_LIMITS[metric];
  if (!Number.isFinite(value)) return 0;
  return Math.min(1, Math.max(0, (value - limits.min) / (limits.max - limits.min)));
}

/** Return a stable blue-to-red marker colour using the fixed metric limits. */
export function climateColor(metric: ClimateMetric, value: number): string {
  const hue = 220 - (220 * climateColorPosition(metric, value));
  return `hsl(${hue} 72% 75%)`;
}
