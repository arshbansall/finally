"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { revaluePortfolio } from "@/lib/portfolio";
import type { Portfolio, PricePoint, Snapshot, WatchlistItem } from "@/lib/types";
import { usePriceStream } from "@/hooks/usePriceStream";
import ChatPanel from "./ChatPanel";
import Header from "./Header";
import MainChart from "./MainChart";
import PnlChart from "./PnlChart";
import PortfolioHeatmap from "./PortfolioHeatmap";
import PositionsTable from "./PositionsTable";
import TradeBar from "./TradeBar";
import Watchlist from "./Watchlist";

const PORTFOLIO_POLL_MS = 10_000;
const HISTORY_POLL_MS = 30_000;
const NO_POINTS: PricePoint[] = [];

export default function Terminal() {
  const stream = usePriceStream();
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [chatCollapsed, setChatCollapsed] = useState(false);

  const refreshWatchlist = useCallback(async () => {
    try {
      setWatchlist(await api.getWatchlist());
    } catch {
      /* keep the last good list; the stream still updates prices */
    }
  }, []);

  const refreshPortfolio = useCallback(async () => {
    try {
      setPortfolio(await api.getPortfolio());
    } catch {
      /* transient; next poll retries */
    }
  }, []);

  const refreshHistory = useCallback(async () => {
    try {
      setSnapshots(await api.getHistory());
    } catch {
      /* transient; next poll retries */
    }
  }, []);

  useEffect(() => {
    void refreshWatchlist();
    void refreshPortfolio();
    void refreshHistory();
    const p = setInterval(refreshPortfolio, PORTFOLIO_POLL_MS);
    const h = setInterval(refreshHistory, HISTORY_POLL_MS);
    return () => {
      clearInterval(p);
      clearInterval(h);
    };
  }, [refreshWatchlist, refreshPortfolio, refreshHistory]);

  const tickers = useMemo(() => watchlist.map((w) => w.ticker), [watchlist]);
  const fallback = useMemo(
    () => Object.fromEntries(watchlist.map((w) => [w.ticker, { price: w.price, change_pct: w.change_pct }])),
    [watchlist],
  );

  // Keep a valid selection: default to the first watched ticker.
  useEffect(() => {
    if (selected && (tickers.includes(selected) || portfolio?.positions.some((p) => p.ticker === selected))) return;
    setSelected(tickers[0] ?? null);
  }, [tickers, selected, portfolio]);

  const live = useMemo(() => (portfolio ? revaluePortfolio(portfolio, stream.prices) : null), [portfolio, stream.prices]);

  const addTicker = useCallback(
    async (ticker: string) => {
      await api.addWatchlist(ticker);
      await refreshWatchlist();
      setSelected(ticker);
    },
    [refreshWatchlist],
  );

  const removeTicker = useCallback(
    async (ticker: string) => {
      await api.removeWatchlist(ticker);
      await refreshWatchlist();
    },
    [refreshWatchlist],
  );

  const trade = useCallback(
    async (ticker: string, quantity: number, side: "buy" | "sell") => {
      const res = await api.trade(ticker, quantity, side);
      setPortfolio(res.portfolio);
      void refreshHistory();
      void refreshWatchlist();
      return res.trade;
    },
    [refreshHistory, refreshWatchlist],
  );

  const onChatActions = useCallback(() => {
    void refreshPortfolio();
    void refreshHistory();
    void refreshWatchlist();
  }, [refreshPortfolio, refreshHistory, refreshWatchlist]);

  const priceFor = useCallback(
    (ticker: string) => stream.prices[ticker]?.price ?? fallback[ticker]?.price ?? null,
    [stream.prices, fallback],
  );

  return (
    <div className="flex min-h-screen flex-col lg:h-screen lg:min-h-0 lg:overflow-hidden">
      <Header
        totalValue={live?.total_value ?? null}
        cash={live?.cash_balance ?? null}
        invested={live?.positions_value ?? null}
        unrealizedPnl={live?.unrealized_pnl ?? null}
        unrealizedPnlPct={live?.unrealized_pnl_pct ?? null}
        status={stream.status}
      />
      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <main className="grid min-h-0 min-w-0 flex-1 grid-cols-1 gap-px bg-line md:grid-cols-[minmax(240px,300px)_minmax(0,1fr)] lg:grid-rows-[minmax(200px,1.25fr)_auto_minmax(170px,1fr)_minmax(130px,0.8fr)]">
          <div className="h-[420px] min-h-0 md:row-span-4 md:h-auto">
            <Watchlist
              tickers={tickers}
              prices={stream.prices}
              history={stream.history}
              fallback={fallback}
              selected={selected}
              onSelect={setSelected}
              onAdd={addTicker}
              onRemove={removeTicker}
            />
          </div>
          <div className="h-[320px] min-h-0 lg:h-auto">
            <MainChart
              ticker={selected}
              tick={selected ? stream.prices[selected] : undefined}
              points={(selected && stream.history[selected]) || NO_POINTS}
            />
          </div>
          <TradeBar selectedTicker={selected} priceFor={priceFor} onTrade={trade} />
          <div className="grid min-h-0 min-w-0 grid-cols-1 gap-px sm:grid-cols-2">
            <div className="h-[240px] min-h-0 lg:h-auto">
              <PortfolioHeatmap positions={live?.positions ?? []} onSelect={setSelected} />
            </div>
            <div className="h-[240px] min-h-0 lg:h-auto">
              <PnlChart snapshots={snapshots} liveValue={live?.total_value ?? null} />
            </div>
          </div>
          <div className="h-[220px] min-h-0 lg:h-auto">
            <PositionsTable positions={live?.positions ?? []} onSelect={setSelected} />
          </div>
        </main>
        <div className={`flex min-h-0 ${chatCollapsed ? "" : "h-[560px] lg:h-auto"}`}>
          <ChatPanel
            sendMessage={api.sendChat}
            loadHistory={api.getChat}
            onActions={onChatActions}
            collapsed={chatCollapsed}
            onToggle={() => setChatCollapsed((c) => !c)}
          />
        </div>
      </div>
    </div>
  );
}
