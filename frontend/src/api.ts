const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:49171";

export type TimeframeSummary = {
  key: string;
  directory: string;
  date_count: number;
  latest_date: string | null;
  latest_file_count: number;
  max_file_count: number;
  recommended_date: string | null;
  recommended_file_count: number;
  dates: Array<{ date: string; file_count: number }>;
};

export type DataSummary = {
  root: string;
  exists: boolean;
  scanned_at: number;
  timeframes: TimeframeSummary[];
};

export type ScreenerRow = {
  inst_id: string;
  latest_ts: number;
  latest_close: number;
  ret_15m: number;
  ret_1h: number;
  amp_15m: number;
  vol_quote_15m: number;
  vol_ratio_60: number;
  latest_time: string;
  metadata_values?: Record<string, string>;
  matched_conditions: string[];
};

export type ScreenerResponse = {
  timeframe: string;
  date: string | null;
  as_of_label: string | null;
  total_contracts: number;
  matched_count: number;
  returned_count: number;
  duration_ms: number;
  condition_stats: Record<string, number>;
  rows: ScreenerRow[];
  message?: string;
};

export type ScreenerTimeCountItem = {
  time: string;
  as_of: string;
  date: string | null;
  as_of_label: string | null;
  total_contracts: number;
  matched_count: number;
  duration_ms: number;
};

export type ScreenerTimeCountsResponse = {
  timeframe: string;
  date: string | null;
  duration_ms: number;
  items: ScreenerTimeCountItem[];
  message?: string;
};

export type ScreenerMetadataFilterPayload = {
  indicator_id: string;
  operator: string;
  value: string;
  time_mode?: string;
  time_offset?: string;
  time_point_mode?: string;
  time_point?: string;
  bar_offset?: string;
  time_offset_value?: string;
  time_offset_unit?: string;
  truncate_mode?: string;
  truncate_count?: string;
  external_relation?: boolean;
  time_range?: boolean;
  exclude?: boolean;
  match_current_bar?: boolean;
};

export type Indicator = {
  id: string;
  name_zh: string;
  storage_period: string;
  data_type: "number" | "string" | "datetime" | "boolean";
  unit: string;
  source_type: "raw" | "manual" | "computed" | "script";
  raw_field?: string;
  description: string;
  created_at: number;
  updated_at: number;
};

export type IndicatorSummary = {
  total: number;
  by_period: Record<string, number>;
  by_type: Record<string, number>;
  store_path: string;
};

export type IndicatorCatalogResponse = {
  items: Indicator[];
  summary: IndicatorSummary;
};

export type IndicatorCreatePayload = {
  id: string;
  name_zh: string;
  storage_period: string;
  data_type: Indicator["data_type"];
  unit: string;
  source_type: Indicator["source_type"];
  description: string;
};

export type DataPreviewResponse = {
  file: string | null;
  rows: Array<Record<string, string>>;
};

export type ContractRow = {
  inst_id: string;
  symbol: string;
  latest_ts: string;
  latest_time: string | null;
  latest_close: string;
  source_file: string;
};

export type ContractListResponse = {
  timeframe: string;
  date: string | null;
  total_count: number;
  returned_count: number;
  rows: ContractRow[];
};

export type DataQualityStatus = "ok" | "warning" | "fail";

export type DataQualityTimeframeStatus = {
  timeframe: string;
  latest_date: string | null;
  latest_file_count: number;
  raw_latest_date?: string | null;
  raw_latest_file_count?: number;
  max_file_count: number;
  date_count: number;
  expected_latest_count: number;
  missing_latest_count: number;
  extra_latest_count: number;
  status: DataQualityStatus;
};

export type DataQualityContractIssue = {
  inst_id: string;
  timeframe: string;
  rows: number;
  start: string | null;
  end: string | null;
  gaps: number;
  duplicates: number;
  unconfirmed: number;
};

