import { expect, test, type Locator } from '@playwright/test';
import { closePosition, getPortfolio, getWatchlist, trade } from '../helpers/api';
import { numberCell, openApp, readMoney } from '../helpers/ui';

const TICKER = 'GOOGL';

/** First non-transparent fill/background colour on the cell or its descendants, as [r, g, b]. */
async function cellColor(cell: Locator): Promise<number[]> {
  const rgb = await cell.evaluate((el) => {
    for (const node of [el, ...Array.from(el.querySelectorAll('rect, path, div'))]) {
      const style = getComputedStyle(node);
      for (const value of [style.backgroundColor, style.fill]) {
        const m = value?.match(/rgba?\(([^)]+)\)/);
        if (!m) continue;
        const parts = m[1].split(',').map((p) => Number.parseFloat(p));
        if (parts.length === 4 && parts[3] === 0) continue; // transparent
        return parts.slice(0, 3);
      }
    }
    return null;
  });
  expect(rgb, 'heatmap cell has a fill/background colour').not.toBeNull();
  return rgb!;
}

test.describe('Portfolio visualizations', () => {
  test.beforeAll(async ({ request }) => {
    await closePosition(request, TICKER);
    await trade(request, TICKER, 'buy', 2);
  });

  test('heatmap renders a cell for the position', async ({ page }) => {
    await openApp(page);
    const heatmap = page.getByTestId('portfolio-heatmap');
    await expect(heatmap).toBeVisible();
    await expect(heatmap).toContainText(TICKER);

    const cell = page.getByTestId(`heatmap-cell-${TICKER}`);
    await expect(cell).toBeVisible();
    const box = await cell.boundingBox();
    expect(box!.width).toBeGreaterThan(20);
    expect(box!.height).toBeGreaterThan(20);
    expect(['gain', 'loss', 'flat']).toContain(await cell.getAttribute('data-pnl'));
  });

  test('heatmap sizes cells by weight and colours them green for profit, red for loss', async ({
    page,
    request,
  }) => {
    // Serve a synthetic portfolio with a clear winner and loser. The UI revalues positions
    // with live prices, so cost bases are set far from the current price to keep the signs stable.
    const prices = Object.fromEntries((await getWatchlist(request)).map((t) => [t.ticker, t.price!]));
    const winner = { ticker: 'AAPL', quantity: 30, avg_cost: prices.AAPL * 0.8 };
    const loser = { ticker: 'TSLA', quantity: 10, avg_cost: prices.TSLA * 1.25 };
    await page.route('**/api/portfolio', async (route) => {
      if (route.request().method() !== 'GET') return route.continue();
      const real = await (await route.fetch()).json();
      const positions = [winner, loser].map((p) => {
        const current_price = prices[p.ticker];
        const market_value = p.quantity * current_price;
        const unrealized_pnl = market_value - p.quantity * p.avg_cost;
        return {
          ...p,
          current_price,
          market_value,
          unrealized_pnl,
          unrealized_pnl_pct: (unrealized_pnl / (p.quantity * p.avg_cost)) * 100,
          weight: 0,
        };
      });
      const positions_value = positions.reduce((a, p) => a + p.market_value, 0);
      for (const p of positions) p.weight = (p.market_value / positions_value) * 100;
      const unrealized_pnl = positions.reduce((a, p) => a + p.unrealized_pnl, 0);
      await route.fulfill({
        json: {
          ...real,
          positions,
          positions_value,
          total_value: real.cash_balance + positions_value,
          unrealized_pnl,
          unrealized_pnl_pct: (unrealized_pnl / (positions_value - unrealized_pnl)) * 100,
        },
      });
    });

    await openApp(page);
    const win = page.getByTestId(`heatmap-cell-${winner.ticker}`);
    const lose = page.getByTestId(`heatmap-cell-${loser.ticker}`);
    await expect(win).toBeVisible();
    await expect(lose).toBeVisible();
    await expect(win).toHaveAttribute('data-pnl', 'gain');
    await expect(lose).toHaveAttribute('data-pnl', 'loss');

    const [winRgb, loseRgb] = await Promise.all([cellColor(win), cellColor(lose)]);
    expect(winRgb[1], `profit cell should be green, got rgb(${winRgb})`).toBeGreaterThan(winRgb[0] + 30);
    expect(loseRgb[0], `loss cell should be red, got rgb(${loseRgb})`).toBeGreaterThan(loseRgb[1] + 30);

    // Area tracks weight (prices tick, so allow slack).
    const [wb, lb] = [(await win.boundingBox())!, (await lose.boundingBox())!];
    const areaRatio = (wb.width * wb.height) / (lb.width * lb.height);
    const valueRatio = (winner.quantity * prices.AAPL) / (loser.quantity * prices.TSLA);
    expect(areaRatio / valueRatio).toBeGreaterThan(0.75);
    expect(areaRatio / valueRatio).toBeLessThan(1.33);
  });

  test('P&L chart has data points', async ({ page, request }) => {
    const res = await request.get('/api/portfolio/history');
    expect(res.status()).toBe(200);
    const { snapshots } = await res.json();
    // At least the startup snapshot plus one per trade.
    expect(snapshots.length).toBeGreaterThanOrEqual(2);

    await openApp(page);
    const chart = page.getByTestId('pnl-chart');
    await expect(chart).toBeVisible();
    const drawing = chart.locator('canvas, svg').first();
    await expect(drawing).toBeVisible();
    const box = await drawing.boundingBox();
    expect(box!.width).toBeGreaterThan(50);
    expect(box!.height).toBeGreaterThan(30);
  });

  test('positions table shows the holding with P&L columns', async ({ page, request }) => {
    await openApp(page);
    const table = page.getByTestId('positions-table');
    await expect(table).toBeVisible();
    const row = page.getByTestId(`position-row-${TICKER}`);
    await expect(row).toBeVisible();
    await expect(row).toContainText(TICKER);
    await expect(numberCell(row, 2)).toBeVisible();

    const position = (await getPortfolio(request)).positions.find((p) => p.ticker === TICKER)!;
    // Average cost is fixed by the trade, so it must appear exactly (2 decimals).
    const avgCost = position.avg_cost.toLocaleString('en-US', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
    await expect(row).toContainText(avgCost);
    // Unrealized P&L % is shown.
    await expect(row).toContainText('%');
  });

  test('header total value tracks the portfolio', async ({ page, request }) => {
    await openApp(page);
    const api = await getPortfolio(request);
    const shown = await readMoney(page.getByTestId('header-total-value'));
    expect(Math.abs(shown - api.total_value) / api.total_value).toBeLessThan(0.01);
    expect(await readMoney(page.getByTestId('header-cash'))).toBeCloseTo(api.cash_balance, 2);
  });
});
