export interface TreemapInput<T> {
  value: number;
  data: T;
}

export interface TreemapRect<T> {
  x: number;
  y: number;
  w: number;
  h: number;
  data: T;
}

/** Worst aspect ratio of a row laid along a side of length `side`. */
function worst(row: number[], side: number): number {
  const sum = row.reduce((a, b) => a + b, 0);
  const max = Math.max(...row);
  const min = Math.min(...row);
  const s2 = side * side;
  const sum2 = sum * sum;
  return Math.max((s2 * max) / sum2, sum2 / (s2 * min));
}

/**
 * Squarified treemap (Bruls, Huizing & van Wijk). Returns rectangles in the same
 * units as width/height, largest values first. Non-positive values are dropped.
 */
export function squarify<T>(items: TreemapInput<T>[], width: number, height: number): TreemapRect<T>[] {
  const sorted = items.filter((i) => i.value > 0).sort((a, b) => b.value - a.value);
  const total = sorted.reduce((s, i) => s + i.value, 0);
  if (!sorted.length || width <= 0 || height <= 0 || total <= 0) return [];

  const scale = (width * height) / total;
  const areas = sorted.map((i) => i.value * scale);
  const out: TreemapRect<T>[] = [];

  let x = 0;
  let y = 0;
  let w = width;
  let h = height;
  let i = 0;

  while (i < areas.length) {
    const side = Math.min(w, h);
    const row: number[] = [areas[i]];
    let j = i + 1;
    while (j < areas.length && worst([...row, areas[j]], side) <= worst(row, side)) {
      row.push(areas[j]);
      j++;
    }
    const rowSum = row.reduce((a, b) => a + b, 0);
    if (w >= h) {
      // Lay the row as a vertical strip on the left.
      const stripW = rowSum / h;
      let cy = y;
      row.forEach((a, k) => {
        const rh = a / stripW;
        out.push({ x, y: cy, w: stripW, h: rh, data: sorted[i + k].data });
        cy += rh;
      });
      x += stripW;
      w -= stripW;
    } else {
      const stripH = rowSum / w;
      let cx = x;
      row.forEach((a, k) => {
        const rw = a / stripH;
        out.push({ x: cx, y, w: rw, h: stripH, data: sorted[i + k].data });
        cx += rw;
      });
      y += stripH;
      h -= stripH;
    }
    i = j;
  }
  return out;
}

/** Map a P&L percent to a fill colour: red (loss) → slate (flat) → green (gain). */
export function pnlColor(pct: number, saturateAt = 4): string {
  const t = Math.max(-1, Math.min(1, pct / saturateAt));
  const neutral = [42, 51, 66];
  const target = t >= 0 ? [22, 138, 80] : [184, 44, 52];
  // sqrt keeps small intraday moves visibly tinted instead of near-grey.
  const k = Math.sqrt(Math.abs(t));
  const mix = neutral.map((n, idx) => Math.round(n + (target[idx] - n) * k));
  return `rgb(${mix[0]}, ${mix[1]}, ${mix[2]})`;
}
