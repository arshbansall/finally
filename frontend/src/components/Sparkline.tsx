import { memo } from "react";
import type { PricePoint } from "@/lib/types";

interface SparklineProps {
  points: PricePoint[];
  width?: number;
  height?: number;
  /** Reference price (session open) used to colour the line. */
  baseline?: number | null;
}

/** Drawn in a fixed coordinate box and stretched to the available width. */
function frame(width: number, height: number) {
  return {
    viewBox: `0 0 ${width} ${height}`,
    width: "100%",
    height,
    preserveAspectRatio: "none",
    "aria-hidden": true,
    "data-testid": "sparkline",
    className: "block",
  } as const;
}

function Sparkline({ points, width = 84, height = 24, baseline }: SparklineProps) {
  if (points.length < 2) {
    return (
      <svg {...frame(width, height)} data-points={points.length}>
        <line x1={0} x2={width} y1={height / 2} y2={height / 2} stroke="#263142" strokeDasharray="2 3" vectorEffect="non-scaling-stroke" />
      </svg>
    );
  }
  let min = Infinity;
  let max = -Infinity;
  for (const p of points) {
    if (p.price < min) min = p.price;
    if (p.price > max) max = p.price;
  }
  const range = max - min || 1;
  const pad = 2;
  const step = (width - pad * 2) / (points.length - 1);
  const d = points
    .map((p, i) => {
      const x = pad + i * step;
      const y = pad + (height - pad * 2) * (1 - (p.price - min) / range);
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join("");
  const last = points[points.length - 1].price;
  const ref = baseline ?? points[0].price;
  const color = last > ref ? "#26b36b" : last < ref ? "#e5484d" : "#8592a6";
  return (
    <svg {...frame(width, height)} data-points={points.length}>
      <path d={d} fill="none" stroke={color} strokeWidth={1.25} strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export default memo(Sparkline);
