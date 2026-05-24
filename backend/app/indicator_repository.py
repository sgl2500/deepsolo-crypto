from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from .config import TIMEFRAMES
from .settings import INDICATOR_STORE_PATH, PROJECT_ROOT

ROOT_DIR = PROJECT_ROOT
STORE_PATH = INDICATOR_STORE_PATH

DataType = Literal["number", "string", "datetime", "boolean"]
SourceType = Literal["raw", "manual", "computed", "script"]


class IndicatorCreate(BaseModel):
    id: str = Field(min_length=2, max_length=80)
    name_zh: str = Field(min_length=1, max_length=80)
    storage_period: str
    data_type: DataType
    unit: str = Field(default="", max_length=40)
    source_type: SourceType = "manual"
    description: str = Field(default="", max_length=240)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        normalized = value.strip()
        if not re.fullmatch(r"[A-Za-z0-9_.:-]+", normalized):
            raise ValueError("id 只能包含英文、数字、下划线、点、冒号和短横线")
        return normalized

    @field_validator("storage_period")
    @classmethod
    def validate_storage_period(cls, value: str) -> str:
        normalized = normalize_period(value)
        if normalized not in TIMEFRAMES:
            supported = ", ".join(TIMEFRAMES)
            raise ValueError(f"不支持的存储周期，请使用：{supported}")
        return normalized

    @field_validator("name_zh", "unit", "description")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


RAW_FIELDS = [
    {
        "field": "inst_id",
        "name_zh": "合约ID",
        "data_type": "string",
        "unit": "",
        "description": "合约标识，例如 BTC-USDT-SWAP。",
    },
    {
        "field": "ts",
        "name_zh": "K线时间戳",
        "data_type": "datetime",
        "unit": "ms",
        "description": "K线开始时间，Unix 毫秒时间戳。",
    },
    {
        "field": "open",
        "name_zh": "开盘价",
        "data_type": "number",
        "unit": "USDT",
        "description": "当前周期 K 线开盘价。",
    },
    {
        "field": "high",
        "name_zh": "最高价",
        "data_type": "number",
        "unit": "USDT",
        "description": "当前周期 K 线最高价。",
    },
    {
        "field": "low",
        "name_zh": "最低价",
        "data_type": "number",
        "unit": "USDT",
        "description": "当前周期 K 线最低价。",
    },
    {
        "field": "close",
        "name_zh": "收盘价",
        "data_type": "number",
        "unit": "USDT",
        "description": "当前周期 K 线收盘价。",
    },
    {
        "field": "vol",
        "name_zh": "成交量",
        "data_type": "number",
        "unit": "张/币",
        "description": "交易所原始成交量字段。",
    },
    {
        "field": "vol_ccy",
        "name_zh": "币本位成交量",
        "data_type": "number",
        "unit": "币",
        "description": "以币为单位的成交量。",
    },
    {
        "field": "vol_ccy_quote",
        "name_zh": "计价成交额",
        "data_type": "number",
        "unit": "USDT",
        "description": "以计价货币 USDT 计算的成交额。",
    },
    {
        "field": "confirm",
        "name_zh": "K线确认状态",
        "data_type": "boolean",
        "unit": "",
        "description": "交易所 K 线是否已确认。",
    },
    {
        "field": "source",
        "name_zh": "数据来源",
        "data_type": "string",
        "unit": "",
        "description": "原始数据采集来源。",
    },
    {
        "field": "ingested_at",
        "name_zh": "入库时间戳",
        "data_type": "datetime",
        "unit": "ms",
        "description": "数据被采集/归一化写入的时间。",
    },
]


