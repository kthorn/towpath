import type {
  CanalCandidatesRequest,
  CanalCandidatesResponse,
  CanalNetworkRequest,
  CanalNetworkResponse,
  CanalRouteRequest,
  CanalRouteResponse,
  TurnaroundCandidatesRequest,
  TurnaroundCandidatesResponse,
  TurnaroundRejection,
  HealthResponse,
  PlacesRequest,
  PlacesResponse,
  PoundApiErrorDetail,
  RoutePoisRequest,
  RoutePoisResponse,
} from './types';

export class PoundApiError extends Error implements PoundApiErrorDetail {
  readonly status: number;
  readonly code: string;
  readonly fields: string[];
  readonly rejections: TurnaroundRejection[];

  constructor(status: number, detail: PoundApiErrorDetail) {
    super(detail.message);
    this.name = 'PoundApiError';
    this.status = status;
    this.code = detail.code;
    this.fields = detail.fields;
    this.rejections = detail.rejections ?? [];
  }
}

function isRejection(value: unknown): value is TurnaroundRejection {
  if (typeof value !== 'object' || value === null) return false;
  const rejection = value as Record<string, unknown>;
  return typeof rejection.code === 'string' && typeof rejection.message === 'string' &&
    Array.isArray(rejection.fields) && rejection.fields.every((field) => typeof field === 'string') &&
    (rejection.turnaround_id === undefined || rejection.turnaround_id === null || typeof rejection.turnaround_id === 'string');
}

function isErrorDetail(value: unknown): value is PoundApiErrorDetail {
  if (typeof value !== 'object' || value === null) return false;
  const detail = value as Record<string, unknown>;
  return (
    typeof detail.code === 'string' &&
    typeof detail.message === 'string' &&
    Array.isArray(detail.fields) &&
    detail.fields.every((field) => typeof field === 'string') &&
    (detail.rejections === undefined || (Array.isArray(detail.rejections) && detail.rejections.every(isRejection)))
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
    canalNetwork(request: CanalNetworkRequest): Promise<CanalNetworkResponse> {
      return postJson(fetchFn, '/api/canal-network', request);
    },
    canalCandidates(request: CanalCandidatesRequest): Promise<CanalCandidatesResponse> {
      return postJson(fetchFn, '/api/canal-candidates', request);
    },
    canalRoute(request: CanalRouteRequest): Promise<CanalRouteResponse> {
      return postJson(fetchFn, '/api/canal-route', request);
    },
    turnaroundCandidates(request: TurnaroundCandidatesRequest): Promise<TurnaroundCandidatesResponse> {
      return postJson(fetchFn, '/api/turnaround-candidates', request);
    },
    routePois(request: RoutePoisRequest): Promise<RoutePoisResponse> {
      return postJson(fetchFn, '/api/route-pois', request);
    },
    places(request: PlacesRequest): Promise<PlacesResponse> {
      return postJson(fetchFn, '/api/places', request);
    },
  };
}
