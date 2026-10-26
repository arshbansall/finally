import { describe, expect, it } from "vitest";
import { formatMoney, formatPct, formatPrice, formatQty, formatSignedMoney, trendClass } from "@/lib/format";
import { revaluePortfolio } from "@/lib/portfolio";
import { pnlColor, squarify } from "@/lib/treemap";
import { fromResponse, fromStored, splitActions } from "@/lib/chat";
import { appendHistory } from "@/hooks/usePriceStream";
import { normalizeSeries } from "@/components/TimeSeriesChart";
import { snapshotsToSeries } from "@/components/PnlChart";
import { portfolio, tick } from "./fixtures";

describe("format", () => {
  it("formats money with separators and two decimals", () => {
    expect(formatMoney(10000)).toBe("$10,000.00");
    expect(formatMoney(1234.5)).toBe("$1,234.50");
    expect(formatMoney(null)).toBe("—");
  });
  it("formats signed values", () => {
    expect(formatSignedMoney(12.3)).toBe("+$12.30");
    expect(formatSignedMoney(-4)).toBe("−$4.00");
    expect(formatSignedMoney(0)).toBe("$0.00");
    expect(formatPct(1.234)).toBe("+1.23%");
    expect(formatPct(-0.4)).toBe("−0.40%");
    expect(formatPct(undefined)).toBe("—");
  });
  it("formats prices and quantities", () => {
    expect(formatPrice(190.1)).toBe("190.10");
    expect(formatQty(10)).toBe("10");
    expect(formatQty(0.12345)).toBe("0.1235");
  });
  it("picks trend colours", () => {
    expect(trendClass(1)).toBe("text-up");
    expect(trendClass(-1)).toBe("text-down");
    expect(trendClass(0)).toBe("text-fg-muted");
  });
});

describe("revaluePortfolio", () => {
  it("re-marks positions to live prices", () => {
    const live = revaluePortfolio(portfolio, { AAPL: tick("AAPL", 200) });
    expect(live.positions[0].current_price).toBe(200);
    expect(live.positions[0].market_value).toBe(2000);
    expect(live.positions[0].unrealized_pnl).toBe(100);
    expect(live.positions[0].unrealized_pnl_pct).toBeCloseTo(5.263, 2);
    expect(live.positions_value).toBe(2000);
    expect(live.total_value).toBe(10100);
    expect(live.unrealized_pnl).toBe(100);
    expect(live.positions[0].weight).toBe(100);
  });
  it("keeps server prices when no tick is available", () => {
    const live = revaluePortfolio(portfolio, {});
    expect(live.total_value).toBeCloseTo(10005);
    expect(live.positions[0].current_price).toBe(190.5);
  });
  it("handles an empty portfolio", () => {
    const live = revaluePortfolio({ ...portfolio, positions: [], positions_value: 0 }, {});
    expect(live.total_value).toBe(8100);
    expect(live.unrealized_pnl_pct).toBe(0);
  });
});

describe("squarify", () => {
  it("tiles the full area with areas proportional to value", () => {
    const rects = squarify(
      [
        { value: 6, data: "a" },
        { value: 3, data: "b" },
        { value: 1, data: "c" },
      ],
      100,
      50,
    );
    expect(rects).toHaveLength(3);
    const total = rects.reduce((s, r) => s + r.w * r.h, 0);
    expect(total).toBeCloseTo(5000);
    const a = rects.find((r) => r.data === "a")!;
    expect(a.w * a.h).toBeCloseTo(3000);
    for (const r of rects) {
      expect(r.x).toBeGreaterThanOrEqual(-1e-9);
      expect(r.y).toBeGreaterThanOrEqual(-1e-9);
      expect(r.x + r.w).toBeLessThanOrEqual(100 + 1e-9);
      expect(r.y + r.h).toBeLessThanOrEqual(50 + 1e-9);
    }
  });
  it("drops non-positive values and handles empty input", () => {
    expect(squarify([{ value: 0, data: 1 }], 10, 10)).toEqual([]);
    expect(squarify([], 10, 10)).toEqual([]);
  });
  it("colours gains green and losses red", () => {
    const [r1, g1] = pnlColor(5).match(/\d+/g)!.map(Number);
    const [r2, g2] = pnlColor(-5).match(/\d+/g)!.map(Number);
    expect(g1).toBeGreaterThan(r1);
    expect(r2).toBeGreaterThan(g2);
  });
});

describe("chat helpers", () => {
  it("splits stored actions in object or list form", () => {
    const trade = { ticker: "AAPL", side: "buy", quantity: 1, status: "executed" };
    const wl = { ticker: "PYPL", action: "add", status: "executed" };
    expect(splitActions({ trades: [trade], watchlist_changes: [wl] })).toEqual({ trades: [trade], watchlist_changes: [wl] });
    expect(splitActions([trade, wl])).toEqual({ trades: [trade], watchlist_changes: [wl] });
    expect(splitActions(null)).toEqual({ trades: [], watchlist_changes: [] });
  });
  it("normalises stored and fresh messages", () => {
    const m = fromStored({ id: "1", role: "user", content: "hi", actions: null, created_at: "" });
    expect(m).toMatchObject({ id: "1", role: "user", content: "hi", trades: [] });
    const r = fromResponse("2", { message: "ok", trades: [], watchlist_changes: [] });
    expect(r.role).toBe("assistant");
  });
});

describe("series helpers", () => {
  it("appends bounded history per ticker and skips duplicate ticks", () => {
    let h = appendHistory({}, { AAPL: tick("AAPL", 1, { timestamp: "2026-10-26T15:00:00Z" }) }, 3);
    h = appendHistory(h, { AAPL: tick("AAPL", 1, { timestamp: "2026-10-26T15:00:00Z" }) }, 3);
    expect(h.AAPL).toHaveLength(1);
    for (let i = 1; i <= 5; i++) {
      h = appendHistory(h, { AAPL: tick("AAPL", 1 + i, { timestamp: `2026-10-26T15:00:0${i}Z` }) }, 3);
    }
    expect(h.AAPL.map((p) => p.price)).toEqual([4, 5, 6]);
  });
  it("normalises chart data to ascending unique seconds", () => {
    expect(
      normalizeSeries([
        { time: 10.2, value: 1 },
        { time: 10.7, value: 2 },
        { time: 9, value: 3 },
        { time: 11, value: 4 },
      ]),
    ).toEqual([
      { time: 10, value: 2 },
      { time: 11, value: 4 },
    ]);
  });
  it("builds the P&L series from snapshots plus a live tail", () => {
    const now = Date.parse("2026-10-26T15:10:00Z");
    const s = snapshotsToSeries(
      [
        { total_value: 10000, recorded_at: "2026-10-26T15:00:00Z" },
        { total_value: 10050, recorded_at: "2026-10-26T15:05:00Z" },
      ],
      10100,
      now,
    );
    expect(s.map((p) => p.value)).toEqual([10000, 10050, 10100]);
  });
});
