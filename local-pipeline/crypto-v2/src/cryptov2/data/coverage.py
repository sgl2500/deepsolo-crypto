from __future__ import annotations

import csv
import gzip
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path


EXPECTED_ROWS_PER_DAY = {"1m": 1440, "5m": 288, "15m": 96, "1H": 24}


@dataclass(frozen=True, slots=True)
class DateCoverage:
    date: str
    bar: str
    expected_symbols: int
    present_symbols: int
    full_symbols: int
    partial_symbols: int
    missing_symbols: int
    rows_total: int
    min_rows: int
    max_rows: int
    missing_symbol_list: list[str]
    partial_symbol_list: list[str]

    @property
    def full_ratio(self) -> float:
        if self.expected_symbols <= 0:
            return 1.0
        return self.full_symbols / self.expected_symbols


def parse_date(value: str) -> date:
    if len(value) == 8 and value.isdigit():
        return datetime.strptime(value, "%Y%m%d").date()
    return datetime.strptime(value, "%Y-%m-%d").date()


def iter_dates(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _count_csv_gzip_rows(path: Path) -> int:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)
        return sum(1 for _ in reader)


def summarize_date_coverage(
    normalized_root: Path | str,
    *,
    bar: str,
    date_value: date | str,
    expected_symbols: list[str] | None = None,
) -> DateCoverage:
    if isinstance(date_value, str):
        date_value = parse_date(date_value)
    date_text = date_value.strftime("%Y-%m-%d")
    root = Path(normalized_root) / f"candles_{bar}" / f"date={date_text}"
    expected_rows = EXPECTED_ROWS_PER_DAY[bar]
    expected_set = set(expected_symbols or [])
    counts: dict[str, int] = {}

    if root.exists():
        for path in sorted(root.glob("*.csv.gz")):
            inst_id = path.name.removesuffix(".csv.gz")
            counts[inst_id] = _count_csv_gzip_rows(path)

    present_symbols = set(counts)
    if expected_set:
        scoped_counts = {sym: counts[sym] for sym in expected_set if sym in counts}
        expected_count = len(expected_set)
        missing = sorted(expected_set - present_symbols)
    else:
        scoped_counts = counts
        expected_count = len(scoped_counts)
        missing = []

    full = sorted(sym for sym, count in scoped_counts.items() if count == expected_rows)
    partial = sorted(sym for sym, count in scoped_counts.items() if 0 < count < expected_rows)
    row_counts = list(scoped_counts.values())
    return DateCoverage(
        date=date_text,
        bar=bar,
        expected_symbols=expected_count,
        present_symbols=len(scoped_counts),
        full_symbols=len(full),
        partial_symbols=len(partial),
        missing_symbols=len(missing),
        rows_total=sum(row_counts),
        min_rows=min(row_counts) if row_counts else 0,
        max_rows=max(row_counts) if row_counts else 0,
        missing_symbol_list=missing,
        partial_symbol_list=partial,
    )


def summarize_range_coverage(
    normalized_root: Path | str,
    *,
    bar: str,
    start: date,
    end: date,
    expected_symbols: list[str] | None = None,
) -> list[DateCoverage]:
    return [
        summarize_date_coverage(
            normalized_root,
            bar=bar,
            date_value=item,
            expected_symbols=expected_symbols,
        )
        for item in iter_dates(start, end)
    ]


def write_coverage_report(path: Path | str, reports: list[DateCoverage], extra: dict | None = None) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "summary": {
            "dates": len(reports),
            "incomplete_dates": sum(
                1 for item in reports if item.full_symbols < item.expected_symbols
            ),
        },
        "extra": extra or {},
        "details": [asdict(item) | {"full_ratio": item.full_ratio} for item in reports],
    }
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
