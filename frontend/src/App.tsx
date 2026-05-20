import { useEffect, useMemo, useRef, useState } from "react";
import ConfigProvider from "antd/es/config-provider";
import Table from "antd/es/table";
import type { ColumnsType } from "antd/es/table";
import {
  DataSummary,
  Indicator,
  IndicatorCatalogResponse,
  ScreenerMetadataFilterPayload,
  ScreenerResponse,
  ScreenerRow,
  TimeframeSummary,
  createIndicator,
  fetchIndicatorValuePreview,
  fetchIndicators,
  fetchSummary,
  queryScreener,
} from "./api";

const navItems = ["选币查询", "指标生产", "指标仓库", "数据源管理", "运行日志"];
const timeframeLabels: Record<string, string> = {
  "1m": "1分钟",
  "5m": "5分钟",
  "15m": "15分钟",
  "1H": "1小时",
};

const metadataOperatorOptions = [
  { value: "gt", label: "大于" },
  { value: "gte", label: "大于等于" },
  { value: "lt", label: "小于" },
  { value: "lte", label: "小于等于" },
  { value: "eq", label: "等于" },
  { value: "ne", label: "不等于" },
  { value: "contains", label: "包含" },
];

type MetadataConditionDraft = {
  indicatorId: string;
  timeMode: string;
  timeOffset: string;
  operator: string;
  value: string;
  truncateMode: string;
  truncateCount: string;
  externalRelation: boolean;
  timeRange: boolean;
  exclude: boolean;
};

type MetadataCondition = MetadataConditionDraft & {
  id: string;
  indicator: Indicator;
};

