export type Direction = "up" | "down" | "flat";

/** One ticker inside an SSE price event (CONTRACT §5). */
export interface PriceTick {
  ticker: string;
  price: number;
  previous_price: number;
  open_price: number;
  timestamp: string;
  direction: Direction;
  change: number;
  change_pct: number;
}

export type PriceEvent = Record<string, PriceTick>;

export interface PricePoint {
  /** Unix seconds (fractional allowed; charts floor/dedupe as needed). */
  time: number;
  price: number;
}

export interface Position {
  ticker: string;
  quantity: number;
  avg_cost: number;
  current_price: number;
  market_value: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  weight: number;
}

export interface Portfolio {
  cash_balance: number;
  positions_value: number;
  total_value: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  positions: Position[];
}

export interface Trade {
  id: string;
  ticker: string;
  side: "buy" | "sell";
  quantity: number;
  price: number;
  executed_at: string;
}

export interface TradeResponse {
  trade: Trade;
  portfolio: Portfolio;
}

export interface Snapshot {
  total_value: number;
  recorded_at: string;
}

export interface WatchlistItem {
  ticker: string;
  price: number | null;
  previous_price: number | null;
  change_pct: number | null;
  direction: Direction | null;
}

export type ActionStatus = "executed" | "failed";

export interface ChatTradeAction {
  ticker: string;
  side: "buy" | "sell";
  quantity: number;
  status: ActionStatus;
  price?: number | null;
  error?: string | null;
}

export interface ChatWatchlistAction {
  ticker: string;
  action: "add" | "remove";
  status: ActionStatus;
  error?: string | null;
}

export interface ChatResponse {
  message: string;
  trades: ChatTradeAction[];
  watchlist_changes: ChatWatchlistAction[];
}

export interface StoredChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  actions: unknown;
  created_at: string;
}

/** Normalised message used by the chat UI. */
export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  trades: ChatTradeAction[];
  watchlist_changes: ChatWatchlistAction[];
  pending?: boolean;
}

export type ConnectionStatus = "connected" | "reconnecting" | "disconnected";
