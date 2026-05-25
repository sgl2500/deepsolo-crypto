from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True, slots=True)
class HistoryExtendResult:
    rows: list[list[str]]
    pages: int
    reached_target: bool
    earliest_fetched_ts: int | None
    latest_fetched_ts: int | None
    stopped_reason: str


def _row_ts(row: list[str]) -> int | None:
    try:
        return int(row[0])
    except (TypeError, ValueError, IndexError):
        return None


def fetch_older_history_rows(
    get_history_candles: Callable[[str | None], list[list[str]]],
    *,
    start_after_ts: int | None,
    target_start_ts: int,
    max_pages: int,
    sleep_seconds: float,
) -> HistoryExtendResult:
    """Fetch older history pages and keep rows at or after the target start.

    OKX history pagination returns rows older than `after`. For an existing
    local series, pass the current earliest timestamp as `start_after_ts`; for a
    bootstrap fetch, pass None to start from the latest available history page.
    """

    rows_by_ts: dict[int, list[str]] = {}
    after = str(start_after_ts) if start_after_ts is not None else None
    previous_min_ts: int | None = None
    earliest_seen: int | None = None
    latest_seen: int | None = None
    stopped_reason = "max_pages"
    pages = 0

    for page_index in range(max_pages):
        batch = get_history_candles(after)
        pages = page_index + 1
        if not batch:
            stopped_reason = "empty_page"
            break

        batch_ts = [ts for ts in (_row_ts(row) for row in batch) if ts is not None]
        if not batch_ts:
            stopped_reason = "invalid_page"
            break

        page_min_ts = min(batch_ts)
        page_max_ts = max(batch_ts)
        earliest_seen = page_min_ts if earliest_seen is None else min(earliest_seen, page_min_ts)
        latest_seen = page_max_ts if latest_seen is None else max(latest_seen, page_max_ts)

        for row in batch:
            ts = _row_ts(row)
            if ts is None:
                continue
            if start_after_ts is not None and ts >= start_after_ts:
                continue
            if ts >= target_start_ts:
                rows_by_ts[ts] = row

        if page_min_ts <= target_start_ts:
            stopped_reason = "reached_target"
            break
        if previous_min_ts is not None and page_min_ts >= previous_min_ts:
            stopped_reason = "pagination_not_progressing"
            break
        previous_min_ts = page_min_ts
        after = str(page_min_ts)
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    rows = [rows_by_ts[ts] for ts in sorted(rows_by_ts)]
    return HistoryExtendResult(
        rows=rows,
        pages=pages,
        reached_target=bool(earliest_seen is not None and earliest_seen <= target_start_ts),
        earliest_fetched_ts=earliest_seen,
        latest_fetched_ts=latest_seen,
        stopped_reason=stopped_reason,
    )
