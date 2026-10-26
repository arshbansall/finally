# FinAlly — the Finance Ally

An AI-powered trading workstation: live-streaming market data, a simulated $10,000 portfolio, and an LLM
chat copilot that can analyze your positions and execute trades for you. Built entirely by coding agents
as the capstone of an agentic AI coding course. See [`planning/PLAN.md`](planning/PLAN.md) for the full spec.

## Quick start (Docker)

Requires [Docker](https://docs.docker.com/get-docker/).

```bash
cp .env.example .env          # then add your OPENROUTER_API_KEY (or set LLM_MOCK=true)
./scripts/start_mac.sh        # macOS / Linux
.\scripts\start_windows.ps1   # Windows PowerShell
```

Open <http://localhost:8000>. The start script builds the image on first run, starts a container named
`finally`, and opens your browser. Options: `--build` / `-Build` forces a rebuild, `--no-open` / `-NoOpen`
skips the browser, and `FINALLY_PORT=8080` changes the host port.

Stop with `./scripts/stop_mac.sh` (or `.\scripts\stop_windows.ps1`). Your portfolio lives in the Docker
volume `finally-data` and survives stops and rebuilds; `docker volume rm finally-data` resets it.

### Docker Compose

```bash
docker compose up -d --build   # http://localhost:8000
docker compose down            # keeps the finally-data volume
```

### Plain Docker

```bash
docker build -t finally .
docker run -d --name finally -v finally-data:/app/db -p 8000:8000 --env-file .env finally
```

## Environment variables

Set these in `.env` at the project root (see [`.env.example`](.env.example)).

| Variable | Default | Purpose |
|---|---|---|
| `OPENROUTER_API_KEY` | — | LLM chat via OpenRouter (not needed when `LLM_MOCK=true`) |
| `MASSIVE_API_KEY` | empty | Real market data from Massive (Polygon.io); empty uses the built-in simulator (see below) |
| `MASSIVE_POLL_INTERVAL` | `15` | Seconds between Massive polls |
| `LLM_MOCK` | `false` | `true` returns deterministic mock chat responses (tests, no API key) |
| `FINALLY_DB_PATH` | `db/finally.db` | SQLite file (`/app/db/finally.db` in Docker) |
| `FINALLY_STATIC_DIR` | `backend/static` | Frontend static export served by FastAPI |

**Real market data needs a paid Massive plan.** The app polls Massive's stocks snapshot endpoint, which
is not in the free Stocks Basic plan. Starter and above include it, and Starter data is 15 minutes delayed.
If Massive rejects the key at startup (HTTP 401 or 403) or can't be reached, the app logs a warning and
uses the built-in simulator instead, so a free key still gives you a working app. Restart the container
after fixing the key or plan to switch back to Massive.

## Local development

Backend ([uv](https://docs.astral.sh/uv/), Python 3.12), API on port 8000:

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

Frontend (Next.js, Node 20+), dev server proxies `/api/*` to the backend on port 8000:

```bash
cd frontend
npm install
npm run dev
```

To have FastAPI serve the production frontend instead, run `npm run build` in `frontend/` and copy
`frontend/out/` to `backend/static/`.

## Tests

```bash
cd backend && uv run pytest          # backend unit tests
cd frontend && npm test              # frontend unit tests
```

Playwright E2E tests run against the production image (with `LLM_MOCK=true` and a throwaway database):

```bash
docker compose -f test/docker-compose.test.yml up --build --abort-on-container-exit --exit-code-from playwright
docker compose -f test/docker-compose.test.yml down -v
```

## Project layout

```
frontend/   Next.js + TypeScript (static export), Tailwind
backend/    FastAPI app (uv project): app/, db/, market/, llm/, tests/
test/       Playwright E2E tests + docker-compose.test.yml
scripts/    start/stop scripts for macOS/Linux and Windows
db/         local SQLite data (gitignored; a Docker volume in containers)
planning/   specs and the team contract for the agents
```
