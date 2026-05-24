from __future__ import annotations

import csv
import gzip
import json
import time
from dataclasses import dataclass
from datetime import datetime, time as datetime_time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .config import APP_TIMEZONE, DATA_ROOT, TIMEFRAMES


PERIOD_STEP_MS = {
    "1m": 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "1H": 60 * 60_000,
    "1D": 24 * 60 * 60_000,
}


@dataclass(frozen=True)
class QualityDatePartition:
    date: str
    files: set[str]

    @property
    def file_count(self) -> int:
        return len(self.files)


class DataQualityService:
    def __init__(self, root: Path = DATA_ROOT) -> None:
        self.root = root
        self.catalog_dir = root.parent / "catalog"
        self._catalog_cache: tuple[float, list[dict[str, Any]]] | None = None
        self._summary_cache: dict[str, Any] = {}
        self._date_cache: dict[str, dict[str, Any]] = {}

    def summary(self, timeframe: str = "1m", force: bool = False) -> dict[str, Any]:
        normalized_timeframe = self._normalize_timeframe(timeframe)
        cache_key = normalized_timeframe
        now = time.time()
        cached = self._summary_cache.get(cache_key)
        if not force and cached and now - float(cached.get("_cached_at", 0)) < 30:
            return {key: value for key, value in cached.items() if key != "_cached_at"}

        instruments = self._online_instruments()
        online_symbols = {str(item.get("inst_id")) for item in instruments if item.get("inst_id")}
        selected_partitions = self._date_partitions(normalized_timeframe)
        selected_latest = self._health_partition(normalized_timeframe, selected_partitions, instruments)
        latest_expected = (
            self._expected_symbols_for_date(normalized_timeframe, selected_latest.date, instruments)
            if selected_latest
            else set()
        )
        latest_missing = sorted(latest_expected - (selected_latest.files if selected_latest else set()))
        latest_extra = sorted((selected_latest.files if selected_latest else set()) - latest_expected)

        timeframes: list[dict[str, Any]] = []
        for period in TIMEFRAMES:
            partitions = self._date_partitions(period)
            latest = self._health_partition(period, partitions, instruments)
            expected = self._expected_symbols_for_date(period, latest.date, instruments) if latest else set()
            missing_count = max(0, len(expected - (latest.files if latest else set())))
            extra_count = max(0, len((latest.files if latest else set()) - expected))
            raw_latest = partitions[-1] if partitions else None
            timeframes.append(
                {
                    "timeframe": period,
                    "latest_date": latest.date if latest else None,
                    "latest_file_count": latest.file_count if latest else 0,
                    "raw_latest_date": raw_latest.date if raw_latest else None,
                    "raw_latest_file_count": raw_latest.file_count if raw_latest else 0,
                    "max_file_count": max((item.file_count for item in partitions), default=0),
                    "date_count": len(partitions),
                    "expected_latest_count": len(expected),
                    "missing_latest_count": missing_count,
                    "extra_latest_count": extra_count,
                    "status": self._status_for_counts(missing_count, extra_count, len(expected)),
                }
            )

        report = self._best_quality_report()
        report_summary = report.get("summary", {}) if report else {}
        report_details = report.get("details", []) if report else []
        top_contract_issues = self._top_contract_issues(report_details)
        report_symbols = int(report_summary.get("symbols") or 0) if isinstance(report_summary, dict) else 0

        issues: list[str] = []
        if selected_latest is None:
            issues.append(f"{normalized_timeframe} 没有数据分区")
        elif latest_missing:
            issues.append(f"{normalized_timeframe} 最新分区缺少 {len(latest_missing)} 个应有合约文件")
        if latest_extra:
            issues.append(f"{normalized_timeframe} 最新分区存在 {len(latest_extra)} 个非预期合约文件")
        if report_symbols and report_symbols < len(online_symbols):
            issues.append(f"现有缺口明细报告只覆盖 {report_symbols} 个合约，单合约报告会实时扫描")
        if top_contract_issues:
            issues.append(f"已有质量报告发现 {len(top_contract_issues)} 个合约异常")

        status = "ok"
        if latest_missing or latest_extra:
            status = self._status_for_counts(len(latest_missing), len(latest_extra), len(latest_expected))
        if top_contract_issues and status == "ok":
            status = "warning"

        result = {
            "root": str(self.root),
            "catalog_updated_at": self._catalog_updated_at(),
            "generated_at": int(now * 1000),
            "timeframe": normalized_timeframe,
            "status": status,
            "status_label": self._status_label(status),
            "online_symbols": len(online_symbols),
            "latest_date": selected_latest.date if selected_latest else None,
            "latest_file_count": selected_latest.file_count if selected_latest else 0,
            "raw_latest_date": selected_partitions[-1].date if selected_partitions else None,
            "raw_latest_file_count": selected_partitions[-1].file_count if selected_partitions else 0,
            "expected_latest_count": len(latest_expected),
            "missing_latest_count": len(latest_missing),
            "extra_latest_count": len(latest_extra),
            "missing_latest_symbols": latest_missing[:30],
            "extra_latest_symbols": latest_extra[:30],
            "quality_report": {
                "source": report.get("_source") if report else "",
                "symbols": report_symbols,
                "rows_total": int(report_summary.get("rows_total") or 0) if isinstance(report_summary, dict) else 0,
                "symbols_with_gaps": int(report_summary.get("symbols_with_gaps") or 0) if isinstance(report_summary, dict) else 0,
                "symbols_with_duplicates": int(report_summary.get("symbols_with_duplicates") or 0) if isinstance(report_summary, dict) else 0,
                "symbols_with_unconfirmed": int(report_summary.get("symbols_with_unconfirmed") or 0) if isinstance(report_summary, dict) else 0,
            },
            "timeframes": timeframes,
            "top_contract_issues": top_contract_issues,
            "issues": issues,
        }
        self._summary_cache[cache_key] = {**result, "_cached_at": now}
        return result

    def date_report(self, timeframe: str = "1m", limit: int = 90, force: bool = False) -> dict[str, Any]:
        normalized_timeframe = self._normalize_timeframe(timeframe)
        cache_key = f"{normalized_timeframe}:{limit}"
        now = time.time()
        cached = self._date_cache.get(cache_key)
        if not force and cached and now - float(cached.get("_cached_at", 0)) < 30:
            return {key: value for key, value in cached.items() if key != "_cached_at"}

        instruments = self._online_instruments()
        partitions = self._date_partitions(normalized_timeframe)
        rows: list[dict[str, Any]] = []
        for partition in reversed(partitions[-max(1, min(limit, 365)) :]):
            expected = self._expected_symbols_for_date(normalized_timeframe, partition.date, instruments)
            missing = sorted(expected - partition.files)
            extra = sorted(partition.files - expected)
            status = self._status_for_counts(len(missing), len(extra), len(expected))
            rows.append(
                {
                    "date": partition.date,
                    "timeframe": normalized_timeframe,
                    "expected_count": len(expected),
                    "actual_count": partition.file_count,
                    "missing_count": len(missing),
                    "extra_count": len(extra),
                    "missing_symbols": missing[:30],
                    "extra_symbols": extra[:30],
                    "status": status,
                    "status_label": self._status_label(status),
                }
            )

        result = {
            "timeframe": normalized_timeframe,
            "generated_at": int(now * 1000),
            "total_dates": len(partitions),
            "returned_count": len(rows),
            "rows": rows,
        }
        self._date_cache[cache_key] = {**result, "_cached_at": now}
        return result

    def contract_report(self, inst_id: str, gap_limit: int = 30) -> dict[str, Any]:
        normalized_inst_id = inst_id.strip().upper()
        instruments = self._online_instruments(include_offline=True)
        instrument = next((item for item in instruments if item.get("inst_id") == normalized_inst_id), None)
        if not normalized_inst_id:
            raise ValueError("合约不能为空")

        timeframes = [
            self._scan_contract_timeframe(
                normalized_inst_id,
                period,
                instrument,
                gap_limit=max(1, min(gap_limit, 100)),
            )
            for period in TIMEFRAMES
        ]
        issue_count = sum(1 for item in timeframes if item["status"] != "ok")
        latest_time = max((item.get("end_time") or "" for item in timeframes), default="")

        return {
            "inst_id": normalized_inst_id,
            "symbol": normalized_inst_id.replace("-USDT-SWAP", "").replace("-USDT", ""),
            "generated_at": int(time.time() * 1000),
            "status": "ok" if issue_count == 0 else "warning",
            "status_label": "正常" if issue_count == 0 else "存在异常",
            "latest_time": latest_time or None,
            "instrument": self._format_instrument(instrument),
            "timeframes": timeframes,
        }

    def _scan_contract_timeframe(
        self,
        inst_id: str,
        timeframe: str,
        instrument: dict[str, Any] | None,
        *,
        gap_limit: int,
    ) -> dict[str, Any]:
        partitions = self._date_partitions(timeframe)
        step = PERIOD_STEP_MS[timeframe]
        expected_dates = [
            partition.date
            for partition in partitions
            if self._is_expected_on_date(instrument, timeframe, partition.date)
        ]
        present_dates: list[str] = []
        timestamps: list[int] = []
        seen: set[int] = set()
        duplicate_rows = 0
        unconfirmed_rows = 0
        bad_rows = 0

        for partition in partitions:
            path = self._timeframe_dir(timeframe) / f"date={partition.date}" / f"{inst_id}.csv.gz"
            if not path.exists():
                continue
            present_dates.append(partition.date)
            with gzip.open(path, "rt", newline="") as handle:
                for row in csv.DictReader(handle):
                    ts = self._to_int(row.get("ts"))
                    if ts is None:
                        bad_rows += 1
                        continue
                    if ts in seen:
                        duplicate_rows += 1
                    else:
                        seen.add(ts)
                        timestamps.append(ts)
                    if str(row.get("confirm", "1")) == "0":
                        unconfirmed_rows += 1

        timestamps.sort()
        gaps: list[dict[str, Any]] = []
        missing_bars = 0
        previous: int | None = None
        for ts in timestamps:
            if previous is not None and ts - previous > step:
                missing_count = max(1, int((ts - previous) // step) - 1)
                missing_bars += missing_count
                if len(gaps) < gap_limit:
                    gaps.append(
                        {
                            "prev_ts": previous,
                            "prev_time": self._format_ts(previous),
                            "next_ts": ts,
                            "next_time": self._format_ts(ts),
                            "missing_count": missing_count,
                            "missing_start": self._format_ts(previous + step),
                            "missing_end": self._format_ts(ts - step),
                        }
                    )
            previous = ts

        missing_dates = sorted(set(expected_dates) - set(present_dates))
        unique_rows = len(timestamps)
        denominator = unique_rows + missing_bars
        coverage = (unique_rows / denominator * 100) if denominator else 0.0
        status = "ok"
        if missing_dates or missing_bars:
            status = "fail"
        elif duplicate_rows or unconfirmed_rows or bad_rows:
            status = "warning"

        return {
            "timeframe": timeframe,
            "status": status,
            "status_label": self._status_label(status),
            "row_count": unique_rows + duplicate_rows,
            "unique_row_count": unique_rows,
            "file_count": len(present_dates),
            "expected_file_count": len(expected_dates),
            "missing_file_count": len(missing_dates),
            "missing_dates": missing_dates[:60],
            "start_ts": timestamps[0] if timestamps else None,
            "start_time": self._format_ts(timestamps[0]) if timestamps else None,
            "end_ts": timestamps[-1] if timestamps else None,
            "end_time": self._format_ts(timestamps[-1]) if timestamps else None,
            "gap_events": len(gaps),
            "missing_bars": missing_bars,
            "gap_samples": gaps,
            "duplicate_rows": duplicate_rows,
            "unconfirmed_rows": unconfirmed_rows,
            "bad_rows": bad_rows,
            "coverage_pct": round(coverage, 4),
        }

    def _top_contract_issues(self, details: Any) -> list[dict[str, Any]]:
        if not isinstance(details, list):
            return []
        issues = []
        for item in details:
            if not isinstance(item, dict):
                continue
            gaps = int(item.get("gaps") or 0)
            duplicates = int(item.get("duplicates") or 0)
            unconfirmed = int(item.get("unconfirmed") or 0)
            score = gaps + duplicates + unconfirmed
            if score <= 0:
                continue
            issues.append(
                {
                    "inst_id": item.get("inst_id", ""),
                    "timeframe": item.get("bar", "1m"),
                    "rows": int(item.get("rows") or 0),
                    "start": item.get("start"),
                    "end": item.get("end"),
                    "gaps": gaps,
                    "duplicates": duplicates,
                    "unconfirmed": unconfirmed,
                    "_score": score,
                }
            )
        issues.sort(key=lambda item: item["_score"], reverse=True)
        return [{key: value for key, value in item.items() if key != "_score"} for item in issues[:20]]

    def _best_quality_report(self) -> dict[str, Any] | None:
        for name in ("okx_1m_update_quality.json", "okx_1m_quality.json"):
            payload = self._read_json(self.catalog_dir / name)
            if isinstance(payload, dict):
                payload["_source"] = name
                return payload
        return None

    def _online_instruments(self, *, include_offline: bool = False) -> list[dict[str, Any]]:
        cached = self._catalog_cache
        catalog_path = self.catalog_dir / "instruments_okx_usdt_swap_dim.json"
        modified_at = catalog_path.stat().st_mtime if catalog_path.exists() else 0.0
        if cached and cached[0] == modified_at:
            rows = cached[1]
        else:
            payload = self._read_json(catalog_path)
            rows = payload.get("symbols", []) if isinstance(payload, dict) else []
            if not isinstance(rows, list):
                rows = []
            self._catalog_cache = (modified_at, rows)

        filtered = []
        for item in rows:
            if not isinstance(item, dict):
                continue
            if str(item.get("settle_ccy", "USDT")).upper() != "USDT":
                continue
            if include_offline or self._is_online(item):
                filtered.append(item)
        return filtered

    def _expected_symbols_for_date(self, timeframe: str, date: str, instruments: list[dict[str, Any]]) -> set[str]:
        return {
            str(item.get("inst_id"))
            for item in instruments
            if item.get("inst_id") and self._is_expected_on_date(item, timeframe, date)
        }

    def _is_expected_on_date(self, instrument: dict[str, Any] | None, timeframe: str, date: str) -> bool:
        if instrument is None:
            return True
        if not self._is_online(instrument):
            return False
        list_time = self._to_int(instrument.get("list_time") or instrument.get("raw", {}).get("listTime"))
        exp_time = self._to_int(instrument.get("exp_time") or instrument.get("raw", {}).get("expTime"))
        start_ts, end_ts = self._partition_bounds(timeframe, date)
        if timeframe == "1D":
            # Daily files are produced only for full CST days with all 24 hours.
            if list_time is not None and list_time > start_ts:
                return False
            if exp_time is not None and exp_time < end_ts:
                return False
        else:
            # Intraday date=YYYY-MM-DD folders use UTC-day boundaries: CST 08:00 to next-day 07:59.
            if list_time is not None and list_time > end_ts:
                return False
            if exp_time is not None and exp_time < start_ts:
                return False
        return True

    def _is_online(self, item: dict[str, Any]) -> bool:
        return bool(item.get("is_online")) or str(item.get("state", "")).lower() == "live"

    def _date_partitions(self, timeframe: str) -> list[QualityDatePartition]:
        tf_dir = self._timeframe_dir(timeframe)
        if not tf_dir.exists():
            return []
        partitions: list[QualityDatePartition] = []
        for entry in tf_dir.iterdir():
            if not entry.is_dir() or not entry.name.startswith("date="):
                continue
            date = entry.name.split("date=", 1)[1]
            files = {path.name.removesuffix(".csv.gz") for path in entry.glob("*.csv.gz")}
            partitions.append(QualityDatePartition(date=date, files=files))
        return sorted(partitions, key=lambda item: item.date)

    def _health_partition(
        self,
        timeframe: str,
        partitions: list[QualityDatePartition],
        instruments: list[dict[str, Any]],
    ) -> QualityDatePartition | None:
        if not partitions:
            return None
        for partition in reversed(partitions):
            expected = self._expected_symbols_for_date(timeframe, partition.date, instruments)
            if not expected:
                continue
            if partition.files == expected:
                return partition
        return partitions[-1]

    def _timeframe_dir(self, timeframe: str) -> Path:
        return self.root / TIMEFRAMES[self._normalize_timeframe(timeframe)]

    def _normalize_timeframe(self, timeframe: str) -> str:
        for key in TIMEFRAMES:
            if key.lower() == timeframe.strip().lower():
                return key
        supported = ", ".join(TIMEFRAMES)
        raise ValueError(f"不支持的数据周期：{timeframe}，可选：{supported}")

    def _format_instrument(self, instrument: dict[str, Any] | None) -> dict[str, Any]:
        if not instrument:
            return {
                "state": "unknown",
                "is_online": False,
                "list_time": None,
                "list_time_text": None,
                "first_seen_at": None,
                "last_seen_at": None,
            }
        list_time = self._to_int(instrument.get("list_time") or instrument.get("raw", {}).get("listTime"))
        return {
            "state": instrument.get("state", "unknown"),
            "is_online": self._is_online(instrument),
            "list_time": list_time,
            "list_time_text": self._format_ts(list_time) if list_time is not None else None,
            "first_seen_at": instrument.get("first_seen_at"),
            "last_seen_at": instrument.get("last_seen_at"),
        }

    def _catalog_updated_at(self) -> str | None:
        payload = self._read_json(self.catalog_dir / "instruments_okx_usdt_swap_dim.json")
        if isinstance(payload, dict):
            meta = payload.get("meta")
            if isinstance(meta, dict):
                return meta.get("updated_at")
        return None

    def _status_for_counts(self, missing: int, extra: int, expected: int) -> str:
        if missing <= 0 and extra <= 0:
            return "ok"
        if expected and missing / expected >= 0.02:
            return "fail"
        if missing >= 3:
            return "fail"
        return "warning"

    def _status_label(self, status: str) -> str:
        return {"ok": "正常", "warning": "轻微异常", "fail": "严重异常"}.get(status, status)

    def _partition_bounds(self, timeframe: str, date: str) -> tuple[int, int]:
        local_date = datetime.fromisoformat(date).date()
        if timeframe == "1D":
            start = datetime.combine(local_date, datetime_time.min).replace(tzinfo=ZoneInfo(APP_TIMEZONE))
        else:
            start = datetime.combine(local_date, datetime_time(8, 0)).replace(tzinfo=ZoneInfo(APP_TIMEZONE))
        start_ts = int(start.timestamp() * 1000)
        return start_ts, start_ts + 24 * 60 * 60_000 - 1

    def _format_ts(self, value: int | str | None) -> str | None:
        ts = self._to_int(value)
        if ts is None:
            return None
        return datetime.fromtimestamp(ts / 1000, tz=ZoneInfo(APP_TIMEZONE)).strftime("%Y-%m-%d %H:%M")

    def _to_int(self, value: Any) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    def _read_json(self, path: Path) -> Any:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None


data_quality_service = DataQualityService()
