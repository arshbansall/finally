# FinAlly — Team Contract

Shared interface contract for the agent team. `PLAN.md` is the product spec; this file pins down the
interfaces between team members so everyone can build in parallel. If you need to change something
here, message the affected owners (and the lead) first, then update this file.

## 1. Team & File Ownership

Only edit files you own. Need a change in someone else's area? Message them by name.

| Teammate | Owns |
|---|---|
| `frontend` | `frontend/**` |
| `backend-api` | `backend/app/**` (FastAPI app, routes, services, background tasks, static serving), `backend/pyproject.toml`, `backend/uv.lock`, `backend/tests/test_api_*.py`, `backend/tests/test_services_*.py`, `backend/tests/conftest.py` |
| `database` | `backend/db/**`, `backend/tests/test_db_*.py` |
| `market-data` | `backend/market/**`, `backend/tests/test_market_*.py` |
| `llm` | `backend/llm/**`, `backend/tests/test_llm_*.py` |
| `integration-tester` | `test/**` (Playwright E2E + `test/docker-compose.test.yml`) |
| `devops` | `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `scripts/**`, `.env.example`, `.gitignore`, `README.md` |

- **Dependencies**: `backend-api` is the only one who runs `uv add` in `backend/`. Others message `backend-api` with the package they need. Already installed: fastapi, uvicorn[standard], litellm, pydantic, python-dotenv, httpx, numpy; dev: pytest, pytest-asyncio (`asyncio_mode = "auto"`).
- **Do not commit** to git. The lead handles commits.
- **No shared task board** in this session: coordinate by messaging teammates by name. Tell the lead when you finish a milestone or get blocked.

## 2. Backend Layout

`backend/` is a uv project (non-packaged, Python 3.12). Top-level Python packages live directly in `backend/`:

```
backend/
├── app/        # backend-api: main.py (FastAPI `app`), routes/, services/, tasks
├── db/         # database: schema.sql, connection, init/seed, repository functions
├── market/     # market-data: interface, simulator, Massive client, price cache, SSE router
├── llm/        # llm: prompts, structured-output schema, LiteLLM client, mock, chat orchestration
├── tests/      # pytest (pythonpath = ".")
└── static/     # frontend build output, copied in at Docker build time (gitignored)
```

- Run locally: `cd backend && uv run uvicorn app.main:app --reload --port 8000`
- Tests: `cd backend && uv run pytest`
- **Environment**: load the project-root `.env` with python-dotenv (`backend/../.env`) when present; real env vars win.
- **Database path**: env `FINALLY_DB_PATH`, default `<project-root>/db/finally.db` (i.e. `backend/../db/finally.db`). In Docker, `FINALLY_DB_PATH=/app/db/finally.db`.
- **Static dir**: env `FINALLY_STATIC_DIR`, default `backend/static`. Serve it only if it exists.
- **Docker layout**: backend code at `/app/backend`, volume at `/app/db`, static at `/app/backend/static`. (Code must NOT live at `/app` directly, or the `/app/db` volume would shadow the `db` package.)
- Constant `DEFAULT_USER_ID = "default"` everywhere; all functions take `user_id: str = "default"`.

## 3. Python Module Interfaces

### 3.1 `market` (owner: market-data)

```python
from market import PriceUpdate, PriceCache, MarketDataSource, create_market_data_source, stream_router

@dataclass(frozen=True)
class PriceUpdate:
    ticker: str
    price: float
    previous_price: float
    open_price: float        # session-open reference price (seed price for simulator), for daily change %
    timestamp: str           # ISO 8601 UTC
    direction: Literal["up", "down", "flat"]
    change: float            # price - open_price
    change_pct: float        # (price - open_price) / open_price * 100
    def to_dict(self) -> dict: ...

class PriceCache:
    def get(self, ticker: str) -> PriceUpdate | None
    def get_price(self, ticker: str) -> float | None
    def get_all(self) -> dict[str, PriceUpdate]
    def update(self, ticker: str, price: float, timestamp: str | None = None) -> PriceUpdate
    def remove(self, ticker: str) -> None
    version: int             # increments on every update (lets SSE detect changes)

class MarketDataSource(ABC):
    async def start(self, tickers: list[str]) -> None   # begin background updates into the cache
    async def stop(self) -> None
    async def add_ticker(self, ticker: str) -> None      # cache should get a price promptly (simulator: immediately)
    async def remove_ticker(self, ticker: str) -> None
    def get_tickers(self) -> list[str]

def create_market_data_source(cache: PriceCache) -> MarketDataSource
    # MASSIVE_API_KEY set & non-empty -> Massive REST poller; else GBM simulator

stream_router: fastapi.APIRouter   # provides GET /api/stream/prices (see §5)
```

- The simulator must handle unknown tickers (e.g. `PYPL`) by assigning a plausible random seed price.
- `backend-api` creates a single `PriceCache` + source at app startup (lifespan), stores them on `app.state.price_cache` / `app.state.market_source`, and the SSE router reads `request.app.state.price_cache`.
- Tracked tickers = watchlist ∪ tickers with open positions. `backend-api` calls `add_ticker`/`remove_ticker` to keep this in sync.

### 3.2 `db` (owner: database)

Sync `sqlite3` is fine (single user, tiny writes). Rows are returned as plain `dict`s. Timestamps are ISO 8601 UTC strings; IDs are UUID4 strings.

```python
from db import init_db, get_connection, transaction

def init_db(db_path: str | None = None) -> None   # create file/dir, tables if missing, seed defaults if empty; idempotent
def get_connection() -> sqlite3.Connection        # row_factory set; check_same_thread=False
@contextmanager
def transaction() -> Iterator[sqlite3.Connection] # BEGIN ... COMMIT / ROLLBACK on exception

# users_profile
def get_cash_balance(user_id="default", conn=None) -> float
def set_cash_balance(amount: float, user_id="default", conn=None) -> None

# watchlist
def get_watchlist(user_id="default") -> list[dict]          # [{id, ticker, added_at}] ordered by added_at
def add_watchlist_ticker(ticker: str, user_id="default") -> bool   # False if already present
def remove_watchlist_ticker(ticker: str, user_id="default") -> bool # False if not present

# positions
def get_positions(user_id="default", conn=None) -> list[dict]       # [{id, ticker, quantity, avg_cost, updated_at}]
def get_position(ticker: str, user_id="default", conn=None) -> dict | None
def upsert_position(ticker: str, quantity: float, avg_cost: float, user_id="default", conn=None) -> None
def delete_position(ticker: str, user_id="default", conn=None) -> None

# trades
def insert_trade(ticker: str, side: str, quantity: float, price: float, user_id="default", conn=None) -> dict
def get_trades(user_id="default", limit: int = 100) -> list[dict]

# portfolio_snapshots
def insert_snapshot(total_value: float, user_id="default", conn=None) -> dict
def get_snapshots(user_id="default", limit: int | None = None) -> list[dict]   # oldest first

# chat_messages
def insert_chat_message(role: str, content: str, actions: dict | list | None = None, user_id="default") -> dict
def get_chat_messages(user_id="default", limit: int = 50) -> list[dict]   # oldest first; actions parsed from JSON
```

`conn=None` means "open/use a connection internally"; passing `conn` lets callers group writes inside `transaction()`.
Seed: user `default` with cash 10000.0; watchlist AAPL, GOOGL, MSFT, AMZN, TSLA, NVDA, META, JPM, V, NFLX.

### 3.3 `app.services` (owner: backend-api) — used by routes AND by `llm`

```python
from app.services.portfolio import execute_trade, get_portfolio_summary, record_snapshot, TradeError
from app.services.watchlist import add_ticker, remove_ticker, get_watchlist_with_prices, WatchlistError

class TradeError(Exception): ...        # message is user-facing, e.g. "Insufficient cash: need $1,900.00, have $500.00"
class WatchlistError(Exception): ...

def execute_trade(ticker: str, side: str, quantity: float, price_cache, user_id="default") -> dict
    # validates (ticker format, side in buy/sell, quantity > 0, price available, enough cash / shares),
    # updates cash + position (weighted avg cost on buy; delete position when quantity hits ~0),
    # inserts trade, records snapshot, all in one transaction. Returns the trade dict. Raises TradeError.
def get_portfolio_summary(price_cache, user_id="default") -> dict     # same shape as GET /api/portfolio
def record_snapshot(price_cache, user_id="default") -> dict
async def add_ticker(ticker: str, price_cache, market_source, user_id="default") -> dict     # raises WatchlistError
async def remove_ticker(ticker: str, price_cache, market_source, user_id="default") -> dict  # raises WatchlistError
def get_watchlist_with_prices(price_cache, user_id="default") -> list[dict]
```

### 3.4 `llm` (owner: llm)

```python
from llm import process_chat

async def process_chat(message: str, price_cache, market_source, user_id="default") -> dict
    # 1. builds context via app.services.portfolio.get_portfolio_summary + get_watchlist_with_prices
    # 2. loads history via db.get_chat_messages
    # 3. calls LLM (cerebras-inference skill: LiteLLM -> openrouter/openai/gpt-oss-120b, provider cerebras,
    #    structured output via a pydantic model) — or the mock when LLM_MOCK=true
    # 4. executes trades / watchlist changes through app.services (never touches db directly for these)
    # 5. stores user + assistant messages (assistant with actions) via db.insert_chat_message
    # 6. returns the POST /api/chat response shape (§4)
```

Must never raise for LLM/network/parse failures: return a friendly `message` with empty actions instead.

**Mock mode** (`LLM_MOCK=true`, deterministic, for E2E). Case-insensitive patterns in the user message:
- `buy <qty> <TICKER>` / `sell <qty> <TICKER>` → that trade, message `"Mock: executing <side> <qty> <TICKER>."`
- `add <TICKER>` / `remove <TICKER>` (also `watch <TICKER>` / `unwatch <TICKER>`) → watchlist change, message `"Mock: <action> <TICKER> to/from watchlist."`
- anything else → `"Mock: I'm FinAlly, your AI trading assistant. Your portfolio is worth $<total_value>."` with no actions.

## 4. REST API (owner: backend-api)

All JSON. Tickers are normalized to uppercase; valid format `^[A-Z][A-Z0-9.]{0,9}$`. Errors use FastAPI's `{"detail": "<user-facing message>"}`.

**GET `/api/health`** → `200 {"status": "ok"}`

**GET `/api/portfolio`** →
```json
{
  "cash_balance": 8100.0,
  "positions_value": 1905.0,
  "total_value": 10005.0,
  "unrealized_pnl": 5.0,
  "unrealized_pnl_pct": 0.26,
  "positions": [
    {"ticker": "AAPL", "quantity": 10, "avg_cost": 190.0, "current_price": 190.5,
     "market_value": 1905.0, "unrealized_pnl": 5.0, "unrealized_pnl_pct": 0.26, "weight": 100.0}
  ]
}
```
(`weight` = % of positions_value. If a price is missing, fall back to `avg_cost`.)

**POST `/api/portfolio/trade`** body `{"ticker": "AAPL", "quantity": 10, "side": "buy"}` →
`200 {"trade": {"id","ticker","side","quantity","price","executed_at"}, "portfolio": <GET /api/portfolio shape>}`; `400 {"detail": ...}` on validation failure.

**GET `/api/portfolio/history`** → `200 {"snapshots": [{"total_value": 10000.0, "recorded_at": "2026-10-26T15:00:00+00:00"}]}` (oldest first). Snapshots every 30s (background task) and after each trade. Record one at startup too, so the chart is never empty.

**GET `/api/watchlist`** → `200 {"tickers": [{"ticker":"AAPL","price":190.12,"previous_price":190.01,"change_pct":0.06,"direction":"up"}]}` (price fields may be `null` until the first tick)

**POST `/api/watchlist`** body `{"ticker":"PYPL"}` → `201 {"ticker":"PYPL", ...same item shape}`; `409` already present; `400` invalid.

**DELETE `/api/watchlist/{ticker}`** → `200 {"ticker":"PYPL"}`; `404` not in watchlist.

**POST `/api/chat`** body `{"message": "Buy 5 AAPL"}` →
```json
{
  "message": "Done — bought 5 AAPL at $190.12.",
  "trades": [{"ticker":"AAPL","side":"buy","quantity":5,"status":"executed","price":190.12,"error":null}],
  "watchlist_changes": [{"ticker":"PYPL","action":"add","status":"executed","error":null}]
}
```
`status` is `"executed"` or `"failed"` (with `error` text). Always 200 unless the request body is invalid (422).

**GET `/api/chat`** → `200 {"messages": [{"id","role","content","actions","created_at"}]}` (oldest first; lets the UI restore the conversation on reload)

Static: everything not under `/api/` serves the Next.js export from the static dir (`index.html` at `/`).

## 5. SSE (owner: market-data)

**GET `/api/stream/prices`** — `Content-Type: text/event-stream`, unnamed events (so `EventSource.onmessage` receives them), ~every 500ms:

```
retry: 1000

data: {"AAPL": {"ticker":"AAPL","price":190.12,"previous_price":190.01,"open_price":190.0,"timestamp":"2026-10-26T15:00:00.123+00:00","direction":"up","change":0.12,"change_pct":0.06}, "GOOGL": {...}}

```
Each event carries every ticker in the cache (watchlist ∪ positions). Send headers `Cache-Control: no-cache`, `X-Accel-Buffering: no`. Stop cleanly when the client disconnects.

## 6. Frontend Conventions (owner: frontend; consumed by integration-tester)

- Static export (`output: 'export'`) to `frontend/out/`. All requests are same-origin `/api/...`. For local dev, `next dev` with a dev-only rewrite of `/api/*` → `http://localhost:8000/api/*` is fine.
- **Required `data-testid`s** so E2E tests can be written in parallel:

| testid | Element |
|---|---|
| `connection-status` | header dot; attribute `data-status="connected" \| "reconnecting" \| "disconnected"` |
| `header-total-value` / `header-cash` | header numbers (text like `$10,000.00`) |
| `watchlist` | watchlist container |
| `watchlist-row-<TICKER>` | one row per ticker |
| `watchlist-price-<TICKER>` | price cell (gets flash class on change) |
| `watchlist-remove-<TICKER>` | remove button in the row |
| `watchlist-add-input` / `watchlist-add-button` | add-ticker controls |
| `main-chart` | selected-ticker chart; attribute `data-ticker="<TICKER>"` |
| `trade-ticker-input` / `trade-quantity-input` / `trade-buy-button` / `trade-sell-button` | trade bar |
| `trade-error` | trade error message, when present |
| `positions-table` / `position-row-<TICKER>` | positions table and rows |
| `portfolio-heatmap` | treemap container |
| `heatmap-cell-<TICKER>` | one treemap cell per position (carries the P&L colour); attribute `data-pnl="gain" \| "loss" \| "flat"` |
| `pnl-chart` | P&L line chart container |
| `chat-panel` / `chat-input` / `chat-send-button` | chat (panel open by default at desktop width) |
| `chat-toggle` | collapse/expand button for the chat panel |
| `chat-message` | each message bubble; attribute `data-role="user" \| "assistant"` |
| `chat-loading` | loading indicator while awaiting response |
| `chat-action` | each inline trade / watchlist confirmation |

## 7. Environment Variables

| Var | Default | Purpose |
|---|---|---|
| `OPENROUTER_API_KEY` | — | LLM calls (not needed with `LLM_MOCK=true`) |
| `MASSIVE_API_KEY` | empty | real market data if set |
| `MASSIVE_POLL_INTERVAL` | `15` | seconds between Massive polls |
| `LLM_MOCK` | `false` | deterministic mock chat |
| `FINALLY_DB_PATH` | `<root>/db/finally.db` | SQLite file |
| `FINALLY_STATIC_DIR` | `backend/static` | frontend export |
