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
  source_type: "raw" | "manual" | "computed";
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

export type IndicatorValuePreviewResponse = {
  indicator: Indicator;
  date: string;
  time: string;
  field?: string;
  total_files?: number;
  returned_count?: number;
  message?: string;
  rows: Array<{
    inst_id: string;
    value: string;
    ts?: string;
    time?: string | null;
  }>;
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
  query?: string;
} = {}): Promise<IndicatorCatalogResponse> {
  const search = new URLSearchParams();
  if (params.storagePeriod && params.storagePeriod !== "all") {
    search.set("storage_period", params.storagePeriod);
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

export async function resetIndicatorSeed(): Promise<IndicatorCatalogResponse> {
  return request("/api/indicators/catalog/reset-seed", { method: "POST" });
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
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}
