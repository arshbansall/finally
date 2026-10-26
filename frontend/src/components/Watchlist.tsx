"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import type { PricePoint, PriceTick } from "@/lib/types";
import { formatPct, formatPrice, trendClass } from "@/lib/format";
import Panel from "./Panel";
import Sparkline from "./Sparkline";

export interface WatchlistRowData {
  ticker: string;
  price: number | null;
  changePct: number | null;
  openPrice: number | null;
}

interface WatchlistProps {
  tickers: string[];
  prices: Record<string, PriceTick>;
  history: Record<string, PricePoint[]>;
  /** Fallback quotes from GET /api/watchlist, used before the first SSE tick. */
  fallback?: Record<string, { price: number | null; change_pct: number | null }>;
  selected: string | null;
  onSelect: (ticker: string) => void;
  onAdd: (ticker: string) => Promise<void>;
  onRemove: (ticker: string) => Promise<void>;
}

const EMPTY: PricePoint[] = [];

/** Flash direction for a value; resets shortly after each change so the CSS fade plays. */
export function usePriceFlash(price: number | null, holdMs = 150): "up" | "down" | null {
  const prev = useRef<number | null>(price);
  const [flash, setFlash] = useState<"up" | "down" | null>(null);
  useEffect(() => {
    const before = prev.current;
    prev.current = price;
    if (price == null || before == null || price === before) return;
    setFlash(price > before ? "up" : "down");
    const t = setTimeout(() => setFlash(null), holdMs);
    return () => clearTimeout(t);
  }, [price, holdMs]);
  return flash;
}

interface RowProps {
  row: WatchlistRowData;
  points: PricePoint[];
  selected: boolean;
  onSelect: (ticker: string) => void;
  onRemove: (ticker: string) => void;
}

function WatchlistRow({ row, points, selected, onSelect, onRemove }: RowProps) {
  const flash = usePriceFlash(row.price);
  return (
    <li
      data-testid={`watchlist-row-${row.ticker}`}
      data-selected={selected ? "true" : "false"}
      className={`group relative flex cursor-pointer items-center gap-2 border-b border-line/70 py-1.5 pl-3 pr-2 hover:bg-ink-850 ${
        selected ? "bg-ink-850" : ""
      }`}
      onClick={() => onSelect(row.ticker)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect(row.ticker);
        }
      }}
      tabIndex={0}
      aria-selected={selected}
      role="option"
    >
      {selected ? <span className="absolute inset-y-0 left-0 w-0.5 bg-accent" aria-hidden /> : null}
      <div className="w-[58px] shrink-0">
        <div className="narrow truncate text-[14px] font-semibold text-fg" title={row.ticker}>
          {row.ticker}
        </div>
        <div className={`num text-2xs ${trendClass(row.changePct)}`} data-testid={`watchlist-change-${row.ticker}`}>
          {formatPct(row.changePct)}
        </div>
      </div>
      <div className="min-w-0 flex-1">
        <Sparkline points={points} baseline={row.openPrice} />
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        <span
          data-testid={`watchlist-price-${row.ticker}`}
          className={`price-cell num w-[72px] rounded-sm px-1 py-0.5 text-right text-[13px] font-medium text-fg ${
            flash === "up" ? "flash-up" : flash === "down" ? "flash-down" : ""
          }`}
        >
          {formatPrice(row.price)}
        </span>
        <button
          type="button"
          data-testid={`watchlist-remove-${row.ticker}`}
          aria-label={`Remove ${row.ticker} from watchlist`}
          title={`Remove ${row.ticker}`}
          className="flex h-5 w-5 items-center justify-center rounded-sm text-fg-faint opacity-40 hover:bg-ink-700 hover:text-down group-hover:opacity-100 focus-visible:opacity-100"
          onClick={(e) => {
            e.stopPropagation();
            onRemove(row.ticker);
          }}
        >
          <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden>
            <path d="M1 1l8 8M9 1L1 9" stroke="currentColor" strokeWidth="1.5" />
          </svg>
        </button>
      </div>
    </li>
  );
}

export default function Watchlist({
  tickers,
  prices,
  history,
  fallback = {},
  selected,
  onSelect,
  onAdd,
  onRemove,
}: WatchlistProps) {
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const ticker = input.trim().toUpperCase();
    if (!ticker) {
      setError("Enter a ticker symbol to add.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onAdd(ticker);
      setInput("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't add that ticker.");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (ticker: string) => {
    setError(null);
    try {
      await onRemove(ticker);
    } catch (err) {
      setError(err instanceof Error ? err.message : `Couldn't remove ${ticker}.`);
    }
  };

  return (
    <Panel title="Watchlist" aside={<span className="num">{tickers.length}</span>} testId="watchlist" bodyClassName="flex flex-col">
      <form onSubmit={submit} className="flex shrink-0 gap-1.5 border-b border-line p-2">
        <input
          data-testid="watchlist-add-input"
          value={input}
          onChange={(e) => setInput(e.target.value.toUpperCase())}
          placeholder="Add ticker, e.g. PYPL"
          aria-label="Ticker to add"
          maxLength={10}
          className="narrow min-w-0 flex-1 rounded-sm border border-line bg-ink-950 px-2 py-1 text-[13px] uppercase text-fg placeholder:normal-case placeholder:text-fg-faint focus:border-primary focus:outline-none"
        />
        <button
          type="submit"
          data-testid="watchlist-add-button"
          disabled={busy}
          className="rounded-sm bg-secondary px-3 text-[12px] font-semibold text-white hover:brightness-110 disabled:opacity-50"
        >
          Add
        </button>
      </form>
      {error ? (
        <p className="shrink-0 border-b border-line bg-down/10 px-3 py-1.5 text-2xs text-down" data-testid="watchlist-error" role="alert">
          {error}
        </p>
      ) : null}
      <ul className="min-h-0 flex-1 overflow-y-auto" role="listbox" aria-label="Watched tickers">
        {tickers.length === 0 ? (
          <li className="px-3 py-6 text-center text-[12px] text-fg-faint">
            Your watchlist is empty. Add a ticker above to start streaming its price.
          </li>
        ) : (
          tickers.map((t) => {
            const tick = prices[t];
            const fb = fallback[t];
            return (
              <WatchlistRow
                key={t}
                row={{
                  ticker: t,
                  price: tick?.price ?? fb?.price ?? null,
                  changePct: tick?.change_pct ?? fb?.change_pct ?? null,
                  openPrice: tick?.open_price ?? null,
                }}
                points={history[t] ?? EMPTY}
                selected={selected === t}
                onSelect={onSelect}
                onRemove={remove}
              />
            );
          })
        )}
      </ul>
    </Panel>
  );
}
