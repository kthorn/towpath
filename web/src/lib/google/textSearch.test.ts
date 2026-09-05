import { describe, expect, it, vi } from 'vitest';

import {
	createGooglePlaceTextSearch,
	type TextSearchFacade,
	type TextSearchResponse,
} from './textSearch';

const bounds = { south: 51.9, west: -0.9, north: 52.1, east: -0.6 };

function createPlace(overrides: Record<string, unknown> = {}) {
	return {
		id: 'place-1',
		displayName: 'Bletchley Park',
		formattedAddress: 'Sherwood Drive, Bletchley',
		location: { lat: 51.997, lng: -0.74 },
		...overrides,
	};
}

function createFacade(
	response: TextSearchResponse,
): TextSearchFacade & { searchByText: ReturnType<typeof vi.fn> } {
	return { searchByText: vi.fn(async () => response) };
}

describe('Google place text-search adapter', () => {
	it('requests bounded fields and converts matching places', async () => {
		const facade = createFacade({ places: [createPlace()] });
		const search = createGooglePlaceTextSearch(facade);

		await expect(search.search('Bletchley Park', bounds)).resolves.toEqual({
			status: 'matches',
			places: [
				{
					id: 'place-1',
					name: 'Bletchley Park',
					address: 'Sherwood Drive, Bletchley',
					coordinate: { lat: 51.997, lon: -0.74 },
				},
			],
		});
		expect(facade.searchByText).toHaveBeenCalledWith({
			textQuery: 'Bletchley Park',
			fields: ['id', 'displayName', 'formattedAddress', 'location'],
			locationRestriction: bounds,
			maxResultCount: 6,
		});
	});

	it('returns not_found for an empty provider result', async () => {
		const search = createGooglePlaceTextSearch(createFacade({ places: [] }));

		await expect(search.search('Bletchley Park', bounds)).resolves.toEqual({
			status: 'not_found',
			places: [],
		});
	});

	it('deduplicates provider IDs and excludes places outside the restriction', async () => {
		const search = createGooglePlaceTextSearch(
			createFacade({
				places: [
					createPlace(),
					createPlace({ displayName: 'Duplicate', location: { lat: 52, lng: -0.7 } }),
					createPlace({ id: 'outside', location: { lat: 52.2, lng: -0.7 } }),
				],
			}),
		);

		await expect(search.search('Bletchley Park', bounds)).resolves.toEqual({
			status: 'matches',
			places: [
				{
					id: 'place-1',
					name: 'Bletchley Park',
					address: 'Sherwood Drive, Bletchley',
					coordinate: { lat: 51.997, lon: -0.74 },
				},
			],
		});
	});

	it('retains five options and reports incomplete when the provider returns more than five', async () => {
		const places = Array.from({ length: 6 }, (_, index) =>
			createPlace({
				id: `place-${index}`,
				displayName: `Place ${index}`,
				location: { lat: 51.95 + index / 100, lng: -0.85 + index / 100 },
			}),
		);
		const search = createGooglePlaceTextSearch(createFacade({ places }));

		const result = await search.search('places', bounds);

		expect(result.status).toBe('incomplete');
		expect(result.places).toHaveLength(5);
		expect(result.places.map(({ id }) => id)).toEqual([
			'place-0',
			'place-1',
			'place-2',
			'place-3',
			'place-4',
		]);
	});

	it('rejects empty and overlong queries without calling the provider', async () => {
		const facade = createFacade({ places: [] });
		const search = createGooglePlaceTextSearch(facade);

		await expect(search.search('', bounds)).resolves.toEqual({ status: 'unavailable', places: [] });
		await expect(search.search('x'.repeat(201), bounds)).resolves.toEqual({
			status: 'unavailable',
			places: [],
		});
		expect(facade.searchByText).not.toHaveBeenCalled();
	});

	it('maps provider errors to a generic unavailable result', async () => {
		const facade = {
			searchByText: vi.fn(async () => {
				throw new Error('provider details must stay private');
			}),
		};
		const search = createGooglePlaceTextSearch(facade);

		await expect(search.search('Bletchley Park', bounds)).resolves.toEqual({
			status: 'unavailable',
			places: [],
		});
	});

	it('does not turn missing identity or coordinates into a false miss', async () => {
		const search = createGooglePlaceTextSearch(
			createFacade({ places: [createPlace({ id: undefined }), createPlace({ location: undefined })] }),
		);

		await expect(search.search('Bletchley Park', bounds)).resolves.toEqual({
			status: 'unavailable',
			places: [],
		});
	});

	it('accepts Google LatLng accessor functions and finite coordinates only', async () => {
		const search = createGooglePlaceTextSearch(
			createFacade({
				places: [
					createPlace({ location: { lat: () => 51.997, lng: () => -0.74 } }),
					createPlace({ id: 'invalid', location: { lat: () => Number.NaN, lng: () => -0.74 } }),
				],
			}),
		);

		await expect(search.search('Bletchley Park', bounds)).resolves.toEqual({
			status: 'unavailable',
			places: [],
		});
	});

	it('preserves the LatLng receiver when reading coordinate accessors', async () => {
		const location = {
			latitude: 51.997,
			longitude: -0.74,
			lat(this: { latitude: number }) { return this.latitude; },
			lng(this: { longitude: number }) { return this.longitude; },
		};
		const search = createGooglePlaceTextSearch(createFacade({ places: [createPlace({ location })] }));

		await expect(search.search('Bletchley Park', bounds)).resolves.toMatchObject({
			status: 'matches',
			places: [{ coordinate: { lat: 51.997, lon: -0.74 } }],
		});
	});

	it('bounds malicious result processing and retained provider fields', async () => {
		const places = Array.from({ length: 10_000 }, (_, index) =>
			createPlace({ id: `place-${index}`, location: { lat: 52, lng: -0.7 } }),
		);
		places[0] = createPlace({ id: 'x'.repeat(257) });
		const facade = createFacade({ places });
		const search = createGooglePlaceTextSearch(facade);

		const result = await search.search('Bletchley Park', bounds);
		expect(result.status).toBe('incomplete');
		expect(result.places).toHaveLength(5);
		expect(result.places.map(({ id }) => id)).toEqual([
			'place-1', 'place-2', 'place-3', 'place-4', 'place-5',
		]);
	});
});
