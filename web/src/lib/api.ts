import type {
  CanalCandidatesRequest,
  CanalCandidatesResponse,
  CanalRouteRequest,
  CanalRouteResponse,
  CatalogPlacesRequest,
  CatalogPlacesResponse,
  HealthResponse,
  PoundApiErrorDetail,
  RoutePoisRequest,
  RoutePoisResponse,
} from './types';

export class PoundApiError extends Error implements PoundApiErrorDetail {
  readonly status: number;
  readonly code: string;
  readonly fields: string[];

  constructor(status: number, detail: PoundApiErrorDetail) {
    super(detail.message);
    this.name = 'PoundApiError';
    this.status = status;
    this.code = detail.code;
    this.fields = detail.fields;
  }
}

function isErrorDetail(value: unknown): value is PoundApiErrorDetail {
  if (typeof value !== 'object' || value === null) return false;
  const detail = value as Record<string, unknown>;
  return (
    typeof detail.code === 'string' &&
    typeof detail.message === 'string' &&
    Array.isArray(detail.fields) &&
    detail.fields.every((field) => typeof field === 'string')
  );
}

async function errorFromResponse(response: Response): Promise<PoundApiError> {
  try {
    const body: unknown = await response.json();
    if (typeof body === 'object' && body !== null && isErrorDetail((body as { detail?: unknown }).detail)) {
      return new PoundApiError(response.status, (body as { detail: PoundApiErrorDetail }).detail);
    }
  } catch {
    // The safe HTTP fallback below intentionally does not expose response bodies.
  }

  return new PoundApiError(response.status, {
    code: 'http_error',
    message: response.statusText || `Request failed with status ${response.status}`,
    fields: [],
  });
}

async function getJson<T>(fetchFn: typeof fetch, url: string): Promise<T> {
  const response = await fetchFn(url, { method: 'GET' });
  if (!response.ok) throw await errorFromResponse(response);
  return (await response.json()) as T;
}

async function postJson<T>(fetchFn: typeof fetch, url: string, body: unknown): Promise<T> {
  const response = await fetchFn(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  if (!response.ok) throw await errorFromResponse(response);
  return (await response.json()) as T;
}

export function createPoundApi(fetchFn: typeof fetch = fetch) {
  return {
    health(): Promise<HealthResponse> {
      return getJson(fetchFn, '/api/health');
    },
    canalCandidates(request: CanalCandidatesRequest): Promise<CanalCandidatesResponse> {
      return postJson(fetchFn, '/api/canal-candidates', request);
    },
    canalRoute(request: CanalRouteRequest): Promise<CanalRouteResponse> {
      return postJson(fetchFn, '/api/canal-route', request);
    },
    routePois(request: RoutePoisRequest): Promise<RoutePoisResponse> {
      return postJson(fetchFn, '/api/route-pois', request);
    },
    catalogPlaces(request: CatalogPlacesRequest): Promise<CatalogPlacesResponse> {
      return postJson(fetchFn, '/api/catalog-places', request);
    },
  };
}
