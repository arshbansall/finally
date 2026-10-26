import { expect, type APIRequestContext } from '@playwright/test';

export const DEFAULT_TICKERS = [
  'AAPL', 'GOOGL', 'MSFT', 'AMZN', 'TSLA', 'NVDA', 'META', 'JPM', 'V', 'NFLX',
] as const;

export interface Position {
  ticker: string;
  quantity: number;
  avg_cost: number;
  current_price: number;
  market_value: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  weight: number;
}

export interface Portfolio {
  cash_balance: number;
  positions_value: number;
  total_value: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  positions: Position[];
}

export interface WatchlistItem {
  ticker: string;
  price: number | null;
  previous_price: number | null;
  change_pct: number | null;
  direction: string | null;
}

export interface Trade {
  id: string;
  ticker: string;
  side: 'buy' | 'sell';
  quantity: number;
  price: number;
  executed_at: string;
}

export async function getPortfolio(request: APIRequestContext): Promise<Portfolio> {
  const res = await request.get('/api/portfolio');
  expect(res.status(), 'GET /api/portfolio').toBe(200);
  return res.json();
}

export function positionQty(portfolio: Portfolio, ticker: string): number {
  return portfolio.positions.find((p) => p.ticker === ticker)?.quantity ?? 0;
}

export async function trade(
  request: APIRequestContext,
  ticker: string,
  side: 'buy' | 'sell',
  quantity: number,
): Promise<{ trade: Trade; portfolio: Portfolio }> {
  const res = await request.post('/api/portfolio/trade', { data: { ticker, side, quantity } });
  expect(res.status(), `${side} ${quantity} ${ticker}: ${await res.text()}`).toBe(200);
  return res.json();
}

/** Sell any existing holding of `ticker` so a test starts flat. */
export async function closePosition(request: APIRequestContext, ticker: string): Promise<void> {
  const qty = positionQty(await getPortfolio(request), ticker);
  if (qty > 0) await trade(request, ticker, 'sell', qty);
}

export async function getWatchlist(request: APIRequestContext): Promise<WatchlistItem[]> {
  const res = await request.get('/api/watchlist');
  expect(res.status(), 'GET /api/watchlist').toBe(200);
  return (await res.json()).tickers;
}

export async function ensureNotWatched(request: APIRequestContext, ticker: string): Promise<void> {
  const res = await request.delete(`/api/watchlist/${ticker}`);
  expect([200, 404], `DELETE /api/watchlist/${ticker}`).toContain(res.status());
}

export async function ensureWatched(request: APIRequestContext, ticker: string): Promise<void> {
  const res = await request.post('/api/watchlist', { data: { ticker } });
  expect([201, 409], `POST /api/watchlist ${ticker}`).toContain(res.status());
}

/** Wait until the backend has a live price for `ticker` (it must be tracked). */
export async function waitForPrice(request: APIRequestContext, ticker: string): Promise<number> {
  let price: number | null = null;
  await expect
    .poll(
      async () => {
        price = (await getWatchlist(request)).find((t) => t.ticker === ticker)?.price ?? null;
        return price;
      },
      { message: `price for ${ticker}`, timeout: 15_000 },
    )
    .not.toBeNull();
  return price as unknown as number;
}
