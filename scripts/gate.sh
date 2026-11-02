#!/usr/bin/env bash
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo=$(git rev-parse --show-toplevel)
name=$(basename "$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")")
cd "$repo"

if [ ! -d packages ]; then
  make check
  exit 0
fi

if [ -d packages/python ]; then
  (
    cd packages/python
    uv sync --extra dev --quiet
    uv run --quiet python "$here/check-repo.py"
    uv run --quiet python "$here/lint-comment.py"
    uv run ruff check src tests
    uv run ruff format --check src tests
    uv run mypy
    uv run pytest -q -p no:cacheprovider -m "not live"
  )
else
  python3 "$here/check-repo.py"
  python3 "$here/lint-comment.py"
fi

if [ -d packages/typescript ]; then
  (
    cd packages/typescript
    npm ci --no-audit --no-fund
    npm run check
    npm run typecheck
    npm test
    npm run build
  )
fi

echo "gate: $name passed"
