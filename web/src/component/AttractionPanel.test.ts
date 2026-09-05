import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { expect, it, vi } from 'vitest';

import type { PlaceController } from '../lib/places/controller';
import AttractionPanel from './AttractionPanel.svelte';

type Choice = {
	option_ref: string;
	source: 'osm' | 'google';
	name: string;
	locality: string | null;
	address?: string;
};

type Transfer =
	| { available: true; durationSeconds: number; distanceMeters: number }
	| { available: false; reason: string };

type Access = {
	candidate: { candidate_id: string; display_name: string };
	outward: Transfer;
	return: Transfer;
	complete: boolean;
};

type WalkingRoutes = Awaited<ReturnType<PlaceController['walkingRoutes']>>;

type State = {
	status: string;
	options: Choice[];
	selected: Choice | null;
	access: Access[];
	error: string;
};

function choice(overrides: Partial<Choice> = {}): Choice {
	return {
		option_ref: 'osm:node:1',
		source: 'osm',
		name: 'Bletchley Park',
		locality: 'Milton Keynes',
		...overrides,
	};
}

function access(overrides: Partial<Access> = {}): Access {
	return {
		candidate: { candidate_id: 'canal-1', display_name: 'Fenny Stratford landing' },
		outward: { available: true, durationSeconds: 600, distanceMeters: 800 },
		return: { available: true, durationSeconds: 720, distanceMeters: 900 },
		complete: true,
		...overrides,
	};
}

function controller(initial: State) {
	let state = initial;
	let listener: ((next: State) => void) | undefined;
	const value = {
		subscribe: vi.fn((next: (next: State) => void) => {
			listener = next;
			next(state);
			return vi.fn();
		}),
		search: vi.fn(),
		searchGoogle: vi.fn(),
		select: vi.fn(),
		selectManual: vi.fn(),
		destroy: vi.fn(),
		cancel: vi.fn(() => {
			state = { status: 'idle', options: [], selected: null, access: [], error: '' };
			listener?.(state);
		}),
		walkingRoutes: vi.fn(async () => ({
			outward: { path: [], durationSeconds: 600, distanceMeters: 800 },
			return: { path: [], durationSeconds: 720, distanceMeters: 900 },
		})),
		publish(next: State) {
			state = next;
			listener?.(state);
		},
	};
	return value;
}

it('shows ambiguous OSM choices and selects the user-chosen option', async () => {
	const fake = controller({
		status: 'ambiguous',
		options: [choice(), choice({ option_ref: 'osm:way:2', name: 'Bletchley Park Museum' })],
		selected: null,
		access: [],
		error: '',
	});

	render(AttractionPanel, { props: { controller: fake as unknown as PlaceController } });

	expect(screen.getByRole('heading', { name: 'Visit an attraction' })).toBeInTheDocument();
	expect(screen.getByLabelText('Attraction name')).toHaveAttribute('maxlength', '200');
	expect(screen.getByText(/choose an attraction/i)).toBeInTheDocument();
	expect(screen.getAllByText('OpenStreetMap')).not.toHaveLength(0);
	await fireEvent.click(screen.getByRole('button', { name: 'Bletchley Park Museum' }));
	expect(fake.select).toHaveBeenCalledWith('osm:way:2');
});

it('offers Google fallback and labels Google choices with attribution', async () => {
	const fake = controller({
		status: 'not_found',
		options: [choice({ option_ref: 'google:abc', source: 'google', name: 'Bletchley Park visitor centre', locality: null })],
		selected: null,
		access: [],
		error: '',
	});

	render(AttractionPanel, { props: { controller: fake as unknown as PlaceController } });

	await fireEvent.click(screen.getByRole('button', { name: 'Search Google' }));
	expect(fake.searchGoogle).toHaveBeenCalledOnce();
	expect(screen.getAllByText('Google Maps')).not.toHaveLength(0);
	expect(screen.getByRole('link', { name: 'Google Maps' })).toHaveAttribute('href', expect.stringContaining('google.com/maps'));
});

