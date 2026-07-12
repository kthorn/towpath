import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { get, writable } from 'svelte/store';
import { describe, expect, it, vi } from 'vitest';

import App from '../App.svelte';
import type { AppDependencies } from '../lib/app';
import type { EndpointSlot, MapView, SelectedPlace } from '../lib/google/contracts';
import type { TripState, TripStore } from '../lib/stores/trip';
import { createTripStore } from '../lib/stores/trip';

const endpoint = (name: string, uid: number, unavailable = false) => ({
  place: { name, address: `${name} address`, coordinate: { lat: 51, lon: -1 } },
  candidates: [
    { candidate: { uid, artifact_revision: 'r1', coordinate: { lat: 51.1, lon: -1.1 }, straight_line_distance_m: 1250, display_name: `${name} Wharf` }, geometricIndex: 0, recommended: true, ...(unavailable ? { available: false as const, reason: 'ZERO_RESULTS' } : { available: true as const, durationSeconds: 600, distanceMeters: 2400 }) },
    { candidate: { uid: uid + 100, artifact_revision: 'r1', coordinate: { lat: 51.2, lon: -1.2 }, straight_line_distance_m: 1700, display_name: `${name} Alternative` }, geometricIndex: 1, recommended: false, available: true as const, durationSeconds: 900, distanceMeters: 3100 },
  ],
  selectedUid: uid, artifactRevision: 'r1', landRoute: unavailable ? null : { path: [], durationSeconds: 600, distanceMeters: 2400 },
  transferWarning: unavailable ? 'Could not verify a land transfer.' : null,
  requiresManualConfirmation: unavailable, confirmed: !unavailable, loading: false, error: null,
});

const route = {
  route: { start: 'A', end: 'B', is_ring: false, legs: [], days: [{ day: 1, legs: [], end_near: 'Braunston', cruising_minutes: 360 }], total_km: 21.4, total_locks: 7, total_minutes: 420, amenities: [], warnings: ['Low bridge clearance'], graph_source_date: 'today' },
  geometry: { type: 'LineString' as const, coordinates: [[-1, 51] as [number, number]] },
};

function setup(overrides: { unavailable?: boolean; mapReject?: boolean; sameNode?: boolean } = {}) {
  const state: TripState = { origin: endpoint('Bletchley Park', 1, overrides.unavailable), destination: endpoint('Canal Base', 2), canalRoute: overrides.sameNode ? { ...route, route: { ...route.route, start: 'A', end: 'A', total_km: 0, total_minutes: 0, total_locks: 0, days: [] } } : route, routeError: null, routing: false };
  const inner = writable(state);
  const calls: Array<{ slot: EndpointSlot; place: SelectedPlace | { lat: number; lon: number } }> = [];
  const store: TripStore = {
    subscribe: inner.subscribe,
    setEndpointCoordinate: vi.fn(async (slot, place) => { calls.push({ slot, place }); }),
    selectCandidate: vi.fn(async () => {}), confirmGeometricFallback: vi.fn(),
    planCanalRoute: vi.fn(async () => route), setMapView: vi.fn(),
  };
  const selects: Array<(place: SelectedPlace) => void> = [];
  const mapClick = { callback: (_coordinate: { lat: number; lon: number }) => {} };
  const map: MapView = { marker: vi.fn(), candidates: vi.fn(), land: vi.fn(), canal: vi.fn(), clearLand: vi.fn(), destroy: vi.fn(), onMapClick: vi.fn((callback) => { mapClick.callback = callback; return vi.fn(); }) };
  const dependencies: AppDependencies = {
    store,
    placeSearch: { attach: vi.fn((_input, onSelect) => { selects.push(onSelect); return vi.fn(); }) },
    loadMapView: overrides.mapReject ? vi.fn(async () => { throw new Error('SDK blocked'); }) : vi.fn(async () => map),
  };
  return { dependencies, store, selects, mapClick, calls };
}

