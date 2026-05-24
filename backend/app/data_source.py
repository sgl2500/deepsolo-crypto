from __future__ import annotations

import csv
import gzip
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .config import APP_TIMEZONE, DATA_ROOT, TIMEFRAMES

SUMMARY_DATE_LIMIT = 365


@dataclass(frozen=True)
class DatePartition:
    date: str
    file_count: int


class DataSourceService:
    def __init__(self, root: Path = DATA_ROOT) -> None:
        self.root = root
        self._summary_cache: dict[str, Any] | None = None
        self._summary_cached_at = 0.0

    def summary(self, force: bool = False) -> dict[str, Any]:
        now = time.time()
        if not force and self._summary_cache and now - self._summary_cached_at < 30:
            return self._summary_cache

        exists = self.root.exists()
        timeframes: list[dict[str, Any]] = []

        for key, dirname in TIMEFRAMES.items():
            tf_dir = self.root / dirname
            partitions = self._date_partitions(tf_dir) if tf_dir.exists() else []
            file_counts = [item.file_count for item in partitions]
            max_files = max(file_counts, default=0)
            latest = partitions[-1].date if partitions else None
            latest_files = partitions[-1].file_count if partitions else 0
            recommended = self._recommended_date(partitions)
            recommended_files = 0
            if recommended:
                recommended_files = next(
                    item.file_count for item in partitions if item.date == recommended
                )

            timeframes.append(
                {
                    "key": key,
                    "directory": dirname,
                    "date_count": len(partitions),
                    "latest_date": latest,
                    "latest_file_count": latest_files,
                    "max_file_count": max_files,
                    "recommended_date": recommended,
                    "recommended_file_count": recommended_files,
                    "dates": [
                        {"date": item.date, "file_count": item.file_count}
                        for item in partitions[-SUMMARY_DATE_LIMIT:]
                    ],
                }
            )

        self._summary_cache = {
            "root": str(self.root),
            "exists": exists,
            "scanned_at": int(now * 1000),
            "timeframes": timeframes,
        }
        self._summary_cached_at = now
        return self._summary_cache

    def contract_files(self, timeframe: str, date: str) -> list[Path]:
        tf_dir = self._timeframe_dir(timeframe)
        date_dir = tf_dir / f"date={date}"
        if not date_dir.exists():
            return []
        return sorted(date_dir.glob("*.csv.gz"))

    def preview(
        self, timeframe: str, date: str, inst_id: str | None = None, limit: int = 20
    ) -> dict[str, Any]:
        files = self.contract_files(timeframe, date)
        if inst_id:
            target = f"{inst_id}.csv.gz"
            files = [path for path in files if path.name == target]

        if not files:
            return {"file": None, "rows": []}

        path = files[0]
        rows: list[dict[str, str]] = []
        with gzip.open(path, "rt", newline="") as handle:
            reader = csv.DictReader(handle)
            for index, row in enumerate(reader):
                if index >= limit:
                    break
                rows.append(row)

        return {"file": str(path), "rows": rows}

    def kline_window(
        self,
        *,
        timeframe: str,
        date: str | None,
        inst_id: str,
        anchor_ts: int | None = None,
        before: int = 33,
        after: int = 33,
    ) -> dict[str, Any]:
        normalized_timeframe = self._normalize_timeframe(timeframe)
        before = max(1, min(before, 300))
        after = max(0, min(after, 300))
        dates = [item.date for item in self._date_partitions(self._timeframe_dir(normalized_timeframe))]
        if not date or date not in dates:
            date = self._resolve_anchor_date(
                normalized_timeframe,
                dates,
                inst_id,
                anchor_ts,
            )
        if not date:
            raise ValueError("没有找到基准日期分区")

        base_path = self._contract_path(normalized_timeframe, date, inst_id)
        if not base_path.exists():
            resolved_date = self._resolve_anchor_date(normalized_timeframe, dates, inst_id, anchor_ts)
            if resolved_date and resolved_date != date:
                date = resolved_date
                base_path = self._contract_path(normalized_timeframe, date, inst_id)
        if not base_path.exists():
            raise ValueError(f"基准日期没有找到合约 K 线：{inst_id}")

        if anchor_ts is None:
            anchor_row = self._row_at_time(base_path, None)
            anchor_ts = self._to_int(anchor_row.get("ts")) if anchor_row else None
        if anchor_ts is None:
            raise ValueError(f"无法定位 {inst_id} 在 {date} 的基准 K 线")

        base_index = dates.index(date)
        rows: list[dict[str, str]] = []
        # Read outward from the base date until the requested before/after window can be satisfied.
        left = base_index
        right = base_index
        while left >= 0 or right < len(dates):
            rows = self._read_contract_rows_for_dates(normalized_timeframe, dates[left : right + 1], inst_id)
            rows.sort(key=lambda item: self._to_int(item.get("ts")) or 0)
            anchor_index = self._nearest_row_index(rows, anchor_ts)
            if anchor_index is not None:
                has_before = anchor_index >= before or left == 0
                has_after = len(rows) - anchor_index - 1 >= after or right == len(dates) - 1
                if has_before and has_after:
                    break
            if left > 0:
                left -= 1
            if right < len(dates) - 1:
                right += 1
            if left == 0 and right == len(dates) - 1:
                break

        anchor_index = self._nearest_row_index(rows, anchor_ts)
        if anchor_index is None:
            raise ValueError(f"没有找到 {inst_id} 的基准 K 线")

        start = max(0, anchor_index - before)
        end = min(len(rows), anchor_index + after + 1)
        window_rows = [self._format_kline_row(row) for row in rows[start:end]]
        selected_anchor = rows[anchor_index]
        selected_anchor_ts = self._to_int(selected_anchor.get("ts")) or anchor_ts
        selected_anchor_index = anchor_index - start

        return {
            "timeframe": normalized_timeframe,
            "date": date,
            "inst_id": inst_id,
            "anchor_ts": selected_anchor_ts,
            "anchor_time": self._format_ts(str(selected_anchor_ts)),
            "anchor_index": selected_anchor_index,
            "before": before,
            "after": after,
            "before_count": selected_anchor_index,
            "after_count": max(0, len(window_rows) - selected_anchor_index - 1),
            "returned_count": len(window_rows),
            "rows": window_rows,
        }

    def active_contracts(
        self,
        timeframe: str = "1m",
        date: str | None = None,
        query: str | None = None,
        limit: int = 2000,
    ) -> dict[str, Any]:
        selected_date = date or self.default_date(timeframe)
        if not selected_date:
            return {
                "timeframe": timeframe,
                "date": None,
                "total_count": 0,
                "returned_count": 0,
                "rows": [],
            }

        files = self.contract_files(timeframe, selected_date)
        needle = query.strip().lower() if query else ""
        rows: list[dict[str, Any]] = []

        for path in files:
            inst_id = path.name.removesuffix(".csv.gz")
            if needle and needle not in inst_id.lower():
                continue

            latest = self._row_at_time(path, None)
            rows.append(
                {
                    "inst_id": inst_id,
                    "symbol": inst_id.replace("-USDT-SWAP", "").replace("-USDT", ""),
                    "latest_ts": latest.get("ts", "") if latest else "",
                    "latest_time": self._format_ts(latest.get("ts")) if latest else None,
                    "latest_close": latest.get("close", "") if latest else "",
                    "source_file": str(path),
                }
            )

        rows.sort(key=lambda item: item["inst_id"])
        limited = rows[: max(1, min(limit, 5000))]
        return {
            "timeframe": timeframe,
            "date": selected_date,
            "total_count": len(rows),
            "returned_count": len(limited),
            "rows": limited,
        }

    def indicator_preview(
        self,
        *,
        timeframe: str,
        date: str,
        field: str,
        time_text: str | None = None,
        query: str | None = None,
        limit: int = 200,
        has_value: bool = True,
    ) -> dict[str, Any]:
        files = self.contract_files(timeframe, date)
        target_ts = self._parse_local_time(date, time_text)
        needle = query.strip().lower() if query else ""
        rows: list[dict[str, Any]] = []

        for path in files:
            inst_id = path.name.removesuffix(".csv.gz")
            if needle and needle not in inst_id.lower():
                continue

            row = self._row_at_time(path, target_ts)
            if not row:
                continue

            value = row.get(field, "")
            if has_value and value == "":
                continue

            rows.append(
                {
                    "inst_id": inst_id,
                    "value": value,
                    "ts": row.get("ts"),
                    "time": self._format_ts(row.get("ts")),
                }
            )

            if len(rows) >= limit:
                break

        return {
            "date": date,
            "time": time_text or "",
            "field": field,
            "target_ts": target_ts,
            "total_files": len(files),
            "returned_count": len(rows),
            "rows": rows,
        }

    def default_date(self, timeframe: str) -> str | None:
        tf = next(
            (
                item
                for item in self.summary()["timeframes"]
                if item["key"].lower() == timeframe.lower()
            ),
            None,
        )
        return tf["recommended_date"] if tf else None

    def _timeframe_dir(self, timeframe: str) -> Path:
        key = self._normalize_timeframe(timeframe)
        return self.root / TIMEFRAMES[key]

    def _normalize_timeframe(self, timeframe: str) -> str:
        for key in TIMEFRAMES:
            if key.lower() == timeframe.lower():
                return key
        supported = ", ".join(TIMEFRAMES)
        raise ValueError(f"Unsupported timeframe '{timeframe}'. Use one of: {supported}.")

    def _date_partitions(self, tf_dir: Path) -> list[DatePartition]:
        partitions: list[DatePartition] = []
        for entry in tf_dir.iterdir():
            if not entry.is_dir() or not entry.name.startswith("date="):
                continue
            date = entry.name.split("date=", 1)[1]
            file_count = sum(1 for _ in entry.glob("*.csv.gz"))
            partitions.append(DatePartition(date=date, file_count=file_count))
        return sorted(partitions, key=lambda item: item.date)

    def _recommended_date(self, partitions: list[DatePartition]) -> str | None:
        if not partitions:
            return None
        max_files = max(item.file_count for item in partitions)
        for item in reversed(partitions):
            if item.file_count >= max_files:
                return item.date
        return partitions[-1].date

    def _row_at_time(self, path: Path, target_ts: int | None) -> dict[str, str] | None:
        selected: dict[str, str] | None = None
        with gzip.open(path, "rt", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if target_ts is None:
                    selected = row
                    continue

                ts = self._to_int(row.get("ts"))
                if ts is None:
                    continue
                if ts <= target_ts:
                    selected = row
                    continue
                break
        return selected

    def _contract_path(self, timeframe: str, date: str, inst_id: str) -> Path:
        return self._timeframe_dir(timeframe) / f"date={date}" / f"{inst_id}.csv.gz"

    def _resolve_anchor_date(
        self,
        timeframe: str,
        dates: list[str],
        inst_id: str,
        anchor_ts: int | None,
    ) -> str | None:
        if anchor_ts is None:
            return dates[-1] if dates else None

        date_set = set(dates)
        for candidate in self._anchor_date_candidates(timeframe, anchor_ts):
            if candidate in date_set and self._contract_path(timeframe, candidate, inst_id).exists():
                return candidate
        return None

    def _anchor_date_candidates(self, timeframe: str, anchor_ts: int) -> list[str]:
        local_dt = datetime.fromtimestamp(anchor_ts / 1000, tz=ZoneInfo(APP_TIMEZONE))
        utc_dt = datetime.fromtimestamp(anchor_ts / 1000, tz=timezone.utc)
        seeds = [local_dt.date()]
        if timeframe != "1D":
            # Intraday folders follow UTC date partitions, which are CST 08:00~next 07:59.
            seeds.insert(0, utc_dt.date())

        candidates: list[str] = []
        for seed in seeds:
            for offset in (0, -1, 1, -2, 2):
                item = (seed + timedelta(days=offset)).isoformat()
                if item not in candidates:
                    candidates.append(item)
        return candidates

    def _read_contract_rows_for_dates(
        self,
        timeframe: str,
        dates: list[str],
        inst_id: str,
    ) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for item_date in dates:
            path = self._contract_path(timeframe, item_date, inst_id)
            if not path.exists():
                continue
            with gzip.open(path, "rt", newline="") as handle:
                reader = csv.DictReader(handle)
                rows.extend(dict(row) for row in reader)
        return rows

    def _nearest_row_index(self, rows: list[dict[str, str]], anchor_ts: int) -> int | None:
        if not rows:
            return None
        best_index: int | None = None
        best_distance: int | None = None
        for index, row in enumerate(rows):
            ts = self._to_int(row.get("ts"))
            if ts is None:
                continue
            distance = abs(ts - anchor_ts)
            if best_distance is None or distance < best_distance:
                best_index = index
                best_distance = distance
        return best_index

    def _format_kline_row(self, row: dict[str, str]) -> dict[str, Any]:
        ts = self._to_int(row.get("ts"))
        return {
            "ts": ts,
            "time": self._format_ts(row.get("ts")),
            "open": self._to_float(row.get("open")),
            "high": self._to_float(row.get("high")),
            "low": self._to_float(row.get("low")),
            "close": self._to_float(row.get("close")),
            "vol": self._to_float(row.get("vol")),
            "vol_ccy": self._to_float(row.get("vol_ccy")),
            "vol_ccy_quote": self._to_float(row.get("vol_ccy_quote")),
        }

    def _parse_local_time(self, date: str, time_text: str | None) -> int | None:
        if not time_text:
            return None
        normalized = time_text.strip()
        if not normalized:
            return None
        if len(normalized) == 5:
            normalized = f"{normalized}:00"
        dt = datetime.fromisoformat(f"{date}T{normalized}")
        dt = dt.replace(tzinfo=ZoneInfo(APP_TIMEZONE))
        return int(dt.timestamp() * 1000)

    def _format_ts(self, value: str | None) -> str | None:
        ts = self._to_int(value)
        if ts is None:
            return None
        dt = datetime.fromtimestamp(ts / 1000, tz=ZoneInfo(APP_TIMEZONE))
        return dt.strftime("%Y-%m-%d %H:%M")

    def _to_int(self, value: str | None) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(float(value))
        except ValueError:
            return None

    def _to_float(self, value: str | None) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except ValueError:
            return None


data_source_service = DataSourceService()
