#!/usr/bin/env bash
# Start LocalStack with the specified AWS services.
# Usage: ./start-localstack.sh [service1,service2,...]
# If no services specified, starts with all community services.
set -euo pipefail

SERVICES="${1:-}"
LOCALSTACK_PORT="${LOCALSTACK_PORT:-4566}"
HEALTH_URL="http://localhost:${LOCALSTACK_PORT}/_localstack/health"
MAX_WAIT=60

# --- Preflight checks ---

if ! command -v localstack &>/dev/null; then
  echo "ERROR: LocalStack CLI not found. Install with:"
  echo "  brew install localstack/tap/localstack-cli"
  echo "  # or: pip install localstack"
  exit 1
fi

if ! docker info &>/dev/null; then
  echo "ERROR: Docker is not running. Please start Docker first."
  exit 1
fi

# Load auth token from .env if not already set
if [[ -z "${LOCALSTACK_AUTH_TOKEN:-}" ]]; then
  ENV_FILE="$(git rev-parse --show-toplevel 2>/dev/null)/.env"
  if [[ -f "$ENV_FILE" ]]; then
    TOKEN=$(grep -E '^LOCALSTACK_AUTH_TOKEN=' "$ENV_FILE" | cut -d'=' -f2- | tr -d '"' | tr -d "'")
    if [[ -n "$TOKEN" ]]; then
      export LOCALSTACK_AUTH_TOKEN="$TOKEN"
      echo "Loaded LOCALSTACK_AUTH_TOKEN from .env"
    fi
  fi
fi

# --- Start LocalStack ---

echo "Starting LocalStack..."
if [[ -n "$SERVICES" ]]; then
  echo "Services: $SERVICES"
  SERVICES="$SERVICES" localstack start -d
else
  echo "Services: all (community edition defaults)"
  localstack start -d
fi

# --- Wait for readiness ---

echo "Waiting for LocalStack to be ready (max ${MAX_WAIT}s)..."
elapsed=0
while [[ $elapsed -lt $MAX_WAIT ]]; do
  if curl -sf "$HEALTH_URL" &>/dev/null; then
    echo "LocalStack is ready! (${elapsed}s)"
    echo ""
    echo "Endpoint: http://localhost:${LOCALSTACK_PORT}"
    echo "Health:   ${HEALTH_URL}"

    # Print service status
    echo ""
    echo "Service status:"
    curl -sf "$HEALTH_URL" | python3 -m json.tool 2>/dev/null || curl -sf "$HEALTH_URL"
    exit 0
  fi
  sleep 2
  elapsed=$((elapsed + 2))
done

echo "ERROR: LocalStack did not become ready within ${MAX_WAIT}s"
echo "Check logs with: localstack logs"
exit 1
