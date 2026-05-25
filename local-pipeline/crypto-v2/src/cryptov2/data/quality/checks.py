from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cryptov2.data.providers.csv_provider import CsvKlineProvider
from cryptov2.data.schemas import Bar, BarSize, fmt_ts

BAR_MS = {"5m": 300_000, "15m": 900_000, "1H": 3_600_000}


@dataclass(frozen=True, slots=True)
class SymbolQuality:
    inst_id: str
    bar: BarSize
    rows: int
    start: str | None
    end: str | None
    gaps: int
    duplicates: int


@dataclass(frozen=True, slots=True)
class QualityReport:
    root: str
    bar: BarSize
    symbols: int
    rows_total: int
    symbols_with_gaps: int
    symbols_with_duplicates: int
    details: list[SymbolQuality]


def inspect_bars(inst_id: str, bar: BarSize, bars: list[Bar]) -> SymbolQuality:
    if not bars:
        return SymbolQuality(inst_id, bar, 0, None, None, 0, 0)
    step = BAR_MS[bar]
    seen = set()
    duplicates = 0
    gaps = 0
    prev = None
    for item in bars:
        if item.ts in seen:
            duplicates += 1
        seen.add(item.ts)
        if prev is not None and item.ts - prev != step:
            gaps += 1
        prev = item.ts
    return SymbolQuality(inst_id, bar, len(bars), fmt_ts(bars[0].ts), fmt_ts(bars[-1].ts), gaps, duplicates)


def inspect_csv_root(root: Path | str, bar: BarSize) -> QualityReport:
    provider = CsvKlineProvider(root)
    details = [inspect_bars(symbol, bar, provider.load_bars(symbol, bar)) for symbol in provider.symbols(bar)]
    return QualityReport(
        root=str(root),
        bar=bar,
        symbols=len(details),
        rows_total=sum(item.rows for item in details),
        symbols_with_gaps=sum(1 for item in details if item.gaps > 0),
        symbols_with_duplicates=sum(1 for item in details if item.duplicates > 0),
        details=details,
    )
