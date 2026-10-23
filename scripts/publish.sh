#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
dest="${PUBLIC_CLONE:-$HOME/Projects/miubais-public}"
push=1; deploy=1; dirty=""
for a in "$@"; do case "$a" in --no-push) push=0; deploy=0;; --no-deploy) deploy=0;; --allow-dirty) dirty=--allow-dirty;; esac; done
[[ -d "$dest/.git" ]] || gh repo clone avlihachev/miubais "$dest"
if git -C "$dest" rev-parse -q --verify '@{u}' >/dev/null 2>&1; then git -C "$dest" pull --ff-only; fi
uv run --frozen miubais publish --dest "$dest" ${dirty:+"$dirty"}
(cd "$dest" && uv sync --frozen && (cd site && pnpm install --frozen-lockfile) && bash scripts/verify.sh --public)
git -C "$dest" add -u
xargs git -C "$dest" add -f -- < "$dest/.git/publish-manifest"
if git -C "$dest" diff --cached --quiet; then echo "nothing to publish"; else git -C "$dest" commit -m "publish: $(git rev-parse --short HEAD)"; fi
if (( push )); then git -C "$dest" push -u origin HEAD:main; fi
# the beacon token stays outside both repos: env first, then ~/.miubais/cf-beacon-token
token="${CF_BEACON_TOKEN:-}"; token_file="${MIUBAIS_HOME:-$HOME/.miubais}/cf-beacon-token"
if [[ -z "$token" && -f "$token_file" ]]; then token="$(head -n 1 "$token_file" | tr -d '[:space:]')"; fi
[[ -n "$token" ]] || echo "beacon: off (no CF_BEACON_TOKEN)"
(cd "$dest/site" && CF_BEACON_TOKEN="$token" pnpm build)
if (( deploy )); then
  out="$(cd "$dest" && npx --yes wrangler@3 pages deploy "$dest/site/dist" --project-name miubais --branch main --commit-hash "$(git -C "$dest" rev-parse HEAD)" --commit-message "$(git -C "$dest" log -1 --pretty=%s)" --commit-dirty=true 2>&1)" || { echo "$out"; exit 1; }
  echo "$out" | grep 'pages.dev' || echo "$out"
else
  echo "deploy: skipped"
fi