it('distinguishes same-name Google choices by address', async () => {
	const fake = controller({
		status: 'ambiguous',
		options: [
			choice({ option_ref: 'google:one', source: 'google', address: '1 Museum Way' }),
			choice({ option_ref: 'google:two', source: 'google', address: '2 Museum Way' }),
		],
		selected: null,
		access: [],
		error: '',
	});

	render(AttractionPanel, { props: { controller: fake as unknown as PlaceController } });

	expect(screen.getByRole('button', { name: 'Bletchley Park, 1 Museum Way' })).toBeInTheDocument();
	expect(screen.getByRole('button', { name: 'Bletchley Park, 2 Museum Way' })).toBeInTheDocument();
	expect(screen.getByText('1 Museum Way')).toBeInTheDocument();
	expect(screen.getByText('2 Museum Way')).toBeInTheDocument();

	fake.publish({
		status: 'resolved',
		options: [],
		selected: choice({ option_ref: 'google:two', source: 'google', address: '2 Museum Way' }),
		access: [],
		error: '',
	});
	await waitFor(() => expect(screen.getByText('2 Museum Way')).toBeInTheDocument());
});

it('accepts explicit coordinates as a manual fallback', async () => {
	const fake = controller({ status: 'unavailable', options: [], selected: null, access: [], error: '' });
	render(AttractionPanel, { props: { controller: fake as unknown as PlaceController } });

	await fireEvent.input(screen.getByLabelText('Latitude'), { target: { value: '52.001' } });
	await fireEvent.input(screen.getByLabelText('Longitude'), { target: { value: '-0.742' } });
	await fireEvent.click(screen.getByRole('button', { name: 'Use coordinates' }));

	expect(fake.selectManual).toHaveBeenCalledWith({ lat: 52.001, lon: -0.742 });
});

it('rejects empty and whitespace-only coordinates before numeric coercion', async () => {
	const fake = controller({ status: 'unavailable', options: [], selected: null, access: [], error: '' });
	render(AttractionPanel, { props: { controller: fake as unknown as PlaceController } });

	await fireEvent.input(screen.getByLabelText('Latitude'), { target: { value: '   ' } });
	await fireEvent.input(screen.getByLabelText('Longitude'), { target: { value: '\t' } });
	await fireEvent.click(screen.getByRole('button', { name: 'Use coordinates' }));

	expect(fake.selectManual).not.toHaveBeenCalled();
	expect(screen.getByText('Latitude must be between -90 and 90.')).toBeInTheDocument();
});

it('shows both directions for incomplete walking access without offering preview', () => {
	const fake = controller({
		status: 'resolved',
		options: [],
		selected: choice(),
		access: [access({
			outward: { available: false, reason: 'TIMEOUT' },
			complete: false,
		})],
		error: '',
	});

	render(AttractionPanel, { props: { controller: fake as unknown as PlaceController } });

	expect(screen.getByText(/to attraction: unavailable/i)).toBeInTheDocument();
	expect(screen.getByText(/return walk: 12 minutes/i)).toBeInTheDocument();
	expect(screen.queryByRole('button', { name: /preview walk/i })).not.toBeInTheDocument();
	expect(screen.getByText(/do not confirm canal access/i)).toBeInTheDocument();
	expect(screen.getByRole('link', { name: 'Google Maps' })).toHaveAttribute('href', expect.stringContaining('google.com/maps'));
});

it('uses generic lookup and walking status messages', async () => {
	const fake = controller({ status: 'unavailable', options: [], selected: null, access: [], error: '' });
	render(AttractionPanel, { props: { controller: fake as unknown as PlaceController } });

	expect(screen.getByText('Place lookup is unavailable.')).toBeInTheDocument();
	fake.publish({ status: 'not_found', options: [], selected: null, access: [], error: '' });
	await waitFor(() => expect(screen.getByText('No matching attraction was found.')).toBeInTheDocument());
	fake.publish({ status: 'walking', options: [], selected: choice(), access: [], error: '' });
	await waitFor(() => expect(screen.getByText('Checking walking access…')).toBeInTheDocument());
});

