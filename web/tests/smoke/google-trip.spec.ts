import { expect, test } from '@playwright/test';

const prerequisitesPresent = process.env.GOOGLE_MAPS_SMOKE === '1'
  && Boolean(process.env.VITE_GOOGLE_MAPS_API_KEY)
  && Boolean(process.env.POUND_ARTIFACT_PATH);

async function selectPlace(page: import('@playwright/test').Page, label: RegExp, query: string) {
  const input = page.getByLabel(label);
  await input.fill(query);
  await page.getByRole('option').first().waitFor({
    state: 'visible',
    timeout: 20_000,
  });
  await input.press('ArrowDown');
  await input.press('Enter');
}

test.describe('live Google trip', () => {
  test.skip(!prerequisitesPresent, 'live, billable Google smoke test is explicitly opt-in');

  test('plans Bletchley Park to a searched Stoke Hammond rental base', async ({ page }) => {
    await page.goto('/');

    await selectPlace(page, /search origin/i, 'Bletchley Park');
    const origin = page.getByRole('region', { name: /^origin$/i });
    await expect(origin.getByRole('radio')).not.toHaveCount(0);

    await selectPlace(page, /search destination/i, 'Black Prince Holidays Stoke Hammond');
    const destination = page.getByRole('region', { name: /^destination$/i });
    await expect(destination.getByRole('radio')).not.toHaveCount(0);

    const alternatives = destination.getByRole('radio');
    expect(await alternatives.count()).toBeGreaterThan(1);
    await alternatives.nth(1).check();

    await page.getByRole('button', { name: /plan canal route/i }).click();
    const map = page.getByTestId('journey-map-canvas');
    await expect(map).toHaveAttribute('data-origin-land-overlay', 'visible');
    await expect(map).toHaveAttribute('data-destination-land-overlay', 'visible');
    await expect(map).toHaveAttribute('data-canal-overlay', 'visible');
    const summary = page.getByRole('region', { name: /trip summary/i });
    await expect(summary.getByText('Origin transfer').locator('..')).toContainText(/min|km/i);
    await expect(summary.getByText('Destination transfer').locator('..')).toContainText(/min|km/i);

    const sameNode = summary.getByText(/no canal travel required/i);
    if (await sameNode.isVisible()) {
      await expect(sameNode).toBeVisible();
    } else {
      await expect(summary.getByText(/km canal/i)).toBeVisible();
      await expect(summary.getByText(/locks/i)).toBeVisible();
      await expect(summary.getByText(/cruising/i)).toBeVisible();
      await expect(summary.getByText(/^Day 1$/i)).toBeVisible();
      const warnings = summary.locator('.warnings');
      if (await warnings.count()) await expect(warnings.getByRole('listitem')).not.toHaveCount(0);
    }
  });
});
