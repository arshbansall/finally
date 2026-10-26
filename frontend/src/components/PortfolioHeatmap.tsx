"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { Position } from "@/lib/types";
import { formatMoney, formatPct } from "@/lib/format";
import { pnlColor, squarify } from "@/lib/treemap";
import Panel from "./Panel";

/** Sign of a position's P&L, rounded to the cent so float noise reads as flat. */
export function pnlSign(pnl: number): "gain" | "loss" | "flat" {
  const cents = Math.round(pnl * 100);
  return cents > 0 ? "gain" : cents < 0 ? "loss" : "flat";
}

interface PortfolioHeatmapProps {
  positions: Position[];
  onSelect?: (ticker: string) => void;
}

export default function PortfolioHeatmap({ positions, onSelect }: PortfolioHeatmapProps) {
  const ref = useRef<HTMLDivElement>(null);
  // Layout is computed in percentages; the measured aspect ratio keeps cells square-ish.
  const [aspect, setAspect] = useState(16 / 9);

  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => {
      const { width, height } = el.getBoundingClientRect();
      if (width > 0 && height > 0) setAspect(width / height);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const rects = useMemo(() => {
    const W = 100 * aspect;
    const H = 100;
    return squarify(
      positions.map((p) => ({ value: p.market_value, data: p })),
      W,
      H,
    ).map((r) => ({ ...r, x: (r.x / W) * 100, w: (r.w / W) * 100, y: r.y, h: r.h }));
  }, [positions, aspect]);

  return (
    <Panel title="Holdings heatmap" aside={<span>size = weight, colour = P&amp;L</span>} bodyClassName="p-1">
      <div ref={ref} className="relative h-full w-full overflow-hidden" data-testid="portfolio-heatmap">
        {rects.length === 0 ? (
          <p className="flex h-full items-center justify-center px-4 text-center text-[12px] text-fg-faint">
            Buy a position to see it here, sized by weight and coloured by profit or loss.
          </p>
        ) : (
          rects.map(({ x, y, w, h, data: p }) => {
            const small = w < 9 || h < 18;
            return (
              <button
                type="button"
                key={p.ticker}
                data-testid={`heatmap-cell-${p.ticker}`}
                data-pnl={pnlSign(p.unrealized_pnl)}
                title={`${p.ticker}: ${formatMoney(p.market_value)} (${p.weight.toFixed(1)}%), P&L ${formatPct(p.unrealized_pnl_pct)}`}
                onClick={() => onSelect?.(p.ticker)}
                className="absolute flex flex-col items-start justify-between overflow-hidden border border-ink-900 p-1.5 text-left transition-colors duration-500 hover:brightness-110"
                style={{
                  left: `${x}%`,
                  top: `${y}%`,
                  width: `${w}%`,
                  height: `${h}%`,
                  backgroundColor: pnlColor(p.unrealized_pnl_pct),
                }}
              >
                <span className="narrow text-[13px] font-bold leading-none text-white">{p.ticker}</span>
                {!small ? (
                  <span className="num text-[11px] leading-tight text-white/85">
                    {formatPct(p.unrealized_pnl_pct)}
                    <br />
                    <span className="text-white/60">{p.weight.toFixed(1)}%</span>
                  </span>
                ) : null}
              </button>
            );
          })
        )}
      </div>
    </Panel>
  );
}
