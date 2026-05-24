from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_env_file(path: Path, protected_keys: set[str]) -> None:
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
        if not key or key in protected_keys:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value


_PROTECTED_ENV_KEYS = set(os.environ)
_load_env_file(PROJECT_ROOT / ".env", _PROTECTED_ENV_KEYS)
_load_env_file(PROJECT_ROOT / ".env.local", _PROTECTED_ENV_KEYS)


def _env_value(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value is not None and value.strip():
            return value.strip()
    return None


def _path_from_env(names: tuple[str, ...], default: Path) -> Path:
    raw = _env_value(*names)
    return _path_from_raw(raw, default)


def _path_from_alias_env(names: tuple[str, ...], default: Path) -> Path:
    for name in names:
        if name in _PROTECTED_ENV_KEYS:
            raw = os.getenv(name)
            if raw is not None and raw.strip():
                return _path_from_raw(raw.strip(), default)
    return _path_from_env(names, default)


def _path_from_raw(raw: str | None, default: Path) -> Path:
    if raw is None:
        return default
    expanded = Path(os.path.expandvars(os.path.expanduser(raw)))
    if expanded.is_absolute():
        return expanded
    return PROJECT_ROOT / expanded


def _bool_from_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


LEGACY_CRYPTO_V2_ROOT = Path("/Users/sunguanlong/Desktop/crypto/crypto-v2")
LEGACY_STRATEGY_RESEARCH_ROOT = Path("/Users/sunguanlong/Desktop/crypto/strategy-research")
LEGACY_DATA_ROOT = LEGACY_CRYPTO_V2_ROOT / "data" / "normalized_gzip"

DEFAULT_CRYPTO_V2_ROOT = LEGACY_CRYPTO_V2_ROOT if LEGACY_CRYPTO_V2_ROOT.exists() else PROJECT_ROOT
CRYPTO_V2_ROOT = _path_from_env(("CRYPTO_V2_ROOT",), DEFAULT_CRYPTO_V2_ROOT)

DEFAULT_STRATEGY_RESEARCH_ROOT = (
    LEGACY_STRATEGY_RESEARCH_ROOT if LEGACY_STRATEGY_RESEARCH_ROOT.exists() else PROJECT_ROOT
)
STRATEGY_RESEARCH_ROOT = _path_from_env(("STRATEGY_RESEARCH_ROOT",), DEFAULT_STRATEGY_RESEARCH_ROOT)

DEFAULT_DATA_ROOT = (
    LEGACY_DATA_ROOT
    if LEGACY_DATA_ROOT.exists()
    else CRYPTO_V2_ROOT / "data" / "normalized_gzip"
    if CRYPTO_V2_ROOT != PROJECT_ROOT
    else PROJECT_ROOT / "data" / "normalized_gzip"
)
DATA_ROOT = _path_from_alias_env(("CRYPTO_DATA_ROOT", "DATA_ROOT"), DEFAULT_DATA_ROOT)

DEFAULT_CATALOG_ROOT = (
    CRYPTO_V2_ROOT / "data" / "catalog"
    if CRYPTO_V2_ROOT != PROJECT_ROOT
    else PROJECT_ROOT / "data" / "catalog"
)
CATALOG_ROOT = _path_from_env(("CATALOG_ROOT",), DEFAULT_CATALOG_ROOT)

RUNTIME_ROOT = _path_from_env(("RUNTIME_ROOT",), PROJECT_ROOT / ".runtime")
BACKTEST_DB_PATH = _path_from_env(("BACKTEST_DB",), RUNTIME_ROOT / "backtests.sqlite3")
SCREENER_FAVORITES_DB_PATH = _path_from_env(
    ("SCREENER_FAVORITES_DB",),
    RUNTIME_ROOT / "screener_favorites.sqlite3",
)
INDICATOR_STORE_PATH = _path_from_env(("INDICATOR_STORE_PATH",), RUNTIME_ROOT / "indicator_repository.json")
SCRIPT_INDICATOR_ROOT = _path_from_env(("SCRIPT_INDICATOR_ROOT",), RUNTIME_ROOT / "script_indicators")
CONTRACT_UPDATE_RUNTIME_DIR = _path_from_env(
    ("CONTRACT_UPDATE_RUNTIME_DIR",),
    RUNTIME_ROOT / "contract_update",
)

APP_TIMEZONE = os.getenv("APP_TIMEZONE", "Asia/Shanghai")
USE_LEGACY_PIPELINE = _bool_from_env(
    "USE_LEGACY_PIPELINE",
    (STRATEGY_RESEARCH_ROOT / "versions-crypto" / "增量下载数据.py").exists(),
)

TIMEFRAMES = {
    "1m": "candles_1m",
    "5m": "candles_5m",
    "15m": "candles_15m",
    "1H": "candles_1H",
    "1D": "candles_1D",
}
