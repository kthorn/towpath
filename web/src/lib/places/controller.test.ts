import { get } from 'svelte/store';
import { describe, expect, it, vi } from 'vitest';

import type { BrowserPlace, PlaceTextSearch } from '../google/textSearch';
import type { TransferRouter } from '../google/contracts';
import type { CanalCandidate, LatLon } from '../types';
import { createPlaceController } from './controller';

const coordinate: LatLon = { lat: 51.997, lon: -0.74 };
const candidate: CanalCandidate = {
	candidate_id: 'candidate-1',
	handle: { edge: [1, 2], fraction: 0.5 },
	coordinate: { lat: 51.998, lon: -0.741 },
	straight_line_distance_m: 100,
	display_name: 'Canal access',
};

function response(value: unknown, ok = true): Response {
	return new Response(JSON.stringify(value), {
		status: ok ? 200 : 500,
		headers: { 'Content-Type': 'application/json' },
	});
}

function sessionResponse() {
	return response({ session_id: 'session-1', token: 'token-1', expires_in: 600 });
}

function resolvedOsmResponse() {
	return {
		run_id: 'run-1',
		status: 'resolved',
		osm: {
			status: 'resolved',
			reason: 'exact',
			options: [
				{
					option_ref: 'osm-1',
					source: 'osm',
					source_id: 'node/1',
					name: 'Bletchley Park',
					coordinate,
					locality: 'Bletchley',
				},
			],
		},
	};
}

function walkingTask() {
	return {
		task_id: 'walking-task-1',
		run_id: 'run-1',
		digest: 'w'.repeat(64),
		kind: 'walking',
		payload: { option_ref: 'osm-1', candidates: [candidate] },
	};
}

function availableRouter(): TransferRouter {
	return {
		matrix: vi.fn(async () => [{ available: true as const, durationSeconds: 10, distanceMeters: 100 }]),
		route: vi.fn(async () => ({
			path: [coordinate, candidate.coordinate],
			durationSeconds: 10,
			distanceMeters: 100,
		})),
	};
}

function textSearch(result: Partial<Awaited<ReturnType<PlaceTextSearch['search']>>> = {}) {
	return {
		search: vi.fn(async () => ({ status: 'matches' as const, places: [], ...result })),
	};
}

