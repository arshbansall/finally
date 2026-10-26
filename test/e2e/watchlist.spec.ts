import { expect, test } from '@playwright/test';
import { ensureNotWatched, getWatchlist } from '../helpers/api';
import { openApp } from '../helpers/ui';

const TICKER = 'PYPL'; // not in the default seed; simulator assigns it a random seed price

test.describe('Watchlist', () => {
  test.beforeEach(async ({ request }) => {
    await ensureNotWatched(request, TICKER);
  });

  test.afterEach(async ({ request }) => {
    await ensureNotWatched(request, TICKER);
  });

  test('add and remove a ticker', async ({ page, request }) => {
    await openApp(page);
    const row = page.getByTestId(`watchlist-row-${TICKER}`);
    await expect(row).toHaveCount(0);

    // Lowercase input: tickers are normalized to uppercase.
    await page.getByTestId('watchlist-add-input').fill(TICKER.toLowerCase());
    await page.getByTestId('watchlist-add-button').click();

    await expect(row).toBeVisible();
    await expect(page.getByTestId(`watchlist-price-${TICKER}`)).toHaveText(/\d+\.\d{2}/);
    expect((await getWatchlist(request)).map((t) => t.ticker)).toContain(TICKER);

    // The new ticker streams like the others.
    const first = await page.getByTestId(`watchlist-price-${TICKER}`).textContent();
    await expect
      .poll(() => page.getByTestId(`watchlist-price-${TICKER}`).textContent(), { timeout: 10_000 })
      .not.toBe(first);

    await page.getByTestId(`watchlist-remove-${TICKER}`).click();
    await expect(row).toHaveCount(0);
    expect((await getWatchlist(request)).map((t) => t.ticker)).not.toContain(TICKER);

    // Removal persists across a reload.
    await page.reload();
    await expect(page.getByTestId('watchlist-row-AAPL')).toBeVisible();
    await expect(row).toHaveCount(0);
  });

  test('added ticker persists across reload', async ({ page }) => {
    await openApp(page);
    await page.getByTestId('watchlist-add-input').fill(TICKER);
    await page.getByTestId('watchlist-add-button').click();
    await expect(page.getByTestId(`watchlist-row-${TICKER}`)).toBeVisible();

    await page.reload();
    await expect(page.getByTestId(`watchlist-row-${TICKER}`)).toBeVisible();
  });

  test('clicking a ticker selects it in the main chart', async ({ page }) => {
    await openApp(page);
    const chart = page.getByTestId('main-chart');
    await expect(chart).toBeVisible();

    for (const ticker of ['NVDA', 'TSLA']) {
      await page.getByTestId(`watchlist-row-${ticker}`).click();
      await expect(chart).toHaveAttribute('data-ticker', ticker);
    }
    // The chart actually draws something of a usable size.
    const drawing = chart.locator('canvas, svg').first();
    await expect(drawing).toBeVisible();
    const box = await drawing.boundingBox();
    expect(box!.width).toBeGreaterThan(200);
    expect(box!.height, 'main chart canvas height').toBeGreaterThan(100);
  });
});
