"use client";

import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import type { ChatMessage, ChatResponse, ChatTradeAction, ChatWatchlistAction, StoredChatMessage } from "@/lib/types";
import { fromResponse, fromStored } from "@/lib/chat";
import { formatMoney, formatQty } from "@/lib/format";

interface ChatPanelProps {
  sendMessage: (message: string) => Promise<ChatResponse>;
  loadHistory: () => Promise<StoredChatMessage[]>;
  /** Called after a reply that carried trades or watchlist changes. */
  onActions?: (response: ChatResponse) => void;
  collapsed: boolean;
  onToggle: () => void;
}

const SUGGESTIONS = ["How is my portfolio doing?", "Buy 5 AAPL", "Add PYPL to my watchlist"];

let localId = 0;
const nextId = () => `local-${Date.now()}-${++localId}`;

export function TradeActionChip({ action }: { action: ChatTradeAction }) {
  const ok = action.status === "executed";
  const verb = action.side === "buy" ? (ok ? "Bought" : "Buy") : ok ? "Sold" : "Sell";
  return (
    <li
      data-testid="chat-action"
      data-kind="trade"
      data-status={action.status}
      className={`flex items-start gap-2 rounded-sm border px-2 py-1 text-[12px] ${
        ok ? "border-up/40 bg-up/10 text-fg" : "border-down/40 bg-down/10 text-fg"
      }`}
    >
      <span className={`mt-1 h-1.5 w-1.5 shrink-0 rounded-full ${ok ? "bg-up" : "bg-down"}`} aria-hidden />
      <span className="num">
        {verb} {formatQty(action.quantity)} <strong className="narrow font-semibold">{action.ticker}</strong>
        {ok && action.price != null ? ` at ${formatMoney(action.price)}` : null}
        {!ok ? <span className="text-down"> failed: {action.error || "not executed"}</span> : null}
      </span>
    </li>
  );
}

export function WatchlistActionChip({ action }: { action: ChatWatchlistAction }) {
  const ok = action.status === "executed";
  const text = action.action === "add" ? "to watchlist" : "from watchlist";
  const verb = action.action === "add" ? (ok ? "Added" : "Add") : ok ? "Removed" : "Remove";
  return (
    <li
      data-testid="chat-action"
      data-kind="watchlist"
      data-status={action.status}
      className={`flex items-start gap-2 rounded-sm border px-2 py-1 text-[12px] ${
        ok ? "border-primary/40 bg-primary/10 text-fg" : "border-down/40 bg-down/10 text-fg"
      }`}
    >
      <span className={`mt-1 h-1.5 w-1.5 shrink-0 rounded-full ${ok ? "bg-primary" : "bg-down"}`} aria-hidden />
      <span>
        {verb} <strong className="narrow font-semibold">{action.ticker}</strong> {text}
        {!ok ? <span className="text-down"> failed: {action.error || "not applied"}</span> : null}
      </span>
    </li>
  );
}