export type DataQualitySummary = {
  root: string;
  catalog_updated_at: string | null;
  generated_at: number;
  timeframe: string;
  status: DataQualityStatus;
  status_label: string;
  online_symbols: number;
  latest_date: string | null;
  latest_file_count: number;
  raw_latest_date?: string | null;
  raw_latest_file_count?: number;
  expected_latest_count: number;
  missing_latest_count: number;
  extra_latest_count: number;
  missing_latest_symbols: string[];
  extra_latest_symbols: string[];
  quality_report: {
    source: string;
    symbols: number;
    rows_total: number;
    symbols_with_gaps: number;
    symbols_with_duplicates: number;
    symbols_with_unconfirmed: number;
  };
  timeframes: DataQualityTimeframeStatus[];
  top_contract_issues: DataQualityContractIssue[];
  issues: string[];
};

export type DataQualityDateRow = {
  date: string;
  timeframe: string;
  expected_count: number;
  actual_count: number;
  missing_count: number;
  extra_count: number;
  missing_symbols: string[];
  extra_symbols: string[];
  status: DataQualityStatus;
  status_label: string;
};

export type DataQualityDateReport = {
  timeframe: string;
  generated_at: number;
  total_dates: number;
  returned_count: number;
  rows: DataQualityDateRow[];
};

export type DataQualityGapSample = {
  prev_ts: number;
  prev_time: string | null;
  next_ts: number;
  next_time: string | null;
  missing_count: number;
  missing_start: string | null;
  missing_end: string | null;
};

export type DataQualityContractTimeframe = {
  timeframe: string;
  status: DataQualityStatus;
  status_label: string;
  row_count: number;
  unique_row_count: number;
  file_count: number;
  expected_file_count: number;
  missing_file_count: number;
  missing_dates: string[];
  start_ts: number | null;
  start_time: string | null;
  end_ts: number | null;
  end_time: string | null;
  gap_events: number;
  missing_bars: number;
  gap_samples: DataQualityGapSample[];
  duplicate_rows: number;
  unconfirmed_rows: number;
  bad_rows: number;
  coverage_pct: number;
};

export type DataQualityContractReport = {
  inst_id: string;
  symbol: string;
  generated_at: number;
  status: DataQualityStatus;
  status_label: string;
  latest_time: string | null;
  instrument: {
    state: string;
    is_online: boolean;
    list_time: number | null;
    list_time_text: string | null;
    first_seen_at: string | null;
    last_seen_at: string | null;
  };
  timeframes: DataQualityContractTimeframe[];
};

export type ContractKlineRow = {
  ts: number | null;
  time: string | null;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  vol: number | null;
  vol_ccy: number | null;
  vol_ccy_quote: number | null;
};

export type ContractKlineResponse = {
  timeframe: string;
  date: string;
  inst_id: string;
  anchor_ts: number;
  anchor_time: string | null;
  anchor_index: number;
  before: number;
  after: number;
  before_count: number;
  after_count: number;
  returned_count: number;
  rows: ContractKlineRow[];
};

export type ContractUpdateStatus = {
  running: boolean;
  stage: string;
  stage_label: string;
  started_at: number | null;
  updated_at: number | null;
  finished_at: number | null;
  success: boolean | null;
  error: string;
  return_code: number | null;
  current_command: string;
  log_file: string;
  strategy_root: string;
  crypto_v2_root: string;
  data_root: string;
  options: Record<string, unknown>;
  log_tail: string;
};

export type ContractUpdatePayload = {
  force?: boolean;
  backfill_history?: boolean;
  pages?: number | null;
  limit?: number;
  build_daily?: boolean;
  daily_days?: number;
  symbol_limit?: number | null;
};

export type IndicatorValuePreviewResponse = {
  indicator: Indicator;
  date: string;
  time: string;
  field?: string;
  total_files?: number;
  returned_count?: number;
  source_type?: Indicator["source_type"];
  success?: boolean;
  run_dir?: string;
  output_file?: string;
  message?: string | null;
  rows: Array<{
    inst_id: string;
    value: string;
    ts?: string;
    time?: string | null;
  }>;
};

export type ScriptWorkspaceResponse = {
  indicator: Indicator;
  script: string;
  prompt: string;
  script_path: string;
  output_dir: string;
  openai_configured: boolean;
  model: string;
};

