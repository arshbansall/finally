"use client";

import { useEffect, useRef } from "react";
import {
  AreaSeries,
  ColorType,
  CrosshairMode,
  LineStyle,
  createChart,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";

export interface SeriesPoint {
  time: number; // unix seconds
  value: number;
}

interface TimeSeriesChartProps {
  data: SeriesPoint[];
  color: string;
  /** Optional dashed reference line (e.g. session open, starting cash). */
  baseline?: number | null;
  baselineLabel?: string;
  /** Show seconds on the time axis (live intraday chart). */
  showSeconds?: boolean;
  className?: string;
}

/**
 * Lightweight Charts needs strictly ascending, unique times. Collapse points that
 * share a whole second (keep the latest) and drop anything out of order.
 */
export function normalizeSeries(points: SeriesPoint[]): { time: UTCTimestamp; value: number }[] {
  const out: { time: UTCTimestamp; value: number }[] = [];
  for (const p of points) {
    if (!Number.isFinite(p.value) || !Number.isFinite(p.time)) continue;
    const t = Math.floor(p.time) as UTCTimestamp;
    const last = out[out.length - 1];
    if (last && t < last.time) continue;
    if (last && t === last.time) last.value = p.value;
    else out.push({ time: t, value: p.value });
  }
  return out;
}

function withAlpha(hex: string, alpha: number): string {
  const a = Math.round(alpha * 255)
    .toString(16)
    .padStart(2, "0");
  return `${hex}${a}`;
}

export default function TimeSeriesChart({
  data,
  color,
  baseline,
  baselineLabel,
  showSeconds = false,
  className = "",
}: TimeSeriesChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Area"> | null>(null);
  const lineRef = useRef<IPriceLine | null>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const chart = createChart(el, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#8592a6",
        fontFamily: "Archivo, ui-sans-serif, system-ui, sans-serif",
        fontSize: 11,
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: "rgba(38, 49, 66, 0.45)" },
        horzLines: { color: "rgba(38, 49, 66, 0.45)" },
      },
      rightPriceScale: { borderColor: "#232c3a" },
      timeScale: { borderColor: "#232c3a", timeVisible: true, secondsVisible: showSeconds },
      crosshair: { mode: CrosshairMode.Normal },
      handleScroll: false,
      handleScale: false,
    });
    const series = chart.addSeries(AreaSeries, {
      lineColor: color,
      topColor: withAlpha(color, 0.28),
      bottomColor: withAlpha(color, 0.02),
      lineWidth: 2,
      priceLineVisible: true,
      lastValueVisible: true,
    });
    chartRef.current = chart;
    seriesRef.current = series;
    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      lineRef.current = null;
    };
    // Colour/axis options are applied in their own effect; chart is created once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    seriesRef.current?.applyOptions({
      lineColor: color,
      topColor: withAlpha(color, 0.28),
      bottomColor: withAlpha(color, 0.02),
    });
  }, [color]);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;
    const normalized = normalizeSeries(data);
    series.setData(normalized);
    // Charts are not pannable, so keep the whole series in view as it grows.
    chartRef.current?.timeScale().fitContent();
  }, [data]);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;
    if (lineRef.current) {
      series.removePriceLine(lineRef.current);
      lineRef.current = null;
    }
    if (baseline != null && Number.isFinite(baseline)) {
      lineRef.current = series.createPriceLine({
        price: baseline,
        color: "#566275",
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: baselineLabel ?? "",
      });
    }
  }, [baseline, baselineLabel]);

  return <div ref={containerRef} className={`h-full w-full ${className}`} />;
}
