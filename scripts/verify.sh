#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export MIUBAIS_SKIP_LIVE=1

fast=0
public=0
[[ "${1:-}" == "--fast" ]] && fast=1
[[ "${1:-}" == "--public" ]] && public=1

if (( public )); then
  uv run --frozen ruff check .
  uv run --frozen ruff format --check .
  uv lock --check
  uv run --frozen pytest -q -m "not slow"
  (cd site && pnpm test && pnpm build)
  grep -q "uv run miubais check m0-cost-lab" site/dist/exercises/m0-cost-lab/index.html \
    || { echo "hosted exercise page lacks the terminal check command"; exit 1; }
  echo "verify --public ok"
  exit 0
fi

uv lock --check
uv run --frozen ruff check .
uv run --frozen ruff format --check .
if (( fast )); then
  uv run --frozen pytest -q -m "not slow"
  (cd site && pnpm test)
  echo "verify --fast ok (slow tests, selftest, tutor-eval, freshen and the site build run in the full gate)"
  exit 0
fi
uv run --frozen pytest -q
uv run --frozen miubais selftest
uv run --frozen miubais tutor-eval
uv run --frozen miubais freshen --dry-run
(cd site && pnpm test && pnpm build)
uv lock --check
