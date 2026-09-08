import type {
  ClimateLocationResponse,
  ClimatePeriodYears,
  ClimateSource,
} from './climate';
import { PoundApiError } from './api';

export type ClimateGridView =
  | 'high_median'
  | 'high_p90'
  | 'low_median'
  | 'low_p10'
  | 'high_exceedance';

export type ClimateGridUnit = 'celsius' | 'probability';

export interface ClimateGridCell {
  id: string;
  coordinate: { lat: number; lon: number };
  value: number | null;
  n_days: number;
}

export interface ClimateGridPolygon {
  type: 'Polygon';
  coordinates: number[][][];
}

export interface ClimateGridMultiPolygon {
  type: 'MultiPolygon';
  coordinates: number[][][][];
}

export type ClimateGridMask = ClimateGridPolygon | ClimateGridMultiPolygon;

export interface ClimateGridMaskSource {
  name: string;
  url: string;
  attribution: string;
}

export interface ClimateGridSurface {
  revision: string;
  end_year: number;
  source: ClimateSource;
  week_id: number;
  week_label: string;
  period_years: ClimatePeriodYears;
  view: ClimateGridView;
  threshold_c: number | null;
  unit: ClimateGridUnit;
  spacing_km: 10;
  mask: ClimateGridMask;
  mask_source?: ClimateGridMaskSource;
  cells: ClimateGridCell[];
}

export interface ClimateGridRequest {
  week_id: number;
  period_years: ClimatePeriodYears;
  view: ClimateGridView;
  threshold_c?: number;
}

export interface ClimateGridCellRequest {
  week_id: number;
}

export interface ClimateGridApi {
  grid(request: ClimateGridRequest): Promise<ClimateGridSurface>;
  cell(id: string, request: ClimateGridCellRequest): Promise<ClimateLocationResponse>;
}

export class ClimateGridApiError extends PoundApiError {
  constructor(status: number, detail: { code: string; message: string; fields?: string[] }) {
    super(status, { code: detail.code, message: detail.message, fields: detail.fields ?? [] });
    this.name = 'ClimateGridApiError';
  }
}

function isErrorDetail(value: unknown): value is { code: string; message: string; fields?: string[] } {
  if (typeof value !== 'object' || value === null) return false;
  const detail = value as Record<string, unknown>;
  return typeof detail.code === 'string' && typeof detail.message === 'string' && (
    detail.fields === undefined || (
      Array.isArray(detail.fields) && detail.fields.every((field) => typeof field === 'string')
    )
  );
}

async function errorFromResponse(response: Response): Promise<ClimateGridApiError> {
  try {
    const body: unknown = await response.json();
    if (typeof body === 'object' && body !== null && isErrorDetail((body as { detail?: unknown }).detail)) {
      return new ClimateGridApiError(response.status, (body as {
        detail: { code: string; message: string; fields?: string[] };
      }).detail);
    }
  } catch {
    // The fallback intentionally avoids exposing an HTML or proxy response body.
  }

  return new ClimateGridApiError(response.status, {
    code: 'http_error',
    message: response.statusText || `Request failed with status ${response.status}`,
  });
}

async function getJson<T>(fetchFn: typeof fetch, url: string): Promise<T> {
  const response = await fetchFn(url, { method: 'GET' });
  if (!response.ok) throw await errorFromResponse(response);
  return (await response.json()) as T;
}

export function createClimateGridApi(fetchFn: typeof fetch = fetch): ClimateGridApi {
  return {
    grid(request) {
      const query = new URLSearchParams({
        week_id: String(request.week_id),
        period_years: String(request.period_years),
        view: request.view,
      });
      if (request.threshold_c !== undefined) query.set('threshold_c', String(request.threshold_c));
      return getJson(fetchFn, `/api/climate/grid?${query.toString()}`);
    },
    cell(id, request) {
      const query = new URLSearchParams({ week_id: String(request.week_id) });
      return getJson(fetchFn, `/api/climate/grid/cells/${encodeURIComponent(id)}?${query.toString()}`);
    },
  };
}

/** Compute count(high > threshold_c) / n_days; equality does not count. */
export function highExceedanceFraction(
  samples: readonly number[],
  thresholdC: number,
  nDays = samples.length,
): number {
  if (!Number.isFinite(thresholdC) || !Number.isFinite(nDays) || nDays <= 0) return 0;
  const count = samples.reduce(
    (total, sample) => total + (Number.isFinite(sample) && sample > thresholdC ? 1 : 0),
    0,
  );
  return Math.min(1, count / nDays);
}
