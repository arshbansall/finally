import { expect, test } from '@playwright/test';
import {
  closePosition,
  ensureNotWatched,
  getPortfolio,
  getWatchlist,
  positionQty,
  trade,
  waitForPrice,
} from '../helpers/api';

test.describe('API: system & static', () => {
  test('GET /api/health', async ({ request }) => {
    const res = await request.get('/api/health');
    expect(res.status()).toBe(200);
    expect(await res.json()).toEqual({ status: 'ok' });
  });

  test('GET / serves the frontend', async ({ request }) => {
    const res = await request.get('/');
    expect(res.status()).toBe(200);
    expect(res.headers()['content-type']).toContain('text/html');
  });

  test('unknown /api route is a JSON 404, not the SPA', async ({ request }) => {
    const res = await request.get('/api/does-not-exist');
    expect(res.status()).toBe(404);
    expect(res.headers()['content-type']).toContain('application/json');
  });
});

test.describe('API: portfolio', () => {
  test('GET /api/portfolio shape', async ({ request }) => {
    const p = await getPortfolio(request);
    for (const key of ['cash_balance', 'positions_value', 'total_value', 'unrealized_pnl', 'unrealized_pnl_pct']) {
      expect(typeof (p as unknown as Record<string, unknown>)[key], key).toBe('number');
    }
    expect(Array.isArray(p.positions)).toBe(true);
    expect(p.total_value).toBeCloseTo(p.cash_balance + p.positions_value, 2);
  });

  test('buy, add to, and fully sell a position (cash and weighted avg cost)', async ({ request }) => {
    const ticker = 'META';
    await closePosition(request, ticker);
    const start = await getPortfolio(request);

    const buy1 = await trade(request, ticker, 'buy', 2);
    expect(buy1.trade).toMatchObject({ ticker, side: 'buy', quantity: 2 });
    expect(typeof buy1.trade.id).toBe('string');
    expect(Number.isNaN(Date.parse(buy1.trade.executed_at))).toBe(false);
    expect(buy1.portfolio.cash_balance).toBeCloseTo(start.cash_balance - 2 * buy1.trade.price, 2);
    let pos = buy1.portfolio.positions.find((x) => x.ticker === ticker)!;
    expect(pos.quantity).toBe(2);
    expect(pos.avg_cost).toBeCloseTo(buy1.trade.price, 4);
    for (const key of ['current_price', 'market_value', 'unrealized_pnl', 'unrealized_pnl_pct', 'weight']) {
      expect(typeof (pos as unknown as Record<string, unknown>)[key], key).toBe('number');
    }

    const buy2 = await trade(request, ticker, 'buy', 1);
    pos = buy2.portfolio.positions.find((x) => x.ticker === ticker)!;
    expect(pos.quantity).toBe(3);
    expect(pos.avg_cost).toBeCloseTo((2 * buy1.trade.price + buy2.trade.price) / 3, 4);

    // Fractional shares are supported.
    const sellPart = await trade(request, ticker, 'sell', 0.5);
    expect(positionQty(sellPart.portfolio, ticker)).toBeCloseTo(2.5, 6);
    // Avg cost is unchanged by a sell.
    expect(sellPart.portfolio.positions.find((x) => x.ticker === ticker)!.avg_cost).toBeCloseTo(pos.avg_cost, 4);

    const sellAll = await trade(request, ticker, 'sell', 2.5);
    expect(positionQty(sellAll.portfolio, ticker)).toBe(0);
    const expectedCash =
      start.cash_balance -
      2 * buy1.trade.price -
      buy2.trade.price +
      0.5 * sellPart.trade.price +
      2.5 * sellAll.trade.price;
    expect(sellAll.portfolio.cash_balance).toBeCloseTo(expectedCash, 2);
  });

  test('weights sum to 100 across positions', async ({ request }) => {
    await trade(request, 'TSLA', 'buy', 1);
    const p = await getPortfolio(request);
    const sum = p.positions.reduce((acc, x) => acc + x.weight, 0);
    expect(sum).toBeCloseTo(100, 0);
    await closePosition(request, 'TSLA');
  });

  test('trade validation errors return 400 with a detail message', async ({ request }) => {
    await closePosition(request, 'NVDA');
    const before = await getPortfolio(request);
    const cases: Array<{ name: string; data: Record<string, unknown>; statuses: number[] }> = [
      { name: 'insufficient cash', data: { ticker: 'AAPL', side: 'buy', quantity: 1_000_000 }, statuses: [400] },
      { name: 'sell more than owned', data: { ticker: 'NVDA', side: 'sell', quantity: 5 }, statuses: [400] },
      { name: 'zero quantity', data: { ticker: 'AAPL', side: 'buy', quantity: 0 }, statuses: [400, 422] },
      { name: 'negative quantity', data: { ticker: 'AAPL', side: 'buy', quantity: -3 }, statuses: [400, 422] },
      { name: 'invalid side', data: { ticker: 'AAPL', side: 'hold', quantity: 1 }, statuses: [400, 422] },
      { name: 'invalid ticker', data: { ticker: '123!', side: 'buy', quantity: 1 }, statuses: [400, 422] },
    ];
    for (const c of cases) {
      const res = await request.post('/api/portfolio/trade', { data: c.data });
      expect(c.statuses, `${c.name}: got ${res.status()} ${await res.text()}`).toContain(res.status());
      const body = await res.json();
      expect(body.detail, c.name).toBeTruthy();
      if (res.status() === 400) expect(typeof body.detail, c.name).toBe('string');
    }
    const after = await getPortfolio(request);
    expect(after.cash_balance).toBeCloseTo(before.cash_balance, 2);
    expect(positionQty(after, 'NVDA')).toBe(0);
  });

  test('lowercase ticker is normalized on trade', async ({ request }) => {
    await closePosition(request, 'AAPL');
    const res = await trade(request, 'aapl' as string, 'buy', 1);
    expect(res.trade.ticker).toBe('AAPL');
    await closePosition(request, 'AAPL');
  });

  test('GET /api/portfolio/history returns snapshots oldest first, one added per trade', async ({ request }) => {
    const get = async () => {
      const res = await request.get('/api/portfolio/history');
      expect(res.status()).toBe(200);
      return (await res.json()).snapshots as Array<{ total_value: number; recorded_at: string }>;
    };
    const before = await get();
    expect(before.length).toBeGreaterThanOrEqual(1);
    for (const s of before) {
      expect(typeof s.total_value).toBe('number');
      expect(Number.isNaN(Date.parse(s.recorded_at))).toBe(false);
    }
    const times = before.map((s) => Date.parse(s.recorded_at));
    expect([...times].sort((a, b) => a - b)).toEqual(times);

    await trade(request, 'AAPL', 'buy', 1);
    const after = await get();
    expect(after.length).toBeGreaterThan(before.length);
    await closePosition(request, 'AAPL');
  });
});

