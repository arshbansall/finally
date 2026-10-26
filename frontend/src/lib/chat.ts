import type {
  ChatMessage,
  ChatResponse,
  ChatTradeAction,
  ChatWatchlistAction,
  StoredChatMessage,
} from "./types";

function asArray<T>(v: unknown): T[] {
  return Array.isArray(v) ? (v as T[]) : [];
}

/** Stored `actions` may be `{trades, watchlist_changes}` or a flat list; accept both. */
export function splitActions(actions: unknown): {
  trades: ChatTradeAction[];
  watchlist_changes: ChatWatchlistAction[];
} {
  if (!actions) return { trades: [], watchlist_changes: [] };
  if (Array.isArray(actions)) {
    const trades: ChatTradeAction[] = [];
    const watchlist_changes: ChatWatchlistAction[] = [];
    for (const a of actions as Record<string, unknown>[]) {
      if (a && "side" in a) trades.push(a as unknown as ChatTradeAction);
      else if (a && "action" in a) watchlist_changes.push(a as unknown as ChatWatchlistAction);
    }
    return { trades, watchlist_changes };
  }
  const obj = actions as Record<string, unknown>;
  return {
    trades: asArray<ChatTradeAction>(obj.trades),
    watchlist_changes: asArray<ChatWatchlistAction>(obj.watchlist_changes),
  };
}

export function fromStored(m: StoredChatMessage): ChatMessage {
  return { id: m.id, role: m.role, content: m.content, ...splitActions(m.actions) };
}

export function fromResponse(id: string, r: ChatResponse): ChatMessage {
  return {
    id,
    role: "assistant",
    content: r.message,
    trades: asArray<ChatTradeAction>(r.trades),
    watchlist_changes: asArray<ChatWatchlistAction>(r.watchlist_changes),
  };
}
