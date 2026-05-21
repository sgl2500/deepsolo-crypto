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

export type ScreenerMetadataFilterPayload = {
  indicator_id: string;
  operator: string;
  value: string;
  time_mode?: string;
  time_offset?: string;
  time_point?: string;
  truncate_mode?: string;
  truncate_count?: string;
  external_relation?: boolean;
  time_range?: boolean;
  exclude?: boolean;
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
  time_point: string;
  operator: string;
  value: string;
  truncate_mode: string;
  truncate_count: string;
  external_relation: boolean;
  time_range: boolean;
  exclude: boolean;
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

export async function fetchContractKlineWindow(params: {
  instId: string;
  timeframe: string;
  date: string;
  anchorTs?: number | null;
  before?: number;
  after?: number;
}): Promise<ContractKlineResponse> {
  const search = new URLSearchParams();
  search.set("timeframe", params.timeframe);
  search.set("date", params.date);
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
  return request(`/api/screener/query?${search.toString()}`);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { cache: "no-store", ...init });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}
