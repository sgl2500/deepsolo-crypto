#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
RUNTIME_DIR="$ROOT_DIR/.runtime"
VENV_DIR="$ROOT_DIR/.venv"

DATA_ROOT="${CRYPTO_DATA_ROOT:-/Users/sunguanlong/Desktop/crypto/crypto-v2/data/normalized_gzip}"
APP_TIMEZONE="${APP_TIMEZONE:-Asia/Shanghai}"

# Some shells export broken certificate variables; pip treats them as hard errors.
for cert_var in REQUESTS_CA_BUNDLE SSL_CERT_FILE CURL_CA_BUNDLE; do
  cert_path="${!cert_var:-}"
  if [ -n "$cert_path" ] && [ ! -f "$cert_path" ]; then
    unset "$cert_var"
  fi
done

# Dedicated high ports reduce collisions with common local projects.
PREFERRED_FRONTEND_PORT="${FRONTEND_PORT:-49170}"
PREFERRED_BACKEND_PORT="${BACKEND_PORT:-49171}"

mkdir -p "$RUNTIME_DIR"

SECRETS_FILE="$RUNTIME_DIR/secrets.env"
if [ -f "$SECRETS_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$SECRETS_FILE"
  set +a
fi

is_port_free() {
  python3 - "$1" <<'PY'
import socket
import sys

port = int(sys.argv[1])
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    sock.bind(("127.0.0.1", port))
except OSError:
    sys.exit(1)
finally:
    sock.close()
PY
}

find_free_port() {
  port="$1"
  avoid="${2:-}"
  while true; do
    if [ "$port" != "$avoid" ] && is_port_free "$port"; then
      echo "$port"
      return 0
    fi
    port=$((port + 1))
  done
}

BACKEND_PORT="$(find_free_port "$PREFERRED_BACKEND_PORT")"
FRONTEND_PORT="$(find_free_port "$PREFERRED_FRONTEND_PORT" "$BACKEND_PORT")"

if [ "$BACKEND_PORT" != "$PREFERRED_BACKEND_PORT" ]; then
  echo "Backend preferred port $PREFERRED_BACKEND_PORT is busy, using $BACKEND_PORT."
fi
if [ "$FRONTEND_PORT" != "$PREFERRED_FRONTEND_PORT" ]; then
  echo "Frontend preferred port $PREFERRED_FRONTEND_PORT is busy, using $FRONTEND_PORT."
fi

if [ ! -d "$VENV_DIR" ]; then
  echo "Creating Python virtualenv: $VENV_DIR"
  python3 -m venv "$VENV_DIR"
fi

REQ_HASH="$(shasum -a 256 "$BACKEND_DIR/requirements.txt" | awk '{print $1}')"
REQ_STAMP="$VENV_DIR/.requirements.sha256"
if [ ! -f "$REQ_STAMP" ] || [ "$(cat "$REQ_STAMP")" != "$REQ_HASH" ]; then
  echo "Installing backend dependencies..."
  "$VENV_DIR/bin/python" -m pip install --upgrade pip >/dev/null
  "$VENV_DIR/bin/python" -m pip install -r "$BACKEND_DIR/requirements.txt"
  echo "$REQ_HASH" > "$REQ_STAMP"
fi

node_dependency_hash() {
  (cd "$FRONTEND_DIR" && shasum -a 256 package.json package-lock.json | shasum -a 256 | awk '{print $1}')
}

NODE_HASH="$(node_dependency_hash)"
NODE_STAMP="$FRONTEND_DIR/node_modules/.dependencies.sha256"
if [ ! -d "$FRONTEND_DIR/node_modules" ] || [ ! -f "$NODE_STAMP" ] || [ "$(cat "$NODE_STAMP")" != "$NODE_HASH" ]; then
  echo "Installing frontend dependencies..."
  (cd "$FRONTEND_DIR" && npm install)
  node_dependency_hash > "$NODE_STAMP"
fi

cat > "$RUNTIME_DIR/local.env" <<EOF
CRYPTO_DATA_ROOT=$DATA_ROOT
APP_TIMEZONE=$APP_TIMEZONE
BACKEND_PORT=$BACKEND_PORT
FRONTEND_PORT=$FRONTEND_PORT
VITE_API_BASE_URL=http://127.0.0.1:$BACKEND_PORT
OPENAI_MODEL=${OPENAI_MODEL:-gpt-5.4-mini}
OPENAI_BASE_URL=${OPENAI_BASE_URL:-https://api.openai.com}
EOF

export CRYPTO_DATA_ROOT="$DATA_ROOT"
export APP_TIMEZONE="$APP_TIMEZONE"
export VITE_API_BASE_URL="http://127.0.0.1:$BACKEND_PORT"
export OPENAI_MODEL="${OPENAI_MODEL:-gpt-5.4-mini}"
export OPENAI_BASE_URL="${OPENAI_BASE_URL:-https://api.openai.com}"

stop_tree() {
  pid="$1"
  if [ -z "$pid" ] || ! kill -0 "$pid" >/dev/null 2>&1; then
    return 0
  fi
  pkill -TERM -P "$pid" >/dev/null 2>&1 || true
  kill "$pid" >/dev/null 2>&1 || true
}

cleanup() {
  stop_tree "${FRONTEND_PID:-}"
  stop_tree "${BACKEND_PID:-}"
}
trap cleanup INT TERM EXIT

echo "Starting backend  http://127.0.0.1:$BACKEND_PORT"
"$VENV_DIR/bin/python" -m uvicorn app.main:app \
  --app-dir "$BACKEND_DIR" \
  --host 127.0.0.1 \
  --port "$BACKEND_PORT" \
  --reload \
  --reload-dir "$BACKEND_DIR" &
BACKEND_PID=$!

echo "Starting frontend http://127.0.0.1:$FRONTEND_PORT"
(cd "$FRONTEND_DIR" && exec npm run dev -- --host 127.0.0.1 --port "$FRONTEND_PORT" --strictPort) &
FRONTEND_PID=$!

echo
echo "Local web platform is starting."
echo "Open: http://127.0.0.1:$FRONTEND_PORT"
echo "API:  http://127.0.0.1:$BACKEND_PORT/api/health"
echo "Env:  $RUNTIME_DIR/local.env"
echo "Press Ctrl+C to stop both services."
echo

while kill -0 "$BACKEND_PID" >/dev/null 2>&1 && kill -0 "$FRONTEND_PID" >/dev/null 2>&1; do
  sleep 1
done