describe('place browser controller', () => {
	it('auto-selects an exact OSM result without calling Google', async () => {
		const fetchFn = vi
			.fn<typeof fetch>()
			.mockResolvedValueOnce(sessionResponse())
			.mockResolvedValueOnce(response(resolvedOsmResponse()))
			.mockResolvedValueOnce(response({ run_id: 'run-1', status: 'pending', task: walkingTask() }))
			.mockResolvedValueOnce(response({ run_id: 'run-1', status: 'complete' }));
		const google = textSearch();
		const controller = createPlaceController({
			textSearch: google,
			transferRouter: availableRouter(),
			fetchFn,
		});

		await controller.search('Bletchley Park');

		expect(google.search).not.toHaveBeenCalled();
		expect(get(controller).selected).toEqual({
			option_ref: 'osm-1',
			name: 'Bletchley Park',
			locality: 'Bletchley',
			coordinate,
			source: 'osm',
		});
		expect(get(controller).status, get(controller).error).toBe('ready');
		expect(get(controller).error).toBe('');
	});

	it('redacts Google provider details from the browser task result', async () => {
		const searchTask = {
			task_id: 'search-task-1',
			run_id: 'run-1',
			digest: 's'.repeat(64),
			kind: 'search',
			payload: { query: 'Bletchley Park', bounds: { south: 51, west: -1, north: 53, east: 0 } },
		};
		const providerPlace: BrowserPlace = {
			id: 'provider-secret-id',
			name: 'Secret provider name',
			address: 'Secret provider address',
			coordinate,
		};
		const fetchFn = vi
			.fn<typeof fetch>()
			.mockResolvedValueOnce(sessionResponse())
			.mockResolvedValueOnce(response({
				run_id: 'run-1',
				status: 'pending',
				task: searchTask,
				osm: { status: 'not_found', options: [] },
			}))
			.mockResolvedValueOnce(response({ run_id: 'run-1', status: 'ambiguous', option_refs: ['google-ref'] }));
		const google = textSearch({ status: 'matches', places: [providerPlace] });
		const controller = createPlaceController({ textSearch: google, transferRouter: availableRouter(), fetchFn });

		await controller.search('Bletchley Park');

		const resultRequest = fetchFn.mock.calls[2]?.[1];
		const body = JSON.parse(String(resultRequest?.body));
		expect(Object.keys(body).sort()).toEqual(['digest', 'option_refs', 'run_id', 'status']);
		expect(JSON.stringify(body)).not.toContain('provider-secret-id');
		expect(JSON.stringify(body)).not.toContain('Secret provider');
		expect(get(controller).options).toHaveLength(1);
		expect(get(controller).options[0]).toMatchObject({
			source: 'google',
			name: 'Secret provider name',
			address: 'Secret provider address',
		});
	});

	it('keeps ambiguous OSM suggestions pending explicit selection', async () => {
		const osm = resolvedOsmResponse();
		osm.status = 'ambiguous';
		osm.osm.status = 'ambiguous';
		osm.osm.options.push({ ...osm.osm.options[0], option_ref: 'osm-2', source_id: 'node/2', name: 'Other Park' });
		const fetchFn = vi
			.fn<typeof fetch>()
			.mockResolvedValueOnce(sessionResponse())
			.mockResolvedValueOnce(response(osm));
		const controller = createPlaceController({ textSearch: textSearch(), transferRouter: availableRouter(), fetchFn });

		await controller.search('Park');

		expect(get(controller).status).toBe('ambiguous');
		expect(get(controller).selected).toBeNull();
		expect(fetchFn).toHaveBeenCalledTimes(2);
	});

	it('posts directional walking availability while retaining both directions in state', async () => {
		const googleChoice: BrowserPlace = {
			id: 'provider-id', name: 'Google Park', address: 'Provider address', coordinate,
		};
		const searchTask = {
			task_id: 'search-task-1', run_id: 'run-1', digest: 's'.repeat(64), kind: 'search',
			payload: { query: 'Park', bounds: { south: 51, west: -1, north: 53, east: 0 } },
		};
		const task = { ...walkingTask(), payload: { option_ref: 'google-ref', candidates: [candidate] } };
		const fetchFn = vi.fn<typeof fetch>(async (input, init) => {
			const url = String(input);
			if (url === '/api/place-sessions') return sessionResponse();
			if (url.endsWith('/resolve')) return response({ run_id: 'run-1', status: 'pending', task: searchTask });
			if (url.endsWith('/tasks/search-task-1/result')) {
				return response({ run_id: 'run-1', status: 'ambiguous', option_refs: ['google-ref'] });
			}
			if (url.endsWith('/select')) {
				const body = JSON.parse(String(init?.body)) as { option_ref: string };
				return response({
					run_id: 'run-1',
					status: 'pending',
					task: { ...task, payload: { option_ref: body.option_ref, candidates: [candidate] } },
				});
			}
			return response({ run_id: 'run-1', status: 'complete' });
		});
		const router = {
			...availableRouter(),
			matrix: vi
				.fn()
			.mockResolvedValueOnce([{ available: true, durationSeconds: 10, distanceMeters: 100 }])
			.mockResolvedValueOnce([{ available: false, reason: 'NO_ROUTE' }]),
		};
		const controller = createPlaceController({
			textSearch: textSearch({ status: 'matches', places: [googleChoice] }),
			transferRouter: router,
			fetchFn,
		});

		await controller.search('Park');
		const optionRef = get(controller).options[0]?.option_ref;
		await controller.select(optionRef as string);

		const resultCall = fetchFn.mock.calls.find(([input]) => String(input).includes('/tasks/walking-task-1/result'));
		const body = JSON.parse(String(resultCall?.[1]?.body));
		expect(body.transfers).toEqual([
			{ candidate_id: 'candidate-1', outward: 'unavailable', return: 'available' },
		]);
		expect(get(controller).access[0]).toMatchObject({ complete: false });
		expect(get(controller).access[0]?.outward).toEqual({ available: false, reason: 'UNAVAILABLE' });
		expect(get(controller).access[0]?.return).toMatchObject({ available: true });
	});

	it('cancels pending work and ignores late provider results', async () => {
		let resolveSearch!: (result: Awaited<ReturnType<PlaceTextSearch['search']>>) => void;
		const google = { search: vi.fn(() => new Promise<Awaited<ReturnType<PlaceTextSearch['search']>>>(resolve => { resolveSearch = resolve; })) };
		const searchTask = {
			task_id: 'search-task-1', run_id: 'run-1', digest: 's'.repeat(64), kind: 'search',
			payload: { query: 'Park', bounds: { south: 51, west: -1, north: 53, east: 0 } },
		};
		const fetchFn = vi
			.fn<typeof fetch>()
			.mockResolvedValueOnce(sessionResponse())
			.mockResolvedValueOnce(response({ run_id: 'run-1', status: 'pending', task: searchTask }));
		const controller = createPlaceController({ textSearch: google, transferRouter: availableRouter(), fetchFn });
		const pending = controller.search('Park');
		await vi.waitFor(() => expect(google.search).toHaveBeenCalledOnce());

		await controller.cancel();
		resolveSearch({ status: 'matches', places: [] });
		await pending;

		expect(fetchFn).toHaveBeenCalledWith('/api/place-sessions/session-1', expect.objectContaining({ method: 'DELETE' }));
		expect(get(controller).selected).toBeNull();
		expect(get(controller).options).toEqual([]);
		expect(get(controller).access).toEqual([]);
	});

	it('does not apply a late detailed route after cancellation', async () => {
		let resolveRoute!: (route: { path: LatLon[]; durationSeconds: number; distanceMeters: number }) => void;
		const route = new Promise<{ path: LatLon[]; durationSeconds: number; distanceMeters: number }>((resolve) => {
			resolveRoute = resolve;
		});
		const fetchFn = vi
			.fn<typeof fetch>()
			.mockResolvedValueOnce(sessionResponse())
			.mockResolvedValueOnce(response(resolvedOsmResponse()))
			.mockResolvedValueOnce(response({ run_id: 'run-1', status: 'pending', task: walkingTask() }))
			.mockResolvedValueOnce(response({ run_id: 'run-1', status: 'complete' }));
		const router = availableRouter();
		router.route = vi.fn(() => route);
		const controller = createPlaceController({ textSearch: textSearch(), transferRouter: router, fetchFn });
		await controller.search('Bletchley Park');

		const pending = controller.walkingRoutes('candidate-1', true);
		await vi.waitFor(() => expect(router.route).toHaveBeenCalledTimes(2));
		await controller.cancel();
		resolveRoute({ path: [coordinate, candidate.coordinate], durationSeconds: 10, distanceMeters: 100 });

		await expect(pending).rejects.toThrow();
		expect(get(controller).selected).toBeNull();
	});

	it('keeps the detailed route budget across new searches in one session', async () => {
		const fetchFn = vi.fn<typeof fetch>(async (input) => {
			const url = String(input);
			if (url === '/api/place-sessions') return sessionResponse();
			if (url.endsWith('/resolve')) return response(resolvedOsmResponse());
			if (url.endsWith('/select')) return response({ run_id: 'run-1', status: 'pending', task: walkingTask() });
			return response({ run_id: 'run-1', status: 'complete' });
		});
		const controller = createPlaceController({ textSearch: textSearch(), transferRouter: availableRouter(), fetchFn });
		await controller.search('Bletchley Park');
		for (let count = 0; count < 10; count += 1) await controller.walkingRoutes('candidate-1', true);
		await controller.search('Bletchley Park');

		await expect(controller.walkingRoutes('candidate-1', true)).rejects.toThrow('limit');
	});

	it('supports manual coordinate recovery before a place run exists', async () => {
		const manualTask = {
			...walkingTask(),
			payload: { option_ref: 'manual-1', candidates: [candidate] },
		};
		const fetchFn = vi
			.fn<typeof fetch>()
			.mockResolvedValueOnce(sessionResponse())
			.mockResolvedValueOnce(response({
				run_id: 'run-manual', status: 'pending', option_ref: 'manual-1', task: manualTask,
			}))
			.mockResolvedValueOnce(response({ run_id: 'run-manual', status: 'complete' }));
		const controller = createPlaceController({ textSearch: textSearch(), transferRouter: availableRouter(), fetchFn });

		await controller.selectManual(coordinate);

		const request = fetchFn.mock.calls[1]?.[1];
		expect(JSON.parse(String(request?.body))).toEqual({ coordinate });
		expect(get(controller).selected).toMatchObject({ option_ref: 'manual-1', source: 'manual', coordinate });
	});

	it('clears old options before a Google retry starts', async () => {
		let resolveGoogle!: (result: Awaited<ReturnType<PlaceTextSearch['search']>>) => void;
		const google = { search: vi.fn(() => new Promise<Awaited<ReturnType<PlaceTextSearch['search']>>>(resolve => { resolveGoogle = resolve; })) };
		const searchTask = {
			task_id: 'search-task-1', run_id: 'run-1', digest: 's'.repeat(64), kind: 'search',
			payload: { query: 'Park', bounds: { south: 51, west: -1, north: 53, east: 0 } },
		};
		const fetchFn = vi
			.fn<typeof fetch>()
			.mockResolvedValueOnce(sessionResponse())
			.mockResolvedValueOnce(response({
				run_id: 'run-1', status: 'ambiguous',
				osm: { status: 'ambiguous', options: [{ option_ref: 'old-ref', name: 'Old Park', coordinate }] },
			}))
			.mockResolvedValueOnce(response({ run_id: 'run-1', status: 'pending', task: searchTask }));
		const controller = createPlaceController({ textSearch: google, transferRouter: availableRouter(), fetchFn });
		await controller.search('Park');
		const pending = controller.searchGoogle();
		await vi.waitFor(() => expect(google.search).toHaveBeenCalledOnce());

		expect(get(controller).options).toEqual([]);
		resolveGoogle({ status: 'not_found', places: [] });
		await pending;
	});
});