export type ScriptGenerateResponse = {
  script: string;
  prompt: string;
  model: string;
};

export type ScriptTrialRunResponse = {
  success: boolean;
  return_code: number | null;
  elapsed_ms: number;
  timed_out: boolean;
  date: string;
  input_timeframe: string;
  output_file: string;
  run_dir: string;
  output_count: number;
  returned_count: number;
  rows: Array<{
    inst_id: string;
    ts: string;
    value: string;
  }>;
  stdout: string;
  stderr: string;
};

export type ScreenerFavoriteCondition = {
  id?: string;
  indicator_id: string;
  indicator: Indicator;
  time_mode: string;
  time_offset: string;
  time_point_mode?: string;
  time_point: string;
  bar_offset?: string;
  time_offset_value?: string;
  time_offset_unit?: string;
  operator: string;
  value: string;
  truncate_mode: string;
  truncate_count: string;
  external_relation: boolean;
  time_range: boolean;
  exclude: boolean;
  match_current_bar?: boolean;
};

export type ScreenerFavoritePayload = {
  name: string;
  timeframe: string;
  date?: string | null;
  as_of_time?: string;
  min_ret_15m?: string;
  min_vol_ratio_60?: string;
  min_vol_quote_15m?: string;
  sort_by?: string;
  metadata_conditions: ScreenerFavoriteCondition[];
};

export type ScreenerFavorite = ScreenerFavoritePayload & {
  id: string;
  created_at: number;
  updated_at: number;
  condition_count: number;
};

export type SignalSetCreateRequest = {
  favorite_id: string;
  name?: string;
  start_date: string;
  end_date: string;
  signal_timeframe: string;
  signal_mode: "daily" | "each_bar_close";
  checkpoint_limit?: number;
};

export type SignalSetSummary = {
  start_date?: string;
  end_date?: string;
  signal_timeframe?: string;
  signal_mode?: string;
  checkpoint_count?: number;
  matched_count?: number;
  returned_count?: number;
  event_count?: number;
  truncated_events?: number;
  unique_contracts?: number;
  total_contracts?: number;
  first_signal_ts?: number | null;
  first_signal_time?: string | null;
  last_signal_ts?: number | null;
  last_signal_time?: string | null;
  first_confirm_ts?: number | null;
  first_confirm_time?: string | null;
  last_confirm_ts?: number | null;
  last_confirm_time?: string | null;
  duration_ms?: number;
};

export type SignalSet = {
  id: string;
  favorite_id: string;
  name: string;
  status: "running" | "completed" | "failed" | string;
  config: SignalSetCreateRequest;
  favorite: {
    id: string;
    name: string;
    timeframe: string;
    condition_count: number;
  };
  summary: SignalSetSummary;
  error: string;
  created_at: number;
  started_at: number | null;
  finished_at: number | null;
};

export type SignalEvent = {
  id: string;
  signal_set_id: string;
  favorite_id: string;
  inst_id: string;
  timeframe: string;
  date: string;
  signal_ts: number;
  confirm_ts: number;
  signal_time: string | null;
  confirm_time: string | null;
  strength: number;
  matched_conditions: string[];
  metadata_values: Record<string, string>;
  row_snapshot: Record<string, unknown>;
};

export type BacktestRunRequest = {
  favorite_id: string;
  name?: string;
  start_date: string;
  end_date: string;
  signal_timeframe: string;
  signal_mode: "daily" | "each_bar_close";
  entry_timeframe: string;
  hold_hours: number;
  position_usdt: number;
  max_positions: number;
  fee_bps_per_side: number;
  slippage_bps_per_side: number;
  checkpoint_limit?: number;
};

export type SignalSetBacktestRequest = {
  signal_set_id: string;
  name?: string;
  side: "long" | "short";
  entry_timeframe: string;
  entry_rule: "next_bar_open" | "consecutive_green_bars";
  entry_window_minutes: number;
  entry_consecutive_bars: number;
  entry_min_gain_pct_each: number;
  exit_hold_minutes: number;
  stop_loss_pct: number;
  stop_model: "bot_like_checkpoint" | "hard_stop_intrabar";
  position_usdt: number;
  leverage: number;
  max_positions: number;
  fee_bps_per_side: number;
  slippage_bps_per_side: number;
};