it('requires access confirmation before previewing a complete walk', async () => {
	const onPreview = vi.fn();
	const fake = controller({
		status: 'resolved',
		options: [],
		selected: choice(),
		access: [access()],
		error: '',
	});

	render(AttractionPanel, { props: { controller: fake as unknown as PlaceController, onPreview } });

	const preview = screen.getByRole('button', { name: 'Preview walk' });
	expect(preview).toBeDisabled();
	await fireEvent.click(preview);
	expect(fake.walkingRoutes).not.toHaveBeenCalled();

	await fireEvent.click(screen.getByLabelText('I understand canal access and mooring are unconfirmed'));
	expect(preview).not.toBeDisabled();
	await fireEvent.click(preview);
	await waitFor(() => expect(fake.walkingRoutes).toHaveBeenCalledWith('canal-1', true));
	await waitFor(() => expect(onPreview).toHaveBeenCalledOnce());
});

it('resets confirmation and suppresses stale preview results and abort errors', async () => {
	const onPreview = vi.fn();
	const onClearPreview = vi.fn();
	const fake = controller({
		status: 'resolved',
		options: [],
		selected: choice(),
		access: [access()],
		error: '',
	});
	let resolveWalk!: (value: WalkingRoutes) => void;
	const pendingRoutes = new Promise<WalkingRoutes>((resolve) => { resolveWalk = resolve; });
	fake.walkingRoutes.mockImplementationOnce(() => pendingRoutes as ReturnType<typeof fake.walkingRoutes>);

	render(AttractionPanel, { props: { controller: fake as unknown as PlaceController, onPreview, onClearPreview } });
	await fireEvent.click(screen.getByLabelText('I understand canal access and mooring are unconfirmed'));
	await fireEvent.click(screen.getByRole('button', { name: 'Preview walk' }));
	await waitFor(() => expect(fake.walkingRoutes).toHaveBeenCalledWith('canal-1', true));

	fake.publish({
		status: 'resolved',
		options: [],
		selected: choice({ option_ref: 'osm:node:2', name: 'Other Park' }),
		access: [access()],
		error: '',
	});
	await waitFor(() => expect(screen.getByRole('button', { name: 'Preview walk' })).toBeDisabled());
	resolveWalk({
		outward: { path: [], durationSeconds: 600, distanceMeters: 800 },
		return: { path: [], durationSeconds: 720, distanceMeters: 900 },
	});
	await new Promise((resolve) => setTimeout(resolve, 0));
	expect(onPreview).not.toHaveBeenCalled();
	expect(onClearPreview).toHaveBeenCalled();

	fake.walkingRoutes.mockRejectedValueOnce(new DOMException('aborted', 'AbortError'));
	await fireEvent.click(screen.getByLabelText('I understand canal access and mooring are unconfirmed'));
	await fireEvent.click(screen.getByRole('button', { name: 'Preview walk' }));
	await waitFor(() => expect(fake.walkingRoutes).toHaveBeenCalledTimes(2));
	fake.cancel();
	await new Promise((resolve) => setTimeout(resolve, 0));
	expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

it('clears previews for a new search and on component unmount', async () => {
	const onClearPreview = vi.fn();
	const fake = controller({ status: 'resolved', options: [], selected: choice(), access: [], error: '' });
	const rendered = render(AttractionPanel, { props: { controller: fake as unknown as PlaceController, onClearPreview } });

	await fireEvent.input(screen.getByLabelText('Attraction name'), { target: { value: 'New place' } });
	await fireEvent.click(screen.getByRole('button', { name: 'Search' }));
	expect(onClearPreview).toHaveBeenCalledOnce();

	rendered.unmount();
	expect(onClearPreview).toHaveBeenCalledTimes(2);
});

it('clears the form and selected attraction on cancel', async () => {
	const fake = controller({ status: 'resolved', options: [], selected: choice(), access: [], error: '' });
	render(AttractionPanel, { props: { controller: fake as unknown as PlaceController } });

	await fireEvent.click(screen.getByRole('button', { name: 'Clear attraction' }));

	expect(fake.cancel).toHaveBeenCalledOnce();
	await waitFor(() => expect(screen.queryByText('Bletchley Park')).not.toBeInTheDocument());
});
