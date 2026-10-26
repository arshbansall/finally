import type {
  ChatResponse,
  Portfolio,
  Snapshot,
  StoredChatMessage,
  TradeResponse,
  WatchlistItem,
} from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function detailToMessage(detail: unknown, fallback: string): string {
  if (typeof detail === "string" && detail) return detail;
  // FastAPI 422s carry a list of {msg, loc}.
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: string };
    if (first?.msg) return first.msg;
  }
  return fallback;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError("Can't reach the server. Check that the backend is running.", 0);
  }
  const text = await res.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = null;
    }
  }
  if (!res.ok) {
    const detail = (body as { detail?: unknown } | null)?.detail;
    throw new ApiError(detailToMessage(detail, `Request failed (${res.status})`), res.status);
  }
  return body as T;
}

export const api = {
  getPortfolio: () => request<Portfolio>("/api/portfolio"),
  getHistory: () =>
    request<{ snapshots: Snapshot[] }>("/api/portfolio/history").then((r) => r.snapshots ?? []),
  trade: (ticker: string, quantity: number, side: "buy" | "sell") =>
    request<TradeResponse>("/api/portfolio/trade", {
      method: "POST",
      body: JSON.stringify({ ticker, quantity, side }),
    }),
  getWatchlist: () =>
    request<{ tickers: WatchlistItem[] }>("/api/watchlist").then((r) => r.tickers ?? []),
  addWatchlist: (ticker: string) =>
    request<WatchlistItem>("/api/watchlist", { method: "POST", body: JSON.stringify({ ticker }) }),
  removeWatchlist: (ticker: string) =>
    request<{ ticker: string }>(`/api/watchlist/${encodeURIComponent(ticker)}`, {
      method: "DELETE",
    }),
  sendChat: (message: string) =>
    request<ChatResponse>("/api/chat", { method: "POST", body: JSON.stringify({ message }) }),
  getChat: () =>
    request<{ messages: StoredChatMessage[] }>("/api/chat").then((r) => r.messages ?? []),
};