type ScreenerTableRow = ScreenerRow & {
  key: string;
  rowIndex: number;
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
  const [metadataConditions, setMetadataConditions] = useState<MetadataCondition[]>([]);
  const [conditionModalOpen, setConditionModalOpen] = useState(false);
  const [editingCondition, setEditingCondition] = useState<MetadataCondition | null>(null);
  const [tableSearch, setTableSearch] = useState("");
  const [asOfTime, setAsOfTime] = useState("");
  const [loading, setLoading] = useState(true);
  const [querying, setQuerying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timeStripRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    void loadSummary();
  }, []);

  useEffect(() => {
    const current = currentTimeframe(summary, timeframe);
    if (current) {
      setDate(preferredQueryDate(current));
    }
  }, [summary, timeframe]);

  useEffect(() => {
    if (date && metadataConditions.length > 0) {
      void runQuery();
    } else {
      setResult(null);
    }
  }, [date, timeframe, metadataConditions, sortBy, asOfTime]);

  const tfSummary = currentTimeframe(summary, timeframe);
  const dates = useMemo(() => tfSummary?.dates.slice().reverse() ?? [], [tfSummary]);
  const rows = result?.rows ?? [];
  const valueConditions = useMemo(
    () => uniqueValueConditions(metadataConditions, date, dates),
    [metadataConditions, date, dates],
  );
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
        render: (value: string) => <span className="pro-symbol-cell">{value}</span>,
      },
      ...valueConditions.map((condition) => ({
        title: (
          <TableColumnHead
            title={condition.indicator.name_zh}
            subtitle={conditionTimeSubtitle(condition, date, dates)}
            sortable
          />
        ),
        key: valueConditionKey(condition, date, dates),
        width: 240,
        align: "center" as const,
        render: (_: unknown, row: ScreenerTableRow) => (
          <FilterValueCell row={row} condition={condition} />
        ),
      })),
    ],
    [date, dates, valueConditions],
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

  async function runQuery() {
    if (!date) return;
    if (metadataConditions.length === 0) {
      setResult(null);
      return;
    }
    setQuerying(true);
    setError(null);
    try {
      const data = await queryScreener({
        timeframe,
        date,
        asOf: date && asOfTime ? `${date}T${asOfTime}:00` : undefined,
        minRet15m,
        minVolRatio60,
        minVolQuote15m,
        sortBy,
        metadataFilters: metadataConditions.map(toMetadataFilterPayload),
      });
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "选币查询失败");
    } finally {
      setQuerying(false);
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
              <b>{item === "指标仓库" ? "CORE" : index === 0 ? "LIVE" : "MVP"}</b>
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
        ) : (
          <>
            <section className="screener-terminal focused-screener">
              <div className="terminal-action-row minimal-actions">
                <button className="filter-only-button" onClick={() => {
                  setEditingCondition(null);
                  setConditionModalOpen(true);
                }}>
                  +筛选条件
                </button>
                <button className="page-refresh-button" onClick={() => { void loadSummary(true); void runQuery(); }}>
                  ↻ 页面刷新
                </button>
              </div>

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
                  <span>选出</span>
                  <strong>{result?.matched_count ?? 0}</strong>
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
              </div>

              <section className="terminal-table-panel focused-table-panel">
                {loading ? (
                  <EmptyState title="正在扫描数据源" text="读取本地 normalized_gzip 分区和合约覆盖。" />
                ) : error ? (
                  <EmptyState title="发生错误" text={error} />
                ) : metadataConditions.length === 0 ? (
                  <EmptyState title="等待筛选条件" text="点击上方「+筛选条件」选择元数据；未设置条件时不会默认展示全部合约。" />
                ) : result === null ? (
                  <EmptyState title="等待查询结果" text="条件添加后会自动查询，也可以点击右上角页面刷新。" />
                ) : rows.length === 0 ? (
                  <EmptyState title="暂无命中合约" text="当前日期下没有合约满足组合筛选条件。" />
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
                  <span>数据基准日期 <b>{formatDateBadge(date) || "--"}</b></span>
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

function FilterValueCell({ row, condition }: { row: ScreenerRow; condition: MetadataCondition }) {
  const rawValue = row.metadata_values?.[condition.indicator.id] ?? "";
  return (
    <div className="filter-value-cell single-value">
      <span>
        <b>{formatPreviewValue(rawValue, condition.indicator)}</b>
      </span>
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
    if (!needle) return items;
    return items.filter(
      (item) =>
        item.name_zh.toLowerCase().includes(needle) ||
        item.id.toLowerCase().includes(needle) ||
        englishName(item).toLowerCase().includes(needle),
    );
  }, [items, metadataSearch]);
  const selectedLabel = selectedIndicator ? metadataOptionLabel(selectedIndicator) : "";
  const currentOperatorOptions = selectedIndicator?.data_type === "number"
    ? metadataOperatorOptions.filter((item) => item.value !== "contains")
    : metadataOperatorOptions.filter((item) => ["eq", "ne", "contains"].includes(item.value));
  const canAdd = Boolean(selectedIndicator && draft.value.trim());

  function selectIndicator(item: Indicator) {
    const nextOptions = item.data_type === "number"
      ? metadataOperatorOptions.filter((option) => option.value !== "contains")
      : metadataOperatorOptions.filter((option) => ["eq", "ne", "contains"].includes(option.value));
    setDraft((current) => ({
      ...current,
      indicatorId: item.id,
      operator: nextOptions.some((option) => option.value === current.operator) ? current.operator : nextOptions[0].value,
    }));
    setMetadataSearch("");
    setSelectOpen(false);
  }

  function applyCondition() {
    if (!selectedIndicator) {
      setError("请先选择一个元数据字段。");
      return;
    }
    if (!selectedIndicator.raw_field) {
      setError("这个元数据暂未接入原始字段，当前不能用于合约筛选。");
      return;
    }
    if (!draft.value.trim()) {
      setError("请填写筛选条件的目标值。");
      return;
    }
    onApply({
      ...draft,
      value: draft.value.trim(),
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
          <button className={draft.exclude ? "active" : ""} onClick={() => setDraft({ ...draft, exclude: !draft.exclude })}>
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
                    options.slice(0, 80).map((item) => (
                      <button
                        key={item.id}
                        className="metadata-option"
                        onClick={() => selectIndicator(item)}
                        title={metadataOptionLabel(item)}
                      >
                        <span>{metadataOptionLabel(item)}</span>
                        {!item.raw_field && <em>暂不可筛选</em>}
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
                <label>选择时间</label>
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

              <div className="condition-form-row">
                <label>{mode === "filter" ? "设置条件" : "取值条件"}</label>
                <select value={draft.operator} onChange={(event) => setDraft({ ...draft, operator: event.target.value })}>
                  {currentOperatorOptions.map((item) => (
                    <option key={item.value} value={item.value}>{item.label}</option>
                  ))}
                </select>
                <input
                  value={draft.value}
                  onChange={(event) => setDraft({ ...draft, value: event.target.value })}
                  placeholder={selectedIndicator.data_type === "number" ? "10" : "请输入条件值"}
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
            {selectedIndicator ? (
              <span>
                当前选择：{selectedIndicator.name_zh} · {timeframeLabels[selectedIndicator.storage_period] ?? selectedIndicator.storage_period}
              </span>
            ) : (
              <span>元数据来自指标仓库，已加载全部周期；可搜索中文名、英文名或 ID。</span>
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
  const periods = summary?.timeframes.map((item) => item.key) ?? ["1m", "5m", "15m", "1H"];
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
              <label className="value-toggle">
                <input type="checkbox" checked readOnly />
                <span>有值</span>
              </label>
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

function defaultMetadataConditionDraft(): MetadataConditionDraft {
  return {
    indicatorId: "",
    timeMode: "previous_trading_day",
    timeOffset: "1",
    operator: "gt",
    value: "",
    truncateMode: "none",
    truncateCount: "",
    externalRelation: false,
    timeRange: false,
    exclude: false,
  };
}

function draftFromCondition(condition: MetadataCondition): MetadataConditionDraft {
  return {
    indicatorId: condition.indicator.id,
    timeMode: condition.timeMode,
    timeOffset: condition.timeOffset,
    operator: condition.operator,
    value: condition.value,
    truncateMode: condition.truncateMode,
    truncateCount: condition.truncateCount,
    externalRelation: condition.externalRelation,
    timeRange: condition.timeRange,
    exclude: condition.exclude,
  };
}

function toMetadataFilterPayload(condition: MetadataCondition): ScreenerMetadataFilterPayload {
  return {
    indicator_id: condition.indicator.id,
    operator: condition.operator,
    value: condition.value,
    time_mode: condition.timeMode,
    time_offset: condition.timeOffset,
    truncate_mode: condition.truncateMode,
    truncate_count: condition.truncateCount,
    external_relation: condition.externalRelation,
    time_range: condition.timeRange,
    exclude: condition.exclude,
  };
}

function metadataOptionLabel(item: Indicator) {
  const period = timeframeLabels[item.storage_period] ?? item.storage_period;
  return `指标仓库/数字币/${period}@${item.name_zh}(交易日)`;
}

function metadataConditionText(condition: MetadataCondition) {
  const operator = metadataOperatorLabel(condition.operator);
  const timeText = condition.timeMode === "previous_trading_day"
    ? `前${condition.timeOffset || "N"}个交易日`
    : condition.timeMode === "current_trading_day"
      ? "当前交易日"
      : "最新可用时间";
  const unit = condition.indicator.unit ? ` ${condition.indicator.unit}` : "";
  const exclude = condition.exclude ? "排除：" : "";
  return `${exclude}${timeText} ${operator} ${condition.value}${unit}`;
}

function metadataOperatorLabel(value: string) {
  return metadataOperatorOptions.find((item) => item.value === value)?.label ?? value;
}

function uniqueValueConditions(
  conditions: MetadataCondition[],
  date: string,
  dates: Array<{ date: string; file_count: number }>,
) {
  const seen = new Set<string>();
  return conditions.filter((condition) => {
    const key = valueConditionKey(condition, date, dates);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function valueConditionKey(
  condition: MetadataCondition,
  date: string,
  dates: Array<{ date: string; file_count: number }>,
) {
  return `${condition.indicator.id}::${conditionTargetDate(condition, date, dates)}`;
}

function conditionTimeSubtitle(
  condition: MetadataCondition,
  date: string,
  dates: Array<{ date: string; file_count: number }>,
) {
  if (condition.timeMode === "previous_trading_day") {
    const targetDate = conditionTargetDate(condition, date, dates);
    const suffix = targetDate ? ` ${formatDateBadge(targetDate)}` : "";
    return `前${condition.timeOffset || "N"}个交易日${suffix}`;
  }
  if (condition.timeMode === "current_trading_day") {
    return formatDateBadge(date) || "当前交易日";
  }
  return "最新可用时间";
}

function conditionTargetDate(
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

function preferredQueryDate(timeframe: TimeframeSummary) {
  const today = localDateString();
  if (timeframe.dates.some((item) => item.date === today)) {
    return today;
  }
  return timeframe.latest_date ?? timeframe.recommended_date ?? "";
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

function weekdayLabel(value: string) {
  if (!value) return "";
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) return "";
  return `星期${["日", "一", "二", "三", "四", "五", "六"][date.getDay()]}`;
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
  const label = value === "raw" ? "原始字段" : value === "computed" ? "计算指标" : "手动";
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
      <div className="radar" />
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