describe('trip planning interface', () => {
  it('connects both place searches and map clicks to the active endpoint', async () => {
    const { dependencies, selects, mapClick, calls } = setup();
    render(App, { props: { dependencies } });
    await vi.waitFor(() => expect(selects).toHaveLength(2));
    selects[0]({ name: 'Museum', address: '', coordinate: { lat: 1, lon: 2 } });
    selects[1]({ name: 'Marina', address: '', coordinate: { lat: 3, lon: 4 } });
    await fireEvent.click(screen.getByRole('radio', { name: /set destination from map/i }));
    await vi.waitFor(() => expect(dependencies.loadMapView).toHaveBeenCalled());
    mapClick.callback({ lat: 5, lon: 6 });
    expect(calls).toEqual([
      { slot: 'origin', place: expect.objectContaining({ name: 'Museum' }) },
      { slot: 'destination', place: expect.objectContaining({ name: 'Marina' }) },
      { slot: 'destination', place: { lat: 5, lon: 6 } },
    ]);
  });

  it('shows candidate recommendation, metrics, unavailable reasons, and confirmation', async () => {
    const { dependencies, store } = setup({ unavailable: true });
    render(App, { props: { dependencies } });
    const origin = screen.getByRole('region', { name: /origin/i });
    expect(within(origin).getByText('Bletchley Park Wharf')).toBeVisible();
    expect(within(origin).getByText(/1.25 km straight line/i)).toBeVisible();
    expect(within(origin).getByText(/unavailable: zero results/i)).toBeVisible();
    expect(within(origin).getByText(/recommended/i)).toBeVisible();
    expect(within(origin).getByRole('alert')).toHaveTextContent(/could not verify/i);
    await fireEvent.click(within(origin).getByRole('button', { name: /confirm geometric/i }));
    expect(store.confirmGeometricFallback).toHaveBeenCalledWith('origin');
  });

  it('shows available transfer metrics and selects a candidate radio', async () => {
    const { dependencies, store } = setup();
    render(App, { props: { dependencies } });
    const origin = screen.getByRole('region', { name: /^origin$/i });
    expect(within(origin).getByText(/10 min.*2.40 km transfer/i)).toBeVisible();
    await fireEvent.click(within(origin).getByRole('radio', { name: /Bletchley Park Alternative/i }));
    expect(store.selectCandidate).toHaveBeenCalledWith('origin', 101);
  });

  it('submits exact controlled boat constraints', async () => {
    const { dependencies, store } = setup();
    render(App, { props: { dependencies } });
    await fireEvent.input(screen.getByLabelText(/^days/i), { target: { value: '4' } });
    await fireEvent.input(screen.getByLabelText(/hours per day/i), { target: { value: '7' } });
    await fireEvent.input(screen.getByLabelText(/boat length/i), { target: { value: '18.3' } });
    await fireEvent.input(screen.getByLabelText(/boat beam/i), { target: { value: '2.1' } });
    await fireEvent.click(screen.getByLabelText(/allow derelict/i));
    await fireEvent.click(screen.getByRole('button', { name: /plan canal route/i }));
    expect(store.planCanalRoute).toHaveBeenCalledWith({ days: 4, hours_per_day: 7, boat_length_m: 18.3, boat_beam_m: 2.1, boat_draft_m: null, boat_height_m: null, allow_derelict: true });
  });

  it.each(['', '0', '-2'])('blocks invalid hours per day %j', async (value) => {
    const { dependencies, store } = setup();
    render(App, { props: { dependencies } });
    await fireEvent.input(screen.getByLabelText(/hours per day/i), { target: { value } });
    await fireEvent.click(screen.getByRole('button', { name: /plan canal route/i }));
    expect(store.planCanalRoute).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent(/hours per day.*greater than 0/i);
  });

  it('blocks invalid optional numeric constraints', async () => {
    const { dependencies, store } = setup();
    render(App, { props: { dependencies } });
    await fireEvent.input(screen.getByLabelText(/boat beam/i), { target: { value: '-1' } });
    await fireEvent.click(screen.getByRole('button', { name: /plan canal route/i }));
    expect(store.planCanalRoute).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent(/boat beam.*greater than 0/i);
  });

  it('renders route metrics, transfers, warnings and days', () => {
    render(App, { props: { dependencies: setup().dependencies } });
    expect(screen.getByText(/21.4 km canal/i)).toBeVisible();
    expect(screen.getByText(/7 locks/i)).toBeVisible();
    expect(screen.getByText(/7 hr cruising/i)).toBeVisible();
    expect(screen.getByText(/low bridge clearance/i)).toBeVisible();
    expect(screen.getByText(/day 1/i)).toBeVisible();
    expect(screen.getAllByText(/10 min.*2.4 km/i)).toHaveLength(2);
  });

  it('uses the exact same-node label without empty day chrome', () => {
    render(App, { props: { dependencies: setup({ sameNode: true }).dependencies } });
    expect(screen.getByText('No canal travel required')).toBeVisible();
    expect(screen.queryByText(/day 1/i)).not.toBeInTheDocument();
  });

  it('does not use the same-node label for a rounded-zero route with legs', () => {
    const fixture = setup({ sameNode: true });
    const state = get(fixture.store);
    const inner = writable({ ...state, canalRoute: { ...state.canalRoute!, route: { ...state.canalRoute!.route, legs: [{ from_place: 'A', to_place: 'B', distance_km: 0, locks: 0, est_minutes: 1, flagged_unknown_dims: false }] } } });
    const store = { ...fixture.store, subscribe: inner.subscribe };
    render(App, { props: { dependencies: { ...fixture.dependencies, store } } });
    expect(screen.queryByText('No canal travel required')).not.toBeInTheDocument();
  });

  it('keeps candidates and planning usable when the map SDK rejects', async () => {
    const { dependencies, store } = setup({ mapReject: true });
    render(App, { props: { dependencies } });
    expect(await screen.findByRole('status')).toHaveTextContent(/map unavailable.*sdk blocked/i);
    expect(screen.getByText('Bletchley Park Wharf')).toBeVisible();
    await fireEvent.click(screen.getByRole('button', { name: /plan canal route/i }));
    expect(store.planCanalRoute).toHaveBeenCalled();
  });

  it('plans from empty state using manual coordinates when the shared SDK rejects', async () => {
    const candidate = (uid: number) => ({ uid, artifact_revision: 'r1', coordinate: { lat: 52, lon: -1 }, straight_line_distance_m: 100, display_name: `Canal node ${uid}` });
    const poundApi = {
      canalCandidates: vi.fn(async ({ lat }: { lat: number }) => ({ artifact_revision: 'r1', candidates: [candidate(lat < 52 ? 10 : 20)] })),
      canalRoute: vi.fn(async () => route),
    };
    const transferRouter = { matrix: vi.fn(async () => { throw new Error('SDK blocked'); }), route: vi.fn(async () => { throw new Error('SDK blocked'); }) };
    const store = createTripStore({ poundApi, transferRouter, transferMode: 'WALK' });
    const unavailable = vi.fn();
    const dependencies: AppDependencies = {
      store,
      placeSearch: { attach: vi.fn((_input, _select, onUnavailable) => { onUnavailable?.(new Error('SDK blocked')); return vi.fn(); }) },
      loadMapView: vi.fn(async () => { throw new Error('SDK blocked'); }),
    };
    render(App, { props: { dependencies } });
    expect(await screen.findAllByText(/place search unavailable.*sdk blocked/i)).toHaveLength(2);
    const origin = screen.getByRole('region', { name: /^origin$/i });
    await fireEvent.input(within(origin).getByLabelText(/origin latitude/i), { target: { value: '51.5' } });
    await fireEvent.input(within(origin).getByLabelText(/origin longitude/i), { target: { value: '-1.2' } });
    await fireEvent.click(within(origin).getByRole('button', { name: /use coordinates/i }));
    const destination = screen.getByRole('region', { name: /^destination$/i });
    await fireEvent.input(within(destination).getByLabelText(/destination latitude/i), { target: { value: '53' } });
    await fireEvent.input(within(destination).getByLabelText(/destination longitude/i), { target: { value: '-2' } });
    await fireEvent.click(within(destination).getByRole('button', { name: /use coordinates/i }));
    expect(await screen.findByText('Canal node 10')).toBeVisible();
    expect(await screen.findByText('Canal node 20')).toBeVisible();
    expect(await within(origin).findByText(/land route unavailable.*sdk blocked/i)).toBeVisible();
    expect(within(origin).getByText('Canal node 10')).toBeVisible();
    await fireEvent.click(within(origin).getByRole('button', { name: /confirm geometric/i }));
    await fireEvent.click(within(destination).getByRole('button', { name: /confirm geometric/i }));
    await fireEvent.click(screen.getByRole('button', { name: /plan canal route/i }));
    expect(poundApi.canalRoute).toHaveBeenCalledWith(expect.objectContaining({ start_uid: 10, end_uid: 20 }));
  });

  it('validates manual coordinate ranges', async () => {
    render(App, { props: { dependencies: setup().dependencies } });
    const origin = screen.getByRole('region', { name: /^origin$/i });
    await fireEvent.input(within(origin).getByLabelText(/origin latitude/i), { target: { value: '91' } });
    await fireEvent.input(within(origin).getByLabelText(/origin longitude/i), { target: { value: '-1' } });
    await fireEvent.click(within(origin).getByRole('button', { name: /use coordinates/i }));
    expect(within(origin).getByRole('alert')).toHaveTextContent(/latitude.*-90.*90/i);
  });

  it('cleans up both searches and the map on unmount', async () => {
    const fixture = setup();
    const detach = [vi.fn(), vi.fn()]; let index = 0;
    fixture.dependencies.placeSearch.attach = vi.fn((_input, _select) => detach[index++]);
    const removeClick = vi.fn(); const destroy = vi.fn();
    const view = { marker: vi.fn(), candidates: vi.fn(), land: vi.fn(), canal: vi.fn(), clearLand: vi.fn(), onMapClick: vi.fn(() => removeClick), destroy } as unknown as MapView;
    fixture.dependencies.loadMapView = vi.fn(async () => view);
    const rendered = render(App, { props: { dependencies: fixture.dependencies } });
    await vi.waitFor(() => expect(view.onMapClick).toHaveBeenCalled());
    rendered.unmount();
    expect(detach[0]).toHaveBeenCalled(); expect(detach[1]).toHaveBeenCalled();
    expect(removeClick).toHaveBeenCalled(); expect(destroy).toHaveBeenCalled();
  });

  it('ignores a map rejection that arrives after unmount', async () => {
    const fixture = setup();
    let reject!: (error: Error) => void;
    fixture.dependencies.loadMapView = vi.fn(() => new Promise<MapView>((_resolve, rejectPromise) => { reject = rejectPromise; }));
    const rendered = render(App, { props: { dependencies: fixture.dependencies } });
    rendered.unmount();
    vi.mocked(fixture.store.setMapView).mockClear();
    reject(new Error('late rejection'));
    await Promise.resolve();
    expect(fixture.store.setMapView).not.toHaveBeenCalled();
  });

  it('exposes the map canvas as a named region', () => {
    render(App, { props: { dependencies: setup().dependencies } });
    expect(screen.getByRole('region', { name: /journey map/i })).toBeVisible();
  });
});
