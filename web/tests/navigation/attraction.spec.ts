import { expect, test, type Page } from '@playwright/test';

type Json = Record<string, unknown>;

async function fulfillJson(route: Parameters<Parameters<Page['route']>[1]>[0], body: Json) {
  await route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });
}

async function mockSession(page: Page, sessionId: string, token: string) {
  await page.route('**/api/place-sessions', async (route) => {
    if (route.request().method() === 'POST') {
      await fulfillJson(route, { session_id: sessionId, token, expires_in: 600 });
      return;
    }
    await route.fallback();
  });

  await page.route(`**/api/place-sessions/${sessionId}`, async (route) => {
    if (route.request().method() === 'DELETE') {
      await fulfillJson(route, { status: 'cancelled' });
      return;
    }
    await route.fallback();
  });
}

test('resolves duplicate attractions, keeps canal access separate, and resets cleanly', async ({ page }) => {
  const selectBodies: Json[] = [];
  let taskRequests = 0;

  page.on('request', (request) => {
    if (/\/tasks\//.test(request.url())) taskRequests += 1;
  });

  await mockSession(page, 'session-1', 'token-1');
  await page.route('**/api/place-sessions/session-1/resolve', async (route) => {
    await fulfillJson(route, {
      run_id: 'run-1',
      status: 'ambiguous',
      osm: {
        status: 'ambiguous',
        options: [
          {
            option_ref: 'osm:node:1',
            name: 'Bletchley Park',
            locality: 'Milton Keynes',
            coordinate: { lat: 51.9977, lon: -0.7401 },
            source: 'osm',
          },
          {
            option_ref: 'osm:node:2',
            name: 'Bletchley Park',
            locality: 'Bletchley',
            coordinate: { lat: 51.9982, lon: -0.7412 },
            source: 'osm',
          },
        ],
      },
    });
  });
  await page.route('**/api/place-sessions/session-1/select', async (route) => {
    selectBodies.push(route.request().postDataJSON() as Json);
    await fulfillJson(route, {
      run_id: 'run-1',
      status: 'unavailable',
      reason: 'no_access_candidates',
    });
  });

  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Visit an attraction' })).toBeVisible();

  await page.getByLabel('Attraction name').fill('Bletchley Park');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Bletchley Park', exact: true })).toHaveCount(2);
  await expect(page.getByText('Choose an attraction from the matching places.')).toBeVisible();

  await page.getByRole('button', { name: 'Bletchley Park', exact: true }).nth(1).click();
  await expect.poll(() => selectBodies.length).toBe(1);
  expect(selectBodies[0]).toEqual({ run_id: 'run-1', option_ref: 'osm:node:2' });

  await expect(page.getByRole('heading', { name: 'Selected attraction' })).toBeVisible();
  await expect(page.getByText('Bletchley', { exact: true })).toBeVisible();
  await expect(page.getByText('No canal access alternatives are available yet.')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Origin', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Destination', exact: true })).toBeVisible();
  expect(taskRequests).toBe(0);

  await page.getByRole('button', { name: 'Reset trip', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Selected attraction' })).toHaveCount(0);
});

test('manual coordinates use the manual endpoint without inventing an attraction name', async ({ page }) => {
  const manualBodies: Json[] = [];
  let taskRequests = 0;

  page.on('request', (request) => {
    if (/\/tasks\//.test(request.url())) taskRequests += 1;
  });

  await mockSession(page, 'session-2', 'token-2');
  await page.route('**/api/place-sessions/session-2/resolve', async (route) => {
    await fulfillJson(route, {
      run_id: 'run-manual-1',
      status: 'not_found',
      osm: { status: 'not_found', options: [] },
    });
  });
  await page.route('**/api/place-sessions/session-2/manual', async (route) => {
    manualBodies.push(route.request().postDataJSON() as Json);
    await fulfillJson(route, {
      run_id: 'run-manual-2',
      status: 'unavailable',
      reason: 'no_access_candidates',
    });
  });

  await page.goto('/');
  await page.getByLabel('Attraction name').fill('A place with no catalog match');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Use coordinates', exact: true })).toBeVisible();

  await page.getByLabel('Latitude').fill('52.001');
  await page.getByLabel('Longitude').fill('-0.742');
  await page.getByRole('button', { name: 'Use coordinates', exact: true }).click();

  await expect.poll(() => manualBodies.length).toBe(1);
  expect(manualBodies[0]).toMatchObject({ coordinate: { lat: 52.001, lon: -0.742 } });
  expect(manualBodies[0]).not.toHaveProperty('name');
  await expect(page.getByRole('heading', { name: 'Selected attraction' })).toBeVisible();
  await expect(page.getByText('Selected coordinates', { exact: true })).toBeVisible();
  await expect(page.getByText('No canal access alternatives are available yet.')).toBeVisible();
  expect(taskRequests).toBe(0);
});
