from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from .settings import PROJECT_ROOT, SCREENER_FAVORITES_DB_PATH


ROOT_DIR = PROJECT_ROOT
DB_PATH = SCREENER_FAVORITES_DB_PATH


class ScreenerFavoriteRepository:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def list(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, name, timeframe, payload, created_at, updated_at
                FROM screener_favorites
                ORDER BY updated_at DESC, created_at DESC
                """
            ).fetchall()
        return [self._row_to_item(row) for row in rows]

    def get(self, favorite_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, name, timeframe, payload, created_at, updated_at
                FROM screener_favorites
                WHERE id = ?
                """,
                (favorite_id,),
            ).fetchone()
        return self._row_to_item(row) if row else None

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValueError("收藏名称不能为空")
        if len(name) > 80:
            raise ValueError("收藏名称最多 80 个字符")

        favorite_id = uuid.uuid4().hex
        now = int(time.time() * 1000)
        normalized = {
            **payload,
            "id": favorite_id,
            "name": name,
            "timeframe": str(payload.get("timeframe") or "1m"),
            "created_at": now,
            "updated_at": now,
        }
        payload_json = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO screener_favorites (id, name, timeframe, payload, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (favorite_id, name, normalized["timeframe"], payload_json, now, now),
            )
        return normalized

    def delete(self, favorite_id: str) -> str:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM screener_favorites WHERE id = ?", (favorite_id,))
        if cursor.rowcount == 0:
            raise KeyError(f"收藏不存在：{favorite_id}")
        return favorite_id

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS screener_favorites (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_screener_favorites_updated_at
                ON screener_favorites(updated_at DESC)
                """
            )

    def _row_to_item(self, row: sqlite3.Row) -> dict[str, Any]:
        try:
            item = json.loads(row["payload"])
        except json.JSONDecodeError:
            item = {}
        if not isinstance(item, dict):
            item = {}

        metadata_conditions = item.get("metadata_conditions")
        if not isinstance(metadata_conditions, list):
            metadata_conditions = []
        condition_count = len(metadata_conditions)
        return {
            **item,
            "id": row["id"],
            "name": row["name"],
            "timeframe": row["timeframe"],
            "date": item.get("date"),
            "as_of_time": item.get("as_of_time", ""),
            "min_ret_15m": item.get("min_ret_15m", ""),
            "min_vol_ratio_60": item.get("min_vol_ratio_60", ""),
            "min_vol_quote_15m": item.get("min_vol_quote_15m", ""),
            "sort_by": item.get("sort_by", "ret_15m"),
            "metadata_conditions": metadata_conditions,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "condition_count": condition_count,
        }


screener_favorite_repository = ScreenerFavoriteRepository()
