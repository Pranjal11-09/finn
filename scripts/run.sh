#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mode="${1:-start}"
if [ "$mode" = setup ]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install -r backend/requirements.txt pytest
  (cd web && npm ci && npm run build)
  [ -f .env ] || cp .env.example .env
  echo "Setup complete. Edit .env, then run: bash scripts/run.sh check"
elif [ "$mode" = test ]; then
  (cd backend && LLM_PROVIDER=off FINN_FIXTURES=1 FINN_DB=/tmp/finn-submission-tests-v2.db ../.venv/bin/python -m pytest -q)
  (cd web && npm run build)
elif [ "$mode" = check ]; then
  .venv/bin/python scripts/preflight.py
elif [ "$mode" = snapshot ]; then
  .venv/bin/python scripts/preflight.py
  .venv/bin/python scripts/snapshot.py
elif [ "$mode" = demo ]; then
  .venv/bin/python backend/tests/make_fixtures.py
  cd backend
  FINN_FIXTURES=1 LLM_PROVIDER=off FINN_DB=/tmp/finn-synthetic-demo.db ../.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
elif [ "$mode" = start ]; then
  cd backend
  ../.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
else
  echo "Usage: bash scripts/run.sh setup|test|check|snapshot|demo|start"; exit 2
fi
