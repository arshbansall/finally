import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import Header from "@/components/Header";
import PositionsTable from "@/components/PositionsTable";
import PortfolioHeatmap from "@/components/PortfolioHeatmap";
import TradeBar from "@/components/TradeBar";
import MainChart from "@/components/MainChart";
import PnlChart from "@/components/PnlChart";
import { ApiError } from "@/lib/api";
import { portfolio, tick, twoPositions } from "./fixtures";

describe("Header", () => {
  it("shows total value, cash and connection status", () => {
    render(<Header totalValue={10000} cash={10000} invested={0} unrealizedPnl={0} unrealizedPnlPct={0} status="connected" />);
    expect(screen.getByTestId("header-total-value")).toHaveTextContent("$10,000.00");
    expect(screen.getByTestId("header-cash")).toHaveTextContent("$10,000.00");
    expect(screen.getByTestId("connection-status")).toHaveAttribute("data-status", "connected");
  });
  it.each(["reconnecting", "disconnected"] as const)("reflects %s", (status) => {
    render(<Header totalValue={null} cash={null} invested={null} unrealizedPnl={null} unrealizedPnlPct={null} status={status} />);
    expect(screen.getByTestId("connection-status")).toHaveAttribute("data-status", status);
  });
});

describe("PositionsTable", () => {
  it("renders one row per position with P&L", () => {
    render(<PositionsTable positions={portfolio.positions} />);
    const row = screen.getByTestId("position-row-AAPL");
    expect(row).toHaveTextContent("AAPL");
    expect(row).toHaveTextContent("190.00");
    expect(row).toHaveTextContent("190.50");
    expect(row).toHaveTextContent("+$5.00");
    expect(row).toHaveTextContent("+0.26%");
  });
  it("shows an empty state", () => {
    render(<PositionsTable positions={[]} />);
    expect(screen.getByTestId("positions-table")).toHaveTextContent("No positions yet");
  });
});

describe("PortfolioHeatmap", () => {
  it("draws a cell per position coloured by P&L", () => {
    render(<PortfolioHeatmap positions={twoPositions.positions} />);
    expect(screen.getByTestId("portfolio-heatmap")).toBeInTheDocument();
    expect(screen.getByTestId("heatmap-cell-AAPL")).toHaveAttribute("data-pnl", "gain");
    expect(screen.getByTestId("heatmap-cell-TSLA")).toHaveAttribute("data-pnl", "loss");
    const tsla = parseFloat(screen.getByTestId("heatmap-cell-TSLA").style.width) * parseFloat(screen.getByTestId("heatmap-cell-TSLA").style.height);
    const aapl = parseFloat(screen.getByTestId("heatmap-cell-AAPL").style.width) * parseFloat(screen.getByTestId("heatmap-cell-AAPL").style.height);
    expect(tsla).toBeGreaterThan(aapl);
  });
  it("marks zero P&L as flat", () => {
    const flat = { ...twoPositions.positions[0], unrealized_pnl: 0.001, unrealized_pnl_pct: 0 };
    render(<PortfolioHeatmap positions={[flat]} />);
    expect(screen.getByTestId("heatmap-cell-AAPL")).toHaveAttribute("data-pnl", "flat");
  });
  it("shows an empty state with no positions", () => {
    render(<PortfolioHeatmap positions={[]} />);
    expect(screen.getByTestId("portfolio-heatmap")).toHaveTextContent("Buy a position");
  });
});

describe("TradeBar", () => {
  const trade = { id: "t1", ticker: "AAPL", side: "buy" as const, quantity: 5, price: 190.12, executed_at: "" };

  it("pre-fills the selected ticker and submits a buy", async () => {
    const user = userEvent.setup();
    const onTrade = vi.fn().mockResolvedValue(trade);
    render(<TradeBar selectedTicker="AAPL" priceFor={() => 190} onTrade={onTrade} />);
    expect(screen.getByTestId("trade-ticker-input")).toHaveValue("AAPL");
    await user.type(screen.getByTestId("trade-quantity-input"), "5");
    expect(screen.getByTestId("trade-estimate")).toHaveTextContent("$950.00");
    await user.click(screen.getByTestId("trade-buy-button"));
    expect(onTrade).toHaveBeenCalledWith("AAPL", 5, "buy");
    expect(await screen.findByTestId("trade-confirmation")).toHaveTextContent("Bought 5 AAPL at $190.12");
    expect(screen.queryByTestId("trade-error")).not.toBeInTheDocument();
  });

  it("shows the API detail when a sell fails", async () => {
    const user = userEvent.setup();
    const onTrade = vi.fn().mockRejectedValue(new ApiError("Insufficient shares: have 0, need 5", 400));
    render(<TradeBar selectedTicker={null} priceFor={() => null} onTrade={onTrade} />);
    await user.type(screen.getByTestId("trade-ticker-input"), "aapl");
    await user.type(screen.getByTestId("trade-quantity-input"), "5");
    await user.click(screen.getByTestId("trade-sell-button"));
    expect(onTrade).toHaveBeenCalledWith("AAPL", 5, "sell");
    expect(await screen.findByTestId("trade-error")).toHaveTextContent("Insufficient shares");
  });

  it("validates quantity before sending", async () => {
    const user = userEvent.setup();
    const onTrade = vi.fn();
    render(<TradeBar selectedTicker="AAPL" priceFor={() => null} onTrade={onTrade} />);
    await user.click(screen.getByTestId("trade-buy-button"));
    await waitFor(() => expect(screen.getByTestId("trade-error")).toHaveTextContent("quantity"));
    expect(onTrade).not.toHaveBeenCalled();
  });
});

describe("charts", () => {
  it("main chart exposes the selected ticker", () => {
    render(
      <MainChart
        ticker="AAPL"
        tick={tick("AAPL", 101)}
        points={[
          { time: 1, price: 100 },
          { time: 2, price: 101 },
        ]}
      />,
    );
    const chart = screen.getByTestId("main-chart");
    expect(chart).toHaveAttribute("data-ticker", "AAPL");
    expect(chart).toHaveAttribute("data-points", "2");
  });
  it("P&L chart counts snapshot points", () => {
    render(<PnlChart snapshots={[{ total_value: 10000, recorded_at: "2020-01-01T15:00:00Z" }]} liveValue={10010} />);
    expect(screen.getByTestId("pnl-chart")).toHaveAttribute("data-points", "2");
  });
});
