from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .settings import LIVE_BOT_RUNTIME_DIR, PROJECT_ROOT


CST = timezone(timedelta(hours=8))
MAX_TOTAL_CAP_USD = 10.0
MAX_CAPITAL_PER_TRADE_USD = 10.0
MAX_LEVERAGE = 1.0
MAX_POSITIONS = 1
MAX_LOG_TAIL_CHARS = 40000
BOT_FILENAME = "bot.py"
CONFIG_FILENAME = "config.live.json"
MANIFEST_FILENAME = "manifest.json"
PID_FILENAME = "bot.pid"


class LiveBotService:
    def __init__(self, root: Path = LIVE_BOT_RUNTIME_DIR) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def generate(self, strategy: dict[str, Any]) -> dict[str, Any]:
        bot_dir = self._bot_dir(strategy)
        state_dir = bot_dir / "state"
        log_dir = bot_dir / "logs"
        bot_dir.mkdir(parents=True, exist_ok=True)
        state_dir.mkdir(parents=True, exist_ok=True)
        log_dir.mkdir(parents=True, exist_ok=True)

        config = self._build_config(strategy)
        bot_path = bot_dir / BOT_FILENAME
        config_path = bot_dir / CONFIG_FILENAME
        manifest_path = bot_dir / MANIFEST_FILENAME

        bot_path.write_text(BOT_TEMPLATE, encoding="utf-8")
        config_path.write_text(_pretty_json(config), encoding="utf-8")

        manifest = {
            "strategy_id": strategy["id"],
            "strategy_name": strategy.get("name") or "",
            "generated_at": _now_ms(),
            "updated_at": _now_ms(),
            "status": "generated",
            "pid": None,
            "bot_path": str(bot_path),
            "config_path": str(config_path),
            "state_dir": str(state_dir),
            "log_dir": str(log_dir),
            "risk_guard": config["risk_guard"],
            "package_hash": (strategy.get("strategy_package") or {}).get("package_hash"),
            "last_error": "",
        }
        self._write_manifest(manifest_path, manifest)
        self._ensure_state_files(state_dir)
        return self.status(strategy["id"])

    def start(self, strategy: dict[str, Any]) -> dict[str, Any]:
        status = self.status(strategy["id"], tail_chars=0)
        if not status.get("generated"):
            status = self.generate(strategy)
        if status.get("running"):
            return self.status(strategy["id"])

        bot_dir = self._bot_dir(strategy)
        bot_path = bot_dir / BOT_FILENAME
        config_path = bot_dir / CONFIG_FILENAME
        log_dir = bot_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        if not bot_path.exists() or not config_path.exists():
            raise FileNotFoundError("实盘 bot 文件不存在，请先生成脚本")

        out_path = log_dir / "process.stdout.log"
        err_path = log_dir / "process.stderr.log"
        out_fh = out_path.open("ab")
        err_fh = err_path.open("ab")
        try:
            proc = subprocess.Popen(
                [_bot_python_executable(), str(bot_path), str(config_path)],
                cwd=str(bot_dir),
                stdout=out_fh,
                stderr=err_fh,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
        finally:
            out_fh.close()
            err_fh.close()

        (bot_dir / PID_FILENAME).write_text(str(proc.pid), encoding="utf-8")
        manifest = self._read_manifest(bot_dir / MANIFEST_FILENAME)
        manifest.update(
            {
                "status": "running",
                "pid": proc.pid,
                "started_at": _now_ms(),
                "updated_at": _now_ms(),
                "last_error": "",
            }
        )
        self._write_manifest(bot_dir / MANIFEST_FILENAME, manifest)
        threading.Thread(
            target=self._watch_process,
            args=(strategy["id"], proc.pid, proc),
            daemon=True,
        ).start()
        return self.status(strategy["id"])

    def stop(self, strategy_id: str) -> dict[str, Any]:
        bot_dir = self._bot_dir_by_id(strategy_id)
        pid = self._pid(bot_dir)
        if pid and _process_alive(pid):
            try:
                os.killpg(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except PermissionError as exc:
                raise RuntimeError(f"无法停止实盘进程：{exc}") from exc
            deadline = time.time() + 8
            while time.time() < deadline and _process_alive(pid):
                time.sleep(0.2)
            if _process_alive(pid):
                try:
                    os.killpg(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        pid_path = bot_dir / PID_FILENAME
        if pid_path.exists():
            pid_path.unlink()
        manifest = self._read_manifest(bot_dir / MANIFEST_FILENAME)
        manifest.update({"status": "stopped", "pid": None, "stopped_at": _now_ms(), "updated_at": _now_ms()})
        self._write_manifest(bot_dir / MANIFEST_FILENAME, manifest)
        return self.status(strategy_id)

    def _watch_process(self, strategy_id: str, pid: int, proc: subprocess.Popen[Any]) -> None:
        return_code = proc.wait()
        bot_dir = self._bot_dir_by_id(strategy_id)
        manifest_path = bot_dir / MANIFEST_FILENAME
        manifest = self._read_manifest(manifest_path)
        if manifest.get("pid") != pid:
            return
        pid_path = bot_dir / PID_FILENAME
        if pid_path.exists():
            pid_path.unlink()
        manifest.update(
            {
                "status": "stopped" if return_code == 0 else "crashed",
                "pid": None,
                "return_code": return_code,
                "finished_at": _now_ms(),
                "updated_at": _now_ms(),
                "last_error": "" if return_code == 0 else f"bot 进程异常退出，return_code={return_code}",
            }
        )
        self._write_manifest(manifest_path, manifest)

    def restart(self, strategy: dict[str, Any]) -> dict[str, Any]:
        self.stop(strategy["id"])
        return self.start(strategy)

    def status(self, strategy_id: str, *, tail_chars: int = 12000) -> dict[str, Any]:
        bot_dir = self._bot_dir_by_id(strategy_id)
        manifest_path = bot_dir / MANIFEST_FILENAME
        manifest = self._read_manifest(manifest_path)
        generated = (bot_dir / BOT_FILENAME).exists() and (bot_dir / CONFIG_FILENAME).exists()
        pid = self._pid(bot_dir)
        running = bool(pid and _process_alive(pid))
        if generated and manifest:
            next_status = "running" if running else manifest.get("status") or "generated"
            if next_status == "running" and not running:
                next_status = "crashed"
            if manifest.get("status") != next_status or manifest.get("pid") != (pid if running else None):
                manifest.update({"status": next_status, "pid": pid if running else None, "updated_at": _now_ms()})
                self._write_manifest(manifest_path, manifest)

        state_dir = bot_dir / "state"
        log_dir = bot_dir / "logs"
        return {
            "strategy_id": strategy_id,
            "generated": generated,
            "status": "running" if running else manifest.get("status", "not_generated"),
            "running": running,
            "pid": pid if running else None,
            "root": str(bot_dir),
            "bot_path": str(bot_dir / BOT_FILENAME) if generated else "",
            "config_path": str(bot_dir / CONFIG_FILENAME) if generated else "",
            "manifest": manifest,
            "config": _read_json(bot_dir / CONFIG_FILENAME, {}),
            "positions": _read_json(state_dir / "positions.json", {}),
            "trades": _read_json(state_dir / "trades.json", []),
            "watchlist": _read_json(state_dir / "watchlist.json", []),
            "handled_signals": _read_json(state_dir / "handled_signals.json", {}),
            "logs": {
                "latest": _read_latest_strategy_log(log_dir, tail_chars),
                "stdout": _read_tail(log_dir / "process.stdout.log", min(tail_chars, 12000)),
                "stderr": _read_tail(log_dir / "process.stderr.log", min(tail_chars, 12000)),
            },
        }

    def _build_config(self, strategy: dict[str, Any]) -> dict[str, Any]:
        package = strategy.get("strategy_package") if isinstance(strategy.get("strategy_package"), dict) else {}
        signal = package.get("signal") if isinstance(package.get("signal"), dict) else {}
        entry = package.get("entry") if isinstance(package.get("entry"), dict) else {}
        exit_cfg = package.get("exit") if isinstance(package.get("exit"), dict) else {}
        risk = package.get("risk") if isinstance(package.get("risk"), dict) else {}
        favorite = signal.get("favorite_snapshot") if isinstance(signal.get("favorite_snapshot"), dict) else {}
        conditions = favorite.get("metadata_conditions") if isinstance(favorite.get("metadata_conditions"), list) else []

        signal_cfg = _signal_config_from_conditions(conditions)
        entry_cfg = {
            "timeframe": str(entry.get("entry_timeframe") or "5m"),
            "rule": str(entry.get("entry_rule") or "consecutive_green_bars"),
            "consecutive_bars": _safe_int(entry.get("entry_consecutive_bars"), 2),
            "min_gain_pct": _safe_float(entry.get("entry_min_gain_pct_each"), 2.0),
            "search_window_minutes": _safe_int(entry.get("entry_window_minutes"), 60),
            "stale_window_minutes": 2,
        }
        exit_live = {
            "hold_minutes": _safe_int(exit_cfg.get("exit_hold_minutes"), 440),
        }
        risk_guard = {
            "max_total_cap_usd": MAX_TOTAL_CAP_USD,
            "capital_per_trade_usd": min(_safe_float(risk.get("position_usdt"), MAX_CAPITAL_PER_TRADE_USD), MAX_CAPITAL_PER_TRADE_USD),
            "leverage": min(_safe_float(risk.get("leverage"), MAX_LEVERAGE), MAX_LEVERAGE),
            "max_positions": min(_safe_int(risk.get("max_positions"), MAX_POSITIONS), MAX_POSITIONS),
            "max_same_symbol_positions": 1,
        }
        return {
            "dry_run": False,
            "env_path": os.getenv("OKX_ENV_PATH", str(PROJECT_ROOT.parent / "crypto" / "okx-trading" / ".env")),
            "relay_base_url": os.getenv("OKX_RELAY_BASE_URL", "http://154.21.91.216:8000"),
            "strategy_id": strategy["id"],
            "strategy_name": strategy.get("name") or "",
            "strategy_package_hash": package.get("package_hash") or "",
            "source_backtest_id": strategy.get("source_backtest_id") or package.get("source_backtest_id") or "",
            "capital_per_trade_usd": risk_guard["capital_per_trade_usd"],
            "max_total_cap_usd": risk_guard["max_total_cap_usd"],
            "leverage": risk_guard["leverage"],
            "max_positions": risk_guard["max_positions"],
            "pos_side": "auto",
            "stop_loss_pct": _safe_float(exit_cfg.get("stop_loss_pct"), 15.0),
            "signal": signal_cfg,
            "entry": entry_cfg,
            "exit": exit_live,
            "risk_guard": risk_guard,
            "universe": {
                "use_dim": True,
                "dim_catalog": os.getenv(
                    "OKX_DIM_CATALOG",
                    str(PROJECT_ROOT.parent / "crypto" / "crypto-v2" / "data" / "catalog" / "instruments_okx_usdt_swap_dim.json"),
                ),
            },
            "scan": {"max_workers": 10},
            "paths": {
                "project_root": str(PROJECT_ROOT.parent / "crypto"),
                "crypto_v2_src": str(PROJECT_ROOT.parent / "crypto" / "crypto-v2" / "src"),
                "pump_fade_live_root": str(PROJECT_ROOT.parent / "crypto" / "pump-fade-live"),
            },
            "supported_strategy": "pump_fade_v1",
            "metadata_conditions": conditions,
        }

    def _bot_dir(self, strategy: dict[str, Any]) -> Path:
        return self._bot_dir_by_id(strategy["id"])

    def _bot_dir_by_id(self, strategy_id: str) -> Path:
        safe = "".join(ch for ch in strategy_id if ch.isalnum() or ch in {"-", "_"})
        return self.root / safe

    def _pid(self, bot_dir: Path) -> int | None:
        pid_path = bot_dir / PID_FILENAME
        if not pid_path.exists():
            return None
        try:
            return int(pid_path.read_text(encoding="utf-8").strip())
        except (TypeError, ValueError):
            return None

    def _read_manifest(self, path: Path) -> dict[str, Any]:
        return _read_json(path, {})

    def _write_manifest(self, path: Path, manifest: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_pretty_json(manifest), encoding="utf-8")

    def _ensure_state_files(self, state_dir: Path) -> None:
        defaults: dict[str, Any] = {
            "positions.json": {},
            "trades.json": [],
            "watchlist.json": [],
            "handled_signals.json": {},
        }
        for name, value in defaults.items():
            path = state_dir / name
            if not path.exists():
                path.write_text(_pretty_json(value), encoding="utf-8")


def _signal_config_from_conditions(conditions: list[Any]) -> dict[str, Any]:
    min_gain_pct = 10.0
    min_vol_usdt = 500_000.0
    unsupported: list[str] = []
    for condition in conditions:
        if not isinstance(condition, dict):
            continue
        indicator_id = str(condition.get("indicator_id") or "")
        operator = str(condition.get("operator") or "")
        value = _safe_float(condition.get("value"), 0.0)
        if indicator_id.endswith("two_bull_gain_pct") and operator == "gt":
            min_gain_pct = value
        elif indicator_id.endswith("quote_volume_24h") and operator == "gt":
            min_vol_usdt = value
        else:
            unsupported.append(indicator_id or "unknown")
    return {
        "timeframe": "1H",
        "min_gain_pct": min_gain_pct,
        "min_vol_usdt": min_vol_usdt,
        "conditions": conditions,
        "unsupported_conditions": unsupported,
        "requires_supported_template": True,
    }


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _pretty_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _now_ms() -> int:
    return int(time.time() * 1000)


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if _process_stat(pid).startswith("Z"):
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _process_stat(pid: int) -> str:
    try:
        output = subprocess.check_output(["ps", "-p", str(pid), "-o", "stat="], text=True, stderr=subprocess.DEVNULL)
    except (subprocess.SubprocessError, OSError):
        return ""
    return output.strip()


def _bot_python_executable() -> str:
    configured = os.getenv("LIVE_BOT_PYTHON")
    if configured:
        return configured
    for candidate in ("python3", "python"):
        try:
            result = subprocess.run(
                [candidate, "-c", "import requests"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except OSError:
            continue
        if result.returncode == 0:
            return candidate
    return sys.executable


def _read_tail(path: Path, max_chars: int) -> str:
    if max_chars <= 0 or not path.exists():
        return ""
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - max_chars))
            return fh.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _read_latest_strategy_log(log_dir: Path, max_chars: int) -> str:
    if max_chars <= 0 or not log_dir.exists():
        return ""
    candidates = sorted(log_dir.glob("*.log"), key=lambda path: path.stat().st_mtime if path.exists() else 0)
    strategy_logs = [path for path in candidates if not path.name.startswith("process.")]
    if not strategy_logs:
        return ""
    return _read_tail(strategy_logs[-1], max_chars)


BOT_TEMPLATE = r'''#!/usr/bin/env python3
"""
Generated small-cap live bot.

This script is intended for real exchange execution with a hard 10 USDT risk
cap. It refuses to increase capital, leverage, or position count even if the
JSON config is edited manually.
"""
from __future__ import annotations

import json
import logging
import signal as sig
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

CST = timezone(timedelta(hours=8))
SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = Path(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else SCRIPT_DIR / "config.live.json"
STATE_DIR = SCRIPT_DIR / "state"
LOG_DIR = SCRIPT_DIR / "logs"
MINUTE_MS = 60_000
HARD_MAX_TOTAL_CAP_USD = 10.0
HARD_MAX_CAPITAL_PER_TRADE_USD = 10.0
HARD_MAX_LEVERAGE = 1.0
HARD_MAX_POSITIONS = 1


def load_config(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        config = json.load(fh)
    risk = config.setdefault("risk_guard", {})
    requested_cap = float(config.get("capital_per_trade_usd") or risk.get("capital_per_trade_usd") or HARD_MAX_CAPITAL_PER_TRADE_USD)
    requested_total = float(config.get("max_total_cap_usd") or risk.get("max_total_cap_usd") or HARD_MAX_TOTAL_CAP_USD)
    requested_leverage = float(config.get("leverage") or risk.get("leverage") or HARD_MAX_LEVERAGE)
    requested_positions = int(config.get("max_positions") or risk.get("max_positions") or HARD_MAX_POSITIONS)
    cap = min(requested_cap, HARD_MAX_CAPITAL_PER_TRADE_USD, HARD_MAX_TOTAL_CAP_USD)
    total = min(requested_total, HARD_MAX_TOTAL_CAP_USD)
    leverage = min(requested_leverage, HARD_MAX_LEVERAGE)
    max_positions = min(requested_positions, HARD_MAX_POSITIONS)
    config["capital_per_trade_usd"] = cap
    config["max_total_cap_usd"] = total
    config["leverage"] = leverage
    config["max_positions"] = max_positions
    risk.update({
        "capital_per_trade_usd": cap,
        "max_total_cap_usd": total,
        "leverage": leverage,
        "max_positions": max_positions,
        "hard_cap_enforced": True,
    })
    return config


def setup_paths(config: dict) -> None:
    paths = config.get("paths") if isinstance(config.get("paths"), dict) else {}
    for item in (paths.get("pump_fade_live_root"), paths.get("crypto_v2_src")):
        if item and str(item) not in sys.path:
            sys.path.insert(0, str(item))


def setup_logger() -> logging.Logger:
    LOG_DIR.mkdir(exist_ok=True)
    log_file = LOG_DIR / f"{datetime.now(CST).strftime('%Y-%m-%d')}.log"
    fmt = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    logger = logging.getLogger("generated_live_bot")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    return logger


def load_state(name: str):
    path = STATE_DIR / f"{name}.json"
    if path.exists():
        try:
            with path.open(encoding="utf-8") as fh:
                return json.load(fh)
        except json.JSONDecodeError:
            logging.getLogger("generated_live_bot").error("状态文件损坏，重置: %s", path)
    return {} if name in {"positions", "handled_signals"} else []


def save_state(name: str, data) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    path = STATE_DIR / f"{name}.json"
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    tmp.replace(path)


def make_signal_key(inst_id: str, confirm_ts: int) -> str:
    return f"{inst_id}|{confirm_ts}"


def resolved_pos_side(config: dict) -> str | None:
    value = config.get("pos_side", "auto")
    return None if value == "auto" else value


def validate_supported_strategy(config: dict, log: logging.Logger) -> bool:
    unsupported = config.get("signal", {}).get("unsupported_conditions") or []
    entry = config.get("entry", {})
    ok = True
    if unsupported:
        log.error("策略包含当前模板不支持的条件，拒绝真实下单: %s", unsupported)
        ok = False
    if entry.get("rule") != "consecutive_green_bars":
        log.error("当前模板只支持 consecutive_green_bars 入场规则，拒绝真实下单: %s", entry.get("rule"))
        ok = False
    if entry.get("timeframe", "5m") != "5m":
        log.error("当前模板只支持 5m 入场周期，拒绝真实下单: %s", entry.get("timeframe"))
        ok = False
    return ok


def build_clients(config: dict, dry_run: bool):
    from data.base import DataClient
    from data.instruments import InstrumentsAPI
    from data.market import MarketAPI
    from data.trade import TradeAPI

    env_path = str(Path(config["env_path"]))
    if dry_run:
        client = DataClient.__new__(DataClient)
        client.api_key = ""
        client.secret_key = ""
        client.passphrase = ""
        client.base_url = config.get("relay_base_url", "http://154.21.91.216:8000")
    else:
        client = DataClient(env_path)
    market = MarketAPI(client)
    instruments = InstrumentsAPI(client)
    trade_api = TradeAPI(client, instruments)
    return market, trade_api


def strategy_config(config: dict):
    from cryptov2.strategies.pump_fade.config import PumpFadeConfig

    mapped = {
        "capital_per_trade_usd": config["capital_per_trade_usd"],
        "leverage": config["leverage"],
        "max_positions": config["max_positions"],
        "stop_loss_pct": config["stop_loss_pct"],
        "signal": {
            "min_gain_pct": config.get("signal", {}).get("min_gain_pct", 10),
            "min_vol_usdt": config.get("signal", {}).get("min_vol_usdt", 500000),
        },
        "entry": {
            "consecutive_bars": config.get("entry", {}).get("consecutive_bars", 2),
            "min_gain_pct": config.get("entry", {}).get("min_gain_pct", 2.0),
            "search_window_minutes": config.get("entry", {}).get("search_window_minutes", 60),
            "stale_window_minutes": config.get("entry", {}).get("stale_window_minutes", 2),
        },
    }
    return PumpFadeConfig.from_dict(mapped)


def filter_tickers_by_universe(tickers: dict, config: dict, log: logging.Logger) -> dict:
    universe = config.get("universe", {})
    if not universe.get("use_dim", True):
        return tickers
    dim_path = Path(universe.get("dim_catalog") or "")
    if not dim_path.exists():
        log.warning("合约维表不存在，实盘扫描退回 ticker 全量: %s", dim_path)
        return tickers
    from cryptov2.data.instruments_dim import select_instrument_symbols

    allowed = set(select_instrument_symbols(dim_path, online_only=True, data_enabled_only=True))
    filtered = {inst_id: ticker for inst_id, ticker in tickers.items() if inst_id in allowed}
    log.info("合约维表过滤: tickers=%s allowed=%s used=%s", len(tickers), len(allowed), len(filtered))
    return filtered


def prune_handled_signals(handled: dict, *, keep_hours: int = 96) -> dict:
    now_ts = int(time.time() * 1000)
    cutoff = now_ts - keep_hours * 3600_000
    return {key: value for key, value in handled.items() if int(value.get("confirm_ts", 0)) >= cutoff}


def scan_signals(market, config: dict, handled: dict, log: logging.Logger) -> list[dict]:
    from cryptov2.strategies.pump_fade.bot_compat import filter_bot_signal_candidates, scan_bot_signals

    cfg = strategy_config(config)
    max_workers = int(config.get("scan", {}).get("max_workers", 10))
    tickers = market.get_tickers("SWAP")
    if not tickers:
        log.warning("获取 tickers 失败")
        return []
    tickers = filter_tickers_by_universe(tickers, config, log)
    candidates = sorted(filter_bot_signal_candidates(tickers, cfg))
    log.info("扫描品种: %s 个", len(candidates))
    kline_map = market.get_klines_batch(candidates, "1H", 5, max_workers=max_workers)
    now_ts = int(time.time() * 1000)
    signals = []
    for signal in scan_bot_signals(tickers, kline_map, cfg, now_ts):
        key = make_signal_key(signal.inst_id, signal.confirm_ts)
        if key in handled:
            continue
        signals.append({
            "signal_key": key,
            "inst_id": signal.inst_id,
            "confirm_ts": signal.confirm_ts,
            "confirm_time": signal.confirm_time,
            "cum_gain": signal.cum_gain,
        })
    signals.sort(key=lambda item: (-item["cum_gain"], item["confirm_ts"], item["inst_id"]))
    log.info("发现有效异动候选: %s 个", len(signals))
    for item in signals[:10]:
        log.info("  %s %s +%.2f%%", item["inst_id"], item["confirm_time"], item["cum_gain"])
    return signals


def check_entry(market, signal_info: dict, config: dict, log: logging.Logger) -> dict | None:
    from cryptov2.strategies.pump_fade.bot_compat import find_bot_entry

    cfg = strategy_config(config)
    limit = max(24, cfg.entry_search_window_min // 5 + 8)
    bars = market.get_klines(signal_info["inst_id"], "5m", limit)
    if not bars:
        return None
    entry = find_bot_entry(
        bars,
        int(signal_info["confirm_ts"]),
        cfg,
        now_ts=int(time.time() * 1000),
        enforce_stale_guard=True,
    )
    if entry is None:
        return None
    log.info(
        "触发入场: %s 触发[%s] 延迟=%.1fmin",
        signal_info["inst_id"],
        "+".join(f"{x:.1f}%" for x in entry.trigger),
        entry.delay_min,
    )
    return {
        "entry_ts": entry.entry_ts,
        "entry_price": entry.entry_price,
        "trigger": entry.trigger,
        "delay_min": entry.delay_min,
    }


def active_margin(positions: dict) -> float:
    return sum(float(pos.get("margin_usd") or 0) for pos in positions.values() if pos.get("status") == "active")


def assert_risk_allows_open(config: dict, positions: dict, log: logging.Logger) -> bool:
    active = [pos for pos in positions.values() if pos.get("status") == "active"]
    margin = float(config["capital_per_trade_usd"])
    if margin > HARD_MAX_CAPITAL_PER_TRADE_USD or margin > float(config["max_total_cap_usd"]):
        log.error("风控拒绝开仓: 单笔保证金 %.2f 超过硬上限", margin)
        return False
    if float(config["leverage"]) > HARD_MAX_LEVERAGE:
        log.error("风控拒绝开仓: 杠杆 %.2f 超过硬上限", float(config["leverage"]))
        return False
    if len(active) >= HARD_MAX_POSITIONS or len(active) >= int(config["max_positions"]):
        log.info("风控拒绝开仓: 已达到最大持仓数")
        return False
    if active_margin(positions) + margin > HARD_MAX_TOTAL_CAP_USD + 1e-9:
        log.error("风控拒绝开仓: 总占用 %.2f + %.2f 超过 10U", active_margin(positions), margin)
        return False
    return True


def planned_exit_ts(entry_ts: int, hold_minutes: int) -> int:
    return entry_ts + hold_minutes * MINUTE_MS


def open_position(trade_api, inst_id: str, entry_info: dict, signal_info: dict, config: dict, log: logging.Logger, dry_run: bool) -> bool:
    positions = load_state("positions")
    active = {iid: pos for iid, pos in positions.items() if pos.get("status") == "active"}
    if inst_id in active:
        return False
    if not assert_risk_allows_open(config, positions, log):
        return False
    margin = float(config["capital_per_trade_usd"])
    leverage = int(float(config["leverage"]))
    stop_price = entry_info["entry_price"] * (1 + float(config["stop_loss_pct"]) / 100.0)
    exit_ts = planned_exit_ts(entry_info["entry_ts"], int(config["exit"]["hold_minutes"]))
    if dry_run:
        log.info("[DRY-RUN] 模拟开空 %s $%.2f %sx @ %.6g", inst_id, margin, leverage, entry_info["entry_price"])
        contracts = 0
        actual_price = entry_info["entry_price"]
        order_id = ""
    else:
        result = trade_api.open_short(inst_id, margin, leverage, pos_side=resolved_pos_side(config))
        if not result.get("success"):
            log.error("开仓失败 %s: %s", inst_id, result.get("msg"))
            return False
        contracts = result["contracts"]
        actual_price = result["price"]
        order_id = result.get("ord_id", "")
        log.info("开仓成功: %s %s张 @ %.6g", inst_id, contracts, actual_price)
    positions[inst_id] = {
        "status": "active",
        "side": "short",
        "entry_time": datetime.now(CST).isoformat(),
        "entry_ts": entry_info["entry_ts"],
        "entry_price": actual_price,
        "trigger": entry_info["trigger"],
        "delay_min": entry_info["delay_min"],
        "stop_price": stop_price,
        "exit_ts": exit_ts,
        "exit_time": datetime.fromtimestamp(exit_ts / 1000, tz=CST).isoformat(),
        "contracts": contracts,
        "order_id": order_id,
        "leverage": leverage,
        "margin_usd": margin,
        "signal_gain_pct": signal_info["cum_gain"],
        "signal_confirm_time": signal_info["confirm_time"],
        "current_pnl_pct": 0.0,
        "current_price": actual_price,
        "max_adverse": 0.0,
    }
    save_state("positions", positions)
    trades = load_state("trades")
    trades.append({
        "time": datetime.now(CST).isoformat(),
        "action": "open_short",
        "inst_id": inst_id,
        "price": actual_price,
        "trigger": entry_info["trigger"],
        "delay_min": entry_info["delay_min"],
        "margin": margin,
        "leverage": leverage,
        "contracts": contracts,
        "order_id": order_id,
        "signal_gain_pct": signal_info["cum_gain"],
        "dry_run": dry_run,
    })
    save_state("trades", trades)
    return True


def close_position(trade_api, inst_id: str, pos: dict, reason: str, log: logging.Logger, dry_run: bool, pos_side: str | None) -> bool:
    current_price = pos.get("current_price", pos["entry_price"])
    pnl_pct = pos.get("current_pnl_pct", 0.0)
    if dry_run:
        log.info("[DRY-RUN] 模拟平仓 %s %s", inst_id, reason)
        pnl_usd = pnl_pct / 100.0 * pos["margin_usd"] * pos["leverage"]
        order_id = ""
    else:
        result = trade_api.close_short(inst_id, pos["contracts"], pos_side=pos_side)
        if not result.get("success"):
            log.error("平仓失败 %s: %s", inst_id, result.get("msg"))
            return False
        pnl_info = trade_api.get_position_pnl(inst_id)
        pnl_usd = float(pnl_info.get("upl", 0)) if pnl_info else pnl_pct / 100.0 * pos["margin_usd"] * pos["leverage"]
        order_id = result.get("ord_id", "")
    positions = load_state("positions")
    pos["status"] = "closed"
    pos["close_time"] = datetime.now(CST).isoformat()
    pos["close_price"] = current_price
    pos["close_pnl_pct"] = round(pnl_pct, 4)
    pos["close_pnl_usd"] = round(pnl_usd, 4)
    pos["close_reason"] = reason
    pos["close_order_id"] = order_id
    positions[inst_id] = pos
    save_state("positions", positions)
    trades = load_state("trades")
    trades.append({
        "time": datetime.now(CST).isoformat(),
        "action": "close_short",
        "inst_id": inst_id,
        "price": current_price,
        "pnl_pct": round(pnl_pct, 4),
        "pnl_usd": round(pnl_usd, 4),
        "reason": reason,
        "order_id": order_id,
        "dry_run": dry_run,
    })
    save_state("trades", trades)
    log.info("已平仓 %s: PnL=%+.2f%% $%+.2f 原因=%s", inst_id, pnl_pct, pnl_usd, reason)
    return True


def manage_positions(market, trade_api, config: dict, log: logging.Logger, dry_run: bool) -> None:
    positions = load_state("positions")
    now_ts = int(time.time() * 1000)
    for inst_id, pos in list(positions.items()):
        if pos.get("status") != "active":
            continue
        ticker = market.get_ticker(inst_id)
        if ticker is None:
            continue
        current_price = ticker.last
        entry_price = pos["entry_price"]
        pnl_pct = -(current_price - entry_price) / entry_price * 100 if entry_price > 0 else 0.0
        pos["current_price"] = current_price
        pos["current_pnl_pct"] = round(pnl_pct, 4)
        pos["max_adverse"] = max(pos.get("max_adverse", 0.0), round(-pnl_pct, 4))
        positions[inst_id] = pos
        reason = None
        if current_price >= pos["stop_price"]:
            reason = f"止损触发 current={current_price:.6g} stop={pos['stop_price']:.6g}"
        elif now_ts >= int(pos["exit_ts"]):
            reason = f"到期平仓 current={current_price:.6g}"
        if reason:
            save_state("positions", positions)
            close_position(trade_api, inst_id, pos, reason, log, dry_run, resolved_pos_side(config))
    save_state("positions", positions)


def merge_watchlist(existing: list[dict], fresh: list[dict], handled: dict) -> list[dict]:
    by_key = {item["signal_key"]: item for item in existing if item["signal_key"] not in handled}
    for item in fresh:
        by_key[item["signal_key"]] = item
    return sorted(by_key.values(), key=lambda item: (-item["cum_gain"], item["confirm_ts"], item["inst_id"]))


def run_cycle(market, trade_api, config: dict, log: logging.Logger, dry_run: bool, *, force_scan: bool = False) -> None:
    now = datetime.now(CST)
    handled = prune_handled_signals(load_state("handled_signals"))
    save_state("handled_signals", handled)
    if now.minute == 0 or force_scan:
        log.info("=" * 50)
        log.info("整点扫描 %s", now.strftime("%Y-%m-%d %H:%M"))
        fresh = scan_signals(market, config, handled, log)
        watchlist = merge_watchlist(load_state("watchlist"), fresh, handled)
        save_state("watchlist", watchlist)
    else:
        watchlist = load_state("watchlist")
    cfg = strategy_config(config)
    expire_ms = cfg.entry_search_window_min * MINUTE_MS
    positions = load_state("positions")
    active_ids = {iid for iid, pos in positions.items() if pos.get("status") == "active"}
    next_watchlist = []
    now_ts = int(time.time() * 1000)
    for signal_info in watchlist:
        if signal_info["signal_key"] in handled:
            continue
        if now_ts > int(signal_info["confirm_ts"]) + expire_ms:
            handled[signal_info["signal_key"]] = {"confirm_ts": signal_info["confirm_ts"], "status": "expired"}
            continue
        if signal_info["inst_id"] in active_ids:
            next_watchlist.append(signal_info)
            continue
        entry_info = check_entry(market, signal_info, config, log)
        if entry_info is None:
            next_watchlist.append(signal_info)
            continue
        opened = open_position(trade_api, signal_info["inst_id"], entry_info, signal_info, config, log, dry_run)
        handled[signal_info["signal_key"]] = {"confirm_ts": signal_info["confirm_ts"], "status": "opened" if opened else "skipped"}
        if opened:
            active_ids.add(signal_info["inst_id"])
    save_state("handled_signals", handled)
    save_state("watchlist", next_watchlist)
    manage_positions(market, trade_api, config, log, dry_run)
    positions = load_state("positions")
    active = sum(1 for pos in positions.values() if pos.get("status") == "active")
    closed = sum(1 for pos in positions.values() if pos.get("status") == "closed")
    log.info("状态: watchlist=%s active=%s closed=%s used_margin=%.2fU", len(next_watchlist), active, closed, active_margin(positions))


def next_minute_seconds() -> float:
    now = datetime.now(CST)
    target = (now + timedelta(minutes=1)).replace(second=5, microsecond=0)
    return max(1.0, (target - now).total_seconds())


def main() -> None:
    config = load_config(CONFIG_PATH)
    setup_paths(config)
    log = setup_logger()
    dry_run = bool(config.get("dry_run", False))
    once = "--once" in sys.argv
    force_scan = "--force-scan" in sys.argv or once
    log.info("真实小资金实盘 bot 启动")
    log.info("配置文件: %s", CONFIG_PATH)
    log.info("模式: %s", "DRY-RUN" if dry_run else "LIVE")
    log.info(
        "硬风控: total_cap<=%.2fU per_trade=%.2fU leverage<=%.1fx max_pos=%s",
        HARD_MAX_TOTAL_CAP_USD,
        float(config["capital_per_trade_usd"]),
        float(config["leverage"]),
        int(config["max_positions"]),
    )
    if not validate_supported_strategy(config, log):
        log.error("策略模板校验失败，进程退出。")
        return
    market, trade_api = build_clients(config, dry_run)
    running = [True]

    def on_signal(signum, frame):
        log.info("收到退出信号，准备停止")
        running[0] = False

    sig.signal(sig.SIGINT, on_signal)
    sig.signal(sig.SIGTERM, on_signal)
    try:
        run_cycle(market, trade_api, config, log, dry_run, force_scan=force_scan)
    except Exception as exc:
        log.error("首次循环异常: %s", exc, exc_info=True)
        if once:
            raise
    if once:
        return
    while running[0]:
        wait = next_minute_seconds()
        log.info("等待 %.0fs 到下一个 1m 边界", wait)
        deadline = time.time() + wait
        while time.time() < deadline and running[0]:
            time.sleep(min(5, max(1, deadline - time.time())))
        if not running[0]:
            break
        try:
            run_cycle(market, trade_api, config, log, dry_run)
        except Exception as exc:
            log.error("循环异常: %s", exc, exc_info=True)
    log.info("Bot 已停止")


if __name__ == "__main__":
    main()
'''


live_bot_service = LiveBotService()
