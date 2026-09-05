import { expect, test, type Page, type Route } from '@playwright/test';

const revision = 'fixture-revision';

function journey(totalKm: number, days: number) {
  return {
    route: {
      start: 'Origin base',
      end: 'Origin base',
      is_ring: false,
      legs: [{
        from_place: 'Origin base', to_place: 'Turnaround', distance_km: totalKm,
        locks: 2, est_minutes: 120, flagged_unknown_dims: false,
      }],
      days: Array.from({ length: days }, (_, index) => ({
        day: index + 1, legs: [], end_near: index + 1 === days ? 'Origin base' : 'Turnaround', cruising_minutes: 120,
      })),
      total_km: totalKm,
      total_locks: 2,
      total_minutes: days * 120,
      amenities: [], warnings: [], access_segments: [], graph_source_date: 'fixture-date',
    },
    geometry: {
      type: 'LineString' as const,
      coordinates: [[-1, 51], [-1.2 - totalKm / 100, 51.1], [-1, 51]],
    },
    day_geometries: Array.from({ length: days }, (_, index) => ({
      day: index + 1,
      geometry: { type: 'LineString' as const, coordinates: [[-1, 51], [-1.2 - (index + 1) / 100, 51.1]] },
      start: { lat: 51, lon: -1 }, end: { lat: 51.1, lon: -1.2 - (index + 1) / 100 },
    })),
    locks: [],
  };
}

const routes = [
  {
    journey_type: 'out_and_back' as const,
    artifact_revision: revision,
    request_id: 'fixture-request',
    route_id: 'branch-left',
    branch_choices: [{ junction_uid: 100, next_uid: 101, junction_name: 'First junction', continuation_name: 'Left branch' }],
    turnaround: {
      turnaround_id: 'fixture:turnaround', kind: 'winding_hole' as const, node_uid: 101,
      coordinate: { lat: 51.1, lon: -1.3 }, display_name: 'Same winding hole',
      eligibility_basis: 'mapped_winding_hole' as const,
      sources: [{ source: 'fixture', attribution: 'Fixture data' }], turning_limits: { length_m: 22 },
    },
    outbound_distance_km: 10,
    selection_basis: 'furthest_reachable' as const,
    budget: { available_minutes: 1080, used_minutes: 240, remaining_minutes: 840, days_used: 1 },
    journey: journey(20, 1),
  },
  {
    journey_type: 'out_and_back' as const,
    artifact_revision: revision,
    request_id: 'fixture-request',
    route_id: 'branch-right',
    branch_choices: [{ junction_uid: 100, next_uid: 102, junction_name: 'First junction', continuation_name: 'Right branch' }],
    turnaround: {
      turnaround_id: 'fixture:turnaround', kind: 'winding_hole' as const, node_uid: 102,
      coordinate: { lat: 51.1, lon: -1.3 }, display_name: 'Same winding hole',
      eligibility_basis: 'mapped_winding_hole' as const,
      sources: [{ source: 'fixture', attribution: 'Fixture data' }], turning_limits: { length_m: 22 },
    },
    outbound_distance_km: 7,
    selection_basis: 'furthest_reachable' as const,
    budget: { available_minutes: 1080, used_minutes: 360, remaining_minutes: 720, days_used: 2 },
    journey: journey(14, 2),
  },
];

async function fakeGoogleScript(route: Route) {
  const url = new URL(route.request().url());
  const callback = url.searchParams.get('callback');
  if (!callback) throw new Error('Google fixture request did not include a callback');
  const script = `(() => {
    class FakeMap {
      constructor(element) { this.element = element; this.listeners = {}; }
      addListener(name, callback) { (this.listeners[name] ||= []).push(callback); return { remove: () => {} }; }
      getBounds() { return { toJSON: () => ({ south: 50, west: -2, north: 53, east: 0 }) }; }
      fitBounds() {}
    }
    class FakePolyline { constructor(options) { this.options = options; } setMap(map) { this.map = map; } }
    class FakeInfoWindow { setContent() {} open() {} close() {} addListener() { return { remove: () => {} }; } }
    class FakeMarker {
      constructor(options) { this.map = options.map || null; this.listeners = {}; }
      addEventListener(name, callback) { (this.listeners[name] ||= []).push(callback); }
      removeEventListener() {}
    }
    class FakeAutocomplete extends HTMLElement {
      constructor() { super(); this.append(document.createElement('input')); }
    }
    if (!customElements.get('gmp-place-autocomplete')) customElements.define('gmp-place-autocomplete', FakeAutocomplete);
    window.google = { maps: { importLibrary: async (name) => {
      if (name === 'maps') return { Map: FakeMap, Polyline: FakePolyline, InfoWindow: FakeInfoWindow };
      if (name === 'marker') return { AdvancedMarkerElement: FakeMarker };
      if (name === 'places') return { PlaceAutocompleteElement: FakeAutocomplete };
      if (name === 'routes') return {
        RouteMatrix: { computeRouteMatrix: async (request) => ({ matrix: { rows: [{ items: request.destinations.map((_, index) => ({ destinationIndex: index, condition: 'OK', durationMillis: 600000, distanceMeters: 2500 })) }] } }) },
        Route: { computeRoutes: async () => ({ routes: [{ path: [{ lat: 51, lng: -1 }, { lat: 51.1, lng: -1.2 }], durationMillis: 600000, distanceMeters: 2500 }] }) },
      };
      throw new Error('Unknown fixture library ' + name);
    } } };
    window[${JSON.stringify(callback)}]();
  })();`;
  await route.fulfill({ status: 200, contentType: 'application/javascript', body: script });
}

