#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
VENV_DIR="$ROOT_DIR/.venv"

ORIGINAL_ENV_KEYS="$(env | sed 's/=.*//' | tr '\n' ' ')"

trim_env_value() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

is_original_env_key() {
  case " $ORIGINAL_ENV_KEYS " in
    *" $1 "*) return 0 ;;
    *) return 1 ;;
  esac
}

load_env_file() {
  local file="$1"
  [ -f "$file" ] || return 0

  while IFS= read -r raw_line || [ -n "$raw_line" ]; do
    local line key value first last
    line="$(trim_env_value "$raw_line")"
    [ -z "$line" ] && continue
    [[ "$line" == \#* ]] && continue
    if [[ "$line" == export\ * ]]; then
      line="$(trim_env_value "${line#export }")"
    fi
    [[ "$line" == *"="* ]] || continue

    key="$(trim_env_value "${line%%=*}")"
    value="$(trim_env_value "${line#*=}")"
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    is_original_env_key "$key" && continue

    if [ "${#value}" -ge 2 ]; then
      first="${value:0:1}"
      last="${value:${#value}-1:1}"
      if { [ "$first" = "'" ] || [ "$first" = '"' ]; } && [ "$first" = "$last" ]; then
        value="${value:1:${#value}-2}"
      fi
    fi
    export "$key=$value"
  done < "$file"
}

resolve_project_path() {
  python3 - "$ROOT_DIR" "$1" <<'PY'
import os
import sys

root, raw = sys.argv[1], sys.argv[2]
path = os.path.expandvars(os.path.expanduser(raw))
if not os.path.isabs(path):
    path = os.path.join(root, path)
print(os.path.normpath(path))
PY
}

load_env_file "$ROOT_DIR/.env"
load_env_file "$ROOT_DIR/.env.local"

DEFAULT_DATA_ROOT="$ROOT_DIR/data/normalized_gzip"

if is_original_env_key "CRYPTO_DATA_ROOT" && [ -n "${CRYPTO_DATA_ROOT:-}" ]; then
  DATA_ROOT="$CRYPTO_DATA_ROOT"
elif is_original_env_key "DATA_ROOT" && [ -n "${DATA_ROOT:-}" ]; then
  DATA_ROOT="$DATA_ROOT"
else
  DATA_ROOT="${CRYPTO_DATA_ROOT:-${DATA_ROOT:-$DEFAULT_DATA_ROOT}}"
fi
DATA_ROOT="$(resolve_project_path "$DATA_ROOT")"
CRYPTO_DATA_ROOT="$DATA_ROOT"
RUNTIME_DIR="${RUNTIME_ROOT:-$ROOT_DIR/.runtime}"
RUNTIME_DIR="$(resolve_project_path "$RUNTIME_DIR")"
RUNTIME_ROOT="$RUNTIME_DIR"
CRYPTO_V2_ROOT="${CRYPTO_V2_ROOT:-$ROOT_DIR/local-pipeline/crypto-v2}"
CRYPTO_V2_ROOT="$(resolve_project_path "$CRYPTO_V2_ROOT")"
STRATEGY_RESEARCH_ROOT="${STRATEGY_RESEARCH_ROOT:-$ROOT_DIR/local-pipeline/strategy-research}"
STRATEGY_RESEARCH_ROOT="$(resolve_project_path "$STRATEGY_RESEARCH_ROOT")"
CATALOG_ROOT="${CATALOG_ROOT:-$ROOT_DIR/data/catalog}"
CATALOG_ROOT="$(resolve_project_path "$CATALOG_ROOT")"
if [ -z "${USE_LEGACY_PIPELINE:-}" ] && [ -f "$STRATEGY_RESEARCH_ROOT/versions-crypto/增量下载数据.py" ]; then
  USE_LEGACY_PIPELINE=true
fi
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
DATA_ROOT=$DATA_ROOT
CRYPTO_DATA_ROOT=$DATA_ROOT
RUNTIME_ROOT=$RUNTIME_ROOT
CRYPTO_V2_ROOT=$CRYPTO_V2_ROOT
STRATEGY_RESEARCH_ROOT=$STRATEGY_RESEARCH_ROOT
CATALOG_ROOT=$CATALOG_ROOT
USE_LEGACY_PIPELINE=${USE_LEGACY_PIPELINE:-}
APP_TIMEZONE=$APP_TIMEZONE
BACKEND_PORT=$BACKEND_PORT
FRONTEND_PORT=$FRONTEND_PORT
VITE_API_BASE_URL=http://127.0.0.1:$BACKEND_PORT
OPENAI_MODEL=${OPENAI_MODEL:-gpt-5.4-mini}
OPENAI_BASE_URL=${OPENAI_BASE_URL:-https://api.openai.com}
EOF

export DATA_ROOT="$DATA_ROOT"
export CRYPTO_DATA_ROOT="$DATA_ROOT"
export RUNTIME_ROOT="$RUNTIME_ROOT"
export CRYPTO_V2_ROOT="$CRYPTO_V2_ROOT"
export STRATEGY_RESEARCH_ROOT="$STRATEGY_RESEARCH_ROOT"
export CATALOG_ROOT="$CATALOG_ROOT"
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