export type BacktestRunConfig = Partial<BacktestRunRequest & SignalSetBacktestRequest> & {
  favorite_name?: string;
};

export type BacktestSummary = {
  checkpoints: number;
  matched_signals: number;
  opened_trades: number;
  skipped_overlap: number;
  skipped_max_positions: number;
  skipped_insufficient_equity?: number;
  skipped_account_depleted?: number;
  skipped_no_entry: number;
  skipped_no_exit: number;
  start_date: string;
  end_date: string;
  signal_mode: string;
  signal_timeframe: string;
  entry_timeframe: string;
  entry_rule?: string;
  side?: string;
  hold_hours: number;
  exit_hold_minutes?: number;
  stop_loss_pct?: number;
  stop_model?: string;
  initial_capital: number;
  total_trades: number;
  win_trades: number;
  loss_trades: number;
  win_rate: number;
  total_pnl: number;
  total_return_pct: number;
  avg_pnl: number;
  profit_factor: number | null;
  max_drawdown_pct: number;
  fee_bps_per_side: number;
  slippage_bps_per_side: number;
  duration_ms: number;
  skipped_entry_rule?: number;
  position_usdt?: number;
  leverage?: number;
};

export type BacktestEquityPoint = {
  ts: number | null;
  time: string | null;
  equity: number;
  pnl_usdt: number;
  drawdown_pct: number;
};

export type BacktestTrade = {
  id: number;
  inst_id: string;
  side?: "long" | "short" | string;
  direction?: string;
  signal_date: string;
  signal_ts: number;
  signal_time: string;
  confirm_ts?: number;
  confirm_time?: string;
  entry_ts: number;
  entry_time: string;
  exit_ts: number;
  exit_time: string;
  hold_hours: number;
  position_usdt: number;
  raw_entry_price: number;
  raw_exit_price: number;
  entry_price: number;
  exit_price: number;
  stop_price?: number;
  liquidation_price?: number | null;
  liquidated?: boolean;
  exit_reason?: string;
  entry_reason?: string;
  trigger_pct?: number[];
  delay_min?: number;
  exit_hold_minutes?: number;
  leverage?: number;
  notional_usdt?: number;
  gross_return_pct: number;
  net_return_pct: number;
  fee_usdt: number;
  slippage_usdt?: number;
  cost_usdt?: number;
  max_adverse_pct?: number;
  max_favorable_pct?: number;
  pnl_usdt: number;
  matched_conditions: string[];
  signal_metrics: Record<string, number | string | null | undefined>;
};

export type BacktestCheckpoint = {
  index: number;
  date: string;
  as_of_ts: number;
  as_of_time: string;
  signal_ts: number;
  signal_time: string;
  matched_count: number;
  opened_count: number;
  duration_ms: number;
};

export type BacktestResult = {
  summary: BacktestSummary;
  equity: BacktestEquityPoint[];
  daily_equity?: BacktestEquityPoint[];
  trades: BacktestTrade[];
  checkpoints: BacktestCheckpoint[];
  favorite?: {
    id: string;
    name: string;
    timeframe: string;
    condition_count: number;
  };
  signal_set?: {
    id: string;
    name: string;
    summary: SignalSetSummary;
  };
};

export type BacktestRun = {
  id: string;
  name: string;
  favorite_id: string;
  status: "running" | "completed" | "failed" | string;
  config: BacktestRunConfig;
  result: BacktestResult | null;
  error: string;
  created_at: number;
  started_at: number | null;
  finished_at: number | null;
};

export async function fetchSummary(force = false): Promise<DataSummary> {
  return request(`/api/data-source/summary?force=${force ? "true" : "false"}`);
}

export async function fetchDataPreview(params: {
  timeframe: string;
  date: string;
  instId?: string;
  limit?: number;
}): Promise<DataPreviewResponse> {
  const search = new URLSearchParams();
  search.set("timeframe", params.timeframe);
  search.set("date", params.date);
  search.set("limit", `${params.limit ?? 30}`);
  if (params.instId) search.set("inst_id", params.instId);
  return request(`/api/data-source/preview?${search.toString()}`);
}