async function installFixtures(page: Page) {
  const discoveryRequests: Array<Record<string, unknown>> = [];
  await page.route('https://maps.googleapis.com/maps/api/js**', fakeGoogleScript);
  await page.route('**/api/health', (route) => route.fulfill({ json: { status: 'healthy', artifact_revision: revision, places_status: 'available' } }));
  await page.route('**/api/canal-network', (route) => route.fulfill({ json: { artifact_revision: revision, lines: [], bases: [] } }));
  await page.route('**/api/canal-candidates', (route) => route.fulfill({ json: {
    artifact_revision: revision,
    candidates: [{ uid: route.request().postDataJSON().lat < 52 ? 10 : 20, artifact_revision: revision, coordinate: { lat: 51.1, lon: -1.3 }, straight_line_distance_m: 100, display_name: 'Fixture canal access' }],
  } }));
  await page.route('**/api/turnaround-candidates', (route) => {
    discoveryRequests.push(route.request().postDataJSON());
    return route.fulfill({ json: { artifact_revision: revision, request_id: 'fixture-request', default_route_id: 'branch-left', routes, rejections: [] } });
  });
  await page.route('**/api/places', (route) => route.fulfill({ json: { places: [] } }));
  return discoveryRequests;
}

async function selectPlace(page: Page, index: number, name: string) {
  const autocomplete = page.locator('gmp-place-autocomplete').nth(index);
  await autocomplete.locator('input').fill(name);
  await autocomplete.evaluate((element, value) => {
    const placePrediction = {
      toPlace: () => ({ displayName: value, formattedAddress: `${value} address`, location: { lat: 51, lng: -1 }, fetchFields: async () => {} }),
    };
    const event = new Event('gmp-select');
    Object.defineProperty(event, 'placePrediction', { value: placePrediction });
    element.dispatchEvent(event);
  }, name);
}

async function openOutAndBack(page: Page) {
  await page.goto('/');
  await page.getByRole('radio', { name: 'Out-and-back' }).check();
  await selectPlace(page, 0, 'Fixture origin');
  await expect(page.getByRole('region', { name: /^origin$/i }).getByRole('radio')).toHaveCount(1);
}

test('origin-only out-and-back submits a null waypoint', async ({ page }) => {
  const requests = await installFixtures(page);
  await openOutAndBack(page);
  await page.getByRole('button', { name: 'Plan out-and-back journey' }).click();
  await expect(page.getByRole('region', { name: 'Out-and-back routes' })).toBeVisible();
  expect(requests[0]).toMatchObject({ artifact_revision: revision, start_uid: 10, waypoint_uid: null, days: 7, hours_per_day: 6 });
  await expect(page.getByText('Destination transfer')).toHaveCount(0);
  await expect(page.getByText(/returns to the origin/i)).toBeVisible();
});

test('keeps same-turnaround branch routes distinct and swaps the selected journey/day geometry', async ({ page }) => {
  await installFixtures(page);
  await openOutAndBack(page);
  await selectPlace(page, 1, 'Fixture waypoint');
  await expect(page.getByRole('region', { name: /visit on the way/i }).getByRole('radio')).toHaveCount(1);
  await page.getByRole('button', { name: 'Plan out-and-back journey' }).click();

  const summary = page.getByRole('region', { name: 'Trip summary' });
  const options = page.getByRole('region', { name: 'Out-and-back routes' }).getByRole('button');
  await expect(options).toHaveCount(2);
  await expect(options.nth(0)).toContainText('Same winding hole');
  await expect(options.nth(1)).toContainText('Right branch');
  await expect(options.nth(1)).not.toContainText('100');
  await options.nth(1).click();
  await expect(summary.getByText('14 km canal')).toBeVisible();
  await expect(summary.getByRole('button', { name: /Day 2/i })).toBeVisible();
  await summary.getByRole('button', { name: /Day 2/i }).click();
  await expect(summary.getByRole('button', { name: /Day 2/i })).toHaveAttribute('aria-pressed', 'true');
});

test('constraint edits invalidate the displayed out-and-back route and branch selection', async ({ page }) => {
  await installFixtures(page);
  await openOutAndBack(page);
  await page.getByRole('button', { name: 'Plan out-and-back journey' }).click();
  await expect(page.getByRole('region', { name: 'Out-and-back routes' })).toBeVisible();
  await page.getByLabel('Days').fill('8');
  await expect(page.getByRole('region', { name: 'Out-and-back routes' })).toHaveCount(0);
  await expect(page.getByText(/km canal/i)).toHaveCount(0);
});