test.describe('API: watchlist', () => {
  const ticker = 'SHOP';

  test.beforeEach(async ({ request }) => {
    await ensureNotWatched(request, ticker);
  });

  test('GET /api/watchlist shape', async ({ request }) => {
    const items = await getWatchlist(request);
    expect(items.length).toBeGreaterThanOrEqual(1);
    for (const item of items) {
      expect(item.ticker).toMatch(/^[A-Z][A-Z0-9.]{0,9}$/);
      expect(item).toHaveProperty('price');
      expect(item).toHaveProperty('previous_price');
      expect(item).toHaveProperty('change_pct');
      expect(item).toHaveProperty('direction');
    }
    const aapl = items.find((t) => t.ticker === 'AAPL')!;
    expect(typeof aapl.price).toBe('number');
  });

  test('add (201, normalized), duplicate (409), price appears, delete (200), delete again (404)', async ({ request }) => {
    const add = await request.post('/api/watchlist', { data: { ticker: ticker.toLowerCase() } });
    expect(add.status(), await add.text()).toBe(201);
    expect((await add.json()).ticker).toBe(ticker);

    const dup = await request.post('/api/watchlist', { data: { ticker } });
    expect(dup.status()).toBe(409);
    expect((await dup.json()).detail).toBeTruthy();

    expect(await waitForPrice(request, ticker)).toBeGreaterThan(0);

    const del = await request.delete(`/api/watchlist/${ticker}`);
    expect(del.status()).toBe(200);
    expect((await del.json()).ticker).toBe(ticker);
    expect((await getWatchlist(request)).map((t) => t.ticker)).not.toContain(ticker);

    const del2 = await request.delete(`/api/watchlist/${ticker}`);
    expect(del2.status()).toBe(404);
  });

  test('invalid ticker is rejected with 400', async ({ request }) => {
    for (const bad of ['bad ticker!', '1ABC', 'TOOLONGTICKER123', '']) {
      const res = await request.post('/api/watchlist', { data: { ticker: bad } });
      expect([400, 422], `"${bad}": ${res.status()}`).toContain(res.status());
    }
  });

  test('a newly watched ticker can be traded', async ({ request }) => {
    await request.post('/api/watchlist', { data: { ticker } });
    await waitForPrice(request, ticker);
    const res = await trade(request, ticker, 'buy', 1);
    expect(res.trade.ticker).toBe(ticker);
    await closePosition(request, ticker);
    await ensureNotWatched(request, ticker);
  });
});

test.describe('API: chat (mock)', () => {
  test('POST /api/chat response shape and history', async ({ request }) => {
    const res = await request.post('/api/chat', { data: { message: 'hello there' } });
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(typeof body.message).toBe('string');
    expect(body.message).toContain("Mock: I'm FinAlly");

    const history = await request.get('/api/chat');
    expect(history.status()).toBe(200);
    const { messages } = await history.json();
    const tail = messages.slice(-2);
    expect(tail[0]).toMatchObject({ role: 'user', content: 'hello there' });
    expect(tail[1]).toMatchObject({ role: 'assistant' });
    expect(tail[1].content).toContain("Mock: I'm FinAlly");
    for (const m of tail) {
      expect(typeof m.id).toBe('string');
      expect(Number.isNaN(Date.parse(m.created_at))).toBe(false);
    }
  });

  test('POST /api/chat watchlist + trade actions are reported per item', async ({ request }) => {
    await ensureNotWatched(request, 'COIN');
    const add = await (await request.post('/api/chat', { data: { message: 'add COIN' } })).json();
    expect(add.message).toContain('Mock:');
    expect(add.watchlist_changes).toEqual([
      expect.objectContaining({ ticker: 'COIN', action: 'add', status: 'executed', error: null }),
    ]);
    await waitForPrice(request, 'COIN');

    const buy = await (await request.post('/api/chat', { data: { message: 'Buy 1 COIN' } })).json();
    expect(buy.trades).toEqual([
      expect.objectContaining({ ticker: 'COIN', side: 'buy', quantity: 1, status: 'executed', error: null }),
    ]);
    expect(typeof buy.trades[0].price).toBe('number');

    const history = await (await request.get('/api/chat')).json();
    const last = history.messages[history.messages.length - 1];
    expect(last.role).toBe('assistant');
    expect(last.actions).toBeTruthy();

    await closePosition(request, 'COIN');
    await ensureNotWatched(request, 'COIN');
  });

  test('invalid chat body returns 422', async ({ request }) => {
    const res = await request.post('/api/chat', { data: {} });
    expect(res.status()).toBe(422);
  });
});
