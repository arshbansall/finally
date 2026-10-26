"use client";

import { useEffect, useRef, useState } from "react";
import type { ConnectionStatus, PriceEvent, PricePoint, PriceTick } from "@/lib/types";

/** ~8 minutes of history at the simulator's 500ms cadence. */
export const MAX_HISTORY = 1000;
/** Backoff when the browser gives up on the EventSource (readyState CLOSED). */
const RECONNECT_DELAY_MS = 2000;
/** Browsers retry refused connections forever; after this long, call it disconnected. */
export const DISCONNECTED_AFTER_MS = 5000;

export interface PriceStreamState {
  prices: PriceEvent;
  history: Record<string, PricePoint[]>;
  status: ConnectionStatus;
}

function toSeconds(ts: string | undefined): number {
  const ms = ts ? Date.parse(ts) : NaN;
  return (Number.isFinite(ms) ? ms : Date.now()) / 1000;
}

/** Fold one SSE event into the accumulated per-ticker history (pure, bounded). */
export function appendHistory(
  history: Record<string, PricePoint[]>,
  event: PriceEvent,
  max = MAX_HISTORY,
): Record<string, PricePoint[]> {
  const next: Record<string, PricePoint[]> = { ...history };
  for (const [ticker, tick] of Object.entries(event)) {
    if (!tick || typeof tick.price !== "number") continue;
    const prev = next[ticker] ?? [];
    const point = { time: toSeconds(tick.timestamp), price: tick.price };
    const last = prev[prev.length - 1];
    // Skip repeats of the same tick (the stream resends the full cache each cadence).
    if (last && last.time === point.time && last.price === point.price) continue;
    const series = prev.length >= max ? prev.slice(prev.length - max + 1) : prev.slice();
    series.push(point);
    next[ticker] = series;
  }
  return next;
}

export function usePriceStream(url = "/api/stream/prices"): PriceStreamState {
  const [state, setState] = useState<PriceStreamState>({
    prices: {},
    history: {},
    status: "reconnecting",
  });
  const sourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    let disposed = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let downTimer: ReturnType<typeof setTimeout> | null = null;

    const setStatus = (status: ConnectionStatus) =>
      setState((s) => (s.status === status ? s : { ...s, status }));

    const markUp = () => {
      if (downTimer) clearTimeout(downTimer);
      downTimer = null;
    };
    const markTrouble = () => {
      if (!downTimer) downTimer = setTimeout(() => setStatus("disconnected"), DISCONNECTED_AFTER_MS);
    };

    const connect = () => {
      if (disposed) return;
      const es = new EventSource(url);
      sourceRef.current = es;

      es.onopen = () => {
        markUp();
        setStatus("connected");
      };

      es.onmessage = (msg: MessageEvent<string>) => {
        let event: PriceEvent;
        try {
          event = JSON.parse(msg.data) as PriceEvent;
        } catch {
          return;
        }
        if (!event || typeof event !== "object") return;
        markUp();
        setState((s) => {
          const prices: PriceEvent = {};
          for (const [ticker, tick] of Object.entries(event)) {
            if (tick && typeof (tick as PriceTick).price === "number") prices[ticker] = tick;
          }
          return { prices, history: appendHistory(s.history, prices), status: "connected" };
        });
      };

      es.onerror = () => {
        if (disposed) return;
        if (es.readyState === EventSource.CLOSED) {
          // The browser won't retry on its own any more; do it ourselves.
          markUp();
          setStatus("disconnected");
          es.close();
          retryTimer = setTimeout(connect, RECONNECT_DELAY_MS);
        } else {
          setState((s) => (s.status === "disconnected" ? s : { ...s, status: "reconnecting" }));
          markTrouble();
        }
      };
    };

    connect();

    return () => {
      disposed = true;
      if (retryTimer) clearTimeout(retryTimer);
      markUp();
      sourceRef.current?.close();
      sourceRef.current = null;
    };
  }, [url]);

  return state;
}
