#!/usr/bin/env bash
# Rebuild and restart only the docker-compose services affected by what changed.
#
# "What changed" is measured against the working tree as it stood the last time
# this script succeeded (a git tree hash kept in .git/redeploy-changes.tree), so
# commits, uncommitted edits, and untracked files are all covered, and nothing
# is rebuilt twice for the same change. With no marker yet, everything is rebuilt.
#
# Usage: scripts/redeploy-changes.sh [--dry-run] [--all] [--since <git-ref>]
#   --dry-run       show what would be rebuilt, change nothing
#   --all           rebuild and restart every service
#   --since <ref>   compare against a git ref instead of the marker
#
# Mapping:
#   src/backend/**   -> backend + reminder-runner (same image; tests are ignored)
#   src/frontend/**  -> frontend (test files are ignored)
#   docker-compose.yml, .env -> `up -d` for all services (recreates what differs)
#   everything else (docs, README, scripts, .deploy, ...) -> nothing to restart
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

DRY_RUN=0
FORCE_ALL=0
SINCE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --all) FORCE_ALL=1 ;;
    --since) SINCE="${2:?--since needs a git ref}"; shift ;;
    -h|--help) sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  echo "Neither 'docker compose' nor 'docker-compose' is available." >&2
  exit 1
fi

GIT_DIR_PATH="$(git rev-parse --absolute-git-dir)"
MARKER="$GIT_DIR_PATH/redeploy-changes.tree"

# A tree object of the whole working tree (tracked + untracked, honouring
# .gitignore), built through a throwaway index so the real one is untouched.
snapshot_tree() {
  local tmp_index
  tmp_index="$(mktemp "${TMPDIR:-/tmp}/redeploy-index.XXXXXX")"
  rm -f "$tmp_index"
  GIT_INDEX_FILE="$tmp_index" git add -A . >/dev/null
  GIT_INDEX_FILE="$tmp_index" git write-tree
  rm -f "$tmp_index"
}

CURRENT_TREE="$(snapshot_tree)"

BASE=""
if [[ -n "$SINCE" ]]; then
  BASE="$(git rev-parse --verify "$SINCE^{tree}")"
elif [[ -f "$MARKER" ]]; then
  candidate="$(cat "$MARKER")"
  # The marker's tree can be garbage-collected; treat that as "unknown".
  if git cat-file -e "$candidate^{tree}" 2>/dev/null; then BASE="$candidate"; fi
fi

BACKEND=0
FRONTEND=0
COMPOSE_CONFIG=0

if [[ $FORCE_ALL -eq 1 || -z "$BASE" ]]; then
  [[ $FORCE_ALL -eq 1 ]] && reason="--all given" || reason="no previous deploy recorded"
  echo "Rebuilding everything ($reason)."
  BACKEND=1; FRONTEND=1; COMPOSE_CONFIG=1
else
  CHANGED="$(git diff-tree -r --no-renames --name-only "$BASE" "$CURRENT_TREE")"
  if [[ -z "$CHANGED" ]]; then
    echo "No changes since the last deploy; nothing to do."
    exit 0
  fi
  while IFS= read -r file; do
    case "$file" in
      src/backend/tests/*|src/backend/*.md) ;;
      src/backend/*) BACKEND=1 ;;
      src/frontend/*.test.ts|src/frontend/*.test.tsx|src/frontend/*.md) ;;
      src/frontend/node_modules/*) ;;
      src/frontend/*) FRONTEND=1 ;;
      docker-compose.yml|docker-compose.yaml|.env) COMPOSE_CONFIG=1 ;;
    esac
  done <<<"$CHANGED"
  echo "Changed files:"; sed 's/^/  /' <<<"$CHANGED"
fi

SERVICES=()
if [[ $COMPOSE_CONFIG -eq 0 ]]; then
  [[ $BACKEND -eq 1 ]] && SERVICES+=(backend reminder-runner)
  [[ $FRONTEND -eq 1 ]] && SERVICES+=(frontend)
fi

if [[ $COMPOSE_CONFIG -eq 0 && ${#SERVICES[@]} -eq 0 ]]; then
  echo "Nothing that affects a container changed (docs, tests, scripts, ...)."
  [[ $DRY_RUN -eq 0 ]] && echo "$CURRENT_TREE" >"$MARKER"
  exit 0
fi

if [[ $COMPOSE_CONFIG -eq 1 ]]; then
  CMD=("${COMPOSE[@]}" up -d --build)
  echo "Plan: rebuild and recreate all services (compose/env config or full rebuild)."
else
  CMD=("${COMPOSE[@]}" up -d --build "${SERVICES[@]}")
  echo "Plan: rebuild and restart: ${SERVICES[*]}"
fi

if [[ $DRY_RUN -eq 1 ]]; then
  echo "[dry run] ${CMD[*]}"
  exit 0
fi

"${CMD[@]}"
echo "$CURRENT_TREE" >"$MARKER"
echo "Done."
