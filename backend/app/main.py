from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .backtest_service import backtest_service
from .data_quality_service import data_quality_service
from .data_source import data_source_service
from .favorite_repository import screener_favorite_repository
from .indicator_repository import IndicatorCreate, indicator_repository
from .screener import builtin_indicators, query_screener, query_screener_time_counts
from .signal_pool_service import signal_pool_service
from . import contract_update_service, script_indicator_service

app = FastAPI(title="Crypto Screener Local API", version="0.1.0")


class ScriptSaveRequest(BaseModel):
    script: str = Field(min_length=1)


class ScriptGenerateRequest(BaseModel):
    requirement: str = ""
    input_timeframe: str = "1m"


class ScriptTrialRunRequest(BaseModel):
    date: str
    input_timeframe: str = "1m"
    script: str | None = None
    limit: int = Field(default=200, ge=1, le=1000)


class ContractUpdateRequest(BaseModel):
    force: bool = True
    backfill_history: bool = False
    pages: int | None = Field(default=None, ge=1, le=200)
    limit: int = Field(default=300, ge=1, le=300)
    build_daily: bool = True
    daily_days: int = Field(default=10, ge=1, le=365)
    symbol_limit: int | None = Field(default=None, ge=1, le=1000)


class ScreenerFavoriteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    timeframe: str = "1m"
    date: str | None = None
    as_of_time: str = ""
    min_ret_15m: str = ""
    min_vol_ratio_60: str = ""
    min_vol_quote_15m: str = ""
    sort_by: str = "ret_15m"
    metadata_conditions: list[dict[str, Any]] = Field(default_factory=list)


class BacktestRunRequest(BaseModel):
    favorite_id: str = Field(min_length=1)
    name: str = ""
    start_date: str
    end_date: str
    signal_timeframe: str = "1H"
    signal_mode: str = "daily"
    entry_timeframe: str = "1m"
    hold_hours: int = Field(default=24, ge=1, le=720)
    position_usdt: float = Field(default=100, gt=0)
    max_positions: int = Field(default=5, ge=1, le=100)
    fee_bps_per_side: float = Field(default=5, ge=0)
    slippage_bps_per_side: float = Field(default=5, ge=0)
    checkpoint_limit: int = Field(default=500, ge=1, le=5000)


class SignalSetCreateRequest(BaseModel):
    favorite_id: str = Field(min_length=1)
    name: str = ""
    start_date: str
    end_date: str
    signal_timeframe: str = "1H"
    signal_mode: str = "daily"
    checkpoint_limit: int = Field(default=500, ge=1, le=5000)


class SignalSetBacktestRequest(BaseModel):
    signal_set_id: str = Field(min_length=1)
    name: str = ""
    side: str = "short"
    entry_timeframe: str = "5m"
    entry_rule: str = "consecutive_green_bars"
    entry_window_minutes: int = Field(default=60, ge=1, le=1440)
    entry_consecutive_bars: int = Field(default=2, ge=1, le=20)
    entry_min_gain_pct_each: float = Field(default=2.0, ge=0)
    exit_hold_minutes: int = Field(default=440, ge=1, le=43200)
    stop_loss_pct: float = Field(default=15.0, ge=0)
    stop_model: str = "bot_like_checkpoint"
    position_usdt: float = Field(default=500, gt=0)
    leverage: float = Field(default=1, gt=0)
    max_positions: int = Field(default=2, ge=1, le=100)
    fee_bps_per_side: float = Field(default=5, ge=0)
    slippage_bps_per_side: float = Field(default=5, ge=0)

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