export async function fetchActiveContracts(params: {
  timeframe?: string;
  date?: string;
  query?: string;
  limit?: number;
} = {}): Promise<ContractListResponse> {
  const search = new URLSearchParams();
  search.set("timeframe", params.timeframe ?? "1m");
  search.set("limit", `${params.limit ?? 2000}`);
  if (params.date) search.set("date", params.date);
  if (params.query) search.set("query", params.query);
  return request(`/api/contracts/active?${search.toString()}`);
}

export async function fetchDataQualitySummary(params: {
  timeframe?: string;
  force?: boolean;
} = {}): Promise<DataQualitySummary> {
  const search = new URLSearchParams();
  search.set("timeframe", params.timeframe ?? "1m");
  if (params.force) search.set("force", "true");
  return request(`/api/data-quality/summary?${search.toString()}`);
}

export async function fetchDataQualityDates(params: {
  timeframe?: string;
  limit?: number;
  force?: boolean;
} = {}): Promise<DataQualityDateReport> {
  const search = new URLSearchParams();
  search.set("timeframe", params.timeframe ?? "1m");
  search.set("limit", `${params.limit ?? 90}`);
  if (params.force) search.set("force", "true");
  return request(`/api/data-quality/dates?${search.toString()}`);
}

export async function fetchDataQualityContract(
  instId: string,
  gapLimit = 30,
): Promise<DataQualityContractReport> {
  return request(`/api/data-quality/contracts/${encodeURIComponent(instId)}?gap_limit=${gapLimit}`);
}

export async function fetchContractKlineWindow(params: {
  instId: string;
  timeframe: string;
  date?: string;
  anchorTs?: number | null;
  before?: number;
  after?: number;
}): Promise<ContractKlineResponse> {
  const search = new URLSearchParams();
  search.set("timeframe", params.timeframe);
  if (params.date) search.set("date", params.date);
  search.set("before", `${params.before ?? 33}`);
  search.set("after", `${params.after ?? 33}`);
  if (params.anchorTs) search.set("anchor_ts", `${params.anchorTs}`);
  return request(`/api/contracts/${encodeURIComponent(params.instId)}/klines?${search.toString()}`);
}

export async function startContractUpdateDeploy(
  payload: ContractUpdatePayload = {},
): Promise<ContractUpdateStatus> {
  return request("/api/contracts/update-deploy", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function fetchContractUpdateStatus(tailChars = 12000): Promise<ContractUpdateStatus> {
  return request(`/api/contracts/update-deploy/status?tail_chars=${tailChars}`);
}

export async function fetchIndicatorValuePreview(params: {
  indicatorId: string;
  date: string;
  time?: string;
  query?: string;
  limit?: number;
}): Promise<IndicatorValuePreviewResponse> {
  const search = new URLSearchParams();
  search.set("date", params.date);
  search.set("limit", `${params.limit ?? 200}`);
  if (params.time) search.set("time", params.time);
  if (params.query) search.set("query", params.query);
  return request(`/api/indicators/${encodeURIComponent(params.indicatorId)}/preview?${search.toString()}`);
}

export async function fetchIndicators(params: {
  storagePeriod?: string;
  sourceType?: Indicator["source_type"];
  query?: string;
} = {}): Promise<IndicatorCatalogResponse> {
  const search = new URLSearchParams();
  if (params.storagePeriod && params.storagePeriod !== "all") {
    search.set("storage_period", params.storagePeriod);
  }
  if (params.sourceType) {
    search.set("source_type", params.sourceType);
  }
  if (params.query) {
    search.set("query", params.query);
  }
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return request(`/api/indicators/catalog${suffix}`);
}

export async function createIndicator(payload: IndicatorCreatePayload): Promise<Indicator> {
  return request("/api/indicators/catalog", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function updateIndicator(indicatorId: string, payload: IndicatorCreatePayload): Promise<Indicator> {
  return request(`/api/indicators/catalog/${encodeURIComponent(indicatorId)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function deleteIndicator(indicatorId: string): Promise<{ deleted: string }> {
  return request(`/api/indicators/catalog/${encodeURIComponent(indicatorId)}`, {
    method: "DELETE",
  });
}

export async function fetchScriptWorkspace(indicatorId: string): Promise<ScriptWorkspaceResponse> {
  return request(`/api/script-indicators/${encodeURIComponent(indicatorId)}/workspace`);
}

export async function generateScriptWithAi(params: {
  indicatorId: string;
  requirement: string;
  inputTimeframe: string;
}): Promise<ScriptGenerateResponse> {
  return request(`/api/script-indicators/${encodeURIComponent(params.indicatorId)}/ai-generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      requirement: params.requirement,
      input_timeframe: params.inputTimeframe,
    }),
  });
}

export async function saveScriptIndicatorScript(params: {
  indicatorId: string;
  script: string;
}): Promise<{ script: string; script_path: string }> {
  return request(`/api/script-indicators/${encodeURIComponent(params.indicatorId)}/script`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ script: params.script }),
  });
}

