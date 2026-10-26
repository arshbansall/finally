import type { Portfolio, PriceTick } from "@/lib/types";

export function tick(ticker: string, price: number, overrides: Partial<PriceTick> = {}): PriceTick {
  const open_price = overrides.open_price ?? 100;
  return {
    ticker,
    price,
    previous_price: overrides.previous_price ?? price,
    open_price,
    timestamp: overrides.timestamp ?? "2026-10-26T15:00:00.000+00:00",
    direction: overrides.direction ?? "flat",
    change: price - open_price,
    change_pct: ((price - open_price) / open_price) * 100,
    ...overrides,
  };
}

export const portfolio: Portfolio = {
  cash_balance: 8100,
  positions_value: 1905,
  total_value: 10005,
  unrealized_pnl: 5,
  unrealized_pnl_pct: 0.26,
  positions: [
    {
      ticker: "AAPL",
      quantity: 10,
      avg_cost: 190,
      current_price: 190.5,
      market_value: 1905,
      unrealized_pnl: 5,
      unrealized_pnl_pct: 0.26,
      weight: 100,
    },
  ],
};

export const twoPositions: Portfolio = {
  cash_balance: 5000,
  positions_value: 5000,
  total_value: 10000,
  unrealized_pnl: 0,
  unrealized_pnl_pct: 0,
  positions: [
    { ticker: "AAPL", quantity: 10, avg_cost: 200, current_price: 220, market_value: 2200, unrealized_pnl: 200, unrealized_pnl_pct: 10, weight: 44 },
    { ticker: "TSLA", quantity: 20, avg_cost: 150, current_price: 140, market_value: 2800, unrealized_pnl: -200, unrealized_pnl_pct: -6.67, weight: 56 },
  ],
};