@app.get("/api/contracts/active")
def active_contracts(
    timeframe: str = "1m",
    date: str | None = None,
    query: str | None = None,
    limit: int = Query(default=2000, ge=1, le=5000),
) -> dict:
    try:
        return data_source_service.active_contracts(timeframe, date, query, limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/data-quality/summary")
def data_quality_summary(timeframe: str = "1m", force: bool = False) -> dict:
    try:
        return data_quality_service.summary(timeframe=timeframe, force=force)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/data-quality/dates")
def data_quality_dates(
    timeframe: str = "1m",
    limit: int = Query(default=90, ge=1, le=365),
    force: bool = False,
) -> dict:
    try:
        return data_quality_service.date_report(timeframe=timeframe, limit=limit, force=force)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/data-quality/contracts/{inst_id}")
def data_quality_contract(
    inst_id: str,
    gap_limit: int = Query(default=30, ge=1, le=100),
) -> dict:
    try:
        return data_quality_service.contract_report(inst_id=inst_id, gap_limit=gap_limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/contracts/update-deploy")
def start_contract_update_deploy(payload: ContractUpdateRequest) -> dict:
    try:
        return contract_update_service.contract_update_service.start(
            force=payload.force,
            backfill_history=payload.backfill_history,
            pages=payload.pages,
            limit=payload.limit,
            build_daily=payload.build_daily,
            daily_days=payload.daily_days,
            symbol_limit=payload.symbol_limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/contracts/update-deploy/status")
def contract_update_deploy_status(
    tail_chars: int = Query(default=12000, ge=0, le=20000),
) -> dict:
    return contract_update_service.contract_update_service.status(tail_chars=tail_chars)


@app.get("/api/contracts/{inst_id}/klines")
def contract_kline_window(
    inst_id: str,
    timeframe: str = "1m",
    date: str | None = None,
    anchor_ts: int | None = None,
    before: int = Query(default=33, ge=1, le=300),
    after: int = Query(default=33, ge=0, le=300),
) -> dict:
    try:
        return data_source_service.kline_window(
            timeframe=timeframe,
            date=date,
            inst_id=inst_id,
            anchor_ts=anchor_ts,
            before=before,
            after=after,
        )
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

    if indicator.get("source_type") == "script":
        try:
            preview = script_indicator_service.preview_output(
                indicator_id,
                date=date,
                time_text=time,
                query=query,
                limit=limit,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"indicator": indicator, **preview}

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


@app.put("/api/indicators/catalog/{indicator_id:path}")
def update_indicator(indicator_id: str, payload: IndicatorCreate) -> dict:
    try:
        return indicator_repository.update(indicator_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.delete("/api/indicators/catalog/{indicator_id:path}")
def delete_indicator(indicator_id: str) -> dict:
    try:
        deleted = indicator_repository.delete(indicator_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"deleted": deleted["id"]}


@app.get("/api/script-indicators/{indicator_id:path}/workspace")
def script_indicator_workspace(indicator_id: str) -> dict:
    try:
        return script_indicator_service.workspace(indicator_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/script-indicators/{indicator_id:path}/script")
def save_script_indicator_script(indicator_id: str, payload: ScriptSaveRequest) -> dict:
    try:
        return script_indicator_service.save_script(indicator_id, payload.script)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/script-indicators/{indicator_id:path}/ai-generate")
def generate_script_indicator_script(indicator_id: str, payload: ScriptGenerateRequest) -> dict:
    try:
        return script_indicator_service.generate_script(
            indicator_id,
            requirement=payload.requirement,
            input_timeframe=payload.input_timeframe,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/script-indicators/{indicator_id:path}/trial-run")
def trial_run_script_indicator(indicator_id: str, payload: ScriptTrialRunRequest) -> dict:
    try:
        return script_indicator_service.trial_run(
            indicator_id,
            date=payload.date,
            input_timeframe=payload.input_timeframe,
            script=payload.script,
            limit=payload.limit,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/indicators/catalog/reset-seed")
def reset_indicator_seed() -> dict:
    items = indicator_repository.reset_seed()
    return {"items": items, "summary": indicator_repository.summary()}


@app.get("/api/indicators/builtin")
def indicators_builtin() -> dict:
    return {"items": builtin_indicators()}


@app.get("/api/screener/favorites")
def screener_favorites() -> dict:
    return {"items": screener_favorite_repository.list()}


@app.post("/api/screener/favorites", status_code=201)
def create_screener_favorite(payload: ScreenerFavoriteCreate) -> dict:
    try:
        return screener_favorite_repository.create(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/screener/favorites/{favorite_id}")
def delete_screener_favorite(favorite_id: str) -> dict:
    try:
        deleted = screener_favorite_repository.delete(favorite_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"deleted": deleted}


@app.get("/api/signal-sets")
def signal_sets() -> dict:
    return {"items": signal_pool_service.list_signal_sets()}


@app.post("/api/signal-sets", status_code=201)
def create_signal_set(payload: SignalSetCreateRequest) -> dict:
    try:
        return signal_pool_service.create_signal_set(payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/signal-sets/{signal_set_id}")
def signal_set(signal_set_id: str) -> dict:
    item = signal_pool_service.get_signal_set(signal_set_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"异动表不存在：{signal_set_id}")
    return item


@app.get("/api/signal-sets/{signal_set_id}/events")
def signal_set_events(
    signal_set_id: str,
    limit: int = Query(default=500, ge=1, le=5000),
) -> dict:
    try:
        return {"items": signal_pool_service.list_events(signal_set_id, limit=limit)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/backtests/runs")
def backtest_runs() -> dict:
    return {"items": backtest_service.list_runs()}


@app.post("/api/backtests/runs/from-signal-set", status_code=201)
def create_backtest_run_from_signal_set(payload: SignalSetBacktestRequest) -> dict:
    try:
        return signal_pool_service.create_backtest_from_signal_set(payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/backtests/runs/{run_id}")
def backtest_run(run_id: str) -> dict:
    item = backtest_service.get_run(run_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"回测记录不存在：{run_id}")
    return item


@app.post("/api/backtests/runs", status_code=201)
def create_backtest_run(payload: BacktestRunRequest) -> dict:
    try:
        return backtest_service.create_run(payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/screener/time-counts")
def screener_time_counts(
    timeframe: str = "1m",
    date: str | None = None,
    min_ret_15m: float | None = None,
    min_vol_ratio_60: float | None = None,
    min_vol_quote_15m: float | None = None,
    sort_by: str = "ret_15m",
    sort_dir: str = "desc",
    metadata_filters: str | None = None,
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
        return query_screener_time_counts(
            timeframe=timeframe,
            date=date,
            min_ret_15m=min_ret_15m,
            min_vol_ratio_60=min_vol_ratio_60,
            min_vol_quote_15m=min_vol_quote_15m,
            sort_by=sort_by,
            sort_dir=sort_dir,
            metadata_filters=parsed_metadata_filters,
        )
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
