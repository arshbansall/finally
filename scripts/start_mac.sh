#!/usr/bin/env bash
# Start FinAlly in Docker (macOS / Linux). Safe to run repeatedly.
#
#   scripts/start_mac.sh            # build image if missing, start container, open browser
#   scripts/start_mac.sh --build    # force an image rebuild (and restart the container)
#   scripts/start_mac.sh --no-open  # don't open a browser
#
# Env: FINALLY_PORT (host port, default 8000)
set -euo pipefail

IMAGE="finally"
CONTAINER="finally"
VOLUME="finally-data"
PORT="${FINALLY_PORT:-8000}"
URL="http://localhost:${PORT}"

BUILD=false
OPEN=true
for arg in "$@"; do
  case "$arg" in
    --build) BUILD=true ;;
    --no-open) OPEN=false ;;
    -h|--help) sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $arg (try --help)" >&2; exit 1 ;;
  esac
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! command -v docker >/dev/null 2>&1; then
  echo "Error: docker is not installed. Install Docker Desktop: https://docs.docker.com/get-docker/" >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "Error: the Docker daemon is not running. Start Docker Desktop and try again." >&2
  exit 1
fi

if $BUILD || ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Building Docker image '$IMAGE'..."
  docker build -t "$IMAGE" .
fi

running="$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null || true)"
if [ "$running" = "true" ] && ! $BUILD; then
  echo "FinAlly is already running at $URL"
else
  # Replace any stale (stopped, or pre-rebuild) container; the data volume is untouched.
  if [ -n "$running" ]; then
    docker stop "$CONTAINER" >/dev/null 2>&1 || true
    docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  fi

  env_args=()
  if [ -f .env ]; then
    env_args=(--env-file .env)
  else
    echo "Warning: no .env file found — AI chat needs OPENROUTER_API_KEY."
    echo "         Create one with: cp .env.example .env   (then add your key)"
  fi

  echo "Starting container '$CONTAINER'..."
  docker run -d \
    --name "$CONTAINER" \
    -p "${PORT}:8000" \
    -v "${VOLUME}:/app/db" \
    ${env_args[@]+"${env_args[@]}"} \
    --restart unless-stopped \
    "$IMAGE" >/dev/null

  printf "Waiting for the app to become ready"
  ready=false
  for _ in $(seq 1 30); do
    if curl -fsS "$URL/api/health" >/dev/null 2>&1; then ready=true; break; fi
    printf "."
    sleep 1
  done
  echo
  if ! $ready; then
    echo "The app did not report healthy yet. Check logs with: docker logs $CONTAINER" >&2
  fi
fi

echo "FinAlly: $URL"

if $OPEN; then
  if command -v open >/dev/null 2>&1; then
    open "$URL" >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$URL" >/dev/null 2>&1 || true
  fi
fi