class IndicatorRepository:
    def __init__(self, store_path: Path = STORE_PATH) -> None:
        self.store_path = store_path
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.store_path.exists():
            self._write(self._seed_indicators())
        else:
            self._ensure_seed_indicators()

    def list(
        self,
        storage_period: str | None = None,
        source_type: SourceType | None = None,
        query: str | None = None,
    ) -> list[dict[str, Any]]:
        items = self._read()
        if storage_period:
            period = normalize_period(storage_period)
            items = [item for item in items if item["storage_period"] == period]
        if source_type:
            items = [item for item in items if item["source_type"] == source_type]
        if query:
            needle = query.strip().lower()
            items = [
                item
                for item in items
                if needle in item["id"].lower()
                or needle in item["name_zh"].lower()
                or needle in item.get("description", "").lower()
            ]
        return sorted(items, key=lambda item: (item["storage_period"], item["source_type"], item["id"]))

    def create(self, payload: IndicatorCreate) -> dict[str, Any]:
        items = self._read()
        if any(item["id"] == payload.id for item in items):
            raise ValueError(f"指标 id 已存在：{payload.id}")

        now = int(time.time() * 1000)
        item = {
            "id": payload.id,
            "name_zh": payload.name_zh,
            "storage_period": payload.storage_period,
            "data_type": payload.data_type,
            "unit": payload.unit,
            "source_type": payload.source_type,
            "description": payload.description,
            "created_at": now,
            "updated_at": now,
        }
        items.append(item)
        self._write(items)
        return item

    def update(self, indicator_id: str, payload: IndicatorCreate) -> dict[str, Any]:
        items = self._read()
        index = next((idx for idx, item in enumerate(items) if item["id"] == indicator_id), None)
        if index is None:
            raise KeyError(f"指标不存在：{indicator_id}")

        current = items[index]
        if current["source_type"] == "raw":
            raise ValueError("内置原始字段不能编辑")
        if payload.source_type != current["source_type"]:
            raise ValueError("不能修改指标来源类型")
        if payload.id != indicator_id and any(
            item["id"] == payload.id for idx, item in enumerate(items) if idx != index
        ):
            raise ValueError(f"指标 id 已存在：{payload.id}")

        now = int(time.time() * 1000)
        item = {
            "id": payload.id,
            "name_zh": payload.name_zh,
            "storage_period": payload.storage_period,
            "data_type": payload.data_type,
            "unit": payload.unit,
            "source_type": payload.source_type,
            "description": payload.description,
            "created_at": current.get("created_at", now),
            "updated_at": now,
        }
        items[index] = item
        self._write(items)
        return item

    def delete(self, indicator_id: str) -> dict[str, Any]:
        items = self._read()
        index = next((idx for idx, item in enumerate(items) if item["id"] == indicator_id), None)
        if index is None:
            raise KeyError(f"指标不存在：{indicator_id}")
        if items[index]["source_type"] == "raw":
            raise ValueError("内置原始字段不能删除")

        deleted = items.pop(index)
        self._write(items)
        return deleted

    def get(self, indicator_id: str) -> dict[str, Any] | None:
        for item in self._read():
            if item["id"] == indicator_id:
                return item
        return None

    def summary(self) -> dict[str, Any]:
        items = self._read()
        by_period = {
            period: sum(1 for item in items if item["storage_period"] == period)
            for period in TIMEFRAMES
        }
        by_type = {
            data_type: sum(1 for item in items if item["data_type"] == data_type)
            for data_type in ("number", "string", "datetime", "boolean")
        }
        return {
            "total": len(items),
            "by_period": by_period,
            "by_type": by_type,
            "store_path": str(self.store_path),
        }

    def reset_seed(self) -> list[dict[str, Any]]:
        items = self._seed_indicators()
        self._write(items)
        return items

    def _ensure_seed_indicators(self) -> None:
        items = self._read()
        existing_ids = {item.get("id") for item in items}
        missing = [item for item in self._seed_indicators() if item["id"] not in existing_ids]
        if missing:
            self._write([*items, *missing])

    def _seed_indicators(self) -> list[dict[str, Any]]:
        now = int(time.time() * 1000)
        items: list[dict[str, Any]] = []
        for period in TIMEFRAMES:
            for field in RAW_FIELDS:
                items.append(
                    {
                        "id": f"raw.{period}.{field['field']}",
                        "name_zh": field["name_zh"],
                        "storage_period": period,
                        "data_type": field["data_type"],
                        "unit": field["unit"],
                        "source_type": "raw",
                        "raw_field": field["field"],
                        "description": field["description"],
                        "created_at": now,
                        "updated_at": now,
                    }
                )
        return items

    def _read(self) -> list[dict[str, Any]]:
        with self.store_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, list):
            return []
        return data

    def _write(self, items: list[dict[str, Any]]) -> None:
        with self.store_path.open("w", encoding="utf-8") as handle:
            json.dump(items, handle, ensure_ascii=False, indent=2)


def normalize_period(value: str) -> str:
    for period in TIMEFRAMES:
        if period.lower() == value.strip().lower():
            return period
    return value.strip()


indicator_repository = IndicatorRepository()
