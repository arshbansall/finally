import { expect, test } from '@playwright/test';
import { closePosition, ensureNotWatched, getPortfolio, getWatchlist, positionQty } from '../helpers/api';
import { expectMoneyNear, openApp, sendChat } from '../helpers/ui';

// Requires the backend to run with LLM_MOCK=true (deterministic responses, CONTRACT §3.4).
test.describe('AI chat (mock LLM)', () => {
  test('send a message and receive a response, with a loading indicator', async ({ page, request }) => {
    await openApp(page);

    // Hold the request briefly so the loading state is observable.
    await page.route('**/api/chat', async (route) => {
      if (route.request().method() === 'POST') await new Promise((r) => setTimeout(r, 1000));
      await route.continue();
    });

    const responsePromise = sendChat(page, 'How is my portfolio doing?');
    await expect(page.getByTestId('chat-loading')).toBeVisible();
    const res = await responsePromise;
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.message).toContain("Mock: I'm FinAlly");
    expect(body.trades ?? []).toEqual([]);
    expect(body.watchlist_changes ?? []).toEqual([]);

    await expect(page.getByTestId('chat-loading')).toHaveCount(0);
    const panel = page.getByTestId('chat-panel');
    await expect(
      panel.locator('[data-testid="chat-message"][data-role="user"]').filter({ hasText: 'How is my portfolio doing?' }),
    ).toBeVisible();
    const reply = panel
      .locator('[data-testid="chat-message"][data-role="assistant"]')
      .filter({ hasText: "Mock: I'm FinAlly" })
      .last();
    await expect(reply).toBeVisible();
    // The mock quotes the portfolio value.
    await expect(reply).toContainText('$');
    expect((await getPortfolio(request)).total_value).toBeGreaterThan(0);
  });

  test('chat buy executes a trade shown inline and updates the portfolio', async ({ page, request }) => {
    const ticker = 'AMZN';
    await closePosition(request, ticker);
    const before = await getPortfolio(request);

    await openApp(page);
    const res = await sendChat(page, `buy 2 ${ticker}`);
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.message).toContain(`Mock: executing buy 2 ${ticker}`);
    expect(body.trades).toHaveLength(1);
    expect(body.trades[0]).toMatchObject({ ticker, side: 'buy', quantity: 2, status: 'executed' });

    const reply = page
      .locator('[data-testid="chat-message"][data-role="assistant"]')
      .filter({ hasText: `Mock: executing buy 2 ${ticker}` })
      .last();
    await expect(reply).toBeVisible();
    const action = page.getByTestId('chat-action').filter({ hasText: ticker }).last();
    await expect(action).toBeVisible();
    await expect(action).toHaveAttribute('data-status', 'executed');

    // Portfolio reflects the chat trade (API + UI, no reload).
    const after = await getPortfolio(request);
    expect(positionQty(after, ticker)).toBe(2);
    const expectedCash = before.cash_balance - 2 * body.trades[0].price;
    expect(after.cash_balance).toBeCloseTo(expectedCash, 2);
    await expect(page.getByTestId(`position-row-${ticker}`)).toBeVisible();
    await expectMoneyNear(page.getByTestId('header-cash'), expectedCash);
  });

  test('chat sell of an unowned position reports a failure inline', async ({ page, request }) => {
    const ticker = 'NFLX';
    await closePosition(request, ticker);
    const before = await getPortfolio(request);

    await openApp(page);
    const res = await sendChat(page, `sell 999 ${ticker}`);
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.trades).toHaveLength(1);
    expect(body.trades[0]).toMatchObject({ ticker, side: 'sell', status: 'failed' });
    expect(body.trades[0].error).toBeTruthy();

    const action = page.getByTestId('chat-action').filter({ hasText: ticker }).last();
    await expect(action).toBeVisible();
    await expect(action).toHaveAttribute('data-status', 'failed');
    expect((await getPortfolio(request)).cash_balance).toBeCloseTo(before.cash_balance, 2);
  });

  test('chat adds a ticker to the watchlist', async ({ page, request }) => {
    const ticker = 'UBER';
    await ensureNotWatched(request, ticker);

    await openApp(page);
    const res = await sendChat(page, `add ${ticker}`);
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.watchlist_changes).toHaveLength(1);
    expect(body.watchlist_changes[0]).toMatchObject({ ticker, action: 'add', status: 'executed' });

    await expect(page.getByTestId('chat-action').filter({ hasText: ticker }).last()).toBeVisible();
    await expect(page.getByTestId(`watchlist-row-${ticker}`)).toBeVisible();
    expect((await getWatchlist(request)).map((t) => t.ticker)).toContain(ticker);

    // And removes it again.
    const res2 = await sendChat(page, `remove ${ticker}`);
    expect((await res2.json()).watchlist_changes[0]).toMatchObject({ ticker, action: 'remove', status: 'executed' });
    await expect(page.getByTestId(`watchlist-row-${ticker}`)).toHaveCount(0);
  });

  test('conversation is restored after reload', async ({ page }) => {
    const marker = `remember-me-${Date.now()}`;
    await openApp(page);
    const res = await sendChat(page, marker);
    expect(res.status()).toBe(200);
    await expect(page.getByTestId('chat-message').filter({ hasText: marker })).toBeVisible();

    await page.reload();
    await expect(page.getByTestId('chat-message').filter({ hasText: marker })).toBeVisible();
  });
});
