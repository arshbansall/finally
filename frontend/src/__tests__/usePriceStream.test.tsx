import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { usePriceStream } from "@/hooks/usePriceStream";
import { MockEventSource } from "./mocks/eventSource";
import { tick } from "./fixtures";

describe("usePriceStream", () => {
  beforeEach(() => MockEventSource.install());
  afterEach(() => vi.useRealTimers());

  it("connects to the SSE endpoint and reports status", () => {
    const { result } = renderHook(() => usePriceStream());
    const es = MockEventSource.latest();
    expect(es.url).toBe("/api/stream/prices");
    expect(result.current.status).toBe("reconnecting");
    act(() => es.open());
    expect(result.current.status).toBe("connected");
  });

  it("stores latest prices and accumulates history", () => {
    const { result } = renderHook(() => usePriceStream());
    const es = MockEventSource.latest();
    act(() => {
      es.open();
      es.emit({ AAPL: tick("AAPL", 190, { timestamp: "2026-10-26T15:00:00Z" }) });
      es.emit({ AAPL: tick("AAPL", 191, { timestamp: "2026-10-26T15:00:01Z" }), MSFT: tick("MSFT", 400) });
    });
    expect(result.current.prices.AAPL.price).toBe(191);
    expect(result.current.prices.MSFT.price).toBe(400);
    expect(result.current.history.AAPL.map((p) => p.price)).toEqual([190, 191]);
    expect(result.current.history.MSFT).toHaveLength(1);
  });

  it("ignores malformed events", () => {
    const { result } = renderHook(() => usePriceStream());
    const es = MockEventSource.latest();
    act(() => {
      es.onmessage?.(new MessageEvent("message", { data: "not json" }));
    });
    expect(result.current.prices).toEqual({});
  });

  it("shows reconnecting on a transient error and recovers on reopen", () => {
    const { result } = renderHook(() => usePriceStream());
    const es = MockEventSource.latest();
    act(() => es.open());
    act(() => es.fail(false));
    expect(result.current.status).toBe("reconnecting");
    act(() => es.open());
    expect(result.current.status).toBe("connected");
  });

  it("escalates to disconnected when retries keep failing", () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => usePriceStream());
    const es = MockEventSource.latest();
    act(() => es.open());
    act(() => es.fail(false));
    expect(result.current.status).toBe("reconnecting");
    act(() => {
      vi.advanceTimersByTime(6000);
    });
    expect(result.current.status).toBe("disconnected");
    act(() => es.fail(false));
    expect(result.current.status).toBe("disconnected");
    act(() => es.open());
    expect(result.current.status).toBe("connected");
  });

  it("goes disconnected when the browser gives up, then reconnects itself", () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => usePriceStream());
    const first = MockEventSource.latest();
    act(() => first.fail(true));
    expect(result.current.status).toBe("disconnected");
    expect(first.closed).toBe(true);
    act(() => {
      vi.advanceTimersByTime(2500);
    });
    const second = MockEventSource.latest();
    expect(second).not.toBe(first);
    act(() => second.open());
    expect(result.current.status).toBe("connected");
  });

  it("closes the connection on unmount", () => {
    const { unmount } = renderHook(() => usePriceStream());
    const es = MockEventSource.latest();
    unmount();
    expect(es.closed).toBe(true);
  });
});
