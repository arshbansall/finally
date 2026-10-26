import { expect, test } from '@playwright/test';
import { closePosition, getPortfolio, positionQty, trade } from '../helpers/api';
import {
  expectMoneyNear,
  numberCell,
  openApp,
  placeTrade,
  readMoney,
  submitTrade,
} from '../helpers/ui';

test.describe('Trading', () => {
  test('buy shares: cash decreases, position appears, portfolio updates', async ({ page, request }) => {
    const ticker = 'MSFT';
    const qty = 3;
    await closePosition(request, ticker);
    const before = await getPortfolio(request);

    await openApp(page);
    await expect(page.getByTestId(`position-row-${ticker}`)).toHaveCount(0);
    await expectMoneyNear(page.getByTestId('header-cash'), before.cash_balance);

    const res = await placeTrade(page, ticker, qty, 'buy');
    expect(res.status(), await res.text()).toBe(200);
    const { trade: executed } = await res.json();
    expect(executed).toMatchObject({ ticker, side: 'buy', quantity: qty });

    const expectedCash = before.cash_balance - qty * executed.price;
    const after = await getPortfolio(request);
    expect(after.cash_balance).toBeCloseTo(expectedCash, 2);
    expect(positionQty(after, ticker)).toBe(qty);

    // UI reflects the trade without a reload.
    await expectMoneyNear(page.getByTestId('header-cash'), expectedCash);
    const row = page.getByTestId(`position-row-${ticker}`);
    await expect(row).toBeVisible();
    await expect(row).toContainText(ticker);
    await expect(numberCell(row, qty)).toBeVisible();
    await expect(page.getByTestId('trade-error')).toHaveCount(0);

    // Total value ~ cash + position value (prices keep moving, so allow some slack).
    const total = await readMoney(page.getByTestId('header-total-value'));
    expect(Math.abs(total - after.total_value) / after.total_value).toBeLessThan(0.01);
  });

  test('sell shares: cash increases, position updates then disappears', async ({ page, request }) => {
    const ticker = 'JPM';
    await closePosition(request, ticker);
    await trade(request, ticker, 'buy', 4);

    await openApp(page);
    const row = page.getByTestId(`position-row-${ticker}`);
    await expect(row).toBeVisible();

    // Partial sell.
    let before = await getPortfolio(request);
    let res = await placeTrade(page, ticker, 2, 'sell');
    expect(res.status(), await res.text()).toBe(200);
    let executed = (await res.json()).trade;
    let expectedCash = before.cash_balance + 2 * executed.price;
    expect((await getPortfolio(request)).cash_balance).toBeCloseTo(expectedCash, 2);
    await expectMoneyNear(page.getByTestId('header-cash'), expectedCash);
    await expect(numberCell(row, 2)).toBeVisible();

    // Sell the rest: the position row goes away.
    before = await getPortfolio(request);
    res = await placeTrade(page, ticker, 2, 'sell');
    expect(res.status(), await res.text()).toBe(200);
    executed = (await res.json()).trade;
    expectedCash = before.cash_balance + 2 * executed.price;
    await expectMoneyNear(page.getByTestId('header-cash'), expectedCash);
    await expect(row).toHaveCount(0);
    expect(positionQty(await getPortfolio(request), ticker)).toBe(0);
  });

  test('selling more than owned shows an error and changes nothing', async ({ page, request }) => {
    const ticker = 'V';
    await closePosition(request, ticker);
    const before = await getPortfolio(request);

    await openApp(page);
    // The UI may reject this client-side or show the server's 400 detail; either way an error shows.
    await submitTrade(page, ticker, 1000, 'sell');

    await expect(page.getByTestId('trade-error')).toBeVisible();
    await expect(page.getByTestId('trade-error')).not.toBeEmpty();
    const after = await getPortfolio(request);
    expect(after.cash_balance).toBeCloseTo(before.cash_balance, 2);
    expect(positionQty(after, ticker)).toBe(0);
    await expect(page.getByTestId(`position-row-${ticker}`)).toHaveCount(0);
    await expectMoneyNear(page.getByTestId('header-cash'), before.cash_balance);
  });

  test('buying with insufficient cash shows an error', async ({ page, request }) => {
    const before = await getPortfolio(request);

    await openApp(page);
    await submitTrade(page, 'AAPL', 1_000_000, 'buy');
    await expect(page.getByTestId('trade-error')).toBeVisible();
    expect((await getPortfolio(request)).cash_balance).toBeCloseTo(before.cash_balance, 2);
  });
});
