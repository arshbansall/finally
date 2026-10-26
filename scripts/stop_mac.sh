#!/usr/bin/env bash
# Stop FinAlly (macOS / Linux). Removes the container but keeps the
# 'finally-data' volume, so your portfolio persists. Safe to run repeatedly.
set -euo pipefail

CONTAINER="finally"

if ! command -v docker >/dev/null 2>&1; then
  echo "Error: docker is not installed." >&2
  exit 1
fi

if docker container inspect "$CONTAINER" >/dev/null 2>&1; then
  docker stop "$CONTAINER" >/dev/null 2>&1 || true
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  echo "FinAlly stopped (data volume 'finally-data' kept)."
else
  echo "FinAlly is not running."
fi
