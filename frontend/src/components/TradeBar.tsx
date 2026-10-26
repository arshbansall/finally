"use client";

import { useEffect, useState, type FormEvent } from "react";
import type { Trade } from "@/lib/types";
import { formatMoney, formatQty } from "@/lib/format";

interface TradeBarProps {
  /** Selecting a ticker elsewhere pre-fills the ticker field. */
  selectedTicker: string | null;
  /** Latest price for the ticker in the field, for the cost estimate. */
  priceFor: (ticker: string) => number | null;
  onTrade: (ticker: string, quantity: number, side: "buy" | "sell") => Promise<Trade>;
}

export default function TradeBar({ selectedTicker, priceFor, onTrade }: TradeBarProps) {
  const [ticker, setTicker] = useState(selectedTicker ?? "");
  const [quantity, setQuantity] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState<string | null>(null);
  const [busy, setBusy] = useState<"buy" | "sell" | null>(null);

  useEffect(() => {
    if (selectedTicker) setTicker(selectedTicker);
  }, [selectedTicker]);

  const qty = Number(quantity);
  const price = ticker ? priceFor(ticker.trim().toUpperCase()) : null;
  const estimate = price != null && qty > 0 ? price * qty : null;

  const submit = async (side: "buy" | "sell") => {
    const t = ticker.trim().toUpperCase();
    setConfirmation(null);
    if (!t) {
      setError("Enter a ticker symbol.");
      return;
    }
    if (!quantity.trim() || !Number.isFinite(qty) || qty <= 0) {
      setError("Enter a quantity greater than zero.");
      return;
    }
    setBusy(side);
    setError(null);
    try {
      const trade = await onTrade(t, qty, side);
      setConfirmation(
        `${trade.side === "buy" ? "Bought" : "Sold"} ${formatQty(trade.quantity)} ${trade.ticker} at ${formatMoney(trade.price)}`,
      );
      setQuantity("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Trade failed.");
    } finally {
      setBusy(null);
    }
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void submit("buy");
  };

  return (
    <form onSubmit={onSubmit} className="flex flex-wrap items-center gap-2 bg-ink-900 px-3 py-2" aria-label="Place a market order">
      <span className="narrow mr-1 text-[12px] font-semibold text-fg-muted">Market order</span>
      <input
        data-testid="trade-ticker-input"
        aria-label="Ticker"
        placeholder="Ticker"
        value={ticker}
        maxLength={10}
        onChange={(e) => setTicker(e.target.value.toUpperCase())}
        className="narrow w-24 rounded-sm border border-line bg-ink-950 px-2 py-1.5 text-[13px] font-semibold uppercase text-fg placeholder:font-normal placeholder:normal-case placeholder:text-fg-faint focus:border-primary focus:outline-none"
      />
      <input
        data-testid="trade-quantity-input"
        aria-label="Quantity"
        placeholder="Qty"
        type="number"
        inputMode="decimal"
        min="0"
        step="any"
        value={quantity}
        onChange={(e) => setQuantity(e.target.value)}
        className="num w-24 rounded-sm border border-line bg-ink-950 px-2 py-1.5 text-[13px] text-fg placeholder:text-fg-faint focus:border-primary focus:outline-none"
      />
      <button
        type="button"
        data-testid="trade-buy-button"
        disabled={busy !== null}
        onClick={() => void submit("buy")}
        className="rounded-sm bg-up px-4 py-1.5 text-[12px] font-bold text-ink-950 hover:brightness-110 disabled:opacity-50"
      >
        {busy === "buy" ? "Buying…" : "Buy"}
      </button>
      <button
        type="button"
        data-testid="trade-sell-button"
        disabled={busy !== null}
        onClick={() => void submit("sell")}
        className="rounded-sm bg-down px-4 py-1.5 text-[12px] font-bold text-white hover:brightness-110 disabled:opacity-50"
      >
        {busy === "sell" ? "Selling…" : "Sell"}
      </button>
      <span className="num text-[12px] text-fg-faint" data-testid="trade-estimate">
        {estimate != null ? `≈ ${formatMoney(estimate)}` : price != null ? `@ ${formatMoney(price)}` : ""}
      </span>
      <div className="ml-auto min-w-0 text-[12px]" aria-live="polite">
        {error ? (
          <span className="text-down" data-testid="trade-error" role="alert">
            {error}
          </span>
        ) : confirmation ? (
          <span className="text-up" data-testid="trade-confirmation">
            {confirmation}
          </span>
        ) : null}
      </div>
    </form>
  );
}
