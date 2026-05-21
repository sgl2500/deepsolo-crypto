from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import DATA_ROOT

ROOT_DIR = Path(__file__).resolve().parents[2]
RUNTIME_DIR = ROOT_DIR / ".runtime" / "contract_update"
STATUS_PATH = RUNTIME_DIR / "status.json"
LOG_PATH = RUNTIME_DIR / "latest.log"

DEFAULT_STRATEGY_ROOT = Path(
    os.getenv(
        "STRATEGY_RESEARCH_ROOT",
        "/Users/sunguanlong/Desktop/crypto/strategy-research",
    )
)
DEFAULT_CRYPTO_V2_ROOT = Path(
    os.getenv(
        "CRYPTO_V2_ROOT",
        str(DATA_ROOT.parents[1] if len(DATA_ROOT.parents) > 1 else DATA_ROOT),
    )
)

CST = timezone(timedelta(hours=8))
MAX_TAIL_CHARS = 20000


class ContractUpdateService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._state: dict[str, Any] = self._initial_state()
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        self._load_previous_state()

    def start(
        self,
        *,
        force: bool = True,
        backfill_history: bool = False,
        pages: int | None = None,
        limit: int = 300,
        build_daily: bool = True,
        daily_days: int = 10,
        symbol_limit: int | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            self._mark_dead_worker_locked()
            if self._state.get("running"):
                raise ValueError("更新部署任务正在运行，请等待完成。")

            RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
            LOG_PATH.write_text("", encoding="utf-8")
            started_at = _now_ms()
            self._state = {
                **self._initial_state(),
                "running": True,
                "stage": "queued",
                "stage_label": "等待启动",
                "started_at": started_at,
                "updated_at": started_at,
                "finished_at": None,
                "success": None,
                "error": "",
                "return_code": None,
                "log_file": str(LOG_PATH),
                "strategy_root": str(DEFAULT_STRATEGY_ROOT),
                "crypto_v2_root": str(DEFAULT_CRYPTO_V2_ROOT),
                "data_root": str(DATA_ROOT),
                "options": {
                    "force": force,
                    "backfill_history": backfill_history,
                    "pages": pages,
                    "limit": limit,
                    "build_daily": build_daily,
                    "daily_days": daily_days,
                    "symbol_limit": symbol_limit,
                },
            }
            self._write_state_locked()

            self._thread = threading.Thread(
                target=self._run,
                kwargs={
                    "force": force,
                    "backfill_history": backfill_history,
                    "pages": pages,
                    "limit": limit,
                    "build_daily": build_daily,
                    "daily_days": daily_days,
                    "symbol_limit": symbol_limit,
                },
                daemon=True,
            )
            self._thread.start()
        return self.status()

    def status(self, tail_chars: int = 12000) -> dict[str, Any]:
        with self._lock:
            self._mark_dead_worker_locked()
            state = dict(self._state)
        state["log_tail"] = _read_tail(LOG_PATH, max(0, min(tail_chars, MAX_TAIL_CHARS)))
        return state

    def _run(
        self,
        *,
        force: bool,
        backfill_history: bool,
        pages: int | None,
        limit: int,
        build_daily: bool,
        daily_days: int,
        symbol_limit: int | None,
    ) -> None:
        try:
            self._append_log("开始更新部署：同步合约维表、刷新最新K线、重建聚合数据。")
            self._set_state(stage="validating", stage_label="检查脚本与数据目录")
            self._validate_paths()

            update_cmd = self._data_update_command(
                force=force,
                backfill_history=backfill_history,
                pages=pages,
                limit=limit,
                symbol_limit=symbol_limit,
            )
            self._run_command("update_data", "更新合约与K线数据", update_cmd, DEFAULT_STRATEGY_ROOT / "versions-crypto")

            if build_daily:
                daily_cmd = self._daily_command(daily_days=daily_days, symbol_limit=symbol_limit)
                self._run_command("build_daily", "生成最近日线数据", daily_cmd, DEFAULT_CRYPTO_V2_ROOT)

            self._set_state(
                running=False,
                stage="completed",
                stage_label="更新完成",
                success=True,
                return_code=0,
                finished_at=_now_ms(),
            )
            self._append_log("更新部署完成。")
        except Exception as exc:
            self._append_log(f"更新部署失败：{exc}")
            for line in traceback.format_exc().rstrip().splitlines():
                self._append_log(line)
            self._set_state(
                running=False,
                stage="failed",
                stage_label="更新失败",
                success=False,
                error=str(exc),
                return_code=self._state.get("return_code"),
                finished_at=_now_ms(),
            )

    def _validate_paths(self) -> None:
        update_script = DEFAULT_STRATEGY_ROOT / "versions-crypto" / "增量下载数据.py"
        daily_script = DEFAULT_CRYPTO_V2_ROOT / "scripts" / "build_daily_bars.py"
        if not update_script.exists():
            raise FileNotFoundError(f"缺少数据更新脚本：{update_script}")
        if not daily_script.exists():
            raise FileNotFoundError(f"缺少日线生成脚本：{daily_script}")
        if not DATA_ROOT.exists():
            raise FileNotFoundError(f"数据目录不存在：{DATA_ROOT}")

    def _data_update_command(
        self,
        *,
        force: bool,
        backfill_history: bool,
        pages: int | None,
        limit: int,
        symbol_limit: int | None,
    ) -> list[str]:
        cmd = [
            _python_bin(),
            str(DEFAULT_STRATEGY_ROOT / "versions-crypto" / "增量下载数据.py"),
            "--limit",
            str(max(1, min(limit, 300))),
            "--coverage-days",
            "3",
        ]
        if force:
            cmd.append("--force")
        if backfill_history:
            cmd.append("--backfill-history")
        elif pages is None:
            # The deploy button is expected to refresh the newest candles first.
            # Coverage gaps can be repaired separately via explicit history backfill.
            cmd.append("--no-auto-backfill-gaps")
        if pages is not None:
            cmd += ["--pages", str(max(1, min(pages, 200)))]
        if symbol_limit is not None:
            cmd += ["--symbol-limit", str(max(1, symbol_limit))]
        return cmd

    def _daily_command(self, *, daily_days: int, symbol_limit: int | None) -> list[str]:
        today = datetime.now(CST).date()
        start = today - timedelta(days=max(1, min(daily_days, 365)) - 1)
        cmd = [
            _python_bin(),
            str(DEFAULT_CRYPTO_V2_ROOT / "scripts" / "build_daily_bars.py"),
            "--normalized-root",
            str(DATA_ROOT),
            "--start",
            start.strftime("%Y%m%d"),
            "--end",
            today.strftime("%Y%m%d"),
        ]
        if symbol_limit is not None:
            cmd += ["--symbol-limit", str(max(1, symbol_limit))]
        return cmd

    def _run_command(self, stage: str, label: str, cmd: list[str], cwd: Path) -> None:
        self._set_state(
            stage=stage,
            stage_label=label,
            current_command=" ".join(cmd),
            updated_at=_now_ms(),
        )
        self._append_log("")
        self._append_log(f"==== {label} ====")
        self._append_log("+ " + " ".join(cmd))

        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")
        process = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            self._append_log(line.rstrip("\n"))
        return_code = process.wait()
        self._set_state(return_code=return_code, updated_at=_now_ms())
        if return_code != 0:
            raise RuntimeError(f"{label} 失败，退出码 {return_code}")

    def _append_log(self, line: str) -> None:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(f"[{timestamp}] {line}\n")
        self._set_state(updated_at=_now_ms(), write=False)

    def _set_state(self, write: bool = True, **updates: Any) -> None:
        with self._lock:
            self._state.update(updates)
            if write:
                self._write_state_locked()

    def _write_state_locked(self) -> None:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        STATUS_PATH.write_text(json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _mark_dead_worker_locked(self) -> None:
        if not self._state.get("running"):
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._state.update(
            {
                "running": False,
                "stage": "interrupted",
                "stage_label": "任务已中断，请重新执行",
                "success": False,
                "error": "更新部署任务没有可运行的后台线程，可能是服务重启或上次启动被中断。",
                "finished_at": _now_ms(),
                "updated_at": _now_ms(),
            }
        )
        self._write_state_locked()

    def _load_previous_state(self) -> None:
        if not STATUS_PATH.exists():
            return
        try:
            data = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(data, dict):
            was_running = bool(data.get("running"))
            data["running"] = False
            if data.get("stage") not in ("completed", "failed"):
                data["stage"] = "interrupted"
                data["stage_label"] = "服务重启，任务状态未知"
                data["success"] = False
                data["error"] = data.get("error") or "服务重启或上次任务被中断，请重新执行更新部署。"
                data["finished_at"] = data.get("finished_at") or _now_ms()
                data["updated_at"] = _now_ms()
            self._state = {**self._initial_state(), **data}
            if was_running:
                self._write_state_locked()

    def _initial_state(self) -> dict[str, Any]:
        return {
            "running": False,
            "stage": "idle",
            "stage_label": "未运行",
            "started_at": None,
            "updated_at": None,
            "finished_at": None,
            "success": None,
            "error": "",
            "return_code": None,
            "current_command": "",
            "log_file": str(LOG_PATH),
            "strategy_root": str(DEFAULT_STRATEGY_ROOT),
            "crypto_v2_root": str(DEFAULT_CRYPTO_V2_ROOT),
            "data_root": str(DATA_ROOT),
            "options": {},
        }


def _python_bin() -> str:
    explicit = os.getenv("PYTHON_BIN", "").strip()
    if explicit:
        return explicit
    homebrew = Path("/opt/homebrew/bin/python3")
    if homebrew.exists():
        return str(homebrew)
    return sys.executable or "python3"


def _read_tail(path: Path, max_chars: int) -> str:
    if max_chars <= 0 or not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _now_ms() -> int:
    return int(time.time() * 1000)


contract_update_service = ContractUpdateService()
