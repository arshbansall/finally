import { vi } from "vitest";

/** Minimal stand-in for lightweight-charts (jsdom has no canvas). */
export const charts: Array<{ series: Array<{ setData: ReturnType<typeof vi.fn> }> }> = [];

export const createChart = vi.fn(() => {
  const record = { series: [] as Array<{ setData: ReturnType<typeof vi.fn> }> };
  charts.push(record);
  const timeScale = { fitContent: vi.fn(), applyOptions: vi.fn(), scrollToRealTime: vi.fn() };
  return {
    addSeries: vi.fn(() => {
      const series = {
        setData: vi.fn(),
        update: vi.fn(),
        applyOptions: vi.fn(),
        createPriceLine: vi.fn(() => ({ applyOptions: vi.fn() })),
        removePriceLine: vi.fn(),
      };
      record.series.push(series);
      return series;
    }),
    timeScale: () => timeScale,
    priceScale: () => ({ applyOptions: vi.fn() }),
    applyOptions: vi.fn(),
    remove: vi.fn(),
  };
});

export const AreaSeries = { type: "Area" };
export const LineSeries = { type: "Line" };
export const ColorType = { Solid: "solid", VerticalGradient: "gradient" };
export const CrosshairMode = { Normal: 0, Magnet: 1, Hidden: 2 };
export const LineStyle = { Solid: 0, Dotted: 1, Dashed: 2, LargeDashed: 3, SparseDotted: 4 };
