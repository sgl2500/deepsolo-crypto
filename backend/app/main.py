from __future__ import annotations

import json

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .data_source import data_source_service
from .indicator_repository import IndicatorCreate, indicator_repository
from .screener import builtin_indicators, query_screener

app = FastAPI(title="Crypto Screener Local API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:49170", "http://localhost:49170"],
    allow_origin_regex=r"http://(127\.0\.0\.1|localhost):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/data-source/summary")
def data_source_summary(force: bool = False) -> dict:
    return data_source_service.summary(force=force)


@app.get("/api/data-source/preview")
def data_source_preview(
    timeframe: str = "1m",
    date: str = Query(...),
    inst_id: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    try:
        return data_source_service.preview(timeframe, date, inst_id, limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/indicators/{indicator_id}/preview")
def indicator_value_preview(
    indicator_id: str,
    date: str = Query(...),
    time: str | None = None,
    query: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict:
    indicator = indicator_repository.get(indicator_id)
    if not indicator:
        raise HTTPException(status_code=404, detail=f"指标不存在：{indicator_id}")

    raw_field = indicator.get("raw_field")
    if not raw_field:
        return {
            "indicator": indicator,
            "date": date,
            "time": time or "",
            "rows": [],
            "message": "这个指标还没有接入数据流，暂时只能预览原始字段指标。",
        }

    try:
        preview = data_source_service.indicator_preview(
            timeframe=indicator["storage_period"],
            date=date,
            field=raw_field,
            time_text=time,
            query=query,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"indicator": indicator, **preview}


@app.get("/api/indicators/catalog")
def indicators_catalog(
    storage_period: str | None = None,
    source_type: str | None = None,
    query: str | None = None,
) -> dict:
    try:
        items = indicator_repository.list(
            storage_period=storage_period,
            source_type=source_type,  # type: ignore[arg-type]
            query=query,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"items": items, "summary": indicator_repository.summary()}


@app.post("/api/indicators/catalog", status_code=201)
def create_indicator(payload: IndicatorCreate) -> dict:
    try:
        return indicator_repository.create(payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/indicators/catalog/reset-seed")
def reset_indicator_seed() -> dict:
    items = indicator_repository.reset_seed()
    return {"items": items, "summary": indicator_repository.summary()}


@app.get("/api/indicators/builtin")
def indicators_builtin() -> dict:
    return {"items": builtin_indicators()}


@app.get("/api/screener/query")
def screener_query(
    timeframe: str = "1m",
    date: str | None = None,
    as_of: str | None = None,
    min_ret_15m: float | None = None,
    min_vol_ratio_60: float | None = None,
    min_vol_quote_15m: float | None = None,
    sort_by: str = "ret_15m",
    sort_dir: str = "desc",
    metadata_filters: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    parsed_metadata_filters = None
    if metadata_filters:
        try:
            parsed_metadata_filters = json.loads(metadata_filters)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="metadata_filters 必须是 JSON 数组") from exc
        if not isinstance(parsed_metadata_filters, list):
            raise HTTPException(status_code=400, detail="metadata_filters 必须是 JSON 数组")

    try:
        return query_screener(
            timeframe=timeframe,
            date=date,
            as_of=as_of,
            min_ret_15m=min_ret_15m,
            min_vol_ratio_60=min_vol_ratio_60,
            min_vol_quote_15m=min_vol_quote_15m,
            sort_by=sort_by,
            sort_dir=sort_dir,
            metadata_filters=parsed_metadata_filters,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
