import type { Position } from "@/lib/types";
import { formatMoney, formatPct, formatPrice, formatQty, formatSignedMoney, trendClass } from "@/lib/format";
import Panel from "./Panel";

interface PositionsTableProps {
  positions: Position[];
  onSelect?: (ticker: string) => void;
}

export default function PositionsTable({ positions, onSelect }: PositionsTableProps) {
  const rows = [...positions].sort((a, b) => b.market_value - a.market_value);
  return (
    <Panel title="Positions" aside={<span className="num">{positions.length}</span>} bodyClassName="overflow-auto">
      <table className="w-full border-collapse text-[12.5px]" data-testid="positions-table">
        <thead className="sticky top-0 bg-ink-900">
          <tr className="narrow text-left text-2xs text-fg-faint">
            <th className="px-3 py-1.5 font-medium">Ticker</th>
            <th className="px-3 py-1.5 text-right font-medium">Qty</th>
            <th className="px-3 py-1.5 text-right font-medium">Avg cost</th>
            <th className="px-3 py-1.5 text-right font-medium">Price</th>
            <th className="px-3 py-1.5 text-right font-medium">Market value</th>
            <th className="px-3 py-1.5 text-right font-medium">Unrealized P&amp;L</th>
            <th className="px-3 py-1.5 text-right font-medium">Change</th>
            <th className="px-3 py-1.5 text-right font-medium">Weight</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={8} className="px-3 py-6 text-center text-[12px] text-fg-faint">
                No positions yet. Place an order in the trade bar or ask FinAlly to buy something.
              </td>
            </tr>
          ) : (
            rows.map((p) => (
              <tr
                key={p.ticker}
                data-testid={`position-row-${p.ticker}`}
                className="num cursor-pointer border-t border-line/70 hover:bg-ink-850"
                onClick={() => onSelect?.(p.ticker)}
              >
                <td className="narrow px-3 py-1.5 text-[13px] font-semibold text-fg">{p.ticker}</td>
                <td className="px-3 py-1.5 text-right" data-testid={`position-qty-${p.ticker}`}>
                  {formatQty(p.quantity)}
                </td>
                <td className="px-3 py-1.5 text-right text-fg-muted">{formatPrice(p.avg_cost)}</td>
                <td className="px-3 py-1.5 text-right">{formatPrice(p.current_price)}</td>
                <td className="px-3 py-1.5 text-right">{formatMoney(p.market_value)}</td>
                <td className={`px-3 py-1.5 text-right ${trendClass(p.unrealized_pnl)}`}>
                  {formatSignedMoney(p.unrealized_pnl)}
                </td>
                <td className={`px-3 py-1.5 text-right ${trendClass(p.unrealized_pnl_pct)}`}>
                  {formatPct(p.unrealized_pnl_pct)}
                </td>
                <td className="px-3 py-1.5 text-right text-fg-muted">{p.weight.toFixed(1)}%</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </Panel>
  );
}
