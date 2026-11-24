#!/usr/bin/env bash
# Fast, verified deployment for admin-only UI changes.
# Usage: ./scripts/deploy-admin-fast.sh "style: compact project summary"
set -euo pipefail

REPO="Naufalspurnomo/keuangan"
WORKFLOW="rumahweb-deploy.yml"
BRANCH="main"
LIVE_MANIFEST="https://hollawall.com/admin/release-manifest.json"

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

if [[ "$(git branch --show-current)" != "$BRANCH" ]]; then
  printf 'ERROR: checkout %s before deploying (current: %s)\n' "$BRANCH" "$(git branch --show-current)" >&2
  exit 1
fi

if ! git diff --cached --quiet; then
  printf 'ERROR: staged changes exist. Commit or unstage them first.\n' >&2
  git diff --cached --name-only >&2
  exit 1
fi

gh auth status >/dev/null

if [[ -z "$(git status --porcelain -- dashboard/src)" ]]; then
  printf 'ERROR: no UI changes under dashboard/src.\n' >&2
  exit 1
fi

MESSAGE="${1:-style: update admin UI}"
git add -- dashboard/src

if git diff --cached --name-only | grep -vE '^dashboard/src/' >/dev/null; then
  printf 'ERROR: fast lane only permits dashboard/src changes.\n' >&2
  git diff --cached --name-only >&2
  git reset -- dashboard/src
  exit 1
fi

git diff --cached --check
git commit -m "$MESSAGE"
git push origin "$BRANCH"

SHA="$(git rev-parse HEAD)"
printf 'Pushed %s\n' "$SHA"

gh workflow run "$WORKFLOW" \
  --repo "$REPO" \
  --ref "$BRANCH" \
  -f "revision=$SHA" \
  -f deploy_scope=admin

RUN_ID=""
for _ in {1..30}; do
  RUN_ID="$(gh run list \
    --repo "$REPO" \
    --workflow "$WORKFLOW" \
    --limit 20 \
    --json databaseId,headSha \
    --jq "map(select(.headSha == \"$SHA\"))[0].databaseId // empty")"
  [[ -n "$RUN_ID" ]] && break
  sleep 2
done

if [[ -z "$RUN_ID" ]]; then
  printf 'ERROR: GitHub Actions run was not found for %s\n' "$SHA" >&2
  exit 1
fi

printf 'Watching deploy run %s\n' "$RUN_ID"
gh run watch "$RUN_ID" --repo "$REPO" --exit-status

python3 - "$LIVE_MANIFEST?sha=$SHA" "$SHA" <<'PY'
import json
import sys
import urllib.request

url, expected = sys.argv[1:]
request = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
with urllib.request.urlopen(request, timeout=30) as response:
    payload = json.load(response)
observed = payload.get("artifact_revision") or payload.get("implementation_head_sha") or payload.get("release_sha")
if observed != expected:
    raise SystemExit(f"live revision mismatch: expected {expected}, observed {observed}")
print(f"LIVE admin verified: {observed}")
PY

git status --short
printf 'DONE: admin UI deployed without cPanel.\n'
