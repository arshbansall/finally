"use client";

import { useMemo } from "react";
import type { Snapshot } from "@/lib/types";
import { formatMoney, formatSignedMoney, trendClass } from "@/lib/format";
import Panel from "./Panel";
import TimeSeriesChart, { type SeriesPoint } from "./TimeSeriesChart";

interface PnlChartProps {
  snapshots: Snapshot[];
  /** Live total value, appended as the newest point. */
  liveValue: number | null;
}

export function snapshotsToSeries(snapshots: Snapshot[], liveValue: number | null, now = Date.now()): SeriesPoint[] {
  const pts: SeriesPoint[] = [];
  for (const s of snapshots) {
    const ms = Date.parse(s.recorded_at);
    if (Number.isFinite(ms) && Number.isFinite(s.total_value)) pts.push({ time: ms / 1000, value: s.total_value });
  }
  pts.sort((a, b) => a.time - b.time);
  const last = pts[pts.length - 1];
  const nowSec = now / 1000;
  if (liveValue != null && Number.isFinite(liveValue) && (!last || Math.floor(nowSec) > Math.floor(last.time))) {
    pts.push({ time: nowSec, value: liveValue });
  }
  return pts;
}

export default function PnlChart({ snapshots, liveValue }: PnlChartProps) {
  const data = useMemo(() => snapshotsToSeries(snapshots, liveValue), [snapshots, liveValue]);
  const start = data[0]?.value ?? null;
  const change = start != null && liveValue != null ? liveValue - start : null;
  return (
    <Panel
      title="Portfolio value"
      testId="pnl-chart"
      data={{ "data-points": data.length }}
      aside={
        start != null ? (
          <span className="num">
            <span className="text-fg-faint">since {formatMoney(start)} </span>
            <span className={trendClass(change)}>{formatSignedMoney(change)}</span>
          </span>
        ) : null
      }
      bodyClassName="relative"
    >
      <TimeSeriesChart data={data} color="#ecad0a" baseline={start} baselineLabel="Start" />
      {data.length < 2 ? (
        <p className="pointer-events-none absolute inset-0 flex items-center justify-center text-[12px] text-fg-faint">
          Value history builds up as snapshots are recorded.
        </p>
      ) : null}
    </Panel>
  );
}
