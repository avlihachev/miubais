#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
dest="${PUBLIC_CLONE:-$HOME/Projects/miubais-public}"
push=1; dirty=""
for a in "$@"; do case "$a" in --no-push) push=0;; --allow-dirty) dirty=--allow-dirty;; esac; done
[[ -d "$dest/.git" ]] || gh repo clone avlihachev/miubais "$dest"
# an empty clone has no upstream branch yet, and pull fails on it
if git -C "$dest" rev-parse -q --verify '@{u}' >/dev/null 2>&1; then git -C "$dest" pull --ff-only; fi
uv run --frozen miubais publish --dest "$dest" ${dirty:+"$dirty"}
(cd "$dest" && uv sync --frozen && (cd site && pnpm install --frozen-lockfile) && bash scripts/verify.sh --public)
git -C "$dest" add -u
xargs git -C "$dest" add -f -- < "$dest/.git/publish-manifest"
if git -C "$dest" diff --cached --quiet; then echo "nothing to publish"; else git -C "$dest" commit -m "publish: $(git rev-parse --short HEAD)"; fi
if (( push )); then git -C "$dest" push -u origin HEAD:main; fi