export function ChatBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  const hasActions = message.trades.length > 0 || message.watchlist_changes.length > 0;
  return (
    <div className={`flex flex-col gap-1.5 ${isUser ? "items-end" : "items-start"}`}>
      <div
        data-testid="chat-message"
        data-role={message.role}
        className={`max-w-[92%] whitespace-pre-wrap break-words rounded-md px-3 py-2 text-[13px] leading-[1.45] ${
          isUser ? "bg-primary/15 text-fg" : "border border-line bg-ink-850 text-fg"
        }`}
      >
        {message.content}
      </div>
      {hasActions ? (
        <ul className="flex w-[92%] flex-col gap-1">
          {message.trades.map((t, i) => (
            <TradeActionChip key={`t${i}`} action={t} />
          ))}
          {message.watchlist_changes.map((w, i) => (
            <WatchlistActionChip key={`w${i}`} action={w} />
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export default function ChatPanel({ sendMessage, loadHistory, onActions, collapsed, onToggle }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    loadHistory()
      .then((stored) => {
        if (cancelled) return;
        // Keep anything sent before history arrived.
        setMessages((current) => [...stored.map(fromStored), ...current]);
      })
      .catch(() => {
        /* History is a nicety; an empty conversation is fine. */
      });
    return () => {
      cancelled = true;
    };
  }, [loadHistory]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, loading, collapsed]);

  const send = async (text: string) => {
    const message = text.trim();
    if (!message || loading) return;
    setError(null);
    setInput("");
    setMessages((m) => [...m, { id: nextId(), role: "user", content: message, trades: [], watchlist_changes: [] }]);
    setLoading(true);
    try {
      const response = await sendMessage(message);
      setMessages((m) => [...m, fromResponse(nextId(), response)]);
      if ((response.trades?.length ?? 0) > 0 || (response.watchlist_changes?.length ?? 0) > 0) {
        onActions?.(response);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "FinAlly couldn't respond. Try again.");
    } finally {
      setLoading(false);
    }
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void send(input);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send(input);
    }
  };

  if (collapsed) {
    return (
      <aside data-testid="chat-panel" data-collapsed="true" className="flex w-10 shrink-0 flex-col items-center border-l border-line bg-ink-900">
        <button
          type="button"
          onClick={onToggle}
          data-testid="chat-toggle"
          aria-label="Open FinAlly chat"
          aria-expanded={false}
          className="mt-2 flex h-8 w-8 items-center justify-center rounded-sm text-accent hover:bg-ink-800"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden>
            <path d="M10 3L5 8l5 5" stroke="currentColor" strokeWidth="1.6" fill="none" />
          </svg>
        </button>
        <span className="narrow mt-3 text-[12px] font-semibold text-fg-muted [writing-mode:vertical-rl]">FinAlly chat</span>
      </aside>
    );
  }

  return (
    <aside
      data-testid="chat-panel"
      data-collapsed="false"
      className="flex w-full shrink-0 flex-col border-l border-line bg-ink-900 lg:w-[360px] xl:w-[400px]"
      aria-label="FinAlly AI assistant"
    >
      <header className="flex h-8 shrink-0 items-center justify-between border-b border-line px-3">
        <h2 className="narrow text-[12px] font-semibold tracking-wide text-fg-muted">
          <span className="text-accent">FinAlly</span> assistant
        </h2>
        <button
          type="button"
          onClick={onToggle}
          data-testid="chat-toggle"
          aria-label="Collapse chat"
          aria-expanded
          className="flex h-6 w-6 items-center justify-center rounded-sm text-fg-faint hover:bg-ink-800 hover:text-fg"
        >
          <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden>
            <path d="M6 3l5 5-5 5" stroke="currentColor" strokeWidth="1.6" fill="none" />
          </svg>
        </button>
      </header>

      <div ref={scrollRef} className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-3 py-3" aria-live="polite">
        {messages.length === 0 && !loading ? (
          <div className="mt-2 flex flex-col gap-3 text-[12.5px] text-fg-muted">
            <p>
              Ask about your holdings, risk and P&amp;L, or tell FinAlly to place trades and manage your watchlist. Orders
              run immediately at market.
            </p>
            <div className="flex flex-wrap gap-1.5">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => void send(s)}
                  className="rounded-full border border-line px-2.5 py-1 text-[12px] text-fg hover:border-primary hover:text-primary"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : null}
        {messages.map((m) => (
          <ChatBubble key={m.id} message={m} />
        ))}
        {loading ? (
          <div data-testid="chat-loading" className="flex items-center gap-2 text-[12px] text-fg-muted" role="status">
            <span className="flex gap-1" aria-hidden>
              <span className="dot-pulse h-1.5 w-1.5 rounded-full bg-accent" />
              <span className="dot-pulse h-1.5 w-1.5 rounded-full bg-accent [animation-delay:150ms]" />
              <span className="dot-pulse h-1.5 w-1.5 rounded-full bg-accent [animation-delay:300ms]" />
            </span>
            FinAlly is thinking…
          </div>
        ) : null}
        {error ? (
          <p className="rounded-sm border border-down/40 bg-down/10 px-2 py-1 text-[12px] text-down" role="alert" data-testid="chat-error">
            {error}
          </p>
        ) : null}
      </div>

      <form onSubmit={onSubmit} className="flex shrink-0 items-end gap-2 border-t border-line p-2">
        <textarea
          data-testid="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          rows={2}
          placeholder="Ask FinAlly or tell it to trade…"
          aria-label="Message FinAlly"
          className="min-h-[40px] flex-1 resize-none rounded-sm border border-line bg-ink-950 px-2 py-1.5 text-[13px] text-fg placeholder:text-fg-faint focus:border-primary focus:outline-none"
        />
        <button
          type="submit"
          data-testid="chat-send-button"
          disabled={loading || !input.trim()}
          className="h-[40px] rounded-sm bg-secondary px-4 text-[12px] font-semibold text-white hover:brightness-110 disabled:opacity-50"
        >
          Send
        </button>
      </form>
    </aside>
  );
}
