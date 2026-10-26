"use client";

import { useMemo } from "react";
import type { PricePoint, PriceTick } from "@/lib/types";
import { formatPct, formatPrice, formatSignedMoney, trendClass } from "@/lib/format";
import Panel from "./Panel";
import TimeSeriesChart from "./TimeSeriesChart";

interface MainChartProps {
  ticker: string | null;
  tick: PriceTick | undefined;
  points: PricePoint[];
}

export default function MainChart({ ticker, tick, points }: MainChartProps) {
  const data = useMemo(() => points.map((p) => ({ time: p.time, value: p.price })), [points]);
  return (
    <Panel
      title={ticker ?? "Chart"}
      testId="main-chart"
      data={{ "data-ticker": ticker ?? "", "data-points": points.length }}
      aside={
        tick ? (
          <span className="num flex items-baseline gap-3 text-[12px]">
            <span className="text-fg-faint">Open {formatPrice(tick.open_price)}</span>
            <span className="text-[14px] font-semibold text-fg">{formatPrice(tick.price)}</span>
            <span className={trendClass(tick.change)}>
              {formatSignedMoney(tick.change)} {formatPct(tick.change_pct)}
            </span>
          </span>
        ) : null
      }
      bodyClassName="relative"
    >
      {ticker ? (
        <>
          <TimeSeriesChart data={data} color="#209dd7" baseline={tick?.open_price} baselineLabel="Open" showSeconds />
          {points.length < 2 ? (
            <p className="pointer-events-none absolute inset-0 flex items-center justify-center text-[12px] text-fg-faint">
              Collecting live prices for {ticker}…
            </p>
          ) : null}
        </>
      ) : (
        <p className="flex h-full items-center justify-center text-[12px] text-fg-faint">
          Select a ticker in the watchlist to chart it.
        </p>
      )}
    </Panel>
  );
}
