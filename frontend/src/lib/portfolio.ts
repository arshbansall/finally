import type { Portfolio, PriceEvent } from "./types";

/**
 * Re-mark a server portfolio snapshot against the latest streamed prices so the
 * header, table and heatmap move with every tick instead of waiting for a refetch.
 */
export function revaluePortfolio(portfolio: Portfolio, prices: PriceEvent): Portfolio {
  const positions = portfolio.positions.map((p) => {
    const live = prices[p.ticker]?.price;
    const current_price = live != null && Number.isFinite(live) ? live : p.current_price;
    const market_value = p.quantity * current_price;
    const cost = p.quantity * p.avg_cost;
    const unrealized_pnl = market_value - cost;
    const unrealized_pnl_pct = cost !== 0 ? (unrealized_pnl / cost) * 100 : 0;
    return { ...p, current_price, market_value, unrealized_pnl, unrealized_pnl_pct };
  });
  const positions_value = positions.reduce((s, p) => s + p.market_value, 0);
  const cost_basis = positions.reduce((s, p) => s + p.quantity * p.avg_cost, 0);
  const unrealized_pnl = positions_value - cost_basis;
  return {
    cash_balance: portfolio.cash_balance,
    positions_value,
    total_value: portfolio.cash_balance + positions_value,
    unrealized_pnl,
    unrealized_pnl_pct: cost_basis !== 0 ? (unrealized_pnl / cost_basis) * 100 : 0,
    positions: positions.map((p) => ({
      ...p,
      weight: positions_value > 0 ? (p.market_value / positions_value) * 100 : 0,
    })),
  };
}
