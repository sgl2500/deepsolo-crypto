from __future__ import annotations

import csv
import gzip
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .config import APP_TIMEZONE, DATA_ROOT, TIMEFRAMES


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
                        for item in partitions[-45:]
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
        threshold = max(1, int(max_files * 0.8))
        for item in reversed(partitions):
            if item.file_count >= threshold:
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


data_source_service = DataSourceService()
