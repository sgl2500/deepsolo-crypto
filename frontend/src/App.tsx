import { useEffect, useMemo, useRef, useState } from "react";
import ConfigProvider from "antd/es/config-provider";
import Table from "antd/es/table";
import type { ColumnsType } from "antd/es/table";
import {
  BacktestRun,
  BacktestTrade,
  ContractListResponse,
  ContractKlineResponse,
  ContractKlineRow,
  ContractUpdateStatus,
  DataQualityContractReport,
  DataQualityDateReport,
  DataQualitySummary,
  DataSummary,
  Indicator,
  IndicatorCatalogResponse,
  ScreenerFavorite,
  ScreenerFavoriteCondition,
  SignalEvent,
  SignalSet,
  ScriptTrialRunResponse,
  ScriptWorkspaceResponse,
  ScreenerMetadataFilterPayload,
  ScreenerResponse,
  ScreenerRow,
  ScreenerTimeCountItem,
  createBacktestRunFromSignalSet,
  createScreenerFavorite,
  createSignalSet,
  TimeframeSummary,
  createIndicator,
  deleteIndicator,
  deleteScreenerFavorite,
  fetchActiveContracts,
  fetchBacktestRun,
  fetchBacktestRuns,
  fetchContractKlineWindow,
  fetchContractUpdateStatus,
  fetchDataQualityContract,
  fetchDataQualityDates,
  fetchDataQualitySummary,
  fetchIndicatorValuePreview,
  fetchIndicators,
  fetchScreenerFavorites,
  fetchSignalSet,
  fetchSignalSetEvents,
  fetchSignalSets,
  fetchScriptWorkspace,
  fetchScreenerTimeCounts,
  fetchSummary,
  generateScriptWithAi,
  queryScreener,
  saveScriptIndicatorScript,
  startContractUpdateDeploy,
  trialRunScriptIndicator,
  updateIndicator,
} from "./api";

const navItems = ["选币查询", "回测验证", "合约列表", "指标生产", "指标仓库"];
const timeframeLabels: Record<string, string> = {
  "1m": "1分钟",
  "5m": "5分钟",
  "15m": "15分钟",
  "1H": "1小时",
  "1D": "日线",
};
const klinePeriodOptions = [
  { value: "1D", label: "日" },
  { value: "1H", label: "1小时" },
  { value: "5m", label: "5分钟" },
  { value: "1m", label: "1分钟" },
];
const backtestSignalTimeframeOptions = [
  { value: "1H", label: "1小时扫描" },
];
const backtestEntryTimeframeOptions = [
  { value: "1m", label: "1分钟成交" },
  { value: "5m", label: "5分钟成交" },
  { value: "1H", label: "1小时成交" },
];
const backtestSignalModeOptions = [
  { value: "each_bar_close", label: "逐根K线扫描" },
];

const metadataOperatorOptions = [
  { value: "any", label: "任意" },
  { value: "any_empty", label: "任意为空" },
  { value: "any_not_empty", label: "任意不为空" },
  { value: "gt", label: "大于" },
  { value: "gte", label: "大于等于" },
  { value: "lt", label: "小于" },
  { value: "lte", label: "小于等于" },
  { value: "eq", label: "等于" },
  { value: "ne", label: "不等于" },
  { value: "contains", label: "包含" },
];
const defaultMetadataOperator = "any_not_empty";

type MetadataConditionDraft = {
  indicatorId: string;
  timeMode: string;
  timeOffset: string;
  timePointMode: string;
  timePoint: string;
  barOffset: string;
  timeOffsetValue: string;
  timeOffsetUnit: string;
  operator: string;
  value: string;
  truncateMode: string;
  truncateCount: string;
  externalRelation: boolean;
  timeRange: boolean;
  exclude: boolean;
  matchCurrentBar: boolean;
};

type MetadataCondition = MetadataConditionDraft & {
  id: string;
  indicator: Indicator;
};

type ScreenerTableRow = ScreenerRow & {
  key: string;
  rowIndex: number;
};

type KlineTarget = {
  instId: string;
  anchorTs?: number | null;
  baselineTs?: number | null;
  baselineTime?: string | null;
};

type KlineTradeMarker = {
  side: "buy" | "sell";
  ts: number;
  price: number;
  label: string;
  time: string;
};