export async function trialRunScriptIndicator(params: {
  indicatorId: string;
  date: string;
  inputTimeframe: string;
  script: string;
  limit?: number;
}): Promise<ScriptTrialRunResponse> {
  return request(`/api/script-indicators/${encodeURIComponent(params.indicatorId)}/trial-run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      date: params.date,
      input_timeframe: params.inputTimeframe,
      script: params.script,
      limit: params.limit ?? 200,
    }),
  });
}

export async function resetIndicatorSeed(): Promise<IndicatorCatalogResponse> {
  return request("/api/indicators/catalog/reset-seed", { method: "POST" });
}

export async function fetchScreenerFavorites(): Promise<{ items: ScreenerFavorite[] }> {
  return request("/api/screener/favorites");
}

export async function createScreenerFavorite(payload: ScreenerFavoritePayload): Promise<ScreenerFavorite> {
  return request("/api/screener/favorites", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function deleteScreenerFavorite(favoriteId: string): Promise<{ deleted: string }> {
  return request(`/api/screener/favorites/${encodeURIComponent(favoriteId)}`, {
    method: "DELETE",
  });
}

export async function fetchSignalSets(): Promise<{ items: SignalSet[] }> {
  return request("/api/signal-sets");
}

export async function fetchSignalSet(signalSetId: string): Promise<SignalSet> {
  return request(`/api/signal-sets/${encodeURIComponent(signalSetId)}`);
}

export async function fetchSignalSetEvents(signalSetId: string, limit = 500): Promise<{ items: SignalEvent[] }> {
  return request(`/api/signal-sets/${encodeURIComponent(signalSetId)}/events?limit=${limit}`);
}

export async function createSignalSet(payload: SignalSetCreateRequest): Promise<SignalSet> {
  return request(
    "/api/signal-sets",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    {
      timeoutMs: 30_000,
      timeoutMessage: "异动表后台任务创建超时：超过 30 秒还没有返回，请检查后端服务是否繁忙。",
    },
  );
}

export async function fetchBacktestRuns(): Promise<{ items: BacktestRun[] }> {
  return request("/api/backtests/runs");
}

export async function fetchBacktestRun(runId: string): Promise<BacktestRun> {
  return request(`/api/backtests/runs/${encodeURIComponent(runId)}`);
}

export async function createBacktestRun(payload: BacktestRunRequest): Promise<BacktestRun> {
  return request(
    "/api/backtests/runs",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    {
      timeoutMs: 120_000,
      timeoutMessage: "回测请求超时：超过 120 秒还没有返回，请缩短日期区间。",
    },
  );
}

export async function createBacktestRunFromSignalSet(payload: SignalSetBacktestRequest): Promise<BacktestRun> {
  return request(
    "/api/backtests/runs/from-signal-set",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    {
      timeoutMs: 120_000,
      timeoutMessage: "基于异动表的回测请求超时：超过 120 秒还没有返回，请缩短区间或降低异动数量。",
    },
  );
}

export async function queryScreener(params: {
  timeframe: string;
  date?: string;
  asOf?: string;
  minRet15m?: string;
  minVolRatio60?: string;
  minVolQuote15m?: string;
  sortBy?: string;
  metadataFilters?: ScreenerMetadataFilterPayload[];
}): Promise<ScreenerResponse> {
  const search = new URLSearchParams();
  search.set("timeframe", params.timeframe);
  if (params.date) search.set("date", params.date);
  if (params.asOf) search.set("as_of", params.asOf);
  if (params.minRet15m) search.set("min_ret_15m", params.minRet15m);
  if (params.minVolRatio60) search.set("min_vol_ratio_60", params.minVolRatio60);
  if (params.minVolQuote15m) search.set("min_vol_quote_15m", params.minVolQuote15m);
  if (params.sortBy) search.set("sort_by", params.sortBy);
  if (params.metadataFilters?.length) {
    search.set("metadata_filters", JSON.stringify(params.metadataFilters));
  }
  search.set("limit", "200");
  return request(`/api/screener/query?${search.toString()}`, undefined, {
    timeoutMs: 45_000,
    timeoutMessage: "选币接口请求超时：超过 45 秒还没有返回，请检查脚本指标是否过慢或数据量过大。",
  });
}

export async function fetchScreenerTimeCounts(params: {
  timeframe: string;
  date?: string;
  minRet15m?: string;
  minVolRatio60?: string;
  minVolQuote15m?: string;
  sortBy?: string;
  metadataFilters?: ScreenerMetadataFilterPayload[];
}): Promise<ScreenerTimeCountsResponse> {
  const search = new URLSearchParams();
  search.set("timeframe", params.timeframe);
  if (params.date) search.set("date", params.date);
  if (params.minRet15m) search.set("min_ret_15m", params.minRet15m);
  if (params.minVolRatio60) search.set("min_vol_ratio_60", params.minVolRatio60);
  if (params.minVolQuote15m) search.set("min_vol_quote_15m", params.minVolQuote15m);
  if (params.sortBy) search.set("sort_by", params.sortBy);
  if (params.metadataFilters?.length) {
    search.set("metadata_filters", JSON.stringify(params.metadataFilters));
  }
  return request(`/api/screener/time-counts?${search.toString()}`, undefined, {
    timeoutMs: 90_000,
    timeoutMessage: "整点命中数请求超时：超过 90 秒还没有返回，请检查脚本指标是否过慢。",
  });
}

type RequestOptions = {
  timeoutMs?: number;
  timeoutMessage?: string;
};

async function request<T>(path: string, init?: RequestInit, options: RequestOptions = {}): Promise<T> {
  const controller = options.timeoutMs ? new AbortController() : null;
  let timer: ReturnType<typeof setTimeout> | null = null;

  if (controller && options.timeoutMs) {
    timer = setTimeout(() => controller.abort(), options.timeoutMs);
    if (init?.signal) {
      if (init.signal.aborted) {
        controller.abort();
      } else {
        init.signal.addEventListener("abort", () => controller.abort(), { once: true });
      }
    }
  }

  try {
    const response = await fetch(`${API_BASE}${path}`, {
      cache: "no-store",
      ...init,
      signal: controller?.signal ?? init?.signal,
    });
    if (!response.ok) {
      const text = await response.text();
      throw new Error(apiErrorMessage(text, response.status));
    }
    return response.json() as Promise<T>;
  } catch (err) {
    if (err instanceof Error && err.name === "AbortError") {
      throw new Error(options.timeoutMessage || "请求超时，请稍后重试。");
    }
    throw err;
  } finally {
    if (timer) {
      clearTimeout(timer);
    }
  }
}

function apiErrorMessage(text: string, status: number) {
  if (!text) return `Request failed: ${status}`;
  try {
    const payload = JSON.parse(text) as { detail?: unknown; message?: unknown };
    if (typeof payload.detail === "string") return payload.detail;
    if (Array.isArray(payload.detail)) return payload.detail.map(String).join("；");
    if (typeof payload.message === "string") return payload.message;
  } catch {
    // Plain-text error body.
  }
  return text;
}
