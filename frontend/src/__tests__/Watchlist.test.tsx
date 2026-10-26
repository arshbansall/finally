import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import Watchlist from "@/components/Watchlist";
import type { PriceTick } from "@/lib/types";
import { tick } from "./fixtures";

function setup(prices: Record<string, PriceTick>, overrides: Partial<Parameters<typeof Watchlist>[0]> = {}) {
  const props = {
    tickers: ["AAPL", "MSFT"],
    prices,
    history: {},
    selected: "AAPL",
    onSelect: vi.fn(),
    onAdd: vi.fn().mockResolvedValue(undefined),
    onRemove: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
  const utils = render(<Watchlist {...props} />);
  return { ...utils, props };
}

describe("Watchlist", () => {
  it("renders a row per ticker with price and change", () => {
    setup({ AAPL: tick("AAPL", 101.5), MSFT: tick("MSFT", 99) });
    expect(screen.getByTestId("watchlist")).toBeInTheDocument();
    expect(screen.getByTestId("watchlist-row-AAPL")).toBeInTheDocument();
    expect(screen.getByTestId("watchlist-price-AAPL")).toHaveTextContent("101.50");
    expect(screen.getByTestId("watchlist-change-AAPL")).toHaveTextContent("+1.50%");
    expect(screen.getByTestId("watchlist-change-MSFT")).toHaveTextContent("−1.00%");
    expect(screen.getByTestId("watchlist-row-AAPL")).toHaveAttribute("data-selected", "true");
  });

  it("falls back to REST quotes before the first tick", () => {
    setup({}, { fallback: { AAPL: { price: 190.12, change_pct: 0.06 } } });
    expect(screen.getByTestId("watchlist-price-AAPL")).toHaveTextContent("190.12");
    expect(screen.getByTestId("watchlist-price-MSFT")).toHaveTextContent("—");
  });

  it("flashes green on an uptick and red on a downtick, then clears", () => {
    vi.useFakeTimers();
    const { rerender, props } = setup({ AAPL: tick("AAPL", 100) });
    const cell = screen.getByTestId("watchlist-price-AAPL");
    expect(cell.className).not.toMatch(/flash/);

    rerender(<Watchlist {...props} prices={{ AAPL: tick("AAPL", 101) }} />);
    expect(cell).toHaveClass("flash-up");
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(cell.className).not.toMatch(/flash-/);

    rerender(<Watchlist {...props} prices={{ AAPL: tick("AAPL", 99) }} />);
    expect(cell).toHaveClass("flash-down");
    vi.useRealTimers();
  });

  it("does not flash when the price is unchanged", () => {
    const { rerender, props } = setup({ AAPL: tick("AAPL", 100) });
    rerender(<Watchlist {...props} prices={{ AAPL: tick("AAPL", 100) }} />);
    expect(screen.getByTestId("watchlist-price-AAPL").className).not.toMatch(/flash-/);
  });

  it("adds a ticker (uppercased) and clears the input", async () => {
    const user = userEvent.setup();
    const { props } = setup({});
    await user.type(screen.getByTestId("watchlist-add-input"), "pypl");
    await user.click(screen.getByTestId("watchlist-add-button"));
    expect(props.onAdd).toHaveBeenCalledWith("PYPL");
    await waitFor(() => expect(screen.getByTestId("watchlist-add-input")).toHaveValue(""));
  });

  it("shows the API error when adding fails", async () => {
    const user = userEvent.setup();
    setup({}, { onAdd: vi.fn().mockRejectedValue(new Error("PYPL is already in your watchlist")) });
    await user.type(screen.getByTestId("watchlist-add-input"), "PYPL{enter}");
    expect(await screen.findByTestId("watchlist-error")).toHaveTextContent("already in your watchlist");
  });

  it("removes a ticker without selecting the row", async () => {
    const user = userEvent.setup();
    const { props } = setup({});
    await user.click(screen.getByTestId("watchlist-remove-MSFT"));
    expect(props.onRemove).toHaveBeenCalledWith("MSFT");
    expect(props.onSelect).not.toHaveBeenCalled();
  });

  it("selects a ticker on click", async () => {
    const user = userEvent.setup();
    const { props } = setup({});
    await user.click(screen.getByTestId("watchlist-row-MSFT"));
    expect(props.onSelect).toHaveBeenCalledWith("MSFT");
  });

  it("renders sparklines from accumulated history", () => {
    setup(
      {},
      {
        history: {
          AAPL: [
            { time: 1, price: 1 },
            { time: 2, price: 2 },
            { time: 3, price: 1.5 },
          ],
        },
      },
    );
    const sparks = screen.getAllByTestId("sparkline");
    expect(sparks[0]).toHaveAttribute("data-points", "3");
    expect(sparks[0].querySelector("path")).not.toBeNull();
  });
});
