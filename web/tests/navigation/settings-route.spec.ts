import { expect, test } from '@playwright/test';

test('direct settings loads, reloads, and navigates with browser history', async ({ page }) => {
  await page.goto('/settings');
  await expect(page).toHaveURL(/\/settings$/);
  await expect(page.getByRole('heading', { name: 'Boat settings' })).toBeVisible();
  await expect(page.getByRole('main')).toHaveCount(1);
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Boat settings' })).toBeVisible();

  await page.getByRole('link', { name: 'Plan trip' }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole('heading', { name: 'Plan your canal journey' })).toBeFocused();
  await page.goBack();
  await expect(page).toHaveURL(/\/settings$/);
  await page.goForward();
  await expect(page).toHaveURL(/\/$/);
});

test('keyboard navigation and narrow settings layout expose one page', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 });
  await page.goto('/');
  await page.getByRole('link', { name: 'Settings' }).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('heading', { name: 'Boat settings' })).toBeFocused();
  await expect(page.getByRole('main')).toHaveCount(1);
  await expect(page.getByRole('button', { name: 'Plan canal route' })).toHaveCount(0);
});

test('save settings returns to planner with status message', async ({ page }) => {
  await page.goto('/settings');
  await page.getByLabel('Boat length (m)').fill('18.3');
  await page.getByRole('button', { name: 'Save settings' }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole('heading', { name: 'Plan your canal journey' })).toBeVisible();
  await expect(page.getByText('Boat settings saved.')).toBeVisible();
});

test('cancel returns to planner without saving a changed draft', async ({ page }) => {
  await page.goto('/settings');
  await page.getByLabel('Boat length (m)').fill('22');
  await page.getByRole('button', { name: 'Cancel' }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole('heading', { name: 'Plan your canal journey' })).toBeVisible();
  await page.getByRole('link', { name: 'Settings' }).click();
  await expect(page.getByLabel('Boat length (m)')).toHaveValue('');
});

test('Enter in cruising time submits the route form', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Days').fill('7');
  await page.getByLabel('Days').press('Enter');
  await expect(page.locator('#route-actions').getByRole('alert')).toBeVisible();
});
