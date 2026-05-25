#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ORIGINAL_ENV_KEYS="$(env | sed 's/=.*//' | tr '\n' ' ')"

DATA_ROOT_RESOLVED="$(
  python3 - "$ROOT_DIR" "$ORIGINAL_ENV_KEYS" <<'PY'
import os
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
original_keys = set(sys.argv[2].split())


def parse_env_file(path: Path, values: dict[str, str]) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in original_keys or key in values:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value


file_values: dict[str, str] = {}
parse_env_file(root / ".env", file_values)
parse_env_file(root / ".env.local", file_values)

if "CRYPTO_DATA_ROOT" in original_keys and os.getenv("CRYPTO_DATA_ROOT"):
    raw = os.environ["CRYPTO_DATA_ROOT"]
elif "DATA_ROOT" in original_keys and os.getenv("DATA_ROOT"):
    raw = os.environ["DATA_ROOT"]
else:
    raw = file_values.get("CRYPTO_DATA_ROOT") or file_values.get("DATA_ROOT") or str(root / "data" / "normalized_gzip")

path = Path(os.path.expandvars(os.path.expanduser(raw)))
if not path.is_absolute():
    path = root / path
print(path.resolve())
PY
)"

ARG_FORCE=false
ARG_RESUME=false
for arg in "$@"; do
  case "$arg" in
    --force) ARG_FORCE=true ;;
    --resume) ARG_RESUME=true ;;
  esac
done

has_candles() {
  python3 - "$1" <<'PY'
import sys
from pathlib import Path

root = Path(sys.argv[1])
raise SystemExit(0 if root.exists() and any(root.glob("candles_*/*/*.csv.gz")) else 1)
PY
}

if has_candles "$DATA_ROOT_RESOLVED" \
  && [ "${INIT_OKX_FORCE:-}" != "true" ] \
  && [ "${INIT_OKX_RESUME:-}" != "true" ] \
  && [ "$ARG_FORCE" != "true" ] \
  && [ "$ARG_RESUME" != "true" ]; then
  echo "Existing candle data found, skipping OKX initialization:"
  echo "  $DATA_ROOT_RESOLVED"
else
  init_args=(--days "${OKX_INIT_DAYS:-5}" --data-root "$DATA_ROOT_RESOLVED")
  if [ "${INIT_OKX_FORCE:-}" = "true" ]; then
    init_args+=(--force)
  fi
  if [ "${INIT_OKX_RESUME:-}" = "true" ]; then
    init_args+=(--resume)
  fi
  python3 "$ROOT_DIR/scripts/init-okx-data.py" "${init_args[@]}" "$@"
fi

exec "$ROOT_DIR/scripts/start-local.sh"
