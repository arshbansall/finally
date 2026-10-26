import { expect, test } from '@playwright/test';
import { DEFAULT_TICKERS, getPortfolio, getWatchlist } from '../helpers/api';
import { openApp, readMoney } from '../helpers/ui';

// Runs first (see playwright.config.ts projects) against a freshly seeded database.
test.describe('Fresh start', () => {
  test('backend is seeded with defaults', async ({ request }) => {
    const health = await request.get('/api/health');
    expect(health.status()).toBe(200);
    expect(await health.json()).toEqual({ status: 'ok' });

    const portfolio = await getPortfolio(request);
    expect(portfolio.cash_balance).toBe(10000);
    expect(portfolio.positions).toEqual([]);
    expect(portfolio.total_value).toBeCloseTo(10000, 2);

    const watchlist = await getWatchlist(request);
    expect(watchlist.map((t) => t.ticker).sort()).toEqual([...DEFAULT_TICKERS].sort());
  });

  test('shows the default watchlist, $10,000 cash and a live connection', async ({ page }) => {
    await openApp(page);

    const rows = page.getByTestId('watchlist').locator('[data-testid^="watchlist-row-"]');
    await expect(rows).toHaveCount(DEFAULT_TICKERS.length);
    for (const ticker of DEFAULT_TICKERS) {
      await expect(page.getByTestId(`watchlist-row-${ticker}`)).toBeVisible();
    }

    expect(await readMoney(page.getByTestId('header-cash'))).toBe(10000);
    expect(await readMoney(page.getByTestId('header-total-value'))).toBeCloseTo(10000, 2);
    await expect(page.getByTestId('header-cash')).toContainText('10,000.00');

    await expect(page.getByTestId('positions-table')).toBeVisible();
    await expect(page.locator('[data-testid^="position-row-"]')).toHaveCount(0);
  });

  test('prices stream and flash on change', async ({ page }) => {
    await openApp(page);

    // Every default ticker gets a numeric price.
    for (const ticker of DEFAULT_TICKERS) {
      await expect(page.getByTestId(`watchlist-price-${ticker}`)).toHaveText(/\d+\.\d{2}/);
    }

    const readPrices = () =>
      Promise.all(
        DEFAULT_TICKERS.map((t) => page.getByTestId(`watchlist-price-${t}`).textContent()),
      );
    const initial = await readPrices();

    // Watch the price cells' class attribute: the flash class is added and removed on each tick.
    await page.evaluate((tickers) => {
      const w = window as unknown as { __flashMutations: number };
      w.__flashMutations = 0;
      const observer = new MutationObserver((records) => {
        for (const r of records) {
          if (/flash-(up|down)/.test((r.target as Element).className)) w.__flashMutations += 1;
        }
      });
      for (const t of tickers) {
        const el = document.querySelector(`[data-testid="watchlist-price-${t}"]`);
        if (el) observer.observe(el, { attributes: true, attributeFilter: ['class'] });
      }
    }, [...DEFAULT_TICKERS]);

    await expect
      .poll(async () => {
        const now = await readPrices();
        return now.filter((p, i) => p !== initial[i]).length;
      }, { message: 'number of tickers whose displayed price changed', timeout: 10_000 })
      .toBeGreaterThanOrEqual(3);

    await expect
      .poll(() => page.evaluate(() => (window as unknown as { __flashMutations: number }).__flashMutations), {
        message: 'flash-up/flash-down applied to price cells',
      })
      .toBeGreaterThan(0);
  });
});
