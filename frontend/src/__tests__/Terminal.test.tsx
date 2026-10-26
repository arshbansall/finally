import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Terminal from "@/components/Terminal";
import { MockEventSource } from "./mocks/eventSource";
import { portfolio, tick } from "./fixtures";

const emptyPortfolio = { cash_balance: 10000, positions_value: 0, total_value: 10000, unrealized_pnl: 0, unrealized_pnl_pct: 0, positions: [] };

function json(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
}

describe("Terminal", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  let watchlist: string[];

  beforeEach(() => {
    MockEventSource.install();
    watchlist = ["AAPL", "MSFT"];
    fetchMock = vi.fn((url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (url === "/api/watchlist" && method === "GET")
        return json({ tickers: watchlist.map((t) => ({ ticker: t, price: null, previous_price: null, change_pct: null, direction: null })) });
      if (url === "/api/watchlist" && method === "POST") {
        const { ticker } = JSON.parse(String(init?.body));
        watchlist.push(ticker);
        return json({ ticker }, 201);
      }
      if (url.startsWith("/api/watchlist/") && method === "DELETE") {
        const t = url.split("/").pop()!;
        watchlist = watchlist.filter((x) => x !== t);
        return json({ ticker: t });
      }
      if (url === "/api/portfolio") return json(emptyPortfolio);
      if (url === "/api/portfolio/history") return json({ snapshots: [{ total_value: 10000, recorded_at: "2026-10-26T15:00:00Z" }] });
      if (url === "/api/portfolio/trade")
        return json({ trade: { id: "1", ticker: "AAPL", side: "buy", quantity: 10, price: 190.5, executed_at: "" }, portfolio });
      if (url === "/api/chat") return json({ messages: [] });
      return json({ detail: "not found" }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => vi.unstubAllGlobals());

  it("loads the watchlist, cash and streams prices", async () => {
    render(<Terminal />);
    expect(await screen.findByTestId("watchlist-row-AAPL")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("header-cash")).toHaveTextContent("$10,000.00"));
    expect(screen.getByTestId("header-total-value")).toHaveTextContent("$10,000.00");
    expect(screen.getByTestId("main-chart")).toHaveAttribute("data-ticker", "AAPL");

    const es = MockEventSource.latest();
    act(() => {
      es.open();
      es.emit({ AAPL: tick("AAPL", 190.12), MSFT: tick("MSFT", 410) });
    });
    expect(screen.getByTestId("connection-status")).toHaveAttribute("data-status", "connected");
    expect(screen.getByTestId("watchlist-price-AAPL")).toHaveTextContent("190.12");
  });

  it("selects a ticker in the main chart and trade bar", async () => {
    const user = userEvent.setup();
    render(<Terminal />);
    await user.click(await screen.findByTestId("watchlist-row-MSFT"));
    expect(screen.getByTestId("main-chart")).toHaveAttribute("data-ticker", "MSFT");
    expect(screen.getByTestId("trade-ticker-input")).toHaveValue("MSFT");
  });

  it("buys shares and shows the new position with updated cash", async () => {
    const user = userEvent.setup();
    render(<Terminal />);
    await screen.findByTestId("watchlist-row-AAPL");
    await user.clear(screen.getByTestId("trade-ticker-input"));
    await user.type(screen.getByTestId("trade-ticker-input"), "AAPL");
    await user.type(screen.getByTestId("trade-quantity-input"), "10");
    await user.click(screen.getByTestId("trade-buy-button"));
    expect(await screen.findByTestId("position-row-AAPL")).toBeInTheDocument();
    expect(screen.getByTestId("header-cash")).toHaveTextContent("$8,100.00");
    expect(screen.getByTestId("heatmap-cell-AAPL")).toBeInTheDocument();
  });

  it("adds and removes watchlist tickers", async () => {
    const user = userEvent.setup();
    render(<Terminal />);
    await screen.findByTestId("watchlist-row-AAPL");
    await user.type(screen.getByTestId("watchlist-add-input"), "PYPL");
    await user.click(screen.getByTestId("watchlist-add-button"));
    expect(await screen.findByTestId("watchlist-row-PYPL")).toBeInTheDocument();
    await user.click(screen.getByTestId("watchlist-remove-PYPL"));
    await waitFor(() => expect(screen.queryByTestId("watchlist-row-PYPL")).not.toBeInTheDocument());
  });
});
