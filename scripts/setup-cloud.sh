#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export UV_CACHE_DIR="${UV_CACHE_DIR:-/workspace/.cache/uv}"
export PIP_CACHE_DIR="${PIP_CACHE_DIR:-/workspace/.cache/pip}"
export npm_config_cache="${npm_config_cache:-/workspace/.cache/npm}"
cd "$project_root/backend"
if [[ ! -x .venv/bin/python ]]; then python -m venv .venv; fi
if ! .venv/bin/python -m pip --version > /dev/null 2>&1; then .venv/bin/python -m ensurepip --upgrade; fi
.venv/bin/python -m pip install --require-hashes -r requirements.lock
# Cloud smoke validation has an isolated SQLite store. The local workflow uses MySQL.
mkdir -p runtime
export DATABASE_URL="sqlite:///$project_root/backend/runtime/cloud.db"
.venv/bin/python -m app.cli init-db --demo
cd "$project_root/frontend"
npm ci --no-audit --no-fund
npm run build