export default function App() {
  const [summary, setSummary] = useState<DataSummary | null>(null);
  const [timeframe, setTimeframe] = useState("1m");
  const [date, setDate] = useState("");
  const [minRet15m, setMinRet15m] = useState("");
  const [minVolRatio60, setMinVolRatio60] = useState("");
  const [minVolQuote15m, setMinVolQuote15m] = useState("");
  const [sortBy, setSortBy] = useState("ret_15m");
  const [result, setResult] = useState<ScreenerResponse | null>(null);
  const [activePage, setActivePage] = useState("选币查询");
  const [favorites, setFavorites] = useState<ScreenerFavorite[]>([]);
  const [favoritesOpen, setFavoritesOpen] = useState(false);
  const [favoriteLoading, setFavoriteLoading] = useState(false);
  const [favoriteSaving, setFavoriteSaving] = useState(false);
  const [favoriteError, setFavoriteError] = useState<string | null>(null);
  const [favoriteNotice, setFavoriteNotice] = useState<string | null>(null);
  const [klineTarget, setKlineTarget] = useState<KlineTarget | null>(null);
  const [klinePeriod, setKlinePeriod] = useState("1D");
  const [klineData, setKlineData] = useState<ContractKlineResponse | null>(null);
  const [klineLoading, setKlineLoading] = useState(false);
  const [klineError, setKlineError] = useState<string | null>(null);
  const [metadataConditions, setMetadataConditions] = useState<MetadataCondition[]>([]);
  const [conditionModalOpen, setConditionModalOpen] = useState(false);
  const [editingCondition, setEditingCondition] = useState<MetadataCondition | null>(null);
  const [tableSearch, setTableSearch] = useState("");
  const [asOfTime, setAsOfTime] = useState("00:00");
  const [baselineTimeCounts, setBaselineTimeCounts] = useState<ScreenerTimeCountItem[]>([]);
  const [baselineCountsLoading, setBaselineCountsLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [querying, setQuerying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timeStripRef = useRef<HTMLDivElement | null>(null);
  const queryRunRef = useRef(0);
  const baselineCountsRunRef = useRef(0);

  useEffect(() => {
    void loadSummary();
    void loadFavorites();
  }, []);

  useEffect(() => {
    const current = currentTimeframe(summary, timeframe);
    if (current) {
      const currentDateStillAvailable = current.dates.some((item) => item.date === date);
      if (!currentDateStillAvailable) {
        setDate(preferredQueryDate(current));
      }
    }
  }, [summary, timeframe, date]);

  useEffect(() => {
    setAsOfTime((current) => normalizeBaselineTimeForPeriod(timeframe, current));
  }, [timeframe]);

  useEffect(() => {
    if (date && metadataConditions.length > 0) {
      void runQuery();
    } else {
      queryRunRef.current += 1;
      setQuerying(false);
      setResult(null);
    }
  }, [date, timeframe, metadataConditions, sortBy, asOfTime]);

  const tfSummary = currentTimeframe(summary, timeframe);
  const dates = useMemo(() => tfSummary?.dates.slice().reverse() ?? [], [tfSummary]);
  const rows = result?.rows ?? [];
  const queryTimedOut = isTimeoutMessage(error);
  const normalizedAsOfTime = normalizeBaselineTimeForPeriod(timeframe, asOfTime);
  const asOfTimeError = metadataTimePointError(timeframe, normalizedAsOfTime);
  const asOfDisplayLabel = result?.as_of_label ?? (date ? `${date} ${normalizedAsOfTime}` : "--");
  const valueConditions = useMemo(
    () => uniqueValueConditions(metadataConditions, date, dates, normalizedAsOfTime),
    [metadataConditions, date, dates, normalizedAsOfTime],
  );

  useEffect(() => {
    if (!date || metadataConditions.length === 0) {
      baselineCountsRunRef.current += 1;
      setBaselineTimeCounts([]);
      setBaselineCountsLoading(false);
      return;
    }
    void loadBaselineTimeCounts();
  }, [date, timeframe, metadataConditions, minRet15m, minVolRatio60, minVolQuote15m, sortBy]);

  const visibleRows = useMemo(() => {
    const needle = tableSearch.trim().toLowerCase();
    if (!needle) return rows;
    return rows.filter((row) => row.inst_id.toLowerCase().includes(needle));
  }, [rows, tableSearch]);
  const tableRows = useMemo<ScreenerTableRow[]>(
    () => visibleRows.map((row, index) => ({ ...row, key: row.inst_id, rowIndex: index + 1 })),
    [visibleRows],
  );
  const tableColumns = useMemo<ColumnsType<ScreenerTableRow>>(
    () => [
      {
        title: <TableColumnHead title="序号" />,
        dataIndex: "rowIndex",
        key: "rowIndex",
        fixed: "left",
        width: 72,
        align: "center",
        render: (value: number) => <span className="pro-index-cell">{value}</span>,
      },
      {
        title: <TableColumnHead title="合约" />,
        dataIndex: "inst_id",
        key: "inst_id",
        fixed: "left",
        width: 250,
        align: "center",
        render: (value: string, row: ScreenerTableRow) => (
          <span className="symbol-with-kline">
            <span className="pro-symbol-cell">{value}</span>
            <button
              className="kline-icon-button"
              title="查看基准时间前后各33根K线"
              onClick={(event) => {
                event.stopPropagation();
                void openKlineWindow(row);
              }}
            >
              K
            </button>
          </span>
        ),
      },
      ...valueConditions.map((condition) => {
        const columnValueKey = valueConditionKey(condition, date, dates, normalizedAsOfTime);
        return {
          title: (
            <TableColumnHead
              title={condition.indicator.name_zh}
              subtitle={conditionTimeSubtitle(condition, date, dates, normalizedAsOfTime)}
              sortable
            />
          ),
          key: columnValueKey,
          width: 240,
          align: "center" as const,
          render: (_: unknown, row: ScreenerTableRow) => (
            <FilterValueCell row={row} condition={condition} valueKey={columnValueKey} />
          ),
        };
      }),
    ],
    [normalizedAsOfTime, date, dates, valueConditions, timeframe],
  );
  const selectedDateIndex = dates.findIndex((item) => item.date === date);
  const previousDate = selectedDateIndex >= 0 ? dates[selectedDateIndex + 1] : undefined;
  const nextDate = selectedDateIndex > 0 ? dates[selectedDateIndex - 1] : undefined;

  async function loadSummary(force = false) {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchSummary(force);
      setSummary(data);
      const first = data.timeframes.find((item) => item.key === timeframe) ?? data.timeframes[0];
      if (first) {
        setTimeframe(first.key);
        setDate(preferredQueryDate(first));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "数据源扫描失败");
    } finally {
      setLoading(false);
    }
  }

  async function loadFavorites() {
    setFavoriteLoading(true);
    setFavoriteError(null);
    try {
      const data = await fetchScreenerFavorites();
      setFavorites(data.items);
    } catch (err) {
      setFavoriteError(err instanceof Error ? err.message : "收藏列表加载失败");
    } finally {
      setFavoriteLoading(false);
    }
  }

  async function saveCurrentFavorite() {
    if (metadataConditions.length === 0) {
      setFavoriteError("请先添加筛选条件，再收藏这组条件。");
      setFavoriteNotice(null);
      setFavoritesOpen(true);
      return;
    }

    setFavoriteSaving(true);
    setFavoriteError(null);
    setFavoriteNotice(null);
    try {
      const favorite = await createScreenerFavorite({
        name: favoriteName(metadataConditions, date, normalizedAsOfTime),
        timeframe,
        date: date || null,
        as_of_time: normalizedAsOfTime,
        min_ret_15m: minRet15m,
        min_vol_ratio_60: minVolRatio60,
        min_vol_quote_15m: minVolQuote15m,
        sort_by: sortBy,
        metadata_conditions: metadataConditions.map(toFavoriteCondition),
      });
      setFavorites((current) => [favorite, ...current.filter((item) => item.id !== favorite.id)]);
      setFavoriteNotice(`已收藏：${favorite.name}`);
      setFavoritesOpen(true);
    } catch (err) {
      setFavoriteError(err instanceof Error ? err.message : "收藏条件保存失败");
    } finally {
      setFavoriteSaving(false);
    }
  }

  function applyFavorite(favorite: ScreenerFavorite) {
    const restoredConditions = favorite.metadata_conditions
      .map(fromFavoriteCondition)
      .filter((condition): condition is MetadataCondition => Boolean(condition));
    setTimeframe(favorite.timeframe || timeframe);
    if (favorite.date) setDate(favorite.date);
    setAsOfTime(normalizeBaselineTimeForPeriod(favorite.timeframe || timeframe, favorite.as_of_time ?? "00:00"));
    setMinRet15m(favorite.min_ret_15m ?? "");
    setMinVolRatio60(favorite.min_vol_ratio_60 ?? "");
    setMinVolQuote15m(favorite.min_vol_quote_15m ?? "");
    setSortBy(favorite.sort_by ?? "ret_15m");
    setMetadataConditions(restoredConditions);
    setFavoriteNotice(null);
    setFavoriteError(null);
    setFavoritesOpen(false);
  }

  async function removeFavorite(favoriteId: string) {
    setFavoriteError(null);
    try {
      await deleteScreenerFavorite(favoriteId);
      setFavorites((current) => current.filter((item) => item.id !== favoriteId));
    } catch (err) {
      setFavoriteError(err instanceof Error ? err.message : "删除收藏失败");
    }
  }

  async function openKlineWindow(row: ScreenerTableRow) {
    if (!date) {
      setKlineError("请先选择基准时间。");
      return;
    }
    const target = {
      instId: row.inst_id,
      anchorTs: row.latest_ts,
      baselineTs: row.latest_ts,
      baselineTime: row.latest_time || asOfDisplayLabel,
    };
    const period = "1D";
    setKlineTarget(target);
    setKlinePeriod(period);
    await loadKlineWindow(target, period);
  }

  async function changeKlinePeriod(period: string) {
    if (!klineTarget) return;
    setKlinePeriod(period);
    await loadKlineWindow(klineTarget, period);
  }

  async function loadKlineWindow(target: KlineTarget, period: string) {
    if (!date) return;
    setKlineData(null);
    setKlineLoading(true);
    setKlineError(null);
    try {
      const data = await fetchContractKlineWindow({
        instId: target.instId,
        timeframe: period,
        date: result?.date || date,
        anchorTs: klineRequestAnchorTs(target, period),
        before: 33,
        after: 33,
      });
      setKlineData(data);
    } catch (err) {
      setKlineError(err instanceof Error ? err.message : "K线数据加载失败");
    } finally {
      setKlineLoading(false);
    }
  }

  async function runQuery() {
    if (!date) return;
    if (metadataConditions.length === 0) {
      queryRunRef.current += 1;
      setQuerying(false);
      setResult(null);
      return;
    }
    if (asOfTimeError) {
      queryRunRef.current += 1;
      setQuerying(false);
      setResult(null);
      setError(asOfTimeError);
      return;
    }
    const runId = queryRunRef.current + 1;
    queryRunRef.current = runId;
    setQuerying(true);
    setError(null);
    setResult(null);
    try {
      const data = await queryScreener({
        timeframe,
        date,
        asOf: date ? `${date}T${normalizedAsOfTime}:00` : undefined,
        minRet15m,
        minVolRatio60,
        minVolQuote15m,
        sortBy,
        metadataFilters: metadataConditions.map(toMetadataFilterPayload),
      });
      if (runId !== queryRunRef.current) return;
      setResult(data);
    } catch (err) {
      if (runId !== queryRunRef.current) return;
      setError(err instanceof Error ? err.message : "选币查询失败");
    } finally {
      if (runId === queryRunRef.current) {
        setQuerying(false);
      }
    }
  }

  async function loadBaselineTimeCounts() {
    if (!date || metadataConditions.length === 0) return;
    const runId = baselineCountsRunRef.current + 1;
    baselineCountsRunRef.current = runId;
    setBaselineCountsLoading(true);
    try {
      const data = await fetchScreenerTimeCounts({
        timeframe,
        date,
        minRet15m,
        minVolRatio60,
        minVolQuote15m,
        sortBy,
        metadataFilters: metadataConditions.map(toMetadataFilterPayload),
      });
      if (runId !== baselineCountsRunRef.current) return;
      setBaselineTimeCounts(data.items);
    } catch (err) {
      if (runId !== baselineCountsRunRef.current) return;
      setBaselineTimeCounts([]);
    } finally {
      if (runId === baselineCountsRunRef.current) {
        setBaselineCountsLoading(false);
      }
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">CB</span>
          <div>
            <strong>数字币选币</strong>
            <small>Local Screener Lab</small>
          </div>
        </div>
        <nav>
          {navItems.map((item, index) => (
            <button
              className={item === activePage ? "nav-item active" : "nav-item"}
              key={item}
              onClick={() => setActivePage(item)}
            >
              <span>{item}</span>
              <b>{item === "指标仓库" ? "CORE" : item === "回测验证" ? "BETA" : index === 0 ? "LIVE" : "MVP"}</b>
            </button>
          ))}
        </nav>
        <div className="source-card">
          <span>数据源</span>
          <strong>{summary?.exists ? "已连接" : "未连接"}</strong>
          <p>{summary?.root ?? "正在扫描本地 normalized_gzip"}</p>
        </div>
      </aside>

      <main className="workspace">
        {activePage === "指标仓库" ? (
          <IndicatorWarehousePage summary={summary} />
        ) : activePage === "回测验证" ? (
          <BacktestPage summary={summary} />
        ) : activePage === "合约列表" ? (
          <ContractListPage summary={summary} onSummaryRefresh={() => loadSummary(true)} />
        ) : activePage === "指标生产" ? (
          <IndicatorProductionPage summary={summary} />
        ) : (
          <>
            <section className="screener-terminal focused-screener">
              <div className="terminal-action-row minimal-actions">
                <div className="screener-action-group">
                  <button className="filter-only-button" onClick={() => {
                    setEditingCondition(null);
                    setConditionModalOpen(true);
                  }}>
                    +筛选条件
                  </button>
                  <button
                    className="favorite-save-button"
                    disabled={favoriteSaving || metadataConditions.length === 0}
                    onClick={() => void saveCurrentFavorite()}
                  >
                    {favoriteSaving ? "收藏中..." : "☆ 收藏条件"}
                  </button>
                </div>
                <div className="screener-action-group right">
                  <button className="favorite-open-button" onClick={() => {
                    setFavoritesOpen(true);
                    void loadFavorites();
                  }}>
                    收藏夹 <b>{favorites.length}</b>
                  </button>
                  <button className="page-refresh-button" onClick={() => { void loadSummary(true); void runQuery(); }}>
                    ↻ 页面刷新
                  </button>
                </div>
              </div>
              {(favoriteNotice || favoriteError) && (
                <div className={favoriteError ? "favorite-message error" : "favorite-message"}>
                  {favoriteError || favoriteNotice}
                </div>
              )}

              <div className="terminal-condition-grid focused-conditions">
                {metadataConditions.length === 0 ? (
                  <button className="condition-add-card" onClick={() => {
                    setEditingCondition(null);
                    setConditionModalOpen(true);
                  }}>
                    <strong>请先添加筛选条件</strong>
                    <span>未设置条件时不展示全量合约；添加后会自动按组合条件查询。</span>
                  </button>
                ) : (
                  metadataConditions.map((condition, index) => (
                    <CompactConditionChip
                      key={condition.id}
                      condition={condition}
                      index={index + 1}
                      hitCount={result?.condition_stats[`metadata_${index + 1}_${condition.indicator.id}`]}
                      onEdit={() => {
                        setEditingCondition(condition);
                        setConditionModalOpen(true);
                      }}
                      onRemove={() =>
                        setMetadataConditions((current) => current.filter((item) => item.id !== condition.id))
                      }
                    />
                  ))
                )}
              </div>

              <div className="terminal-query-row focused-date-row" ref={timeStripRef}>
                <div className="selected-total">
                  <span>{querying ? "查询中" : "选出"}</span>
                  <strong>{querying ? "..." : result?.matched_count ?? 0}</strong>
                  {!querying && result && <em>{result.duration_ms}ms</em>}
                </div>
                <div className="date-switcher compact-date-switcher">
                  <button disabled={!previousDate} onClick={() => previousDate && setDate(previousDate.date)}>‹</button>
                  {previousDate && (
                    <button className="date-item" onClick={() => setDate(previousDate.date)}>
                      <b>{formatDateBadge(previousDate.date)}</b>
                      <span>{weekdayLabel(previousDate.date)}</span>
                    </button>
                  )}
                  <button className="date-item current">
                    <b>{formatDateBadge(date) || "--"}</b>
                    <span>{weekdayLabel(date) || "今天"}</span>
                  </button>
                  {nextDate && (
                    <button className="date-item" onClick={() => setDate(nextDate.date)}>
                      <b>{formatDateBadge(nextDate.date)}</b>
                      <span>{weekdayLabel(nextDate.date)}</span>
                    </button>
                  )}
                  <button disabled={!nextDate} onClick={() => nextDate && setDate(nextDate.date)}>›</button>
                </div>
                <BaselineHourStrip
                  value={normalizedAsOfTime}
                  timeframe={timeframe}
                  counts={baselineTimeCounts}
                  loading={baselineCountsLoading}
                  onChange={setAsOfTime}
                />
              </div>

              <section className="terminal-table-panel focused-table-panel">
                {loading ? (
                  <EmptyState title="正在扫描数据源" text="读取本地 normalized_gzip 分区和合约覆盖。" />
                ) : querying ? (
                  <EmptyState title="正在查询选币结果" text="正在运行组合条件和脚本指标；成功返回后显示命中数量，接口或脚本超时会显示明确错误。" />
                ) : error ? (
                  <EmptyState title={queryTimedOut ? "接口请求超时" : "查询失败"} text={error} />
                ) : metadataConditions.length === 0 ? (
                  <EmptyState title="等待筛选条件" text="点击上方「+筛选条件」选择元数据；未设置条件时不会默认展示全部合约。" />
                ) : result === null ? (
                  <EmptyState title="等待查询结果" text="条件添加后会自动查询，也可以点击右上角页面刷新。" />
                ) : rows.length === 0 ? (
                  <EmptyState title="暂无命中合约" text={`选币接口已正常返回，${date || "当前日期"} 没有合约满足组合筛选条件；本次耗时 ${result.duration_ms}ms。`} />
                ) : (
                  <ConfigProvider
                    theme={{
                      token: {
                        colorPrimary: "#2f80ed",
                        colorText: "#4f5968",
                        fontFamily: '"Avenir Next", "PingFang SC", "Hiragino Sans GB", sans-serif',
                        borderRadius: 0,
                      },
                      components: {
                        Table: {
                          cellFontSize: 16,
                          cellPaddingBlock: 0,
                          cellPaddingInline: 16,
                          headerBg: "#fbfbfc",
                          headerColor: "#1f242c",
                          rowHoverBg: "#eaf8ff",
                        },
                      },
                    }}
                  >
                    <Table<ScreenerTableRow>
                      bordered
                      className="screener-pro-table"
                      columns={tableColumns}
                      dataSource={tableRows}
                      pagination={false}
                      rowClassName={(_, index) =>
                        index === 0 ? "pro-row-highlight" : index % 2 === 1 ? "pro-row-even" : ""
                      }
                      scroll={{ x: "max-content", y: "calc(100vh - 412px)" }}
                      size="middle"
                      sticky
                    />
                  </ConfigProvider>
                )}
                <div className="terminal-table-footer focused-footer">
                  <span>选币基准时间 <b>{asOfDisplayLabel}</b></span>
                  <span>共{visibleRows.length}条</span>
                </div>
              </section>
            </section>
            {conditionModalOpen && (
              <MetadataConditionModal
                timeframe={timeframe}
                initialCondition={editingCondition}
                onClose={() => {
                  setConditionModalOpen(false);
                  setEditingCondition(null);
                }}
                onOpenWarehouse={() => {
                  setConditionModalOpen(false);
                  setEditingCondition(null);
                  setActivePage("指标仓库");
                }}
                onApply={(condition) => {
                  setMetadataConditions((current) =>
                    editingCondition
                      ? current.map((item) => (item.id === editingCondition.id ? condition : item))
                      : [...current, condition],
                  );
                  setConditionModalOpen(false);
                  setEditingCondition(null);
                }}
              />
            )}
            {favoritesOpen && (
              <ScreenerFavoritesModal
                favorites={favorites}
                loading={favoriteLoading}
                error={favoriteError}
                onClose={() => setFavoritesOpen(false)}
                onRefresh={() => void loadFavorites()}
                onApply={applyFavorite}
                onDelete={(favoriteId) => void removeFavorite(favoriteId)}
              />
            )}
            {klineTarget && (
              <ContractKlineModal
                target={klineTarget}
                activePeriod={klinePeriod}
                data={klineData}
                loading={klineLoading}
                error={klineError}
                onPeriodChange={(period) => void changeKlinePeriod(period)}
                onClose={() => {
                  setKlineTarget(null);
                  setKlineData(null);
                  setKlineError(null);
                }}
              />
            )}
          </>
        )}
      </main>
    </div>
  );
}

function TableColumnHead({
  title,
  subtitle,
  sortable = false,
}: {
  title: string;
  subtitle?: string;
  sortable?: boolean;
}) {
  return (
    <div className="pro-table-head">
      <div>
        <strong>{title}</strong>
        {subtitle && <span>{subtitle}</span>}
      </div>
      {sortable && <i aria-hidden="true" />}
    </div>
  );
}

function BaselineHourStrip({
  value,
  timeframe,
  counts,
  loading,
  onChange,
}: {
  value: string;
  timeframe: string;
  counts: ScreenerTimeCountItem[];
  loading: boolean;
  onChange: (value: string) => void;
}) {
  const normalized = normalizeBaselineTimeForPeriod(timeframe, value);
  const [activeHour] = baselineTimeParts(normalized);
  const hours = baselineHourOptions(timeframe);
  const countsByTime = new Map(counts.map((item) => [item.time, item]));

  return (
    <div className="baseline-hour-control">
      <div className="baseline-hour-strip" role="list" aria-label="选择整点基准时间">
        {hours.map((hour) => {
          const timeText = formatTimeParts(hour, 0);
          const item = countsByTime.get(timeText);
          const count = item?.matched_count;
          const countLabel = loading ? "..." : typeof count === "number" ? String(count) : "--";
          const className = [
            "baseline-hour-item",
            hour === activeHour ? "active" : "",
            typeof count === "number" && count > 0 ? "has-hit" : "",
          ].filter(Boolean).join(" ");
          return (
            <button
              type="button"
              role="listitem"
              key={timeText}
              className={className}
              title={`${timeText} 选出 ${countLabel} 个合约`}
              onClick={() => onChange(timeText)}
            >
              <b>{timeText}</b>
              <span>{countLabel}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function CompactConditionChip({
  condition,
  index,
  hitCount,
  onEdit,
  onRemove,
}: {
  condition: MetadataCondition;
  index: number;
  hitCount?: number;
  onEdit: () => void;
  onRemove: () => void;
}) {
  return (
    <button className="compact-condition-chip" onClick={onEdit}>
      <div className="chip-actions">
        <span>条件{index}</span>
        <em
          onClick={(event) => {
            event.stopPropagation();
            onRemove();
          }}
        >
          ×
        </em>
      </div>
      <p>{condition.indicator.name_zh}{condition.exclude ? " 不满足 " : " "}{metadataConditionText(condition)}</p>
      <strong>({hitCount === undefined ? "--" : hitCount})</strong>
    </button>
  );
}

function FilterValueCell({
  row,
  condition,
  valueKey,
}: {
  row: ScreenerRow;
  condition: MetadataCondition;
  valueKey: string;
}) {
  const rawValue = row.metadata_values?.[valueKey] ?? row.metadata_values?.[condition.indicator.id] ?? "";
  return (
    <div className="filter-value-cell single-value">
      <span>
        <b>{formatPreviewValue(rawValue, condition.indicator)}</b>
      </span>
    </div>
  );
}

function ScreenerFavoritesModal({
  favorites,
  loading,
  error,
  onClose,
  onRefresh,
  onApply,
  onDelete,
}: {
  favorites: ScreenerFavorite[];
  loading: boolean;
  error: string | null;
  onClose: () => void;
  onRefresh: () => void;
  onApply: (favorite: ScreenerFavorite) => void;
  onDelete: (favoriteId: string) => void;
}) {
  return (
    <div className="modal-backdrop favorite-backdrop" role="presentation" onMouseDown={onClose}>
      <div className="favorite-modal" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}>
        <div className="modal-head favorite-modal-head">
          <div>
            <span className="eyebrow">SQLite 收藏夹</span>
            <h2>收藏的选币条件</h2>
          </div>
          <div className="favorite-head-actions">
            <button className="secondary-action" onClick={onRefresh}>刷新</button>
            <button className="close-button" onClick={onClose}>×</button>
          </div>
        </div>

        {error && <div className="inline-error favorite-modal-error">{error}</div>}

        <div className="favorite-list">
          {loading ? (
            <EmptyState title="正在读取收藏" text="从后端 SQLite 数据库加载选币条件。" />
          ) : favorites.length === 0 ? (
            <EmptyState title="还没有收藏" text="组合好筛选条件后，点击「收藏条件」保存到 SQLite。" />
          ) : (
            favorites.map((favorite) => (
              <article className="favorite-card" key={favorite.id}>
                <button className="favorite-apply-area" onClick={() => onApply(favorite)}>
                  <div className="favorite-card-top">
                    <strong>{favorite.name}</strong>
                    <span>{favoriteTimeframeLabel(favorite.timeframe)}</span>
                  </div>
                  <div className="favorite-card-meta">
                    <span>{favorite.condition_count} 个条件</span>
                    <span>{favorite.date ? `基准 ${formatDateBadge(favorite.date)} ${normalizeBaselineTimeForPeriod(favorite.timeframe, favorite.as_of_time ?? "00:00")}` : "不固定日期"}</span>
                    <span>更新 {formatDateTime(favorite.updated_at)}</span>
                  </div>
                  <div className="favorite-condition-preview">
                    {favorite.metadata_conditions.slice(0, 3).map((condition, index) => (
                      <em key={`${favorite.id}-${condition.indicator_id}-${index}`}>
                        {favoriteConditionText(condition)}
                      </em>
                    ))}
                    {favorite.metadata_conditions.length > 3 && <em>还有 {favorite.metadata_conditions.length - 3} 个条件...</em>}
                  </div>
                </button>
                <button className="favorite-delete-button" onClick={() => onDelete(favorite.id)}>
                  删除
                </button>
              </article>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

function ContractKlineModal({
  target,
  activePeriod,
  data,
  loading,
  error,
  markers = [],
  onPeriodChange,
  onClose,
}: {
  target: KlineTarget;
  activePeriod: string;
  data: ContractKlineResponse | null;
  loading: boolean;
  error: string | null;
  markers?: KlineTradeMarker[];
  onPeriodChange: (period: string) => void;
  onClose: () => void;
}) {
  return (
    <div className="modal-backdrop kline-backdrop" role="presentation" onMouseDown={onClose}>
      <div className="kline-modal" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}>
        <div className="modal-head kline-modal-head">
          <div>
            <span className="eyebrow">K线窗口</span>
            <h2>{target.instId}</h2>
          </div>
          <div className="kline-head-actions">
            <div className="kline-period-tabs" role="tablist" aria-label="K线周期">
              {klinePeriodOptions.map((option) => (
                <button
                  className={option.value === activePeriod ? "active" : ""}
                  disabled={loading}
                  key={option.value}
                  onClick={() => onPeriodChange(option.value)}
                >
                  {option.label}
                </button>
              ))}
            </div>
            <button className="close-button" onClick={onClose}>×</button>
          </div>
        </div>

        {loading ? (
          <EmptyState title="正在读取K线" text="默认获取基准日前后各 33 根 K 线。" />
        ) : error ? (
          <EmptyState title="K线加载失败" text={error} />
        ) : data ? (
          <>
            <div className="kline-summary-strip">
              <div>
                <span>周期</span>
                <strong>{klinePeriodLabel(data.timeframe)}</strong>
              </div>
              <div>
                <span>选币基准</span>
                <strong>{formatKlineDisplayTime(target.baselineTime) || formatKlineDisplayTime(data.anchor_time) || "--"}</strong>
              </div>
              <div>
                <span>锚定K线</span>
                <strong>{formatKlineDisplayTime(data.anchor_time) || "--"}</strong>
              </div>
              <div>
                <span>已返回</span>
                <strong>{data.returned_count} 根</strong>
              </div>
              <div>
                <span>前/后</span>
                <strong>{data.before_count}/{data.after_count}</strong>
              </div>
            </div>
            {markers.length > 0 && (
              <div className="kline-trade-legend">
                {markers.map((marker) => (
                  <span className={marker.side} key={`${marker.side}-${marker.ts}`}>
                    {marker.label} {marker.time} @{formatOptionalNumber(marker.price)}
                  </span>
                ))}
              </div>
            )}
            <KlineChart rows={data.rows} anchorIndex={data.anchor_index} markers={markers} />
          </>
        ) : (
          <EmptyState title="等待K线数据" text="点击合约旁的 K 图标加载前后 33 根 K 线。" />
        )}
      </div>
    </div>
  );
}

function KlineChart({
  rows,
  anchorIndex,
  markers = [],
}: {
  rows: ContractKlineRow[];
  anchorIndex: number;
  markers?: KlineTradeMarker[];
}) {
  const [activeIndex, setActiveIndex] = useState(anchorIndex);
  const [lockedIndex, setLockedIndex] = useState<number | null>(null);

  useEffect(() => {
    setActiveIndex(anchorIndex);
    setLockedIndex(null);
  }, [anchorIndex, rows]);

  const candles = rows.filter(hasKlineNumbers);
  if (candles.length === 0) {
    return <EmptyState title="暂无可绘制K线" text="当前返回数据缺少开高低收价格。" />;
  }

  const width = 980;
  const height = 430;
  const padding = { top: 22, right: 54, bottom: 38, left: 54 };
  const volumeHeight = 74;
  const volumeGap = 18;
  const plotWidth = width - padding.left - padding.right;
  const pricePlotHeight = height - padding.top - padding.bottom - volumeHeight - volumeGap;
  const volumeTop = padding.top + pricePlotHeight + volumeGap;
  const visibleMarkers = markers
    .map((marker) => {
      const index = klineMarkerIndex(rows, marker.ts);
      const row = index === null ? null : rows[index];
      if (index === null || !row || !hasKlineNumbers(row)) return null;
      const price = Number.isFinite(marker.price) ? marker.price : row.close;
      return { ...marker, index, price };
    })
    .filter((item): item is KlineTradeMarker & { index: number; price: number } => Boolean(item));
  const markerPrices = visibleMarkers.map((marker) => marker.price);
  const maxHigh = Math.max(...candles.map((row) => row.high), ...markerPrices);
  const minLow = Math.min(...candles.map((row) => row.low), ...markerPrices);
  const span = maxHigh - minLow || Math.max(1, maxHigh * 0.01);
  const yFor = (value: number) => padding.top + ((maxHigh - value) / span) * pricePlotHeight;
  const step = plotWidth / Math.max(1, rows.length - 1);
  const candleWidth = Math.max(4, Math.min(12, step * 0.56));
  const gridValues = [0, 0.25, 0.5, 0.75, 1].map((ratio) => maxHigh - span * ratio);
  const maxVolume = Math.max(...rows.map(klineVolumeValue), 0);
  const volumeBarWidth = Math.max(3, Math.min(12, step * 0.62));
  const volumeYFor = (value: number) =>
    volumeTop + volumeHeight - (maxVolume > 0 ? (value / maxVolume) * volumeHeight : 0);
  const activeRow = rows[activeIndex] && hasKlineNumbers(rows[activeIndex]) ? rows[activeIndex] : null;
  const activeChange = activeRow && activeRow.open !== 0 ? ((activeRow.close - activeRow.open) / activeRow.open) * 100 : null;

  return (
    <div
      className="kline-chart-shell"
      onMouseLeave={() => setActiveIndex(lockedIndex ?? anchorIndex)}
    >
      {activeRow && (
        <div className={lockedIndex === activeIndex ? "kline-hover-card locked" : "kline-hover-card"}>
          <div className="kline-hover-head">
            <strong>{activeRow.time ?? "--"}</strong>
            <span>{lockedIndex === activeIndex ? "已固定" : "悬浮查看 · 点击固定"}</span>
          </div>
          <div className="kline-hover-grid">
            <span>开 <b>{formatOptionalNumber(activeRow.open)}</b></span>
            <span>高 <b>{formatOptionalNumber(activeRow.high)}</b></span>
            <span>低 <b>{formatOptionalNumber(activeRow.low)}</b></span>
            <span>收 <b>{formatOptionalNumber(activeRow.close)}</b></span>
            <span>涨跌 <b className={activeChange !== null ? numberTone(activeChange) : ""}>{formatKlineChangePercent(activeChange)}</b></span>
            <span>量 <b>{formatCompact(klineVolumeValue(activeRow))}</b></span>
          </div>
          <em>第 {activeIndex + 1}/{rows.length} 根</em>
        </div>
      )}
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="K线图">
        <rect x="0" y="0" width={width} height={height} rx="14" />
        {gridValues.map((value) => {
          const y = yFor(value);
          return (
            <g key={value}>
              <line className="kline-grid" x1={padding.left} x2={width - padding.right} y1={y} y2={y} />
              <text className="kline-axis-text" x={width - padding.right + 10} y={y + 4}>
                {formatOptionalNumber(value)}
              </text>
            </g>
          );
        })}
        {rows.map((row, index) => {
          if (!hasKlineNumbers(row)) return null;
          const x = padding.left + index * step;
          const openY = yFor(row.open);
          const closeY = yFor(row.close);
          const highY = yFor(row.high);
          const lowY = yFor(row.low);
          const bodyY = Math.min(openY, closeY);
          const bodyHeight = Math.max(2, Math.abs(closeY - openY));
          const tone = row.close >= row.open ? "up" : "down";
          return (
            <g
              className={`kline-candle ${tone} ${index === anchorIndex ? "anchor" : ""} ${index === activeIndex ? "selected" : ""}`}
              key={`${row.ts}-${index}`}
              onClick={() => {
                setActiveIndex(index);
                setLockedIndex((current) => (current === index ? null : index));
              }}
              onMouseEnter={() => {
                if (lockedIndex === null) setActiveIndex(index);
              }}
            >
              {index === activeIndex && (
                <line className="kline-selected-line" x1={x} x2={x} y1={padding.top} y2={height - padding.bottom} />
              )}
              {index === anchorIndex && (
                <line className="kline-anchor-line" x1={x} x2={x} y1={padding.top} y2={height - padding.bottom} />
              )}
              <line x1={x} x2={x} y1={highY} y2={lowY} />
              <rect x={x - candleWidth / 2} y={bodyY} width={candleWidth} height={bodyHeight} rx="1.5" />
              <rect
                className="kline-hit-area"
                height={height - padding.top - padding.bottom}
                width={Math.max(10, step)}
                x={x - Math.max(10, step) / 2}
                y={padding.top}
              />
            </g>
          );
        })}
        <line className="kline-volume-separator" x1={padding.left} x2={width - padding.right} y1={volumeTop - 9} y2={volumeTop - 9} />
        <text className="kline-axis-text" x={padding.left} y={volumeTop - 14}>
          成交量
        </text>
        {maxVolume > 0 && (
          <text className="kline-axis-text" x={width - padding.right + 10} y={volumeTop + 4}>
            {formatCompact(maxVolume)}
          </text>
        )}
        {rows.map((row, index) => {
          if (!hasKlineNumbers(row)) return null;
          const volume = klineVolumeValue(row);
          const x = padding.left + index * step;
          const y = volumeYFor(volume);
          const tone = row.close >= row.open ? "up" : "down";
          return (
            <rect
              className={`kline-volume-bar ${tone} ${index === anchorIndex ? "anchor" : ""} ${index === activeIndex ? "selected" : ""}`}
              height={volumeTop + volumeHeight - y}
              key={`volume-${row.ts}-${index}`}
              rx="1"
              width={volumeBarWidth}
              x={x - volumeBarWidth / 2}
              y={y}
            />
          );
        })}
        {visibleMarkers.map((marker) => {
          const x = padding.left + marker.index * step;
          const y = yFor(marker.price);
          const isBuy = marker.side === "buy";
          const labelY = isBuy ? y + 26 : y - 18;
          const triangle = isBuy
            ? `${x - 7},${y + 12} ${x + 7},${y + 12} ${x},${y + 1}`
            : `${x - 7},${y - 12} ${x + 7},${y - 12} ${x},${y - 1}`;
          return (
            <g className={`kline-trade-marker ${marker.side}`} key={`${marker.side}-${marker.ts}-${marker.index}`}>
              <line x1={x} x2={x} y1={padding.top} y2={volumeTop - 12} />
              <circle cx={x} cy={y} r="4.5" />
              <polygon points={triangle} />
              <text x={x} y={labelY}>{marker.label}</text>
            </g>
          );
        })}
        <text className="kline-axis-text" x={padding.left} y={height - 12}>
          {rows[0]?.time ?? ""}
        </text>
        <text className="kline-axis-text end" x={width - padding.right} y={height - 12}>
          {rows.at(-1)?.time ?? ""}
        </text>
      </svg>
    </div>
  );
}

function AnomalyEvidenceModal({
  event,
  signalName,
  target,
  activePeriod,
  data,
  loading,
  error,
  onPeriodChange,
  onClose,
}: {
  event: SignalEvent;
  signalName: string;
  target: { instId: string; anchorTs?: number | null };
  activePeriod: string;
  data: ContractKlineResponse | null;
  loading: boolean;
  error: string | null;
  onPeriodChange: (period: string) => void;
  onClose: () => void;
}) {
  const conditions = event.matched_conditions || [];

  return (
    <div className="modal-backdrop anomaly-detail-backdrop" role="presentation" onMouseDown={onClose}>
      <div className="anomaly-detail-modal" role="dialog" aria-modal="true" onMouseDown={(mouseEvent) => mouseEvent.stopPropagation()}>
        <div className="modal-head anomaly-detail-head">
          <div>
            <span className="eyebrow">异动证据</span>
            <h2>{target.instId}</h2>
            <p>这里展示生成异动表时保存的命中条件和异动K线，方便核对这条异动是不是符合预期。</p>
          </div>
          <button className="close-button" onClick={onClose}>×</button>
        </div>

        <div className="anomaly-detail-body">
          <div className="anomaly-summary-grid">
            <div>
              <span>异动名称</span>
              <strong>{signalName}</strong>
            </div>
            <div>
              <span>异动时间</span>
              <strong>{event.signal_time ?? "--"}</strong>
            </div>
            <div>
              <span>确认时间</span>
              <strong>{event.confirm_time ?? "--"}</strong>
            </div>
            <div>
              <span>扫描周期</span>
              <strong>{klinePeriodLabel(event.timeframe)}</strong>
            </div>
            <div>
              <span>强度</span>
              <strong>{formatOptionalNumber(event.strength)}</strong>
            </div>
            <div>
              <span>交易日</span>
              <strong>{formatDateBadge(event.date) || "--"}</strong>
            </div>
          </div>

          <section className="anomaly-evidence-section">
            <div className="anomaly-section-head">
              <strong>命中条件</strong>
              <em>{conditions.length} 条</em>
            </div>
            {conditions.length === 0 ? (
              <EmptyState title="没有命中条件快照" text="这条异动没有保存 matched_conditions 字段。" />
            ) : (
              <div className="anomaly-condition-list">
                {conditions.map((condition, index) => (
                  <span key={`${condition}-${index}`}>{condition}</span>
                ))}
              </div>
            )}
          </section>

          <section className="anomaly-evidence-section anomaly-kline-section">
            <div className="anomaly-section-head anomaly-kline-head">
              <div>
                <strong>异动K线</strong>
                <em>黄色竖线为异动时间所在K线</em>
              </div>
              <div className="kline-period-tabs" role="tablist" aria-label="异动K线周期">
                {klinePeriodOptions.map((option) => (
                  <button
                    className={option.value === activePeriod ? "active" : ""}
                    disabled={loading}
                    key={option.value}
                    onClick={() => onPeriodChange(option.value)}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            </div>
            {loading ? (
              <EmptyState title="正在读取异动K线" text="默认获取异动前后各 33 根 K 线。" />
            ) : error ? (
              <EmptyState title="异动K线加载失败" text={error} />
            ) : data ? (
              <>
                <div className="kline-summary-strip anomaly-kline-summary">
                  <div>
                    <span>周期</span>
                    <strong>{klinePeriodLabel(data.timeframe)}</strong>
                  </div>
                  <div>
                    <span>基准日期</span>
                    <strong>{formatDateBadge(data.date)}</strong>
                  </div>
                  <div>
                    <span>基准K线</span>
                    <strong>{data.anchor_time ?? "--"}</strong>
                  </div>
                  <div>
                    <span>已返回</span>
                    <strong>{data.returned_count} 根</strong>
                  </div>
                  <div>
                    <span>前/后</span>
                    <strong>{data.before_count}/{data.after_count}</strong>
                  </div>
                </div>
                <KlineChart rows={data.rows} anchorIndex={data.anchor_index} />
              </>
            ) : (
              <EmptyState title="等待异动K线" text="打开异动详情后会自动加载异动时间附近的K线。" />
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

function BacktestPage({ summary }: { summary: DataSummary | null }) {
  const initialRange = suggestedBacktestRange(summary, "1H", "each_bar_close");
  const [favorites, setFavorites] = useState<ScreenerFavorite[]>([]);
  const [signalSets, setSignalSets] = useState<SignalSet[]>([]);
  const [signalEvents, setSignalEvents] = useState<SignalEvent[]>([]);
  const [runs, setRuns] = useState<BacktestRun[]>([]);
  const [activeRun, setActiveRun] = useState<BacktestRun | null>(null);
  const [form, setForm] = useState({
    favoriteId: "",
    signalSetId: "",
    signalSetName: "",
    backtestName: "",
    startDate: initialRange.start,
    endDate: initialRange.end,
    signalTimeframe: "1H",
    signalMode: "each_bar_close",
    side: "short",
    entryTimeframe: "5m",
    entryRule: "consecutive_green_bars",
    entryWindowMinutes: "60",
    entryConsecutiveBars: "2",
    entryMinGainPctEach: "2",
    exitHoldMinutes: "440",
    stopLossPct: "15",
    stopModel: "bot_like_checkpoint",
    positionUsdt: "500",
    leverage: "1",
    maxPositions: "2",
    feeBps: "5",
    slippageBps: "5",
  });
  const [loadingFavorites, setLoadingFavorites] = useState(true);
  const [loadingSignalSets, setLoadingSignalSets] = useState(true);
  const [loadingEvents, setLoadingEvents] = useState(false);
  const [generatingSignalSet, setGeneratingSignalSet] = useState(false);
  const [running, setRunning] = useState(false);
  const [loadingRun, setLoadingRun] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [klineTarget, setKlineTarget] = useState<{ instId: string; anchorTs?: number | null } | null>(null);
  const [klinePeriod, setKlinePeriod] = useState("1m");
  const [klineData, setKlineData] = useState<ContractKlineResponse | null>(null);
  const [klineLoading, setKlineLoading] = useState(false);
  const [klineError, setKlineError] = useState<string | null>(null);
  const [klineMarkers, setKlineMarkers] = useState<KlineTradeMarker[]>([]);
  const [selectedAnomaly, setSelectedAnomaly] = useState<SignalEvent | null>(null);

  useEffect(() => {
    void loadFavorites();
    void loadSignalSets();
    void loadRuns();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const nextRange = suggestedBacktestRange(summary, form.signalTimeframe, form.signalMode);
    setForm((current) => ({
      ...current,
      startDate: current.startDate || nextRange.start,
      endDate: current.endDate || nextRange.end,
    }));
  }, [summary, form.signalTimeframe, form.signalMode]);

  useEffect(() => {
    if (form.signalSetId) {
      void loadSignalEvents(form.signalSetId);
    } else {
      setSignalEvents([]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.signalSetId]);

  useEffect(() => {
    if (!form.favoriteId || signalSets.length === 0) return;
    const currentSignalSet = signalSets.find((item) => item.id === form.signalSetId);
    if (currentSignalSet?.favorite_id === form.favoriteId) return;
    const latestForFavorite = signalSets.find((item) => item.favorite_id === form.favoriteId);
    setForm((current) => ({
      ...current,
      signalSetId: latestForFavorite?.id ?? "",
    }));
  }, [form.favoriteId, form.signalSetId, signalSets]);

  async function loadFavorites() {
    setLoadingFavorites(true);
    setError(null);
    try {
      const data = await fetchScreenerFavorites();
      setFavorites(data.items);
      setForm((current) => ({
        ...current,
        favoriteId: current.favoriteId || data.items[0]?.id || "",
      }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "收藏条件加载失败");
    } finally {
      setLoadingFavorites(false);
    }
  }

  async function loadSignalSets() {
    setLoadingSignalSets(true);
    try {
      const data = await fetchSignalSets();
      setSignalSets(data.items);
      setForm((current) => ({
        ...current,
        signalSetId: current.signalSetId || data.items[0]?.id || "",
      }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "异动表加载失败");
    } finally {
      setLoadingSignalSets(false);
    }
  }

  async function loadSignalEvents(signalSetId: string) {
    setLoadingEvents(true);
    try {
      const data = await fetchSignalSetEvents(signalSetId, 200);
      setSignalEvents(data.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "异动明细加载失败");
    } finally {
      setLoadingEvents(false);
    }
  }

  async function loadRuns() {
    try {
      const data = await fetchBacktestRuns();
      setRuns(data.items);
      setActiveRun((current) => current ?? data.items[0] ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "回测记录加载失败");
    }
  }

  async function openRun(runId: string) {
    setLoadingRun(true);
    setError(null);
    try {
      const run = await fetchBacktestRun(runId);
      setActiveRun(run);
    } catch (err) {
      setError(err instanceof Error ? err.message : "回测详情加载失败");
    } finally {
      setLoadingRun(false);
    }
  }

  async function generateSignalSet() {
    if (!form.favoriteId) {
      setError("请先选择一个收藏条件。");
      return;
    }
    setGeneratingSignalSet(true);
    setError(null);
    try {
      const signalSet = await createSignalSet({
        favorite_id: form.favoriteId,
        name: form.signalSetName.trim(),
        start_date: form.startDate,
        end_date: form.endDate,
        signal_timeframe: form.signalTimeframe,
        signal_mode: form.signalMode as "daily" | "each_bar_close",
        checkpoint_limit: form.signalMode === "each_bar_close"
          ? form.signalTimeframe === "1m"
            ? 2000
            : form.signalTimeframe === "1H"
              ? 5000
            : 600
          : 1500,
      });
      upsertSignalSet(signalSet);
      setForm((current) => ({ ...current, signalSetId: signalSet.id }));
      if (signalSet.status === "failed") {
        setError(signalSet.error || "异动信号生成失败");
      } else if (signalSet.status === "completed") {
        void loadSignalEvents(signalSet.id);
      } else {
        setSignalEvents([]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "异动信号生成失败");
    } finally {
      setGeneratingSignalSet(false);
    }
  }

  async function startBacktest() {
    if (!form.signalSetId) {
      setError("请先生成或选择一张异动信号表。");
      return;
    }
    const currentSignalSet = signalSets.find((item) => item.id === form.signalSetId);
    if (currentSignalSet && currentSignalSet.status !== "completed") {
      setError("请选择已完成的异动表再开始回测。");
      return;
    }
    setRunning(true);
    setError(null);
    try {
      const run = await createBacktestRunFromSignalSet({
        signal_set_id: form.signalSetId,
        name: form.backtestName.trim(),
        side: form.side as "long" | "short",
        entry_timeframe: form.entryTimeframe,
        entry_rule: form.entryRule as "next_bar_open" | "consecutive_green_bars",
        entry_window_minutes: Number(form.entryWindowMinutes),
        entry_consecutive_bars: Number(form.entryConsecutiveBars),
        entry_min_gain_pct_each: Number(form.entryMinGainPctEach),
        exit_hold_minutes: Number(form.exitHoldMinutes),
        stop_loss_pct: Number(form.stopLossPct),
        stop_model: form.stopModel as "bot_like_checkpoint" | "hard_stop_intrabar",
        position_usdt: Number(form.positionUsdt),
        leverage: Number(form.leverage),
        max_positions: Number(form.maxPositions),
        fee_bps_per_side: Number(form.feeBps),
        slippage_bps_per_side: Number(form.slippageBps),
      });
      setActiveRun(run);
      if (run.status === "failed") {
        setError(run.error || "回测失败");
      }
      void loadRuns();
    } catch (err) {
      setError(err instanceof Error ? err.message : "回测启动失败");
    } finally {
      setRunning(false);
    }
  }

  function updateForm(key: keyof typeof form, value: string) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function upsertSignalSet(signalSet: SignalSet) {
    setSignalSets((current) => {
      if (current.some((item) => item.id === signalSet.id)) {
        return current.map((item) => (item.id === signalSet.id ? signalSet : item));
      }
      return [signalSet, ...current];
    });
  }

  function changeSignalTimeframe(value: string) {
    const nextRange = suggestedBacktestRange(summary, value, form.signalMode);
    setForm((current) => ({
      ...current,
      signalTimeframe: value,
      startDate: nextRange.start,
      endDate: nextRange.end,
    }));
  }

  function changeSignalMode(value: string) {
    const nextRange = suggestedBacktestRange(summary, form.signalTimeframe, value);
    setForm((current) => ({
      ...current,
      signalMode: value,
      startDate: nextRange.start,
      endDate: nextRange.end,
    }));
  }

  async function openTradeKline(trade: BacktestTrade, period: string) {
    const target = { instId: trade.inst_id, anchorTs: trade.entry_ts };
    const markers = tradeKlineMarkers(trade);
    const normalizedPeriod = defaultTradeKlinePeriod(trade, period);
    setSelectedAnomaly(null);
    setKlineTarget(target);
    setKlinePeriod(normalizedPeriod);
    setKlineMarkers(markers);
    await loadTradeKlineWindow(target, normalizedPeriod, markers);
  }

  async function openAnomalyDetail(event: SignalEvent) {
    const target = { instId: event.inst_id, anchorTs: event.signal_ts };
    const normalizedPeriod = defaultAnomalyKlinePeriod(event.timeframe || form.signalTimeframe);
    setSelectedAnomaly(event);
    setKlineTarget(target);
    setKlinePeriod(normalizedPeriod);
    setKlineMarkers([]);
    await loadAnomalyKlineWindow(target, normalizedPeriod);
  }

  async function changeKlinePeriod(period: string) {
    if (!klineTarget) return;
    setKlinePeriod(period);
    if (selectedAnomaly) {
      await loadAnomalyKlineWindow(klineTarget, period);
    } else {
      await loadTradeKlineWindow(klineTarget, period, klineMarkers);
    }
  }

  function closeKlineModal() {
    setKlineTarget(null);
    setKlineData(null);
    setKlineError(null);
    setKlineMarkers([]);
    setSelectedAnomaly(null);
  }

  async function loadTradeKlineWindow(
    target: { instId: string; anchorTs?: number | null },
    period: string,
    markers: KlineTradeMarker[],
  ) {
    setKlineData(null);
    setKlineLoading(true);
    setKlineError(null);
    try {
      const windowSize = tradeKlineWindowSize(period, target.anchorTs, markers);
      const data = await fetchContractKlineWindow({
        instId: target.instId,
        timeframe: period,
        anchorTs: target.anchorTs,
        before: windowSize.before,
        after: windowSize.after,
      });
      setKlineData(data);
    } catch (err) {
      setKlineError(err instanceof Error ? err.message : "成交K线加载失败");
    } finally {
      setKlineLoading(false);
    }
  }

  async function loadAnomalyKlineWindow(
    target: { instId: string; anchorTs?: number | null },
    period: string,
  ) {
    setKlineData(null);
    setKlineLoading(true);
    setKlineError(null);
    try {
      const data = await fetchContractKlineWindow({
        instId: target.instId,
        timeframe: period,
        anchorTs: target.anchorTs,
        before: 33,
        after: 33,
      });
      setKlineData(data);
    } catch (err) {
      setKlineError(err instanceof Error ? err.message : "异动K线加载失败");
    } finally {
      setKlineLoading(false);
    }
  }

  const selectedFavorite = favorites.find((item) => item.id === form.favoriteId) ?? null;
  const favoriteSignalSets = signalSets.filter((item) => item.favorite_id === form.favoriteId);
  const selectedSignalSet = signalSets.find((item) => item.id === form.signalSetId) ?? null;
  const result = activeRun?.result ?? null;
  const summaryStats = result?.summary;
  const trades = result?.trades ?? [];
  const checkpoints = result?.checkpoints ?? [];
  const equityPoints = result?.daily_equity?.length ? result.daily_equity : result?.equity ?? [];
  const tradeKlinePeriod = activeRun?.config.entry_timeframe ?? form.entryTimeframe;
  const selectedSignalSummary = selectedSignalSet?.summary ?? null;
  const canStartBacktest = Boolean(form.signalSetId && selectedSignalSet?.status === "completed");

  useEffect(() => {
    if (!selectedSignalSet || selectedSignalSet.status !== "running") return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const pollSignalSet = async () => {
      try {
        const next = await fetchSignalSet(selectedSignalSet.id);
        if (cancelled) return;
        upsertSignalSet(next);
        if (next.status === "completed") {
          await loadSignalEvents(next.id);
          void loadSignalSets();
        } else if (next.status === "failed") {
          setError(next.error || "异动信号生成失败");
        } else {
          timer = setTimeout(pollSignalSet, 3000);
        }
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "异动表状态刷新失败");
        timer = setTimeout(pollSignalSet, 5000);
      }
    };

    timer = setTimeout(pollSignalSet, 2000);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedSignalSet?.id, selectedSignalSet?.status]);

  return (
    <section className="metadata-page backtest-page">
      <div className="metadata-page-head">
        <div>
          <h1>回测验证</h1>
          <p className="contract-page-subtitle">
            收藏条件先沉淀成按时间排序的异动信号表，再配置买卖规则和账户参数做可复现回测。
          </p>
        </div>
        <div className="metadata-actions">
          <button className="secondary-action" onClick={() => { void loadFavorites(); void loadSignalSets(); void loadRuns(); }}>
            刷新
          </button>
        </div>
      </div>

      <div className="backtest-layout">
        <div className="backtest-main-stack">
          <form
            className="backtest-card backtest-form"
            onSubmit={(event) => {
              event.preventDefault();
              void generateSignalSet();
            }}
          >
            <div className="backtest-card-head">
              <span className="eyebrow">Step 1</span>
              <strong>收藏条件生成异动表</strong>
              <em>{selectedFavorite ? `${selectedFavorite.condition_count} 条条件 · ${favoriteSignalSets.length} 张历史表` : "先选择收藏"}</em>
            </div>
            <div className="backtest-form-grid">
              <label className="field wide">
                <span>收藏条件</span>
                <select value={form.favoriteId} onChange={(event) => updateForm("favoriteId", event.target.value)}>
                  {favorites.length === 0 ? (
                    <option value="">暂无收藏条件</option>
                  ) : (
                    favorites.map((favorite) => (
                      <option key={favorite.id} value={favorite.id}>
                        {favorite.name} ({favorite.condition_count} 条)
                      </option>
                    ))
                  )}
                </select>
              </label>
              <label className="field wide">
                <span>异动表名称</span>
                <input
                  placeholder={selectedFavorite ? `${selectedFavorite.name} 异动信号` : "可不填，系统自动命名"}
                  value={form.signalSetName}
                  onChange={(event) => updateForm("signalSetName", event.target.value)}
                />
              </label>
              <label className="field">
                <span>开始日期</span>
                <input type="date" value={form.startDate} onChange={(event) => updateForm("startDate", event.target.value)} />
              </label>
              <label className="field">
                <span>结束日期</span>
                <input type="date" value={form.endDate} onChange={(event) => updateForm("endDate", event.target.value)} />
              </label>
              <label className="field">
                <span>异动扫描周期</span>
                <select value={form.signalTimeframe} onChange={(event) => changeSignalTimeframe(event.target.value)}>
                  {backtestSignalTimeframeOptions.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>异动扫描频率</span>
                <select value={form.signalMode} onChange={(event) => changeSignalMode(event.target.value)}>
                  {backtestSignalModeOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="backtest-form-actions">
              <p className="backtest-hint">
                异动表会记录合约、异动时间、确认时间和命中快照；回测只从确认时间之后交易，避免未来函数。
              </p>
              <button className="primary-action" disabled={generatingSignalSet || loadingFavorites} type="submit">
                {generatingSignalSet ? "提交中..." : "生成/刷新异动表"}
              </button>
            </div>
          </form>

          <div className="backtest-card signal-set-preview">
            <div className="backtest-card-head">
              <span className="eyebrow">Step 2</span>
              <strong>异动信号表</strong>
              <em>{selectedSignalSet ? `${runStatusLabel(selectedSignalSet.status)} · ${formatDateTime(selectedSignalSet.created_at)}` : "选择或生成后查看"}</em>
            </div>
            {!selectedSignalSet ? (
              <EmptyState title="暂无异动信号表" text="先选择收藏条件并点击「生成/刷新异动表」，这里会展示按时间排序的异动记录。" />
            ) : (
              <>
                <div className="signal-set-stats">
                  <span>异动信号 <b>{selectedSignalSummary?.event_count ?? 0}</b></span>
                  <span>唯一合约 <b>{selectedSignalSummary?.unique_contracts ?? 0}</b></span>
                  <span>扫描时刻 <b>{selectedSignalSummary?.checkpoint_count ?? 0}</b></span>
                  <span>区间 <b>{selectedSignalSummary?.start_date ?? "--"} ~ {selectedSignalSummary?.end_date ?? "--"}</b></span>
                  <span>首个异动 <b>{selectedSignalSummary?.first_signal_time ?? "--"}</b></span>
                  <span>最后异动 <b>{selectedSignalSummary?.last_signal_time ?? "--"}</b></span>
                </div>
                {selectedSignalSet.status === "running" ? (
                  <EmptyState
                    title="异动表后台生成中"
                    text="任务已经提交到后端，页面会每 3 秒自动刷新状态；逐根K线大区间可能需要几分钟。"
                  />
                ) : selectedSignalSet.status === "failed" ? (
                  <EmptyState title="异动表生成失败" text={selectedSignalSet.error || "请调整区间、扫描频率或脚本指标后重新生成。"} />
                ) : (
                  <>
                    <div className="anomaly-table-scroll">
                      <table className="anomaly-table">
                        <thead>
                          <tr>
                            <th>异动时间</th>
                            <th>确认时间</th>
                            <th>合约代码</th>
                            <th>异动名称</th>
                            <th>强度</th>
                            <th>命中条件</th>
                          </tr>
                        </thead>
                        <tbody>
                          {loadingEvents ? (
                            <tr>
                              <td colSpan={6}>正在加载异动明细...</td>
                            </tr>
                          ) : signalEvents.length === 0 ? (
                            <tr>
                              <td colSpan={6}>这张异动表没有命中记录。</td>
                            </tr>
                          ) : (
                            signalEvents.slice(0, 200).map((event) => (
                              <tr className="anomaly-table-row" key={event.id}>
                                <td>{event.signal_time ?? "--"}</td>
                                <td>{event.confirm_time ?? "--"}</td>
                                <td>
                                  <button
                                    className="anomaly-symbol-button"
                                    title="查看这条异动的命中条件和K线"
                                    type="button"
                                    onClick={() => void openAnomalyDetail(event)}
                                  >
                                    {event.inst_id}
                                  </button>
                                </td>
                                <td>{selectedFavorite?.name ?? selectedSignalSet.name}</td>
                                <td>{formatOptionalNumber(event.strength)}</td>
                                <td title={(event.matched_conditions || []).join("；")}>
                                  {anomalyConditionPreview(event)}
                                </td>
                              </tr>
                            ))
                          )}
                        </tbody>
                      </table>
                    </div>
                    {signalEvents.length > 200 && (
                      <p className="backtest-hint">当前仅展示前 200 条异动，完整数据已存入本地 SQLite。</p>
                    )}
                  </>
                )}
              </>
            )}
          </div>

          <form
            className="backtest-card backtest-form"
            noValidate
            onSubmit={(event) => {
              event.preventDefault();
              void startBacktest();
            }}
          >
            <div className="backtest-card-head">
              <span className="eyebrow">Step 3</span>
              <strong>买卖规则与账户配置</strong>
              <em>异动确认后如何成交、出场和计入资金曲线</em>
            </div>
            <div className="backtest-form-grid">
              <label className="field wide">
                <span>异动表</span>
                <select value={form.signalSetId} onChange={(event) => updateForm("signalSetId", event.target.value)}>
                  {favoriteSignalSets.length === 0 ? (
                    <option value="">暂无异动表</option>
                  ) : (
                    favoriteSignalSets.map((signalSet) => (
                      <option key={signalSet.id} value={signalSet.id}>
                        {signalSet.name} ({signalSet.summary?.event_count ?? 0} 个异动)
                      </option>
                    ))
                  )}
                </select>
              </label>
              <label className="field wide">
                <span>回测名称</span>
                <input
                  placeholder={selectedSignalSet ? `${selectedSignalSet.name} 回测` : "可不填，系统自动命名"}
                  value={form.backtestName}
                  onChange={(event) => updateForm("backtestName", event.target.value)}
                />
              </label>
              <label className="field">
                <span>方向</span>
                <select value={form.side} onChange={(event) => updateForm("side", event.target.value)}>
                  <option value="short">做空</option>
                  <option value="long">做多</option>
                </select>
              </label>
              <label className="field">
                <span>成交K线</span>
                <select value={form.entryTimeframe} onChange={(event) => updateForm("entryTimeframe", event.target.value)}>
                  {backtestEntryTimeframeOptions.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </label>
              <label className="field wide">
                <span>入场规则</span>
                <select value={form.entryRule} onChange={(event) => updateForm("entryRule", event.target.value)}>
                  <option value="consecutive_green_bars">异动确认后连续N根阳线，再下一根开盘</option>
                  <option value="next_bar_open">异动确认后下一根开盘</option>
                </select>
              </label>
              <label className="field">
                <span>入场窗口分钟</span>
                <input min="1" type="number" value={form.entryWindowMinutes} onChange={(event) => updateForm("entryWindowMinutes", event.target.value)} />
              </label>
              <label className="field">
                <span>连续阳线根数</span>
                <input min="1" max="20" type="number" value={form.entryConsecutiveBars} onChange={(event) => updateForm("entryConsecutiveBars", event.target.value)} />
              </label>
              <label className="field">
                <span>单根涨幅%</span>
                <input min="0" step="0.1" type="number" value={form.entryMinGainPctEach} onChange={(event) => updateForm("entryMinGainPctEach", event.target.value)} />
              </label>
              <label className="field">
                <span>持仓分钟</span>
                <input min="1" type="number" value={form.exitHoldMinutes} onChange={(event) => updateForm("exitHoldMinutes", event.target.value)} />
              </label>
              <label className="field">
                <span>止损%</span>
                <input min="0" step="0.1" type="number" value={form.stopLossPct} onChange={(event) => updateForm("stopLossPct", event.target.value)} />
              </label>
              <label className="field wide">
                <span>止损模型</span>
                <select value={form.stopModel} onChange={(event) => updateForm("stopModel", event.target.value)}>
                  <option value="bot_like_checkpoint">检查点止损（贴近旧bot）</option>
                  <option value="hard_stop_intrabar">盘中硬止损</option>
                </select>
              </label>
              <label className="field">
                <span>单笔保证金U</span>
                <input min="1" type="number" value={form.positionUsdt} onChange={(event) => updateForm("positionUsdt", event.target.value)} />
              </label>
              <label className="field">
                <span>杠杆</span>
                <input min="0.01" step="0.1" type="number" value={form.leverage} onChange={(event) => updateForm("leverage", event.target.value)} />
              </label>
              <label className="field">
                <span>最多持仓</span>
                <input min="1" max="100" type="number" value={form.maxPositions} onChange={(event) => updateForm("maxPositions", event.target.value)} />
              </label>
              <label className="field">
                <span>手续费bps</span>
                <input min="0" step="0.1" type="number" value={form.feeBps} onChange={(event) => updateForm("feeBps", event.target.value)} />
              </label>
              <label className="field">
                <span>滑点bps</span>
                <input min="0" step="0.1" type="number" value={form.slippageBps} onChange={(event) => updateForm("slippageBps", event.target.value)} />
              </label>
            </div>
            <div className="backtest-form-actions">
              <p className="backtest-hint">
                默认：异动确认后60分钟内，5m连续2根阳线且单根≥2%，下一根开盘做空，持仓440分钟，15%止损。
              </p>
              <button className="primary-action" disabled={running || !canStartBacktest} type="submit">
                {running ? "回测中..." : "开始规则回测"}
              </button>
            </div>
          </form>
        </div>

        <aside className="backtest-history-stack">
          <div className="backtest-card backtest-runs">
            <div className="backtest-card-head">
              <span className="eyebrow">History</span>
              <strong>最近回测</strong>
            </div>
            {runs.length === 0 ? (
              <EmptyState title="暂无回测记录" text="点击开始回测后，会把结果写入本地 SQLite。" />
            ) : (
              <div className="backtest-run-list">
                {runs.map((run) => (
                  <button
                    className={activeRun?.id === run.id ? "active" : ""}
                    disabled={loadingRun}
                    key={run.id}
                    onClick={() => void openRun(run.id)}
                  >
                    <strong>{run.name}</strong>
                    <span>{runStatusLabel(run.status)} · {formatDateTime(run.created_at)}</span>
                    {run.result?.summary && (
                      <em className={numberTone(run.result.summary.total_pnl)}>
                        {formatSignedNumber(run.result.summary.total_pnl)}U / {formatPercent(run.result.summary.total_return_pct)}
                      </em>
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>
        </aside>
      </div>

      {error && <div className="inline-error backtest-error">{error}</div>}
      {generatingSignalSet && (
        <EmptyState
          title="正在提交异动表后台任务"
          text="提交成功后后端会按1小时K线逐根扫描，页面会自动轮询任务状态。"
        />
      )}
      {running && <EmptyState title="正在回测" text="先从异动表寻找入场，再按止损和到期规则模拟出场。" />}

      {summaryStats && (
        <>
          <div className="backtest-section-head">
            <span className="eyebrow">Step 4</span>
            <strong>回测结果</strong>
            <em>成交记录、执行诊断和账户每日权益曲线</em>
          </div>
          <div className="backtest-summary-grid">
            <BacktestStat label="总收益" value={`${formatSignedNumber(summaryStats.total_pnl)}U`} tone={numberTone(summaryStats.total_pnl)} />
            <BacktestStat label="收益率" value={formatPercent(summaryStats.total_return_pct)} tone={numberTone(summaryStats.total_return_pct)} />
            <BacktestStat label="交易数" value={`${summaryStats.total_trades}`} />
            <BacktestStat label="胜率" value={formatPercent(summaryStats.win_rate)} />
            <BacktestStat label="最大回撤" value={formatPercent(summaryStats.max_drawdown_pct)} tone={summaryStats.max_drawdown_pct < 0 ? "down" : ""} />
            <BacktestStat label="异动命中" value={`${summaryStats.matched_signals}`} />
          </div>

          <div className="backtest-result-grid">
            <div className="backtest-card">
              <div className="backtest-card-head">
                <span className="eyebrow">Equity</span>
                <strong>账户每日权益曲线</strong>
              </div>
              <BacktestEquityChart points={equityPoints} />
            </div>
            <div className="backtest-card backtest-diagnostics">
              <div className="backtest-card-head">
                <span className="eyebrow">Diagnostics</span>
                <strong>执行诊断</strong>
              </div>
              <div className="diagnostic-grid">
                <span>检查点 <b>{summaryStats.checkpoints}</b></span>
                <span>开仓 <b>{summaryStats.opened_trades}</b></span>
                <span>重叠跳过 <b>{summaryStats.skipped_overlap}</b></span>
                <span>满仓跳过 <b>{summaryStats.skipped_max_positions}</b></span>
                <span>保证金不足 <b>{summaryStats.skipped_insufficient_equity ?? 0}</b></span>
                <span>账户归零 <b>{summaryStats.skipped_account_depleted ?? 0}</b></span>
                <span>无入场 <b>{summaryStats.skipped_no_entry}</b></span>
                <span>无出场 <b>{summaryStats.skipped_no_exit}</b></span>
                <span>方向 <b>{summaryStats.side === "short" ? "做空" : summaryStats.side === "long" ? "做多" : "--"}</b></span>
                <span>持仓 <b>{summaryStats.exit_hold_minutes ?? Math.round(summaryStats.hold_hours * 60)}分钟</b></span>
                <span>Profit Factor <b>{summaryStats.profit_factor ?? "--"}</b></span>
                <span>耗时 <b>{summaryStats.duration_ms}ms</b></span>
              </div>
            </div>
          </div>

          <div className="backtest-card backtest-table-card">
            <div className="backtest-card-head">
              <span className="eyebrow">Trades</span>
              <strong>交易明细</strong>
              <em>展示前 {Math.min(trades.length, 200)} / {trades.length} 笔</em>
            </div>
            <div className="backtest-table-scroll">
              <table className="backtest-table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>合约</th>
                    <th>方向</th>
                    <th>异动确认</th>
                    <th>入场</th>
                    <th>出场</th>
                    <th>入场价</th>
                    <th>出场价</th>
                    <th>出场原因</th>
                    <th>收益</th>
                    <th>盈亏U</th>
                  </tr>
                </thead>
                <tbody>
                  {trades.slice(0, 200).map((trade) => (
                    <tr key={`${activeRun?.id}-${trade.id}`}>
                      <td>{trade.id}</td>
                      <td>
                        <span className="symbol-with-kline backtest-symbol-with-kline">
                          <span>{trade.inst_id}</span>
                          <button
                            className="kline-icon-button"
                            title="查看这笔交易的买卖点K线"
                            onClick={() => void openTradeKline(trade, tradeKlinePeriod)}
                          >
                            K
                          </button>
                        </span>
                      </td>
                      <td>{trade.direction ?? (trade.side === "short" ? "做空" : "做多")}</td>
                      <td>{trade.confirm_time ?? trade.signal_time}</td>
                      <td>{trade.entry_time}</td>
                      <td>{trade.exit_time}</td>
                      <td>{formatOptionalNumber(trade.entry_price)}</td>
                      <td>{formatOptionalNumber(trade.exit_price)}</td>
                      <td>{trade.exit_reason ?? "--"}</td>
                      <td className={numberTone(trade.net_return_pct)}>{formatPercent(trade.net_return_pct)}</td>
                      <td className={numberTone(trade.pnl_usdt)}>{formatSignedNumber(trade.pnl_usdt)}</td>
                    </tr>
                  ))}
                  {trades.length === 0 && (
                    <tr>
                      <td colSpan={11}>本次回测没有产生可成交交易。</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
      {selectedAnomaly && klineTarget ? (
        <AnomalyEvidenceModal
          event={selectedAnomaly}
          signalName={selectedFavorite?.name ?? selectedSignalSet?.name ?? "异动信号"}
          target={klineTarget}
          activePeriod={klinePeriod}
          data={klineData}
          loading={klineLoading}
          error={klineError}
          onPeriodChange={(period) => void changeKlinePeriod(period)}
          onClose={closeKlineModal}
        />
      ) : klineTarget ? (
        <ContractKlineModal
          target={klineTarget}
          activePeriod={klinePeriod}
          data={klineData}
          loading={klineLoading}
          error={klineError}
          onPeriodChange={(period) => void changeKlinePeriod(period)}
          onClose={closeKlineModal}
          markers={klineMarkers}
        />
      ) : null}
    </section>
  );
}

function BacktestStat({ label, value, tone = "" }: { label: string; value: string; tone?: string }) {
  return (
    <div className="backtest-stat">
      <span>{label}</span>
      <strong className={tone}>{value}</strong>
    </div>
  );
}

function BacktestEquityChart({ points }: { points: Array<{ time: string | null; equity: number; drawdown_pct: number }> }) {
  if (points.length === 0) {
    return <EmptyState title="暂无账户曲线" text="生成回测结果后，会按每日权益展示账户变化。" />;
  }
  const width = 760;
  const height = 260;
  const padding = { top: 22, right: 26, bottom: 36, left: 56 };
  const equities = points.map((point) => point.equity);
  const minEquity = Math.min(...equities);
  const maxEquity = Math.max(...equities);
  const span = maxEquity - minEquity || Math.max(1, maxEquity * 0.01);
  const xFor = (index: number) => padding.left + (index / Math.max(1, points.length - 1)) * (width - padding.left - padding.right);
  const yFor = (value: number) => padding.top + ((maxEquity - value) / span) * (height - padding.top - padding.bottom);
  const polyline = points.map((point, index) => `${xFor(index)},${yFor(point.equity)}`).join(" ");
  const latest = points.at(-1);

  return (
    <div className="backtest-equity-chart">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="账户每日权益曲线">
        <rect x="0" y="0" width={width} height={height} rx="14" />
        {[minEquity, (minEquity + maxEquity) / 2, maxEquity].map((value, index) => {
          const y = yFor(value);
          return (
            <g key={`${index}-${value}`}>
              <line x1={padding.left} x2={width - padding.right} y1={y} y2={y} />
              <text x={padding.left - 10} y={y + 4}>{formatNumber(value)}</text>
            </g>
          );
        })}
        <polyline points={polyline} />
        <circle cx={xFor(points.length - 1)} cy={yFor(latest?.equity ?? 0)} r="5" />
        <text className="end" x={width - padding.right} y={height - 12}>{latest?.time ?? ""}</text>
      </svg>
      <div className="equity-chart-caption">
        <span>最新权益 <b>{formatNumber(latest?.equity ?? 0)}U</b></span>
        <span>当前回撤 <b>{formatPercent(latest?.drawdown_pct ?? 0)}</b></span>
      </div>
    </div>
  );
}

function MetadataConditionModal({
  timeframe,
  initialCondition,
  onClose,
  onOpenWarehouse,
  onApply,
}: {
  timeframe: string;
  initialCondition?: MetadataCondition | null;
  onClose: () => void;
  onOpenWarehouse: () => void;
  onApply: (condition: MetadataCondition) => void;
}) {
  const [catalog, setCatalog] = useState<IndicatorCatalogResponse | null>(null);
  const [draft, setDraft] = useState<MetadataConditionDraft>(() =>
    initialCondition ? draftFromCondition(initialCondition) : defaultMetadataConditionDraft(),
  );
  const [mode, setMode] = useState<"filter" | "value">("filter");
  const [metadataSearch, setMetadataSearch] = useState("");
  const [selectOpen, setSelectOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void loadCatalog();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function loadCatalog() {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchIndicators();
      setCatalog(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "元数据加载失败");
    } finally {
      setLoading(false);
    }
  }

  const items = catalog?.items ?? [];
  const selectedIndicator = items.find((item) => item.id === draft.indicatorId) ?? null;
  const options = useMemo(() => {
    const needle = metadataSearch.trim().toLowerCase();
    const filtered = needle ? items.filter(
      (item) =>
        item.name_zh.toLowerCase().includes(needle) ||
        item.id.toLowerCase().includes(needle) ||
        englishName(item).toLowerCase().includes(needle),
    ) : items;
    return filtered.slice().sort(metadataOptionSort);
  }, [items, metadataSearch]);
  const selectedLabel = selectedIndicator ? metadataOptionLabel(selectedIndicator) : "";
  const currentOperatorOptions = selectedIndicator?.data_type === "number"
    ? metadataOperatorOptions.filter((item) => item.value !== "contains")
    : metadataOperatorOptions.filter((item) => ["any", "any_empty", "any_not_empty", "eq", "ne", "contains"].includes(item.value));
  const isValueFreeOperator = metadataOperatorNoValue(draft.operator);
  const timePointMode = selectedIndicator
    ? normalizeTimePointModeForPeriod(selectedIndicator.storage_period, draft.timePointMode, draft.timePoint)
    : "baseline";
  const timePointError = selectedIndicator && timePointMode === "fixed"
    ? metadataTimePointError(selectedIndicator.storage_period, draft.timePoint)
    : "";
  const timeTakeError = selectedIndicator ? metadataTimeTakeError(selectedIndicator.storage_period, draft) : "";
  const timeStepSeconds = selectedIndicator ? metadataTimeStepSeconds(selectedIndicator.storage_period) : 60;
  const timeDisabled = selectedIndicator ? !metadataPeriodAllowsTime(selectedIndicator.storage_period) : true;
  const canAdd = Boolean(
    selectedIndicator &&
    metadataCanFilter(selectedIndicator) &&
    (isValueFreeOperator || draft.value.trim()) &&
    !timePointError &&
    !timeTakeError,
  );

  function selectIndicator(item: Indicator) {
    const nextOptions = item.data_type === "number"
      ? metadataOperatorOptions.filter((option) => option.value !== "contains")
      : metadataOperatorOptions.filter((option) => ["any", "any_empty", "any_not_empty", "eq", "ne", "contains"].includes(option.value));
    setDraft((current) => ({
      ...current,
      indicatorId: item.id,
      operator: nextOptions.some((option) => option.value === current.operator)
        ? current.operator
        : defaultMetadataOperator,
      timePointMode: normalizeTimePointModeForPeriod(item.storage_period, current.timePointMode, current.timePoint),
      timePoint: normalizeDraftTimePointForPeriod(item.storage_period, current.timePoint),
    }));
    setMetadataSearch("");
    setSelectOpen(false);
  }

  function applyCondition() {
    if (!selectedIndicator) {
      setError("请先选择一个元数据字段。");
      return;
    }
    if (!metadataCanFilter(selectedIndicator)) {
      setError("这个元数据暂未接入数据流，当前不能用于合约筛选。");
      return;
    }
    if (!isValueFreeOperator && !draft.value.trim()) {
      setError("请填写筛选条件的目标值。");
      return;
    }
    const normalizedTimePointMode = normalizeTimePointModeForPeriod(
      selectedIndicator.storage_period,
      draft.timePointMode,
      draft.timePoint,
    );
    const currentTimeTakeError = metadataTimeTakeError(selectedIndicator.storage_period, {
      ...draft,
      timePointMode: normalizedTimePointMode,
    });
    if (currentTimeTakeError) {
      setError(currentTimeTakeError);
      return;
    }
    onApply({
      ...draft,
      value: isValueFreeOperator ? "" : draft.value.trim(),
      timePointMode: normalizedTimePointMode,
      timePoint: normalizedTimePointMode === "fixed"
        ? normalizeDraftTimePointForPeriod(selectedIndicator.storage_period, draft.timePoint)
        : "",
      barOffset: normalizeNonNegativeText(draft.barOffset, "0"),
      timeOffsetValue: normalizeNonNegativeText(draft.timeOffsetValue, "0"),
      timeOffsetUnit: draft.timeOffsetUnit === "minute" ? "minute" : "hour",
      id: initialCondition?.id ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`,
      indicator: selectedIndicator,
    });
  }

  return (
    <div className="condition-modal-backdrop" role="presentation" onMouseDown={onClose}>
      <div className="condition-modal" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}>
        <div className="condition-modal-title-row">
          <h2>元数据条件生成器</h2>
          <button className="condition-close" onClick={onClose}>×</button>
        </div>

        <div className="condition-modal-actions">
          <button onClick={onOpenWarehouse}>查看元数据</button>
          <button onClick={() => setMode((current) => (current === "filter" ? "value" : "filter"))}>
            {mode === "filter" ? "切换取值条件" : "切换筛选条件"}
          </button>
          <button
            className={draft.exclude ? "active" : ""}
            disabled={isValueFreeOperator}
            onClick={() => setDraft({ ...draft, exclude: !draft.exclude })}
          >
            排除
          </button>
          <button className="add-action" disabled={!canAdd} onClick={applyCondition}>
            <span>{initialCondition ? "✓" : "＋"}</span> {initialCondition ? "保存" : "新增"}
          </button>
        </div>

        <div className="condition-builder-panel">
          <div className="condition-form-row first-row">
            <label>选择元数据字段</label>
            <div className="metadata-combobox">
              <input
                value={selectOpen ? metadataSearch : selectedLabel}
                placeholder="选择元数据"
                onFocus={() => setSelectOpen(true)}
                onChange={(event) => {
                  setMetadataSearch(event.target.value);
                  setSelectOpen(true);
                }}
              />
              <button
                className={selectOpen ? "combobox-arrow open" : "combobox-arrow"}
                onClick={() => setSelectOpen((current) => !current)}
                aria-label="展开元数据"
              >
               ⌃
              </button>
              {selectOpen && (
                <div className="metadata-options">
                  {loading ? (
                    <div className="metadata-option muted">正在加载元数据...</div>
                  ) : options.length === 0 ? (
                    <div className="metadata-option muted">没有匹配的元数据</div>
                  ) : (
                    options.map((item) => (
                      <button
                        key={item.id}
                        className="metadata-option"
                        onClick={() => selectIndicator(item)}
                        title={metadataOptionLabel(item)}
                      >
                        <span>{metadataOptionLabel(item)}</span>
                        {item.source_type === "script" ? <em>生产指标</em> : !metadataCanFilter(item) && <em>暂不可筛选</em>}
                      </button>
                    ))
                  )}
                </div>
              )}
            </div>
            <label className="inline-checkbox">
              <input
                type="checkbox"
                checked={draft.externalRelation}
                onChange={(event) => setDraft({ ...draft, externalRelation: event.target.checked })}
              />
              <span>是否外部关联</span>
            </label>
          </div>

          {selectedIndicator && (
            <>
              <div className="condition-form-row">
                <label>选择交易日</label>
                <select value={draft.timeMode} onChange={(event) => setDraft({ ...draft, timeMode: event.target.value })}>
                  <option value="previous_trading_day">前N个交易日</option>
                  <option value="current_trading_day">当前交易日</option>
                  <option value="latest">最新可用时间</option>
                </select>
                <input
                  value={draft.timeOffset}
                  disabled={draft.timeMode !== "previous_trading_day"}
                  onChange={(event) => setDraft({ ...draft, timeOffset: event.target.value })}
                  placeholder="1"
                />
                <label className="inline-checkbox">
                  <input
                    type="checkbox"
                    checked={draft.timeRange}
                    onChange={(event) => setDraft({ ...draft, timeRange: event.target.checked })}
                  />
                  <span>时间范围</span>
                </label>
              </div>

              <div className="condition-form-row condition-time-row">
                <label>取值时间</label>
                <select
                  value={timePointMode}
                  disabled={timeDisabled}
                  onChange={(event) => setDraft({ ...draft, timePointMode: event.target.value, timePoint: "" })}
                >
                  <option value="baseline">跟随基准时间</option>
                  <option value="bar_offset">前N根K线</option>
                  <option value="time_offset">前N分钟/小时</option>
                  <option value="fixed">固定时刻</option>
                </select>
                {timePointMode === "bar_offset" && (
                  <input
                    value={draft.barOffset}
                    onChange={(event) => setDraft({ ...draft, barOffset: event.target.value })}
                    placeholder="1"
                  />
                )}
                {timePointMode === "time_offset" && (
                  <>
                    <input
                      value={draft.timeOffsetValue}
                      onChange={(event) => setDraft({ ...draft, timeOffsetValue: event.target.value })}
                      placeholder="1"
                    />
                    <select
                      value={draft.timeOffsetUnit === "minute" ? "minute" : "hour"}
                      onChange={(event) => setDraft({ ...draft, timeOffsetUnit: event.target.value })}
                    >
                      <option value="hour">小时</option>
                      <option value="minute">分钟</option>
                    </select>
                  </>
                )}
                {timePointMode === "fixed" && (
                  <input
                    type="time"
                    step={timeStepSeconds}
                    value={timeDisabled ? "" : draft.timePoint}
                    disabled={timeDisabled}
                    onChange={(event) => setDraft({ ...draft, timePoint: event.target.value })}
                  />
                )}
                <span className={(timePointError || timeTakeError) ? "condition-time-hint invalid" : "condition-time-hint"}>
                  {timeTakeError || timePointError || metadataTimePointHint(selectedIndicator.storage_period, draft)}
                </span>
              </div>

              <div className="condition-form-row">
                <label>{mode === "filter" ? "设置条件" : "取值条件"}</label>
                <select
                  value={draft.operator}
                  onChange={(event) => {
                    const operator = event.target.value;
                    setDraft({
                      ...draft,
                      operator,
                      value: metadataOperatorNoValue(operator) ? "" : draft.value,
                      exclude: metadataOperatorNoValue(operator) ? false : draft.exclude,
                    });
                  }}
                >
                  {currentOperatorOptions.map((item) => (
                    <option key={item.value} value={item.value}>{item.label}</option>
                  ))}
                </select>
                <input
                  value={draft.value}
                  disabled={isValueFreeOperator}
                  onChange={(event) => setDraft({ ...draft, value: event.target.value })}
                  placeholder={metadataOperatorPlaceholder(draft.operator, selectedIndicator.data_type)}
                  autoFocus
                />
              </div>

              <div className="condition-form-row narrow-row">
                <label>截取前N条</label>
                <select value={draft.truncateMode} onChange={(event) => setDraft({ ...draft, truncateMode: event.target.value })}>
                  <option value="none">不截断</option>
                  <option value="top">截取前N条</option>
                  <option value="bottom">截取后N条</option>
                </select>
                <input
                  value={draft.truncateCount}
                  disabled={draft.truncateMode === "none"}
                  onChange={(event) => setDraft({ ...draft, truncateCount: event.target.value })}
                  placeholder="N"
                />
              </div>
            </>
          )}
        </div>

        <div className="condition-modal-foot">
          <div>
            {selectedIndicator && (
              <span>
                当前选择：{selectedIndicator.name_zh} · {timeframeLabels[selectedIndicator.storage_period] ?? selectedIndicator.storage_period}
              </span>
            )}
            {error && <strong>{error}</strong>}
          </div>
          <button className="primary-action" disabled={!canAdd} onClick={applyCondition}>
            {initialCondition ? "保存并刷新" : "应用条件"}
          </button>
        </div>
      </div>
    </div>
  );
}

function ContractListPage({
  summary,
  onSummaryRefresh,
}: {
  summary: DataSummary | null;
  onSummaryRefresh: () => void | Promise<void>;
}) {
  const periods = summary?.timeframes.map((item) => item.key) ?? ["1m", "5m", "15m", "1H", "1D"];
  const [storagePeriod, setStoragePeriod] = useState("1m");
  const [date, setDate] = useState("");
  const [query, setQuery] = useState("");
  const [data, setData] = useState<ContractListResponse | null>(null);
  const [updateStatus, setUpdateStatus] = useState<ContractUpdateStatus | null>(null);
  const [qualitySummary, setQualitySummary] = useState<DataQualitySummary | null>(null);
  const [qualityDates, setQualityDates] = useState<DataQualityDateReport | null>(null);
  const [qualityOpen, setQualityOpen] = useState(false);
  const [qualityLoading, setQualityLoading] = useState(false);
  const [qualityError, setQualityError] = useState<string | null>(null);
  const [contractQualityTarget, setContractQualityTarget] = useState<string | null>(null);
  const [contractQuality, setContractQuality] = useState<DataQualityContractReport | null>(null);
  const [contractQualityLoading, setContractQualityLoading] = useState(false);
  const [contractQualityError, setContractQualityError] = useState<string | null>(null);
  const [startingUpdate, setStartingUpdate] = useState(false);
  const [repairTarget, setRepairTarget] = useState<string | null>(null);
  const [repairAllOpen, setRepairAllOpen] = useState(false);
  const [repairStartDate, setRepairStartDate] = useState("2026-01-01");
  const [startingRepair, setStartingRepair] = useState(false);
  const [updateNotice, setUpdateNotice] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const updateWasRunningRef = useRef(false);
  const lastTaskModeRef = useRef<"update" | "repair" | null>(null);

  useEffect(() => {
    const current = currentTimeframe(summary, storagePeriod);
    if (current) {
      setDate(preferredContractDate(current));
    }
  }, [summary, storagePeriod]);

  useEffect(() => {
    if (date) void loadContracts();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [date, storagePeriod]);

  useEffect(() => {
    void loadUpdateStatus();
  }, []);

  useEffect(() => {
    void loadQualityOverview();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storagePeriod]);

  useEffect(() => {
    if (!updateStatus?.running) return;
    const timer = window.setInterval(() => {
      void loadUpdateStatus();
    }, 2500);
    return () => window.clearInterval(timer);
  }, [updateStatus?.running]);

  useEffect(() => {
    if (updateStatus?.running) {
      updateWasRunningRef.current = true;
      return;
    }
    if (!updateStatus || !updateWasRunningRef.current) return;
    updateWasRunningRef.current = false;
    if (updateStatus.success) {
      const mode = updateStatus.options?.mode === "repair" ? "repair" : lastTaskModeRef.current;
      setUpdateNotice(mode === "repair" ? "补数完成，缺失1分钟K线已补齐并重建聚合数据。" : "更新部署完成。");
    }
    void onSummaryRefresh();
    void loadContracts();
    void loadQualityOverview(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [updateStatus?.running, updateStatus?.success]);

  async function loadContracts() {
    setLoading(true);
    setError(null);
    try {
      const result = await fetchActiveContracts({
        timeframe: storagePeriod,
        date: date || undefined,
        query,
        limit: 5000,
      });
      setData(result);
      if (!date && result.date) setDate(result.date);
    } catch (err) {
      setError(err instanceof Error ? err.message : "合约列表加载失败");
    } finally {
      setLoading(false);
    }
  }

  async function loadUpdateStatus() {
    try {
      const status = await fetchContractUpdateStatus(12000);
      setUpdateStatus(status);
    } catch (err) {
      setError(err instanceof Error ? err.message : "更新状态读取失败");
    }
  }

  async function loadQualityOverview(force = false) {
    setQualityLoading(true);
    setQualityError(null);
    try {
      const [summaryResult, dateResult] = await Promise.all([
        fetchDataQualitySummary({ timeframe: storagePeriod, force }),
        fetchDataQualityDates({ timeframe: storagePeriod, limit: 90, force }),
      ]);
      setQualitySummary(summaryResult);
      setQualityDates(dateResult);
    } catch (err) {
      setQualityError(err instanceof Error ? err.message : "数据完整性报告加载失败");
    } finally {
      setQualityLoading(false);
    }
  }

  async function openContractQuality(instId: string) {
    setContractQualityTarget(instId);
    setContractQuality(null);
    setContractQualityLoading(true);
    setContractQualityError(null);
    try {
      const report = await fetchDataQualityContract(instId, 30);
      setContractQuality(report);
    } catch (err) {
      setContractQualityError(err instanceof Error ? err.message : "单合约数据报告加载失败");
    } finally {
      setContractQualityLoading(false);
    }
  }

  async function startUpdateDeploy() {
    setStartingUpdate(true);
    setError(null);
    setUpdateNotice(null);
    try {
      lastTaskModeRef.current = "update";
      const status = await startContractUpdateDeploy({
        force: true,
        limit: 300,
        build_daily: true,
        daily_days: 10,
      });
      setUpdateStatus(status);
    } catch (err) {
      setError(err instanceof Error ? err.message : "更新部署启动失败");
    } finally {
      setStartingUpdate(false);
    }
  }

  async function startRepairDeploy() {
    if (!repairTarget && !repairAllOpen) return;
    setStartingRepair(true);
    setError(null);
    setUpdateNotice(null);
    try {
      lastTaskModeRef.current = "repair";
      const status = await startContractUpdateDeploy({
        force: true,
        limit: 300,
        build_daily: true,
        daily_days: 365,
        symbols: repairTarget ? [repairTarget] : null,
        repair_start: repairStartDate.replaceAll("-", ""),
      });
      setUpdateStatus(status);
      setRepairTarget(null);
      setRepairAllOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "补数部署启动失败");
    } finally {
      setStartingRepair(false);
    }
  }

  const rows = data?.rows ?? [];
  const tf = currentTimeframe(summary, storagePeriod);
  const updateRunning = Boolean(updateStatus?.running);
  const updateLabel = updateStatus?.stage_label ?? "未运行";
  const latestQualityTimeframe = qualitySummary?.timeframes.find((item) => item.timeframe === storagePeriod);

  return (
    <>
    <section className="metadata-page contract-list-page">
      <div className="metadata-page-head">
        <div>
          <h1>合约列表 ({data?.total_count ?? rows.length})</h1>
          <p className="contract-page-subtitle">
            记录当前仍在交易、并展示本地最新K线数据的合约。
          </p>
        </div>
        <div className="metadata-actions">
          <button className="secondary-action" onClick={() => {
            setQualityOpen(true);
            void loadQualityOverview();
          }}>
            数据完整性报告
          </button>
          <button
            className="primary-action"
            disabled={startingUpdate || updateRunning}
            onClick={() => void startUpdateDeploy()}
          >
            {updateRunning ? "更新中..." : startingUpdate ? "启动中..." : "更新部署"}
          </button>
          <button
            className="secondary-action"
            disabled={startingRepair || updateRunning}
            onClick={() => {
              setRepairTarget(null);
              setRepairAllOpen(true);
              setRepairStartDate("2026-01-01");
              setUpdateNotice(null);
            }}
          >
            {startingRepair ? "启动中..." : "全部补数"}
          </button>
          <button
            className="secondary-action" onClick={() => void loadContracts()}>
            刷新
          </button>
        </div>
      </div>

      <div className="contract-summary-strip">
        <div>
          <span>数据周期</span>
          <strong>{timeframeLabels[storagePeriod] ?? storagePeriod}</strong>
        </div>
        <div>
          <span>基准日期</span>
          <strong>{formatDateBadge(data?.date ?? date) || "--"}</strong>
        </div>
        <div>
          <span>在线合约</span>
          <strong>{data?.total_count ?? 0}</strong>
        </div>
        <div>
          <span>最新数据分区</span>
          <strong>{formatDateBadge(tf?.latest_date ?? "") || "--"}</strong>
        </div>
        <div className={`quality-strip-card ${qualitySummary?.status ?? ""}`}>
          <span>数据健康</span>
          <strong>{qualityLoading ? "检查中" : qualitySummary?.status_label ?? "--"}</strong>
          {latestQualityTimeframe && <em>缺 {latestQualityTimeframe.missing_latest_count} / 多 {latestQualityTimeframe.extra_latest_count}</em>}
        </div>
      </div>

      <div className={updateRunning ? "contract-update-panel running" : updateStatus?.success === false ? "contract-update-panel failed" : "contract-update-panel"}>
        <div className="contract-update-main">
          <span>更新部署</span>
          <strong>{updateLabel}</strong>
          {updateStatus?.error && <em>{updateStatus.error}</em>}
          {updateNotice && !updateStatus?.running && updateStatus?.success && <em className="contract-update-success">{updateNotice}</em>}
        </div>
        <div className="contract-update-meta">
          <span>数据目录：{updateStatus?.data_root ?? "等待状态"}</span>
          <span>{updateStatus?.finished_at ? `完成时间：${formatDateTime(updateStatus.finished_at)}` : updateStatus?.started_at ? `开始时间：${formatDateTime(updateStatus.started_at)}` : "尚未启动"}</span>
        </div>
        <details className="contract-update-log">
          <summary>查看日志</summary>
          <pre>{updateStatus?.log_tail || "暂无日志"}</pre>
        </details>
      </div>

      <div className="metadata-filterbar contract-filterbar">
        <label>
          <span>关键词</span>
          <input
            value={query}
            placeholder="BTC / ETH / 合约代码"
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void loadContracts();
            }}
          />
        </label>
        <label>
          <span>数据周期</span>
          <select value={storagePeriod} onChange={(event) => setStoragePeriod(event.target.value)}>
            {periods.map((period) => (
              <option key={period} value={period}>{timeframeLabels[period] ?? period}</option>
            ))}
          </select>
        </label>
        <label>
          <span>数据日期</span>
          <input type="date" value={date} onChange={(event) => setDate(event.target.value)} />
        </label>
        <button className="query-button" disabled={loading} onClick={() => void loadContracts()}>
          查询
        </button>
      </div>

      <div className="metadata-table-shell">
        {error && <div className="inline-error">{error}</div>}
        <div className="metadata-table-wrap contract-list-table-wrap">
          <table className="metadata-table contract-list-table">
            <thead>
              <tr>
                <th className="contract-index-col">序号</th>
                <th>合约</th>
                <th>标的</th>
                <th>最新价格</th>
                <th>最新K线时间</th>
                <th>周期</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={8}>
                    <EmptyState title="正在加载合约" text="读取当前在线合约与本地K线数据。" />
                  </td>
                </tr>
              ) : rows.length === 0 ? (
                <tr>
                  <td colSpan={8}>
                    <EmptyState title="暂无合约" text="当前条件下没有找到合约，换个日期或搜索词试试。" />
                  </td>
                </tr>
              ) : (
                rows.map((row, index) => (
                  <tr key={row.inst_id}>
                    <td className="contract-index-col">{index + 1}</td>
                    <td className="contract-inst-id">{row.inst_id}</td>
                    <td>{row.symbol || compactSymbolName(row.inst_id)}</td>
                    <td className="numeric-id">{formatContractPrice(row.latest_close)}</td>
                    <td>{row.latest_time ?? "--"}</td>
                    <td>{timeframeLabels[data?.timeframe ?? storagePeriod] ?? data?.timeframe ?? storagePeriod}</td>
                    <td><span className="contract-status-badge">交易中</span></td>
                    <td className="contract-row-actions">
                      <button className="quality-report-button" onClick={() => void openContractQuality(row.inst_id)}>
                        报告
                      </button>
                      <button
                        className="quality-report-button"
                        disabled={updateRunning || startingRepair}
                        onClick={() => {
                          setRepairTarget(row.inst_id);
                          setRepairStartDate("2026-01-01");
                          setUpdateNotice(null);
                        }}
                      >
                        补数
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        <div className="metadata-pagination">
          <span>共{data?.total_count ?? rows.length}条</span>
          <button disabled>‹</button>
          <button className="current-page">1</button>
          <button disabled>›</button>
          <select value="all" disabled>
            <option value="all">全部</option>
          </select>
        </div>
      </div>
    </section>
    {qualityOpen && (
      <DataQualityModal
        summary={qualitySummary}
        dates={qualityDates}
        timeframe={storagePeriod}
        loading={qualityLoading}
        error={qualityError}
        onClose={() => setQualityOpen(false)}
        onRefresh={() => void loadQualityOverview(true)}
        onOpenContract={(instId) => void openContractQuality(instId)}
      />
    )}
    {contractQualityTarget && (
      <ContractQualityModal
        instId={contractQualityTarget}
        report={contractQuality}
        loading={contractQualityLoading}
        error={contractQualityError}
        onClose={() => {
          setContractQualityTarget(null);
          setContractQuality(null);
          setContractQualityError(null);
        }}
      />
    )}
    {(repairTarget || repairAllOpen) && (
      <div className="modal-backdrop repair-backdrop" role="presentation" onMouseDown={() => {
        setRepairTarget(null);
        setRepairAllOpen(false);
      }}>
        <div className="repair-modal" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}>
          <div className="modal-head">
            <div>
              <h2>{repairTarget ? `补数：${repairTarget}` : "全部合约补数"}</h2>
              <p>{repairTarget ? "按指定开始日期补齐该合约到昨日的缺失1分钟K线，并重建5分钟、15分钟、1小时和日线数据。" : "按指定开始日期补齐全部合约到昨日的缺失1分钟K线，并重建5分钟、15分钟、1小时和日线数据。"}</p>
            </div>
            <button className="close-button" onClick={() => {
              setRepairTarget(null);
              setRepairAllOpen(false);
            }}>×</button>
          </div>
          <div className="repair-form">
            <label>
              <span>补数开始日期</span>
              <input type="date" value={repairStartDate} onChange={(event) => setRepairStartDate(event.target.value)} />
            </label>
          </div>
          <div className="modal-actions">
            <button className="secondary-action" disabled={startingRepair} onClick={() => {
              setRepairTarget(null);
              setRepairAllOpen(false);
            }}>取消</button>
            <button className="primary-action" disabled={startingRepair || updateRunning || !repairStartDate} onClick={() => void startRepairDeploy()}>
              {startingRepair ? "启动中..." : "开始补数"}
            </button>
          </div>
        </div>
      </div>
    )}
    </>
  );
}

function DataQualityModal({
  summary,
  dates,
  timeframe,
  loading,
  error,
  onClose,
  onRefresh,
  onOpenContract,
}: {
  summary: DataQualitySummary | null;
  dates: DataQualityDateReport | null;
  timeframe: string;
  loading: boolean;
  error: string | null;
  onClose: () => void;
  onRefresh: () => void;
  onOpenContract: (instId: string) => void;
}) {
  const abnormalDates = dates?.rows.filter((row) => row.status !== "ok") ?? [];
  const latestDateRows = dates?.rows.slice(0, 12) ?? [];
  const issues = summary?.top_contract_issues ?? [];

  return (
    <div className="modal-backdrop quality-backdrop" role="presentation" onMouseDown={onClose}>
      <div className="quality-modal" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}>
        <div className="modal-head quality-modal-head">
          <div>
            <span className="eyebrow">数据体检中心</span>
            <h2>数据完整性报告</h2>
          </div>
          <div className="quality-head-actions">
            <button className="secondary-action" disabled={loading} onClick={onRefresh}>重新检查</button>
            <button className="close-button" onClick={onClose}>×</button>
          </div>
        </div>

        {loading ? (
          <EmptyState title="正在生成报告" text="检查合约维表、交易日文件数和已有缺口报告。" />
        ) : error ? (
          <EmptyState title="报告加载失败" text={error} />
        ) : summary && dates ? (
          <>
            <div className="quality-summary-grid">
              <div className={`quality-status-card ${summary.status}`}>
                <span>整体状态</span>
                <strong>{summary.status_label}</strong>
                <em>{timeframeLabels[summary.timeframe] ?? summary.timeframe}</em>
              </div>
              <div>
                <span>在线合约</span>
                <strong>{summary.online_symbols}</strong>
                <em>维表 {summary.catalog_updated_at ?? "--"}</em>
              </div>
              <div>
                <span>健康基准分区</span>
                <strong>{formatDateBadge(summary.latest_date ?? "") || "--"}</strong>
                <em>{summary.latest_file_count}/{summary.expected_latest_count} 文件</em>
              </div>
              <div>
                <span>最新缺失/多余</span>
                <strong>{summary.missing_latest_count}/{summary.extra_latest_count}</strong>
                <em>按合约生命周期判断</em>
              </div>
              <div>
                <span>质量报告覆盖</span>
                <strong>{summary.quality_report.symbols}</strong>
                <em>{summary.quality_report.source || "实时文件数"}</em>
              </div>
            </div>

            {summary.issues.length > 0 && (
              <div className="quality-issue-banner">
                {summary.issues.map((item) => <span key={item}>{item}</span>)}
              </div>
            )}

            <div className="quality-section-grid">
              <section className="quality-panel">
                <div className="quality-panel-head">
                  <strong>各周期健康基准</strong>
                  <span>优先使用最近完整分区，避免盘中半截数据误报</span>
                </div>
                <div className="quality-table-wrap">
                  <table className="quality-table">
                    <thead>
                      <tr>
                        <th>周期</th>
                        <th>基准日期</th>
                        <th>实际/应有</th>
                        <th>缺失</th>
                        <th>状态</th>
                      </tr>
                    </thead>
                    <tbody>
                      {summary.timeframes.map((item) => (
                        <tr key={item.timeframe}>
                          <td>{timeframeLabels[item.timeframe] ?? item.timeframe}</td>
                          <td>{formatDateBadge(item.latest_date ?? "") || "--"}</td>
                          <td>{item.latest_file_count}/{item.expected_latest_count}</td>
                          <td>{item.missing_latest_count}</td>
                          <td><QualityBadge status={item.status} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>

              <section className="quality-panel">
                <div className="quality-panel-head">
                  <strong>已有缺口报告</strong>
                  <span>{issues.length ? "点击合约可打开实时详情" : "当前已有报告没有发现异常合约"}</span>
                </div>
                <div className="quality-issue-list">
                  {issues.length === 0 ? (
                    <p>暂无合约级缺口记录；如需精确判断，点击合约列表每行的「报告」实时扫描。</p>
                  ) : (
                    issues.slice(0, 8).map((item) => (
                      <button key={item.inst_id} onClick={() => onOpenContract(item.inst_id)}>
                        <strong>{item.inst_id}</strong>
                        <span>缺口 {item.gaps} · 重复 {item.duplicates} · 未确认 {item.unconfirmed}</span>
                      </button>
                    ))
                  )}
                </div>
              </section>
            </div>

            <section className="quality-panel">
              <div className="quality-panel-head">
                <strong>交易日合约数异常</strong>
                <span>最近 {dates.returned_count} 个交易日，异常 {abnormalDates.length} 天</span>
              </div>
              <div className="quality-table-wrap large">
                <table className="quality-table">
                  <thead>
                    <tr>
                      <th>日期</th>
                      <th>周期</th>
                      <th>实际</th>
                      <th>应有</th>
                      <th>缺失</th>
                      <th>多余</th>
                      <th>状态</th>
                      <th>样例</th>
                    </tr>
                  </thead>
                  <tbody>
                    {latestDateRows.map((row) => (
                      <tr key={row.date}>
                        <td>{formatDateBadge(row.date)}</td>
                        <td>{timeframeLabels[row.timeframe] ?? row.timeframe}</td>
                        <td>{row.actual_count}</td>
                        <td>{row.expected_count}</td>
                        <td>{row.missing_count}</td>
                        <td>{row.extra_count}</td>
                        <td><QualityBadge status={row.status} /></td>
                        <td className="quality-sample-cell">{qualitySampleText(row.missing_symbols, row.extra_symbols)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          </>
        ) : (
          <EmptyState title="暂无报告" text="点击重新检查生成数据完整性报告。" />
        )}
      </div>
    </div>
  );
}

function ContractQualityModal({
  instId,
  report,
  loading,
  error,
  onClose,
}: {
  instId: string;
  report: DataQualityContractReport | null;
  loading: boolean;
  error: string | null;
  onClose: () => void;
}) {
  const issueFrames = report?.timeframes.filter((item) => item.status !== "ok") ?? [];

  return (
    <div className="modal-backdrop quality-backdrop" role="presentation" onMouseDown={onClose}>
      <div className="quality-modal contract-quality-modal" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}>
        <div className="modal-head quality-modal-head">
          <div>
            <span className="eyebrow">单合约数据报告</span>
            <h2>{instId}</h2>
          </div>
          <button className="close-button" onClick={onClose}>×</button>
        </div>

        {loading ? (
          <EmptyState title="正在扫描合约" text="读取该合约所有周期的 K 线文件，检查缺口、重复和未确认数据。" />
        ) : error ? (
          <EmptyState title="合约报告加载失败" text={error} />
        ) : report ? (
          <>
            <div className="quality-summary-grid contract-quality-grid">
              <div className={`quality-status-card ${report.status}`}>
                <span>整体状态</span>
                <strong>{report.status_label}</strong>
                <em>{report.instrument.is_online ? "在线合约" : "非在线/未知"}</em>
              </div>
              <div>
                <span>上市时间</span>
                <strong>{report.instrument.list_time_text ?? "--"}</strong>
                <em>{report.instrument.state}</em>
              </div>
              <div>
                <span>最新数据</span>
                <strong>{report.latest_time ?? "--"}</strong>
                <em>跨周期最大时间</em>
              </div>
              <div>
                <span>异常周期</span>
                <strong>{issueFrames.length}</strong>
                <em>共 {report.timeframes.length} 个周期</em>
              </div>
            </div>

            <section className="quality-panel">
              <div className="quality-panel-head">
                <strong>周期完整性</strong>
                <span>覆盖率按已存在行与检测到的缺失 K 线估算</span>
              </div>
              <div className="quality-table-wrap">
                <table className="quality-table">
                  <thead>
                    <tr>
                      <th>周期</th>
                      <th>文件</th>
                      <th>行数</th>
                      <th>覆盖率</th>
                      <th>缺K</th>
                      <th>重复</th>
                      <th>未确认</th>
                      <th>起止时间</th>
                      <th>状态</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.timeframes.map((item) => (
                      <tr key={item.timeframe}>
                        <td>{timeframeLabels[item.timeframe] ?? item.timeframe}</td>
                        <td>{item.file_count}/{item.expected_file_count}</td>
                        <td>{formatCompact(item.row_count)}</td>
                        <td>{item.coverage_pct ? `${item.coverage_pct.toFixed(2)}%` : "--"}</td>
                        <td>{item.missing_bars}</td>
                        <td>{item.duplicate_rows}</td>
                        <td>{item.unconfirmed_rows}</td>
                        <td>{item.start_time ?? "--"} → {item.end_time ?? "--"}</td>
                        <td><QualityBadge status={item.status} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            <section className="quality-panel">
              <div className="quality-panel-head">
                <strong>缺口明细</strong>
                <span>{issueFrames.length ? "展示每个异常周期的前 30 个缺口样例" : "没有检测到中间断 K"}</span>
              </div>
              {issueFrames.length === 0 ? (
                <div className="quality-empty-note">当前合约未发现缺口、缺文件、重复或未确认 K 线。</div>
              ) : (
                <div className="gap-sample-list">
                  {issueFrames.map((frame) => (
                    <article key={frame.timeframe}>
                      <div>
                        <strong>{timeframeLabels[frame.timeframe] ?? frame.timeframe}</strong>
                        <span>缺文件 {frame.missing_file_count} · 缺K {frame.missing_bars} · 重复 {frame.duplicate_rows}</span>
                      </div>
                      {frame.missing_dates.length > 0 && (
                        <p>缺失日期：{frame.missing_dates.slice(0, 12).map(formatDateBadge).join("、")}{frame.missing_dates.length > 12 ? " ..." : ""}</p>
                      )}
                      {frame.gap_samples.length === 0 ? (
                        <p>没有中间断 K 样例。</p>
                      ) : (
                        frame.gap_samples.map((gap) => (
                          <p key={`${frame.timeframe}-${gap.prev_ts}-${gap.next_ts}`}>
                            {gap.missing_start ?? "--"} ~ {gap.missing_end ?? "--"}，缺 {gap.missing_count} 根
                          </p>
                        ))
                      )}
                    </article>
                  ))}
                </div>
              )}
            </section>
          </>
        ) : (
          <EmptyState title="等待报告" text="正在准备合约数据完整性报告。" />
        )}
      </div>
    </div>
  );
}

function QualityBadge({ status }: { status: "ok" | "warning" | "fail" }) {
  return <span className={`quality-badge ${status}`}>{qualityStatusText(status)}</span>;
}

function IndicatorProductionPage({ summary }: { summary: DataSummary | null }) {
  const periods = summary?.timeframes.map((item) => item.key) ?? ["1m", "5m", "15m", "1H", "1D"];
  const [items, setItems] = useState<Indicator[]>([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingTarget, setEditingTarget] = useState<Indicator | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Indicator | null>(null);
  const [scriptPreview, setScriptPreview] = useState<Indicator | null>(null);
  const [aiTarget, setAiTarget] = useState<Indicator | null>(null);
  const [form, setForm] = useState(() => defaultScriptIndicatorForm(periods[0] ?? "1m"));
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void loadScriptIndicators();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function loadScriptIndicators() {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchIndicators({ sourceType: "script" });
      setItems(data.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "脚本指标加载失败");
    } finally {
      setLoading(false);
    }
  }

  function openCreateModal() {
    setEditingTarget(null);
    setForm(defaultScriptIndicatorForm(periods[0] ?? "1m"));
    setModalOpen(true);
  }

  function openEditModal(item: Indicator) {
    setEditingTarget(item);
    setForm(scriptIndicatorFormFromItem(item));
    setModalOpen(true);
  }

  async function saveScriptIndicator() {
    const name = form.nameZh.trim();
    if (!name) {
      setError("请输入指标中文名。");
      return;
    }

    setSaving(true);
    setError(null);
    try {
      const payload = {
        id: `script.${form.period}.${form.englishName}`,
        name_zh: name,
        storage_period: form.period,
        data_type: "number",
        unit: "",
        source_type: "script",
        description: "脚本生产指标，可在选币条件中引用。",
      } as const;
      if (editingTarget) {
        await updateIndicator(editingTarget.id, payload);
      } else {
        await createIndicator(payload);
      }
      setEditingTarget(null);
      setModalOpen(false);
      await loadScriptIndicators();
    } catch (err) {
      setError(err instanceof Error ? err.message : editingTarget ? "脚本指标更新失败" : "脚本指标保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function deleteScriptIndicator() {
    if (!deleteTarget) return;
    setDeleting(true);
    setError(null);
    try {
      await deleteIndicator(deleteTarget.id);
      setScriptPreview((current) => (current?.id === deleteTarget.id ? null : current));
      setAiTarget((current) => (current?.id === deleteTarget.id ? null : current));
      setDeleteTarget(null);
      await loadScriptIndicators();
    } catch (err) {
      setError(err instanceof Error ? err.message : "脚本指标删除失败");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <section className="indicator-production-page">
      <div className="production-head">
        <div>
          <h1>指标生产</h1>
          <p>用 shell 脚本生产公式指标；先创建指标卡片，再配置运行、部署和历史回补。</p>
        </div>
        <button className="primary-action" onClick={openCreateModal}>新增指标</button>
      </div>

      {error && <div className="inline-error production-error">{error}</div>}

      {loading ? (
        <EmptyState title="正在加载脚本指标" text="读取指标仓库里的 script 类型指标。" />
      ) : items.length === 0 ? (
        <div className="production-empty">
          <strong>还没有脚本指标</strong>
          <p>点击右上角「新增指标」创建第一个脚本生产指标。</p>
          <button className="primary-action" onClick={openCreateModal}>新增指标</button>
        </div>
      ) : (
        <div className="script-indicator-grid">
          {items.map((item) => (
            <article className="script-indicator-card" key={item.id}>
              <div className="script-card-top">
                <span>脚本指标</span>
                <b>可用于选币</b>
              </div>
              <h2>{item.name_zh}</h2>
              <p>{item.id}</p>
              <div className="script-card-meta">
                <span>{timeframeLabels[item.storage_period] ?? item.storage_period}</span>
                <span>{typeLabel(item.data_type)}</span>
                <span>{item.unit || "无单位"}</span>
              </div>
              <div className="script-card-actions">
                <button onClick={() => setScriptPreview(item)}>查看脚本</button>
                <button className="ai-help-button" onClick={() => setAiTarget(item)}>AI助力</button>
                <button onClick={() => openEditModal(item)}>编辑</button>
                <button className="danger-action" onClick={() => setDeleteTarget(item)}>删除</button>
              </div>
            </article>
          ))}
        </div>
      )}

      {modalOpen && (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => {
          setEditingTarget(null);
          setModalOpen(false);
        }}>
          <div className="script-create-modal" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}>
            <div className="modal-head">
              <div>
                <span className="eyebrow">{editingTarget ? "编辑脚本指标" : "新增脚本指标"}</span>
                <h2>{editingTarget ? "修改指标卡片" : "创建指标卡片"}</h2>
              </div>
              <button className="close-button" onClick={() => {
                setEditingTarget(null);
                setModalOpen(false);
              }}>×</button>
            </div>
            <div className="script-create-body">
              <label>
                指标中文名
                <input
                  value={form.nameZh}
                  placeholder="例如：大阳线放量强度"
                  onChange={(event) => {
                    const nameZh = event.target.value;
                    setForm({ ...form, nameZh, englishName: autoScriptEnglishName(nameZh) });
                  }}
                />
              </label>
              <label>
                指标英文名
                <input value={form.englishName} disabled />
              </label>
              <label>
                指标周期
                <select value={form.period} onChange={(event) => setForm({ ...form, period: event.target.value })}>
                  {periods.map((period) => (
                    <option value={period} key={period}>{timeframeLabels[period] ?? period}</option>
                  ))}
                </select>
              </label>
              <div className="script-id-preview">
                指标 ID：<strong>script.{form.period}.{form.englishName}</strong>
              </div>
              {editingTarget && (
                <p className="script-edit-note">
                  修改中文名或周期后，系统会同步更新指标仓库里的脚本指标 ID。
                </p>
              )}
            </div>
            <div className="modal-actions">
              <button className="secondary-action" onClick={() => {
                setEditingTarget(null);
                setModalOpen(false);
              }}>取消</button>
              <button className="primary-action" disabled={saving || !form.nameZh.trim()} onClick={() => void saveScriptIndicator()}>
                {saving ? "保存中..." : editingTarget ? "保存修改" : "保存"}
              </button>
            </div>
          </div>
        </div>
      )}

      {deleteTarget && (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setDeleteTarget(null)}>
          <div className="script-delete-modal" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}>
            <div className="modal-head">
              <div>
                <span className="eyebrow danger">删除脚本指标</span>
                <h2>{deleteTarget.name_zh}</h2>
              </div>
              <button className="close-button" onClick={() => setDeleteTarget(null)}>×</button>
            </div>
            <p>
              删除后会从指标仓库移除这个 script 类型指标。后续如果已经绑定脚本文件或产出数据，也会以这个指标 ID 为关联入口，请确认不再需要。
            </p>
            <div className="modal-actions">
              <button className="secondary-action" disabled={deleting} onClick={() => setDeleteTarget(null)}>取消</button>
              <button className="danger-confirm" disabled={deleting} onClick={() => void deleteScriptIndicator()}>
                {deleting ? "删除中..." : "确认删除"}
              </button>
            </div>
          </div>
        </div>
      )}

      {scriptPreview && (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setScriptPreview(null)}>
          <div className="script-preview-modal" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}>
            <div className="modal-head">
              <div>
                <span className="eyebrow">查看脚本</span>
                <h2>{scriptPreview.name_zh}</h2>
              </div>
              <button className="close-button" onClick={() => setScriptPreview(null)}>×</button>
            </div>
            <pre>{scriptTemplate(scriptPreview)}</pre>
          </div>
        </div>
      )}

      {aiTarget && (
        <AiScriptWorkspaceModal
          indicator={aiTarget}
          periods={periods}
          summary={summary}
          onClose={() => setAiTarget(null)}
        />
      )}
    </section>
  );
}

function AiScriptWorkspaceModal({
  indicator,
  periods,
  summary,
  onClose,
}: {
  indicator: Indicator;
  periods: string[];
  summary: DataSummary | null;
  onClose: () => void;
}) {
  const [workspace, setWorkspace] = useState<ScriptWorkspaceResponse | null>(null);
  const [requirement, setRequirement] = useState("");
  const [inputTimeframe, setInputTimeframe] = useState(indicator.storage_period);
  const [runDate, setRunDate] = useState(defaultRunDate(summary, indicator.storage_period));
  const [script, setScript] = useState("");
  const [result, setResult] = useState<ScriptTrialRunResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [savingScript, setSavingScript] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setInputTimeframe(indicator.storage_period);
    setRunDate(defaultRunDate(summary, indicator.storage_period));
    void loadWorkspace();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [indicator.id]);

  function changeInputTimeframe(next: string) {
    setInputTimeframe(next);
    setRunDate(defaultRunDate(summary, next));
  }

  async function loadWorkspace() {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchScriptWorkspace(indicator.id);
      setWorkspace(data);
      setScript(data.script);
    } catch (err) {
      setError(err instanceof Error ? err.message : "脚本工作台加载失败");
    } finally {
      setLoading(false);
    }
  }

  async function generateScript() {
    setGenerating(true);
    setError(null);
    try {
      const data = await generateScriptWithAi({
        indicatorId: indicator.id,
        requirement,
        inputTimeframe,
      });
      setScript(data.script);
      setWorkspace((current) => current ? { ...current, prompt: data.prompt, model: data.model, script: data.script } : current);
    } catch (err) {
      setError(err instanceof Error ? err.message : "AI 生成脚本失败");
    } finally {
      setGenerating(false);
    }
  }

  async function saveScript() {
    setSavingScript(true);
    setError(null);
    try {
      const data = await saveScriptIndicatorScript({ indicatorId: indicator.id, script });
      setScript(data.script);
      setWorkspace((current) => current ? { ...current, script: data.script, script_path: data.script_path } : current);
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存脚本失败");
    } finally {
      setSavingScript(false);
    }
  }

  async function trialRun() {
    if (!runDate) {
      setError("请选择试运行日期。");
      return;
    }
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const data = await trialRunScriptIndicator({
        indicatorId: indicator.id,
        date: runDate,
        inputTimeframe,
        script,
        limit: 200,
      });
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "试运行失败");
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="modal-backdrop ai-workspace-backdrop" role="presentation" onMouseDown={onClose}>
      <div className="script-ai-workspace-modal" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}>
        <div className="modal-head">
          <div>
            <span className="eyebrow">AI助力 · 脚本工作台</span>
            <h2>{indicator.name_zh}</h2>
          </div>
          <button className="close-button" onClick={onClose}>×</button>
        </div>

        {error && <div className="inline-error ai-workspace-error">{error}</div>}

        {loading ? (
          <EmptyState title="正在加载脚本工作台" text="读取脚本、内置提示词和本地运行目录。" />
        ) : (
          <>
            <div className="ai-workspace-grid">
              <aside className="ai-workspace-side">
                <label>
                  指标需求
                  <textarea
                    value={requirement}
                    onChange={(event) => setRequirement(event.target.value)}
                    placeholder="描述你想计算的指标，例如：计算每个合约当前15分钟成交额 / 过去1小时平均15分钟成交额。"
                  />
                </label>
                <div className="ai-workspace-row">
                  <label>
                    输入周期
                    <select value={inputTimeframe} onChange={(event) => changeInputTimeframe(event.target.value)}>
                      {periods.map((period) => (
                        <option value={period} key={period}>{timeframeLabels[period] ?? period}</option>
                      ))}
                    </select>
                  </label>
                  <label>
                    试运行日期
                    <input type="date" value={runDate} onChange={(event) => setRunDate(event.target.value)} />
                  </label>
                </div>
                <div className="ai-workspace-actions">
                  <button className="primary-action" disabled={generating} onClick={() => void generateScript()}>
                    {generating ? "生成中..." : "AI生成脚本"}
                  </button>
                  <button className="secondary-action" disabled={savingScript || !script.trim()} onClick={() => void saveScript()}>
                    {savingScript ? "保存中..." : "保存脚本"}
                  </button>
                  <button className="run-action" disabled={running || !script.trim()} onClick={() => void trialRun()}>
                    {running ? "试运行中..." : "试运行"}
                  </button>
                </div>
                <div className="ai-workspace-meta">
                  <span>模型：{workspace?.model || "--"}</span>
                  <span>{workspace?.openai_configured ? "OpenAI Key 已配置" : "OpenAI Key 未配置"}</span>
                  <span>输出目录：{workspace?.output_dir || "--"}</span>
                </div>
              </aside>

              <main className="ai-code-panel">
                <div className="ai-code-head">
                  <strong>可运行脚本</strong>
                  <span>必须写入环境变量 OUTPUT_FILE 指定的 CSV。</span>
                </div>
                <textarea value={script} onChange={(event) => setScript(event.target.value)} spellCheck={false} />
              </main>
            </div>

            <details className="ai-prompt-preview">
              <summary>查看内置提示词</summary>
              <pre>{workspace?.prompt}</pre>
            </details>

            {result && (
              <div className={result.success ? "ai-run-result success" : "ai-run-result failed"}>
                <div className="ai-run-head">
                  <strong>{result.success ? "试运行成功" : "试运行失败"}</strong>
                  <span>耗时 {result.elapsed_ms}ms · 输出 {result.output_count} 条 · 返回 {result.returned_count} 条</span>
                  <span>{result.output_file}</span>
                </div>
                {result.rows.length > 0 && (
                  <div className="ai-run-table-wrap">
                    <table className="ai-run-table">
                      <thead>
                        <tr>
                          <th>序号</th>
                          <th>合约</th>
                          <th>时间戳</th>
                          <th>指标值</th>
                        </tr>
                      </thead>
                      <tbody>
                        {result.rows.map((row, index) => (
                          <tr key={`${row.inst_id}-${index}`}>
                            <td>{index + 1}</td>
                            <td>{row.inst_id}</td>
                            <td>{row.ts}</td>
                            <td>{row.value}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                {(result.stdout || result.stderr) && (
                  <div className="ai-run-logs">
                    {result.stdout && <pre>{result.stdout}</pre>}
                    {result.stderr && <pre className="stderr">{result.stderr}</pre>}
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function MetadataConditionCard({
  condition,
  index,
  hitCount,
  onRemove,
}: {
  condition: MetadataCondition;
  index: number;
  hitCount?: number;
  onRemove: () => void;
}) {
  return (
    <div className={condition.exclude ? "metadata-condition-card excluded" : "metadata-condition-card"}>
      <div className="metadata-condition-card-head">
        <span>条件 {index}</span>
        <button onClick={onRemove}>移除</button>
      </div>
      <strong>{condition.indicator.name_zh}</strong>
      <p>{metadataConditionText(condition)}</p>
      <div className="metadata-condition-card-foot">
        <span>{timeframeLabels[condition.indicator.storage_period] ?? condition.indicator.storage_period}</span>
        <b>{hitCount === undefined ? "--" : hitCount} 命中</b>
      </div>
    </div>
  );
}

function IndicatorWarehousePage({ summary }: { summary: DataSummary | null }) {
  const periods = summary?.timeframes.map((item) => item.key) ?? ["1m", "5m", "15m", "1H", "1D"];
  const [catalog, setCatalog] = useState<IndicatorCatalogResponse | null>(null);
  const [storagePeriod, setStoragePeriod] = useState("all");
  const [search, setSearch] = useState("");
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [preview, setPreview] = useState<{
    item: Indicator;
    date?: string;
    time: string;
    query: string;
    rows: Array<{ inst_id: string; value: string; ts?: string; time?: string | null }>;
    loading: boolean;
    error?: string | null;
  } | null>(null);
  const [form, setForm] = useState(defaultIndicatorForm("1m"));

  useEffect(() => {
    void loadCatalog();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storagePeriod]);

  async function loadCatalog() {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchIndicators({ storagePeriod, query: search });
      setCatalog(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "指标仓库加载失败");
    } finally {
      setLoading(false);
    }
  }

  function openCreateModal() {
    const period = storagePeriod === "all" ? periods[0] ?? "1m" : storagePeriod;
    setForm(defaultIndicatorForm(period));
    setModalOpen(true);
  }

  async function saveIndicator() {
    setSaving(true);
    setError(null);
    try {
      await createIndicator(form);
      setModalOpen(false);
      setForm(defaultIndicatorForm(form.storage_period));
      await loadCatalog();
    } catch (err) {
      setError(err instanceof Error ? err.message : "指标保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function openPreview(item: Indicator) {
    const tf = summary?.timeframes.find(
      (candidate) => candidate.key.toLowerCase() === item.storage_period.toLowerCase(),
    );
    const date = tf?.recommended_date ?? tf?.latest_date ?? undefined;
    if (!date) {
      setPreview({ item, rows: [], time: "", query: "", loading: false, error: "没有找到可预览的数据分区。" });
      return;
    }
    await loadPreview(item, date, "", "");
  }

  async function loadPreview(item: Indicator, date: string, time: string, query: string) {
    setPreview({ item, date, time, query, rows: [], loading: true, error: null });

    try {
      const data = await fetchIndicatorValuePreview({
        indicatorId: item.id,
        date,
        time,
        query,
        limit: 200,
      });
      setPreview({
        item,
        date,
        time,
        query,
        rows: data.rows,
        loading: false,
        error: data.message ?? null,
      });
    } catch (err) {
      setPreview({
        item,
        date,
        time,
        query,
        rows: [],
        loading: false,
        error: err instanceof Error ? err.message : "数据预览失败",
      });
    }
  }

  const items = catalog?.items ?? [];
  const total = catalog?.summary.total ?? 0;

  return (
    <section className="metadata-page">
      <div className="metadata-page-head">
        <div>
          <h1>全部元数据 ({total})</h1>
        </div>
        <div className="metadata-actions">
          <button className="secondary-action">导出字段</button>
          <button className="primary-action" onClick={openCreateModal}>新增元数据</button>
        </div>
      </div>

      <div className="metadata-filterbar">
        <label>
          <span>关键词</span>
          <input
            value={search}
            placeholder="中文/英文/id"
            onChange={(event) => setSearch(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void loadCatalog();
            }}
          />
        </label>
        <label>
          <span>存储周期</span>
          <select value={storagePeriod} onChange={(event) => setStoragePeriod(event.target.value)}>
            <option value="all">请选择</option>
            {periods.map((period) => (
              <option key={period} value={period}>{timeframeLabels[period] ?? period}</option>
            ))}
          </select>
        </label>
        <label>
          <span>上线状态</span>
          <select value="online" disabled>
            <option value="online">已上线</option>
          </select>
        </label>
        <label className="wide-filter">
          <span>指标分类</span>
          <select value="local" disabled>
            <option value="local">本地原始字段</option>
          </select>
        </label>
        <button className="link-action">更多条件</button>
        <button className="query-button" onClick={() => void loadCatalog()}>查询</button>
      </div>

      <div className="metadata-table-shell">
        {error && <div className="inline-error">{error}</div>}
        <div className="metadata-table-wrap">
          <table className="metadata-table">
            <thead>
              <tr>
                <th className="check-col"><input type="checkbox" aria-label="全选" /></th>
                <th>字段名称</th>
                <th>英文名称</th>
                <th>ID</th>
                <th>数据类型</th>
                <th>存储周期</th>
                <th>单位</th>
                <th>最新指标时间</th>
                <th className="operation-col">操作</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id}>
                  <td className="check-col"><input type="checkbox" aria-label={`选择 ${item.id}`} /></td>
                  <td><button className="field-link">{item.name_zh}</button></td>
                  <td className="english-name">{englishName(item)}</td>
                  <td className="numeric-id">{stableNumericId(item.id)}</td>
                  <td>{typeLabel(item.data_type)}</td>
                  <td>{timeframeLabels[item.storage_period] ?? item.storage_period}</td>
                  <td>{item.unit || "--"}</td>
                  <td>{formatDateCompact(item.updated_at)}</td>
                  <td className="operation-col">
                    <div className="row-actions">
                      <button onClick={() => void openPreview(item)}>数据预览</button>
                    </div>
                  </td>
                </tr>
              ))}
              {!loading && items.length === 0 && (
                <tr>
                  <td colSpan={9}>
                    <EmptyState title="没有匹配元数据" text="换一个搜索词，或点击右上角新增元数据。" />
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="metadata-pagination">
          <span>共{items.length}条</span>
          <button disabled>‹</button>
          <button className="current-page">1</button>
          <button disabled>›</button>
          <select value="50" disabled>
            <option value="50">50条/页</option>
          </select>
        </div>
      </div>

      {modalOpen && (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setModalOpen(false)}>
          <div className="metadata-modal" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}>
            <div className="modal-head">
              <div>
                <span className="eyebrow">新增元数据</span>
                <h2>登记指标元数据</h2>
              </div>
              <button className="close-button" onClick={() => setModalOpen(false)}>×</button>
            </div>
            <div className="modal-form-grid">
              <label>
                指标 ID
                <input
                  value={form.id}
                  onChange={(event) => setForm({ ...form, id: event.target.value })}
                  placeholder="manual.1m.factor_name"
                />
              </label>
              <label>
                中文名
                <input
                  value={form.name_zh}
                  onChange={(event) => setForm({ ...form, name_zh: event.target.value })}
                  placeholder="例如：近15分钟涨幅"
                />
              </label>
              <label>
                存储周期
                <select
                  value={form.storage_period}
                  onChange={(event) => {
                    const nextPeriod = event.target.value;
                    setForm({
                      ...form,
                      storage_period: nextPeriod,
                      id: form.id.replace(/manual\.[^.]+\./, `manual.${nextPeriod}.`),
                    });
                  }}
                >
                  {periods.map((period) => (
                    <option key={period} value={period}>{timeframeLabels[period] ?? period}</option>
                  ))}
                </select>
              </label>
              <label>
                数据类型
                <select
                  value={form.data_type}
                  onChange={(event) =>
                    setForm({ ...form, data_type: event.target.value as Indicator["data_type"] })
                  }
                >
                  <option value="number">小数 number</option>
                  <option value="string">文本 string</option>
                  <option value="datetime">时间 datetime</option>
                  <option value="boolean">布尔 boolean</option>
                </select>
              </label>
              <label>
                单位
                <input
                  value={form.unit}
                  onChange={(event) => setForm({ ...form, unit: event.target.value })}
                  placeholder="例如 % / USDT / x"
                />
              </label>
              <label className="full-field">
                描述
                <textarea
                  value={form.description}
                  onChange={(event) => setForm({ ...form, description: event.target.value })}
                  placeholder="这个指标表达什么，后续如何被选币复用"
                />
              </label>
            </div>
            <div className="modal-actions">
              <button className="secondary-action" onClick={() => setModalOpen(false)}>取消</button>
              <button
                className="primary-action"
                disabled={saving || !form.id || !form.name_zh}
                onClick={() => void saveIndicator()}
              >
                {saving ? "保存中..." : "保存"}
              </button>
            </div>
          </div>
        </div>
      )}

      {preview && (
        <div className="modal-backdrop preview-backdrop" role="presentation" onMouseDown={() => setPreview(null)}>
          <div className="preview-modal large" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}>
            <div className="preview-title-row">
              <h2>{preview.item.name_zh}</h2>
              <button className="preview-close" onClick={() => setPreview(null)}>×</button>
            </div>
            <div className="preview-toolbar-title">预览数据</div>
            <div className="preview-toolbar">
              <label className="preview-date-field">
                <span>日期：</span>
                <input
                  type="date"
                  value={preview.date ?? ""}
                  onChange={(event) => setPreview({ ...preview, date: event.target.value })}
                />
              </label>
              <label className="preview-time-field">
                <span>时间：</span>
                <input
                  type="time"
                  value={preview.time}
                  onChange={(event) => setPreview({ ...preview, time: event.target.value })}
                />
              </label>
              <input
                className="preview-search"
                value={preview.query}
                placeholder="合约名称、代码"
                onChange={(event) => setPreview({ ...preview, query: event.target.value })}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && preview.date) {
                    void loadPreview(preview.item, preview.date, preview.time, preview.query);
                  }
                }}
              />
              <button
                className="query-button"
                disabled={!preview.date || preview.loading}
                onClick={() => preview.date && void loadPreview(preview.item, preview.date, preview.time, preview.query)}
              >
                查询
              </button>
            </div>
            {preview.loading ? (
              <EmptyState title="正在读取样例数据" text="按当前日期和时间聚合到合约维度。" />
            ) : preview.error ? (
              <EmptyState title="无法预览数据" text={preview.error} />
            ) : (
              <>
                <div className="preview-context">
                  <span>{preview.item.id}</span>
                  <span>{timeframeLabels[preview.item.storage_period] ?? preview.item.storage_period}</span>
                  <span>{preview.time ? `时间 ${preview.time}` : "未指定时间，取每个合约最新值"}</span>
                </div>
                <div className="preview-table-wrap contract-value-table-wrap">
                  <table className="preview-table contract-value-table">
                    <thead>
                      <tr>
                        <th>合约</th>
                        <th>{preview.item.name_zh}</th>
                      </tr>
                      <tr className="type-row">
                        <th>STRING</th>
                        <th>{typeLabel(preview.item.data_type).toUpperCase()}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {preview.rows.map((row) => (
                        <tr key={row.inst_id}>
                          <td className="symbol">{row.inst_id}</td>
                          <td>{formatPreviewValue(row.value, preview.item)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="preview-pagination">
                  <span>共{preview.rows.length}条</span>
                  <button disabled>‹</button>
                  <button className="current-page">1</button>
                  <button disabled>›</button>
                  <select value="200" disabled>
                    <option value="200">200条/页</option>
                  </select>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

function defaultIndicatorForm(period: string) {
  return {
    id: `manual.${period}.my_indicator`,
    name_zh: "",
    storage_period: period,
    data_type: "number" as Indicator["data_type"],
    unit: "",
    source_type: "manual" as Indicator["source_type"],
    description: "",
  };
}

function defaultScriptIndicatorForm(period: string) {
  return {
    nameZh: "",
    englishName: "script_indicator",
    period,
  };
}

function scriptIndicatorFormFromItem(item: Indicator) {
  return {
    nameZh: item.name_zh,
    englishName: scriptEnglishNameFromId(item) || autoScriptEnglishName(item.name_zh),
    period: item.storage_period,
  };
}

function scriptEnglishNameFromId(item: Indicator) {
  const prefix = `script.${item.storage_period}.`;
  if (item.id.startsWith(prefix)) return item.id.slice(prefix.length);
  const parts = item.id.split(".");
  return parts.at(-1) ?? "";
}

function autoScriptEnglishName(nameZh: string) {
  const ascii = nameZh
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  if (ascii) return ascii.slice(0, 48);
  const fallback = stableNumericId(nameZh || `${Date.now()}`).slice(0, 8);
  return `indicator_${fallback}`;
}

function scriptTemplate(item: Indicator) {
  return [
    "#!/usr/bin/env bash",
    "set -euo pipefail",
    "",
    `# 指标：${item.name_zh}`,
    `# ID：${item.id}`,
    `# 周期：${item.storage_period}`,
    "#",
    "# 平台后续会以环境变量方式传入：",
    "# RUN_DATE=2026-05-20",
    `# TIMEFRAME=${item.storage_period}`,
    "# DATA_ROOT=/path/to/normalized_gzip",
    "# OUTPUT_ROOT=/path/to/.runtime/script_indicators",
    "#",
    "# 输出格式必须是：",
    "# inst_id,ts,value",
    "",
    `echo "TODO: calculate ${item.id} for $RUN_DATE"`,
    "",
  ].join("\n");
}

function defaultMetadataConditionDraft(): MetadataConditionDraft {
  return {
    indicatorId: "",
    timeMode: "previous_trading_day",
    timeOffset: "1",
    timePointMode: "baseline",
    timePoint: "",
    barOffset: "1",
    timeOffsetValue: "1",
    timeOffsetUnit: "hour",
    operator: defaultMetadataOperator,
    value: "",
    truncateMode: "none",
    truncateCount: "",
    externalRelation: false,
    timeRange: false,
    exclude: false,
    matchCurrentBar: true,
  };
}

function draftFromCondition(condition: MetadataCondition): MetadataConditionDraft {
  return {
    indicatorId: condition.indicator.id,
    timeMode: condition.timeMode,
    timeOffset: condition.timeOffset,
    timePointMode: condition.timePointMode || legacyTimePointMode(condition.timePoint),
    timePoint: normalizeDraftTimePointForPeriod(condition.indicator.storage_period, condition.timePoint || ""),
    barOffset: condition.barOffset || "1",
    timeOffsetValue: condition.timeOffsetValue || "1",
    timeOffsetUnit: condition.timeOffsetUnit || "hour",
    operator: condition.operator,
    value: condition.value,
    truncateMode: condition.truncateMode,
    truncateCount: condition.truncateCount,
    externalRelation: condition.externalRelation,
    timeRange: condition.timeRange,
    exclude: condition.exclude,
    matchCurrentBar: condition.matchCurrentBar,
  };
}

function toMetadataFilterPayload(condition: MetadataCondition): ScreenerMetadataFilterPayload {
  return {
    indicator_id: condition.indicator.id,
    operator: condition.operator,
    value: condition.value,
    time_mode: condition.timeMode,
    time_offset: condition.timeOffset,
    time_point_mode: condition.timePointMode || legacyTimePointMode(condition.timePoint),
    time_point: condition.timePoint || "",
    bar_offset: condition.barOffset || "0",
    time_offset_value: condition.timeOffsetValue || "0",
    time_offset_unit: condition.timeOffsetUnit || "hour",
    truncate_mode: condition.truncateMode,
    truncate_count: condition.truncateCount,
    external_relation: condition.externalRelation,
    time_range: condition.timeRange,
    exclude: condition.exclude,
    match_current_bar: condition.indicator.source_type === "script" ? condition.matchCurrentBar : undefined,
  };
}

function toFavoriteCondition(condition: MetadataCondition): ScreenerFavoriteCondition {
  return {
    id: condition.id,
    indicator_id: condition.indicator.id,
    indicator: condition.indicator,
    time_mode: condition.timeMode,
    time_offset: condition.timeOffset,
    time_point_mode: condition.timePointMode || legacyTimePointMode(condition.timePoint),
    time_point: condition.timePoint,
    bar_offset: condition.barOffset || "0",
    time_offset_value: condition.timeOffsetValue || "0",
    time_offset_unit: condition.timeOffsetUnit || "hour",
    operator: condition.operator,
    value: condition.value,
    truncate_mode: condition.truncateMode,
    truncate_count: condition.truncateCount,
    external_relation: condition.externalRelation,
    time_range: condition.timeRange,
    exclude: condition.exclude,
    match_current_bar: condition.indicator.source_type === "script" ? condition.matchCurrentBar : undefined,
  };
}

function fromFavoriteCondition(condition: ScreenerFavoriteCondition): MetadataCondition | null {
  if (!condition.indicator) return null;
  return {
    id: condition.id ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`,
    indicatorId: condition.indicator_id || condition.indicator.id,
    indicator: condition.indicator,
    timeMode: condition.time_mode || "previous_trading_day",
    timeOffset: condition.time_offset || "1",
    timePointMode: condition.time_point_mode || legacyTimePointMode(condition.time_point || ""),
    timePoint: normalizeDraftTimePointForPeriod(condition.indicator.storage_period, condition.time_point || ""),
    barOffset: condition.bar_offset || "1",
    timeOffsetValue: condition.time_offset_value || "1",
    timeOffsetUnit: condition.time_offset_unit || "hour",
    operator: condition.operator || "gt",
    value: condition.value || "",
    truncateMode: condition.truncate_mode || "none",
    truncateCount: condition.truncate_count || "",
    externalRelation: Boolean(condition.external_relation),
    timeRange: Boolean(condition.time_range),
    exclude: Boolean(condition.exclude),
    matchCurrentBar: condition.match_current_bar ?? condition.indicator.source_type === "script",
  };
}

function favoriteName(conditions: MetadataCondition[], date: string, asOfTime: string) {
  const names = conditions.slice(0, 2).map((condition) => condition.indicator.name_zh);
  const suffix = conditions.length > 2 ? `等${conditions.length}个条件` : `${conditions.length}个条件`;
  const dateLabel = formatDateBadge(date) || "未选日期";
  const timeLabel = date && asOfTime ? ` ${asOfTime}` : date ? " 最新K线" : "";
  return `${names.join(" + ")} ${suffix} · ${dateLabel}${timeLabel}`;
}

function favoriteConditionText(condition: ScreenerFavoriteCondition) {
  const restored = fromFavoriteCondition(condition);
  if (!restored) return condition.indicator_id;
  return `${restored.indicator.name_zh} ${metadataConditionText(restored)}`;
}

function favoriteTimeframeLabel(timeframe: string) {
  return `按${timeframeLabels[timeframe] ?? timeframe}K线聚合计算`;
}

function klinePeriodLabel(period: string) {
  return klinePeriodOptions.find((option) => option.value === period)?.label ?? timeframeLabels[period] ?? period;
}

function klineRequestAnchorTs(target: KlineTarget, period: string) {
  const baselineTs = target.baselineTs ?? target.anchorTs;
  if (baselineTs == null) return target.anchorTs;
  return baselineTs;
}

function anomalyConditionPreview(event: SignalEvent) {
  const conditions = event.matched_conditions || [];
  if (conditions.length === 0) return "--";
  const preview = conditions.slice(0, 2).join("；");
  return conditions.length > 2 ? `${preview}；+${conditions.length - 2}` : preview;
}

function metadataOptionLabel(item: Indicator) {
  const period = timeframeLabels[item.storage_period] ?? item.storage_period;
  const source = item.source_type === "script" ? "指标生产" : "指标仓库";
  return `${source}/数字币/${period}@${item.name_zh}(交易日)`;
}

function metadataCanFilter(item: Indicator) {
  return Boolean(item.raw_field || item.source_type === "script");
}

function metadataOptionSort(a: Indicator, b: Indicator) {
  const aPriority = a.source_type === "script" ? 0 : a.raw_field ? 1 : 2;
  const bPriority = b.source_type === "script" ? 0 : b.raw_field ? 1 : 2;
  if (aPriority !== bPriority) return aPriority - bPriority;
  if (a.storage_period !== b.storage_period) return a.storage_period.localeCompare(b.storage_period);
  return a.name_zh.localeCompare(b.name_zh, "zh-Hans-CN");
}

function metadataConditionText(condition: MetadataCondition) {
  const operator = metadataOperatorLabel(condition.operator);
  const timeText = condition.timeMode === "previous_trading_day"
    ? `前${condition.timeOffset || "N"}个交易日`
    : condition.timeMode === "current_trading_day"
      ? "当前交易日"
      : "最新可用时间";
  const pointText = conditionTimePointText(condition);
  if (condition.operator === "any") {
    return `${timeText}${pointText} 任意取值`;
  }
  if (condition.operator === "any_empty") {
    return `${timeText}${pointText} 任意为空`;
  }
  if (condition.operator === "any_not_empty") {
    return `${timeText}${pointText} 任意不为空`;
  }
  const unit = condition.indicator.unit ? ` ${condition.indicator.unit}` : "";
  const exclude = condition.exclude ? "排除：" : "";
  return `${exclude}${timeText}${pointText} ${operator} ${condition.value}${unit}`;
}

function metadataOperatorNoValue(value: string) {
  return ["any", "any_empty", "any_not_empty"].includes(value);
}

function metadataOperatorPlaceholder(value: string, dataType: Indicator["data_type"]) {
  if (value === "any") return "只取值，不筛选";
  if (value === "any_empty") return "筛选空值";
  if (value === "any_not_empty") return "筛选非空值";
  return dataType === "number" ? "10" : "请输入条件值";
}

function metadataOperatorLabel(value: string) {
  return metadataOperatorOptions.find((item) => item.value === value)?.label ?? value;
}

function isTimeoutMessage(message: string | null) {
  return Boolean(message && /超时|timeout|timed out|abort/i.test(message));
}

function uniqueValueConditions(
  conditions: MetadataCondition[],
  date: string,
  dates: Array<{ date: string; file_count: number }>,
  asOfTime: string,
) {
  const seen = new Set<string>();
  return conditions.filter((condition) => {
    const key = valueConditionKey(condition, date, dates, asOfTime);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function valueConditionKey(
  condition: MetadataCondition,
  date: string,
  dates: Array<{ date: string; file_count: number }>,
  asOfTime: string,
) {
  return metadataValueKey(
    condition.indicator.id,
    conditionTargetDate(condition, date, dates, asOfTime),
    conditionTimePointKey(condition),
  );
}

function conditionTimeSubtitle(
  condition: MetadataCondition,
  date: string,
  dates: Array<{ date: string; file_count: number }>,
  asOfTime: string,
) {
  if (!metadataPeriodAllowsTime(condition.indicator.storage_period)) {
    const targetDate = conditionTargetLocalDate(condition, date, dates);
    return formatDateBadge(targetDate) || "当前交易日";
  }
  const targetTs = conditionTargetLocalTimestamp(condition, date, dates, asOfTime);
  if (targetTs !== null) {
    return formatShanghaiDateTimeBadge(targetTs);
  }
  const targetDate = conditionTargetLocalDate(condition, date, dates);
  return formatDateBadge(targetDate) || "当前交易日";
}

function conditionTimePointText(condition: MetadataCondition) {
  if (!metadataPeriodAllowsTime(condition.indicator.storage_period)) return "";
  const mode = conditionTimePointMode(condition);
  if (mode === "fixed") return condition.timePoint ? ` 固定${condition.timePoint}` : " 固定时刻";
  if (mode === "bar_offset") {
    const offset = normalizeNonNegativeText(condition.barOffset, "0");
    return offset === "0" ? " 基准时间" : ` 前${offset}根K线`;
  }
  if (mode === "time_offset") {
    const offset = normalizeNonNegativeText(condition.timeOffsetValue, "0");
    const unit = condition.timeOffsetUnit === "minute" ? "分钟" : "小时";
    return offset === "0" ? " 基准时间" : ` 前${offset}${unit}`;
  }
  return " 基准时间";
}

function metadataValueKey(indicatorId: string, targetDate: string, timePointKey: string | undefined) {
  return `${indicatorId}::${targetDate}::${normalizeConditionTimePoint(timePointKey) || "latest"}`;
}

function conditionTimePointMode(condition: Pick<MetadataConditionDraft, "timePointMode" | "timePoint">) {
  return normalizeTimePointModeForPeriod("1m", condition.timePointMode, condition.timePoint);
}

function conditionTimePointKey(condition: MetadataCondition) {
  if (!metadataPeriodAllowsTime(condition.indicator.storage_period)) return "latest";
  const mode = conditionTimePointMode(condition);
  if (mode === "fixed") return normalizeConditionTimePoint(condition.timePoint) || "latest";
  if (mode === "bar_offset") {
    const offset = normalizeNonNegativeText(condition.barOffset, "0");
    return offset === "0" ? "latest" : `bar_offset:${offset}`;
  }
  if (mode === "time_offset") {
    const offset = normalizeNonNegativeText(condition.timeOffsetValue, "0");
    const unit = condition.timeOffsetUnit === "minute" ? "minute" : "hour";
    return offset === "0" ? "latest" : `time_offset:${offset}${unit}`;
  }
  return "latest";
}

function normalizeConditionTimePoint(value: string | undefined) {
  return (value || "").trim();
}

function normalizeDraftTimePointForPeriod(period: string, value: string | undefined) {
  const normalized = normalizeConditionTimePoint(value);
  if (!normalized) return "";
  return metadataTimePointError(period, normalized) ? "" : normalized;
}

function normalizeBaselineTimeForPeriod(period: string, value: string | undefined) {
  const [hour, minute] = baselineTimeParts(value || "00:00");
  const minuteOptions = baselineMinuteOptions(period);
  const alignedMinute = minuteOptions
    .slice()
    .reverse()
    .find((item) => item <= minute) ?? minuteOptions[0] ?? 0;
  const normalizedHour = metadataPeriodAllowsTime(period) ? hour : 0;
  return formatTimeParts(normalizedHour, alignedMinute);
}

function baselineTimeParts(value: string) {
  const match = String(value || "").match(/^(\d{1,2}):(\d{2})(?::\d{2})?$/);
  if (!match) return [0, 0] as const;
  const hour = Math.max(0, Math.min(23, Number.parseInt(match[1], 10) || 0));
  const minute = Math.max(0, Math.min(59, Number.parseInt(match[2], 10) || 0));
  return [hour, minute] as const;
}

function baselineMinuteOptions(period: string) {
  const step = metadataPeriodStepMinutes(period);
  if (step === null || step >= 60) return [0];
  const safeStep = Math.max(1, step);
  return Array.from({ length: Math.ceil(60 / safeStep) }, (_, index) => index * safeStep).filter((item) => item < 60);
}

function baselineHourOptions(period: string) {
  return metadataPeriodAllowsTime(period) ? Array.from({ length: 24 }, (_, index) => index) : [0];
}

function formatTimeParts(hour: number, minute: number) {
  return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}

function legacyTimePointMode(timePoint: string | undefined) {
  return normalizeConditionTimePoint(timePoint) ? "fixed" : "baseline";
}

function normalizeTimePointModeForPeriod(period: string, mode: string | undefined, timePoint: string | undefined) {
  if (!metadataPeriodAllowsTime(period)) return "baseline";
  const normalized = (mode || "").trim();
  if (["baseline", "bar_offset", "time_offset", "fixed"].includes(normalized)) return normalized;
  return legacyTimePointMode(timePoint);
}

function normalizeNonNegativeText(value: string | undefined, fallback: string) {
  const parsed = Number.parseInt(String(value ?? ""), 10);
  if (!Number.isFinite(parsed) || parsed < 0) return fallback;
  return String(parsed);
}

function metadataPeriodAllowsTime(period: string) {
  return metadataPeriodStepMinutes(period) !== null;
}

function metadataTimeStepSeconds(period: string) {
  return (metadataPeriodStepMinutes(period) ?? 1) * 60;
}

function metadataTimePointHint(period: string, timePoint: string | MetadataConditionDraft | undefined) {
  const label = timeframeLabels[period] ?? period;
  const step = metadataPeriodStepMinutes(period);
  if (step === null) return `${label}只按交易日取值，不填写分钟时间`;
  const rule = metadataTimePointRuleText(period);
  if (typeof timePoint !== "object") {
    if (timePoint) return `取 ${timePoint} 这根 ${label} K线；${rule}`;
    return `跟随全局基准时间；${rule}`;
  }
  const mode = normalizeTimePointModeForPeriod(period, timePoint.timePointMode, timePoint.timePoint);
  if (mode === "bar_offset") return `按全局基准时间向前偏移 ${timePoint.barOffset || "N"} 根${label}K线；${rule}`;
  if (mode === "time_offset") {
    const unit = timePoint.timeOffsetUnit === "minute" ? "分钟" : "小时";
    return `按全局基准时间向前偏移 ${timePoint.timeOffsetValue || "N"} ${unit}；${rule}`;
  }
  if (mode === "fixed") return timePoint.timePoint ? `每天固定取 ${timePoint.timePoint} 这根${label}K线；${rule}` : `固定时刻；${rule}`;
  return `跟随全局基准时间，偏移0；${rule}`;
}

function metadataTimePointRuleText(period: string) {
  const step = metadataPeriodStepMinutes(period);
  if (step === null) return "只需要选择交易日";
  if (step === 1) return "可精确到任意分钟";
  if (step === 60) return "只能选择整点时间";
  return `只能选择 ${step} 分钟整数倍时间`;
}

function metadataTimePointError(period: string, value: string | undefined) {
  const normalized = normalizeConditionTimePoint(value);
  if (!normalized) return "";

  const label = timeframeLabels[period] ?? period;
  const step = metadataPeriodStepMinutes(period);
  if (step === null) return `${label}只能选择交易日，不能填写分钟时间`;

  const match = normalized.match(/^(\d{2}):(\d{2})(?::(\d{2}))?$/);
  if (!match) return "K线时刻格式应为 HH:mm";
  const hour = Number.parseInt(match[1], 10);
  const minute = Number.parseInt(match[2], 10);
  const second = match[3] ? Number.parseInt(match[3], 10) : 0;
  if (hour > 23 || minute > 59 || second > 59) return "K线时刻超出有效范围";
  if (second !== 0) return "K线时刻只能精确到分钟";
  const totalMinutes = hour * 60 + minute;
  if (totalMinutes % step !== 0) return `${label}${metadataTimePointRuleText(period)}`;
  return "";
}

function metadataTimeTakeError(period: string, draft: MetadataConditionDraft) {
  if (!metadataPeriodAllowsTime(period)) return "";
  const mode = normalizeTimePointModeForPeriod(period, draft.timePointMode, draft.timePoint);
  if (mode === "fixed") return metadataTimePointError(period, draft.timePoint) || (draft.timePoint ? "" : "请填写固定 K线时刻");
  if (mode === "bar_offset") {
    const raw = String(draft.barOffset || "").trim();
    if (!/^\d+$/.test(raw)) return "K线偏移必须是大于等于0的整数";
  }
  if (mode === "time_offset") {
    const raw = String(draft.timeOffsetValue || "").trim();
    if (!/^\d+$/.test(raw)) return "时间偏移必须是大于等于0的整数";
  }
  return "";
}

function metadataPeriodStepMinutes(period: string) {
  const normalized = period.trim().toLowerCase();
  const match = normalized.match(/^(\d+)(m|h|d)$/);
  if (!match) return 1;
  const count = Number.parseInt(match[1], 10);
  if (!Number.isFinite(count) || count <= 0) return 1;
  if (match[2] === "m") return count;
  if (match[2] === "h") return count * 60;
  return null;
}

function conditionTargetDate(
  condition: MetadataCondition,
  date: string,
  dates: Array<{ date: string; file_count: number }>,
  asOfTime = "",
) {
  const targetLocalDate = conditionTargetLocalDate(condition, date, dates);
  if (condition.timeMode !== "previous_trading_day") {
    if (metadataPeriodAllowsTime(condition.indicator.storage_period) && asOfTime) {
      return conditionTargetPartitionDate(condition, targetLocalDate, asOfTime);
    }
    return targetLocalDate;
  }
  if (metadataPeriodAllowsTime(condition.indicator.storage_period) && asOfTime) {
    return conditionTargetPartitionDate(condition, targetLocalDate, asOfTime);
  }
  return targetLocalDate;
}

function conditionTargetLocalDate(
  condition: MetadataCondition,
  date: string,
  dates: Array<{ date: string; file_count: number }>,
) {
  if (condition.timeMode !== "previous_trading_day") return date;
  const offset = Math.max(1, Number.parseInt(condition.timeOffset, 10) || 1);
  const currentIndex = dates.findIndex((item) => item.date === date);
  if (currentIndex >= 0) {
    return dates[currentIndex + offset]?.date ?? dates[dates.length - 1]?.date ?? date;
  }
  const ascending = dates.map((item) => item.date).slice().sort();
  const insertAt = ascending.findIndex((item) => item >= date);
  const baseIndex = insertAt >= 0 ? insertAt : ascending.length;
  return ascending[Math.max(0, baseIndex - offset)] ?? date;
}

function conditionTargetPartitionDate(condition: MetadataCondition, date: string, asOfTime: string) {
  const targetTs = conditionTargetTimestampOnDate(condition, date, asOfTime);
  if (targetTs === null) return date;
  return new Date(targetTs).toISOString().slice(0, 10);
}

function conditionTargetLocalTimestamp(
  condition: MetadataCondition,
  date: string,
  dates: Array<{ date: string; file_count: number }>,
  asOfTime: string,
) {
  const targetDate = conditionTargetLocalDate(condition, date, dates);
  return conditionTargetTimestampOnDate(condition, targetDate, asOfTime);
}

function conditionTargetTimestampOnDate(condition: MetadataCondition, date: string, asOfTime: string) {
  const baseTs = shanghaiLocalTimestamp(date, asOfTime);
  if (baseTs === null) return null;
  const mode = conditionTimePointMode(condition);
  let targetTs = baseTs;
  if (mode === "bar_offset") {
    const offset = Number.parseInt(normalizeNonNegativeText(condition.barOffset, "0"), 10);
    targetTs -= offset * (metadataPeriodStepMinutes(condition.indicator.storage_period) ?? 1) * 60_000;
  } else if (mode === "time_offset") {
    const offset = Number.parseInt(normalizeNonNegativeText(condition.timeOffsetValue, "0"), 10);
    const unitMinutes = condition.timeOffsetUnit === "minute" ? 1 : 60;
    targetTs -= offset * unitMinutes * 60_000;
  } else if (mode === "fixed") {
    const fixedTs = shanghaiLocalTimestamp(date, condition.timePoint);
    if (fixedTs !== null) targetTs = fixedTs;
  }
  return targetTs;
}

function shanghaiLocalTimestamp(date: string, time: string) {
  const dateMatch = date.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  const timeMatch = time.match(/^(\d{2}):(\d{2})(?::(\d{2}))?$/);
  if (!dateMatch || !timeMatch) return null;
  const year = Number.parseInt(dateMatch[1], 10);
  const month = Number.parseInt(dateMatch[2], 10);
  const day = Number.parseInt(dateMatch[3], 10);
  const hour = Number.parseInt(timeMatch[1], 10);
  const minute = Number.parseInt(timeMatch[2], 10);
  const second = timeMatch[3] ? Number.parseInt(timeMatch[3], 10) : 0;
  return Date.UTC(year, month - 1, day, hour - 8, minute, second);
}

function preferredQueryDate(timeframe: TimeframeSummary) {
  const today = localDateString();
  if (timeframe.dates.some((item) => item.date === today)) {
    return today;
  }
  return timeframe.latest_date ?? timeframe.recommended_date ?? "";
}

function preferredContractDate(timeframe: TimeframeSummary) {
  return timeframe.recommended_date ?? timeframe.latest_date ?? "";
}

function defaultRunDate(summary: DataSummary | null, period: string) {
  const timeframe = summary?.timeframes.find((item) => item.key === period);
  if (!timeframe) return localDateString();
  return preferredQueryDate(timeframe) || localDateString();
}

function tradeKlineMarkers(trade: BacktestTrade): KlineTradeMarker[] {
  const isShort = trade.side === "short";
  return [
    {
      side: isShort ? "sell" : "buy",
      ts: trade.entry_ts,
      price: trade.entry_price,
      label: isShort ? "卖开" : "买入",
      time: trade.entry_time,
    },
    {
      side: isShort ? "buy" : "sell",
      ts: trade.exit_ts,
      price: trade.exit_price,
      label: isShort ? "买平" : "卖出",
      time: trade.exit_time,
    },
  ];
}

function defaultTradeKlinePeriod(trade: BacktestTrade, preferredPeriod: string) {
  const durationMs = Math.max(0, trade.exit_ts - trade.entry_ts);
  const candidates = [preferredPeriod, "1m", "5m", "1H", "1D"].filter(
    (period, index, list) =>
      list.indexOf(period) === index && klinePeriodOptions.some((option) => option.value === period),
  );
  return candidates.find((period) => Math.ceil(durationMs / klinePeriodMs(period)) + 10 <= 300) ?? "1D";
}

function defaultAnomalyKlinePeriod(preferredPeriod: string) {
  return [preferredPeriod, "1H", "5m", "1m", "1D"].find((period) =>
    klinePeriodOptions.some((option) => option.value === period),
  ) ?? "1H";
}

function tradeKlineWindowSize(
  period: string,
  anchorTs: number | null | undefined,
  markers: KlineTradeMarker[],
) {
  const periodMs = klinePeriodMs(period);
  const anchor = anchorTs ?? markers[0]?.ts ?? 0;
  const markerTsValues = markers.map((marker) => marker.ts).filter((value) => Number.isFinite(value));
  const minTs = Math.min(anchor, ...markerTsValues);
  const maxTs = Math.max(anchor, ...markerTsValues);
  return {
    before: Math.min(300, Math.max(33, Math.ceil((anchor - minTs) / periodMs) + 10)),
    after: Math.min(300, Math.max(33, Math.ceil((maxTs - anchor) / periodMs) + 10)),
  };
}

function klinePeriodMs(period: string) {
  const normalized = period.trim().toLowerCase();
  const match = normalized.match(/^(\d+)(m|h|d)$/);
  if (!match) return 60 * 1000;
  const count = Number.parseInt(match[1], 10);
  if (match[2] === "m") return count * 60 * 1000;
  if (match[2] === "h") return count * 60 * 60 * 1000;
  return count * 24 * 60 * 60 * 1000;
}

function suggestedBacktestRange(summary: DataSummary | null, period: string, mode: string) {
  const timeframe = currentTimeframe(summary, period);
  const end = timeframe ? preferredQueryDate(timeframe) || localDateString() : localDateString();
  const rows = timeframe?.dates ?? [];
  if (rows.length === 0) return { start: end, end };
  const endIndex = rows.findIndex((item) => item.date === end);
  const fallbackEndIndex = endIndex >= 0 ? endIndex : rows.length - 1;
  const span = mode === "each_bar_close"
    ? period === "1m"
      ? 1
      : period === "5m"
        ? 1
        : 14
    : 180;
  const startIndex = Math.max(0, fallbackEndIndex - span + 1);
  return {
    start: rows[startIndex]?.date ?? end,
    end: rows[fallbackEndIndex]?.date ?? end,
  };
}

function runStatusLabel(status: string) {
  if (status === "completed") return "完成";
  if (status === "failed") return "失败";
  if (status === "running") return "运行中";
  return status;
}

function localDateString() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function formatDateBadge(value: string) {
  if (!value) return "";
  return value.replaceAll("-", "");
}

function formatShanghaiDateTimeBadge(value: number) {
  const date = new Date(value + 8 * 60 * 60 * 1000);
  if (Number.isNaN(date.getTime())) return "";
  const year = date.getUTCFullYear();
  const month = String(date.getUTCMonth() + 1).padStart(2, "0");
  const day = String(date.getUTCDate()).padStart(2, "0");
  const hour = String(date.getUTCHours()).padStart(2, "0");
  const minute = String(date.getUTCMinutes()).padStart(2, "0");
  return `${year}${month}${day} ${hour}:${minute}`;
}

function formatKlineDisplayTime(value: string | null | undefined) {
  if (!value) return "";
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})/);
  if (!match) return value;
  return `${match[1]}${match[2]}${match[3]} ${match[4]}${match[5]}`;
}

function weekdayLabel(value: string) {
  if (!value) return "";
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) return "";
  return `星期${["日", "一", "二", "三", "四", "五", "六"][date.getDay()]}`;
}

function formatDateTime(value: number | null | undefined) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--";
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const hour = String(date.getHours()).padStart(2, "0");
  const minute = String(date.getMinutes()).padStart(2, "0");
  const second = String(date.getSeconds()).padStart(2, "0");
  return `${year}-${month}-${day} ${hour}:${minute}:${second}`;
}

function compactSymbolName(value: string) {
  return value.replace("-USDT-SWAP", "").replace("-USDT", "");
}

function englishName(item: Indicator) {
  return item.raw_field ?? item.id.split(".").slice(2).join(".") ?? item.id;
}

function typeLabel(value: Indicator["data_type"]) {
  return {
    number: "小数",
    string: "文本",
    datetime: "时间",
    boolean: "布尔",
  }[value];
}

function stableNumericId(value: string) {
  let hash = 0;
  for (const char of value) {
    hash = (hash * 31 + char.charCodeAt(0)) % 100000000;
  }
  return hash.toString().padStart(8, "0");
}

function formatDateCompact(value: number) {
  const date = new Date(value);
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}${month}${day}`;
}

function formatPreviewValue(value: string, item: Indicator) {
  if (value === "") return "--";
  if (item.data_type === "boolean") {
    return value === "1" || value.toLowerCase() === "true" ? "1" : "0";
  }
  if (item.data_type === "number") {
    const numeric = Number(value);
    if (Number.isFinite(numeric)) {
      return Intl.NumberFormat("zh-CN", { maximumFractionDigits: 8 }).format(numeric);
    }
  }
  return value;
}

function TypeBadge({ value }: { value: Indicator["data_type"] }) {
  return <span className={`type-badge ${value}`}>{value}</span>;
}

function SourceBadge({ value }: { value: Indicator["source_type"] }) {
  const label = value === "raw" ? "原始字段" : value === "computed" ? "计算指标" : value === "script" ? "脚本指标" : "手动";
  return <span className={`source-badge ${value}`}>{label}</span>;
}

function currentTimeframe(summary: DataSummary | null, key: string): TimeframeSummary | undefined {
  return summary?.timeframes.find((item) => item.key === key);
}

function StatusPill({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div className={`status-pill ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function ConditionCard(props: {
  label: string;
  value: string;
  suffix: string;
  placeholder: string;
  hitCount?: number;
  onChange: (value: string) => void;
}) {
  return (
    <div className="condition-card">
      <div>
        <span>{props.label}</span>
        <strong>
          {props.hitCount === undefined ? "--" : props.hitCount}
          <small> 命中</small>
        </strong>
      </div>
      <label>
        大于等于
        <div className="input-with-suffix">
          <input
            value={props.value}
            placeholder={props.placeholder}
            onChange={(event) => props.onChange(event.target.value)}
          />
          {props.suffix && <em>{props.suffix}</em>}
        </div>
      </label>
    </div>
  );
}

function EmptyState({ title, text }: { title: string; text: string }) {
  return (
    <div className="empty-state">
      <strong>{title}</strong>
      <p>{text}</p>
    </div>
  );
}

function formatPercent(value: number) {
  return `${value.toFixed(2)}%`;
}

function formatNumber(value: number) {
  return Intl.NumberFormat("zh-CN", { maximumFractionDigits: 8 }).format(value);
}

function formatSignedNumber(value: number) {
  const sign = value > 0 ? "+" : "";
  return `${sign}${formatNumber(value)}`;
}

function formatOptionalNumber(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return "--";
  return formatNumber(value);
}

function hasKlineNumbers(row: ContractKlineRow): row is ContractKlineRow & {
  open: number;
  high: number;
  low: number;
  close: number;
} {
  return [row.open, row.high, row.low, row.close].every(
    (value) => typeof value === "number" && Number.isFinite(value),
  );
}

function klineMarkerIndex(rows: ContractKlineRow[], markerTs: number) {
  const timestamps = rows
    .map((row, index) => ({ index, ts: row.ts }))
    .filter((item): item is { index: number; ts: number } => typeof item.ts === "number" && Number.isFinite(item.ts));
  if (timestamps.length === 0 || markerTs < timestamps[0].ts) return null;

  const stepMs = estimatedKlineStepMs(timestamps.map((item) => item.ts));
  const last = timestamps[timestamps.length - 1];
  if (stepMs && markerTs > last.ts + stepMs - 1) return null;

  let selected = timestamps[0].index;
  for (const item of timestamps) {
    if (item.ts > markerTs) break;
    selected = item.index;
  }
  return selected;
}

function estimatedKlineStepMs(timestamps: number[]) {
  for (let index = 1; index < timestamps.length; index += 1) {
    const diff = timestamps[index] - timestamps[index - 1];
    if (diff > 0) return diff;
  }
  return null;
}

function klineVolumeValue(row: ContractKlineRow) {
  return row.vol_ccy_quote ?? row.vol_ccy ?? row.vol ?? 0;
}

function formatKlineChangePercent(value: number | null) {
  if (value === null || !Number.isFinite(value)) return "--";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

function formatContractPrice(value: string) {
  if (!value) return "--";
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return value;
  return Intl.NumberFormat("zh-CN", { maximumFractionDigits: 10 }).format(parsed);
}

function formatCompact(value: number) {
  return Intl.NumberFormat("zh-CN", {
    notation: "compact",
    maximumFractionDigits: 2,
  }).format(value);
}

function numberTone(value: number) {
  if (value > 0) return "up";
  if (value < 0) return "down";
  return "";
}

function qualityStatusText(status: "ok" | "warning" | "fail") {
  return status === "ok" ? "正常" : status === "warning" ? "轻微异常" : "严重异常";
}

function qualitySampleText(missing: string[], extra: string[]) {
  const parts: string[] = [];
  if (missing.length > 0) {
    parts.push(`缺：${missing.slice(0, 3).join("、")}${missing.length > 3 ? "..." : ""}`);
  }
  if (extra.length > 0) {
    parts.push(`多：${extra.slice(0, 3).join("、")}${extra.length > 3 ? "..." : ""}`);
  }
  return parts.join("；") || "--";
}
