"""System prompt, portfolio context block and message assembly for the chat LLM."""

SYSTEM_PROMPT = """You are FinAlly, an AI trading assistant embedded in a simulated trading workstation.
The user trades a simulated portfolio with virtual money (market orders only, instant fill at the current price, no fees).

Your job:
- Analyze the portfolio: composition, risk concentration, diversification and P&L.
- Suggest trades with brief, data-driven reasoning.
- Execute trades when the user asks for them or agrees to a suggestion.
- Manage the watchlist proactively (e.g. add tickers the user discusses or trades).
- Be concise and data-driven: short paragraphs or bullets, real numbers from the context. Only cite figures that appear in the context (there is no historical price data).

How actions work:
- Put every trade you want executed in "trades" and every watchlist change in "watchlist_changes". Anything not listed there does NOT happen.
- Actions run automatically right after your reply, with the same validation as manual trades (enough cash for buys, enough shares for sells). Check the numbers in the context before placing orders.
- Tickers are upper-case symbols. Quantities are share counts (fractional allowed) and must be positive. If the user specifies a dollar amount, convert it to shares using the current price.
- Do not invent trades the user did not ask or agree to. If you only suggest a trade, leave "trades" empty.
- Describe actions as being placed (e.g. "Buying 10 AAPL at ~$190"), since results are shown to the user separately.
- Prices come from a live feed; a ticker without a price cannot be traded yet.

Always respond with valid JSON matching the required schema: {"message": string, "trades": [...], "watchlist_changes": [...]}. Use empty lists when there is nothing to do."""


def _money(value: float | None) -> str:
    return "n/a" if value is None else f"${value:,.2f}"


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.2f}%"


def _qty(value: float) -> str:
    return f"{value:g}"


def build_portfolio_context(portfolio: dict | None, watchlist: list[dict] | None) -> str:
    """Render a compact, LLM-friendly snapshot of the user's account."""
    lines = ["# Current account state"]

    if portfolio is None:
        lines.append("Portfolio data is currently unavailable.")
    else:
        lines.append(
            f"Total value: {_money(portfolio.get('total_value'))} | "
            f"Cash: {_money(portfolio.get('cash_balance'))} | "
            f"Positions value: {_money(portfolio.get('positions_value'))} | "
            f"Unrealized P&L: {_money(portfolio.get('unrealized_pnl'))} "
            f"({_pct(portfolio.get('unrealized_pnl_pct'))})"
        )
        positions = portfolio.get("positions") or []
        if positions:
            lines.append("")
            lines.append("## Positions (ticker | qty | avg cost | price | value | P&L | % of positions value)")
            for p in positions:
                weight = p.get("weight")
                lines.append(
                    f"{p.get('ticker')} | {_qty(p.get('quantity', 0))} | {_money(p.get('avg_cost'))} | "
                    f"{_money(p.get('current_price'))} | {_money(p.get('market_value'))} | "
                    f"{_money(p.get('unrealized_pnl'))} ({_pct(p.get('unrealized_pnl_pct'))}) | "
                    f"{'n/a' if weight is None else f'{weight:.1f}%'}"
                )
        else:
            lines.append("No open positions (all cash).")

    lines.append("")
    if watchlist is None:
        lines.append("Watchlist data is currently unavailable.")
    elif not watchlist:
        lines.append("Watchlist is empty.")
    else:
        lines.append("## Watchlist (ticker | price | change today)")
        for w in watchlist:
            lines.append(f"{w.get('ticker')} | {_money(w.get('price'))} | {_pct(w.get('change_pct'))}")

    return "\n".join(lines)


def _describe_actions(actions: dict | list | None) -> str:
    """Summarize stored assistant actions so the model remembers what actually happened."""
    if not isinstance(actions, dict):
        return ""
    parts = []
    for t in actions.get("trades") or []:
        desc = f"{t.get('side')} {_qty(t.get('quantity') or 0)} {t.get('ticker')}"
        if t.get("status") == "executed":
            parts.append(f"{desc} executed at {_money(t.get('price'))}")
        else:
            parts.append(f"{desc} FAILED ({t.get('error')})")
    for c in actions.get("watchlist_changes") or []:
        desc = f"watchlist {c.get('action')} {c.get('ticker')}"
        parts.append(desc if c.get("status") == "executed" else f"{desc} FAILED ({c.get('error')})")
    return f"\n[Actions: {'; '.join(parts)}]" if parts else ""


def build_messages(context: str, history: list[dict], user_message: str) -> list[dict]:
    """Assemble the chat-completion message list: system prompt, context, history, new message."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": context},
    ]
    for msg in history:
        role = msg.get("role")
        if role not in ("user", "assistant"):
            continue
        content = msg.get("content") or ""
        if role == "assistant":
            content += _describe_actions(msg.get("actions"))
        messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_message})
    return messages
