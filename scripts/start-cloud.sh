#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$project_root/.local"
export DATABASE_URL="sqlite:///$project_root/backend/runtime/cloud.db"
cd "$project_root/backend"
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 > "$project_root/.local/api.log" 2>&1 &
api_pid=$!
web_pid=''
cleanup() {
  if [[ -n "$web_pid" ]]; then kill "$web_pid" 2>/dev/null || true; fi
  kill "$api_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
cd "$project_root/frontend"
# Use the node process directly so cleanup owns the actual server PID.
node node_modules/vite/bin/vite.js --host 127.0.0.1 > "$project_root/.local/web.log" 2>&1 &
web_pid=$!
ready='false'
for ((i=0;i<30;i++)); do
  if ! kill -0 "$api_pid" 2>/dev/null || ! kill -0 "$web_pid" 2>/dev/null; then
    echo 'A service exited; inspect .local/api.log and .local/web.log.' >&2
    exit 1
  fi
  if curl --fail --silent http://127.0.0.1:8000/api/health > /dev/null && curl --fail --silent http://127.0.0.1:5173/api/health > /dev/null; then ready='true'; break; fi
  sleep 1
done
if [[ "$ready" != 'true' ]]; then echo 'Service readiness failed.' >&2; exit 1; fi
echo 'Backend and frontend proxy are ready. Ctrl+C stops both.'
wait "$api_pid" "$web_pid"
