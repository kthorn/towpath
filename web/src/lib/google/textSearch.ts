import type { LatLon, MapBounds } from '../types';

const FIELDS = ['id', 'displayName', 'formattedAddress', 'location'];
const MAX_OPTIONS = 5;
const PROVIDER_RESULT_CAP = MAX_OPTIONS + 1;
const MAX_PROVIDER_ID_LENGTH = 256;
const MAX_PROVIDER_TEXT_LENGTH = 512;

export interface BrowserPlace {
	id: string;
	name: string;
	address: string;
	coordinate: LatLon;
}

export interface PlaceTextSearch {
	search(
		query: string,
		bounds: MapBounds,
	): Promise<{
		status: 'matches' | 'not_found' | 'unavailable' | 'incomplete';
		places: BrowserPlace[];
	}>;
}

interface TextSearchRequest {
	textQuery: string;
	fields: string[];
	locationRestriction: MapBounds;
	maxResultCount: number;
}

export interface TextSearchResponse {
	places?: unknown[];
}

export interface TextSearchFacade {
	searchByText(request: TextSearchRequest): Promise<TextSearchResponse>;
}

function readCoordinate(value: unknown, receiver: object): number | undefined {
	if (typeof value === 'number') return value;
	if (typeof value !== 'function') return undefined;
	try {
		const result = value.call(receiver);
		return typeof result === 'number' ? result : undefined;
	} catch {
		return undefined;
	}
}

function validBounds(bounds: MapBounds): boolean {
	return (
		Number.isFinite(bounds.south) &&
		Number.isFinite(bounds.west) &&
		Number.isFinite(bounds.north) &&
		Number.isFinite(bounds.east) &&
		bounds.south >= -90 &&
		bounds.south <= 90 &&
		bounds.north >= -90 &&
		bounds.north <= 90 &&
		bounds.west >= -180 &&
		bounds.west <= 180 &&
		bounds.east >= -180 &&
		bounds.east <= 180 &&
		bounds.south <= bounds.north
	);
}

function inBounds(coordinate: LatLon, bounds: MapBounds): boolean {
	const longitudeInBounds =
		bounds.west <= bounds.east
			? coordinate.lon >= bounds.west && coordinate.lon <= bounds.east
			: coordinate.lon >= bounds.west || coordinate.lon <= bounds.east;
	return (
		coordinate.lat >= bounds.south &&
		coordinate.lat <= bounds.north &&
		longitudeInBounds
	);
}

function parsePlace(value: unknown): BrowserPlace | undefined {
	if (!value || typeof value !== 'object') return undefined;
	const place = value as {
		id?: unknown;
		displayName?: unknown;
		formattedAddress?: unknown;
		location?: unknown;
	};
	if (typeof place.id !== 'string' || place.id.trim().length === 0) return undefined;
	if (!place.location || typeof place.location !== 'object') return undefined;
	const location = place.location as { lat?: unknown; lng?: unknown };
	const lat = readCoordinate(location.lat, location);
	const lon = readCoordinate(location.lng, location);
	if (
		lat === undefined ||
		lon === undefined ||
		!Number.isFinite(lat) ||
		!Number.isFinite(lon) ||
		lat < -90 ||
		lat > 90 ||
		lon < -180 ||
		lon > 180
	) {
		return undefined;
	}
	if (
		place.id.length > MAX_PROVIDER_ID_LENGTH ||
		(typeof place.displayName === 'string' && place.displayName.length > MAX_PROVIDER_TEXT_LENGTH) ||
		(typeof place.formattedAddress === 'string' && place.formattedAddress.length > MAX_PROVIDER_TEXT_LENGTH)
	) {
		return undefined;
	}
	const name = typeof place.displayName === 'string' ? place.displayName : '';
	const address = typeof place.formattedAddress === 'string' ? place.formattedAddress : '';
	return { id: place.id, name, address, coordinate: { lat, lon } };
}

function unavailable(): Awaited<ReturnType<PlaceTextSearch['search']>> {
	return { status: 'unavailable', places: [] };
}

export function createGooglePlaceTextSearch(places: TextSearchFacade): PlaceTextSearch {
	return {
		async search(query, bounds) {
			if (
				typeof query !== 'string' ||
				query.trim().length === 0 ||
				query.length > 200 ||
				!validBounds(bounds)
			) {
				return unavailable();
			}

			let response: TextSearchResponse;
			try {
				response = await places.searchByText({
					textQuery: query,
					fields: FIELDS,
					locationRestriction: { ...bounds },
					maxResultCount: PROVIDER_RESULT_CAP,
				});
			} catch {
				return unavailable();
			}

			if (!response || !Array.isArray(response.places)) return unavailable();
			const incomplete = response.places.length > MAX_OPTIONS;
			const seen = new Set<string>();
			const parsed: BrowserPlace[] = [];
			let malformed = false;
			for (const value of response.places.slice(0, PROVIDER_RESULT_CAP)) {
				const place = parsePlace(value);
				if (!place) {
					malformed = true;
					continue;
				}
				if (!inBounds(place.coordinate, bounds) || seen.has(place.id)) continue;
				seen.add(place.id);
				if (parsed.length < MAX_OPTIONS) parsed.push(place);
			}

			if (malformed && !incomplete) return unavailable();
			if (!parsed.length) return { status: incomplete ? 'incomplete' : 'not_found', places: [] };
			return { status: incomplete ? 'incomplete' : 'matches', places: parsed };
		},
	};
}

export const createGoogleTextSearch = createGooglePlaceTextSearch;
