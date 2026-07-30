// 后端 API 网关（apps/api，开发端口 8001）的类型契约。
// 与 apps/api/main.py 的响应结构保持一致。

export interface Candle {
  t: string // 时间戳：A股本地数据为 ordinal 顺序整数（datetime 为占位 NaT）
  o: number
  h: number
  l: number
  c: number
  v: number
}

export interface KlineResp {
  ok: boolean
  source?: 'local' | 'empty' | string
  symbol: string
  interval: string
  count: number
  candles: Candle[]
  error?: string
  quality?: {
    status: 'ok' | 'empty' | 'invalid' | string
    usable: boolean
    row_count: number
    missing_rate: number
    invalid_rows: number
    latest_time: string | null
    latency_ms?: number
    reason: string | null
  }
}

export interface HealthResp {
  status: string
  time: string
  strategies: number
  live_trading: boolean
  version: string
  deployment_mode: string
  started_at: string
  build_id: string
}

export interface DataSourceStatusResp {
  ok: boolean
  generated_at: number
  configured: Array<{ market: string; primary: string | null; fallbacks: string[] }>
  sources: Array<{
    source: string
    operation: DataSourceOperation
    calls: number
    successes: number
    errors: number
    success_rate: number
    error_rate: number
    avg_latency_ms: number
    last_called_at: number | null
    last_success_at: number | null
    last_error: string | null
  }>
  cache: {
    hits: number
    misses: number
    requests: number
    hit_rate: number
    kline_entries: number
    document_entries: number
    latest_write_at: number | null
  }
}

export type DataSourceOperation = 'get_kline' | 'get_news' | 'get_announcements'

export interface DataSourceCheckResult {
  ok: boolean
  source: string
  operation: DataSourceOperation
  count: number
  latency_ms: number
  error: string | null
}

// ---------- 可追溯研究运行 ----------

export type ResearchStatus =
  | 'draft'
  | 'queued'
  | 'running'
  | 'succeeded'
  | 'partial'
  | 'failed'
  | 'cancelled'
  | 'timeout'

export type AnalysisTaskKind = 'pa' | 'news' | 'ensemble' | 'evaluation'
export type AnalysisTaskStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'timeout'

export interface AnalysisTask {
  id: string
  kind: AnalysisTaskKind
  status: AnalysisTaskStatus
  symbol: string
  market: string
  timeframe: string
  fingerprint: string
  request: Record<string, unknown>
  result: Record<string, unknown> | null
  error: string | null
  attempt: number
  parent_task_id: string | null
  created_at: number
  updated_at: number
  started_at: number | null
  finished_at: number | null
  duration_ms: number | null
}

export interface ResearchEvidence {
  id: string
  run_id: string
  kind: string
  source: string
  title: string
  uri: string | null
  payload: Record<string, unknown>
  captured_at: number
}

export interface ResearchRun {
  id: string
  symbol: string
  market: string
  timeframe: string
  status: ResearchStatus
  modules: string[]
  input: Record<string, unknown>
  summary: Record<string, unknown>
  error: string | null
  note: string
  favorite: boolean
  created_at: number
  updated_at: number
  evidence_count: number
  evidence?: ResearchEvidence[]
}

export interface ResearchVerification {
  ok: boolean
  run_id: string
  snapshot_count: number
  snapshots_valid: boolean
  has_analysis_output: boolean
  replay_ready: boolean
  checks: Array<{
    evidence_id: string
    title: string
    expected_sha256: string | null
    actual_sha256: string | null
    valid: boolean
    bar_count: number
  }>
}

export interface ResearchComparison {
  ok: boolean
  same_context: boolean
  contexts: Array<{ symbol: string; market: string; timeframe: string }>
  modules: string[]
  summary_keys: string[]
  rows: Array<{
    id: string
    status: ResearchStatus
    updated_at: number
    modules: string[]
    module_presence: Record<string, boolean>
    summary: Record<string, unknown>
    evidence_count: number
    evidence_kind_counts: Record<string, number>
    snapshot_sha256: string[]
  }>
}

export interface StrategyInfo {
  name: string
  market: string
  live_capable: boolean
  description: string
}

export interface StrategiesResp {
  count: number
  strategies: StrategyInfo[]
}

export interface SignalResp {
  /** DB 主键（删除用）；内存态旧信号可能缺失 */
  id?: string
  symbol: string
  market: string
  timeframe: string
  direction: string // buy | sell | hold
  score: number
  confidence: number
  source: string
  tags: string[]
  meta: Record<string, unknown>
  ts: string | null
  status?: SignalLifecycleStatus
  expires_at?: number | null
  reviewed_at?: number | null
  decision_note?: string | null
  order_id?: string | null
  deduplicated?: boolean
}

export type SignalLifecycleStatus = 'new' | 'accepted' | 'rejected' | 'expired' | 'converted'

export type SimulationOrderStatus = 'pending' | 'partially_filled' | 'filled' | 'cancelled'
export type SimulationLedgerSyncStatus = 'pending' | 'synced' | 'failed'

export interface SimulationExecution {
  id: string
  order_id: string
  quantity: number
  price: number
  fee: number
  executed_at: number
  ledger_sync_status: SimulationLedgerSyncStatus
  ledger_trade_id: string | null
  ledger_sync_error: string | null
}

export interface SimulationOrder {
  id: string
  signal_id: string | null
  account_id: string
  symbol: string
  market: string
  side: 'buy' | 'sell'
  order_type: 'market' | 'limit'
  quantity: number
  limit_price: number | null
  status: SimulationOrderStatus
  filled_quantity: number
  average_price: number | null
  created_at: number
  updated_at: number
  executions: SimulationExecution[]
}

export interface SimulationAccount {
  ok: boolean
  mode: 'paper'
  starting_cash: number
  cash: number
  market_value: number
  equity: number
  total_fees: number
  realized_pnl: number
  unrealized_pnl: number
  positions: Array<{
    symbol: string
    market: string
    quantity: number
    average_cost: number
    mark_price: number
    market_value: number
    realized_pnl: number
    unrealized_pnl: number
  }>
  order_count: number
  execution_count: number
  reconciled: boolean
  reconciliation_issues: Array<{ order_id: string; field: string }>
}

export interface SimulationOrderPreviewCheck {
  key: string
  label: string
  status: 'passed' | 'failed' | 'unavailable'
  actual: number | null
  limit: number | null
  unit: 'ratio' | 'currency' | 'price'
}

export interface SimulationOrderPreview {
  symbol: string
  market: string
  side: 'buy' | 'sell'
  quantity: number
  price: number | null
  order_notional: number | null
  current_quantity: number
  projected_quantity: number
  current_symbol_value: number | null
  projected_symbol_value: number | null
  gross_exposure_before: number
  gross_exposure_after: number | null
  cash_before: number
  cash_after: number | null
  equity: number
  risk_evaluated: boolean
  can_submit: boolean
  checks: SimulationOrderPreviewCheck[]
}

export interface SignalsResp {
  count: number
  total: number
  next_cursor: string | null
  signals: SignalResp[]
}

export interface ResearchRunsResp {
  ok: boolean
  count: number
  total: number
  next_cursor: string | null
  runs: ResearchRun[]
}

export interface SimulationOrdersResp {
  ok: boolean
  count: number
  total: number
  next_cursor: string | null
  orders: SimulationOrder[]
}

/** POST /signals/publish 请求体，对应后端 PublishRequest（apps/api/main.py:100-109）。 */
export interface PublishSignalReq {
  symbol: string
  market?: string
  direction?: string // buy | sell | hold
  score?: number
  confidence?: number
  source?: string
  timeframe?: string
  tags?: string[]
  meta?: Record<string, unknown>
}

export interface RunResp {
  ok: boolean
  name: string
  count: number
  signals: SignalResp[]
  error?: string
}

// ---- G2 预设 / 运行历史（后端持久化）----
export interface Preset {
  id: string
  name: string
  params: Record<string, unknown>
}

export interface RunRecord {
  id: string
  name: string
  params: Record<string, unknown>
  result: RunResp
  ts: number // epoch seconds
}

// ---- G6 回测 ----
export interface BacktestResp {
  ok: boolean
  name: string
  symbol: string
  market: string
  error?: string
  summary?: {
    engine: string
    final_equity: number
    total_return: number
    max_drawdown: number
    metrics: Record<string, number>
    n_trades: number
  }
  trades: Array<Record<string, unknown>>
  equity: Array<{ t: string | null; equity: number }>
}

// ---- 因子研究 ----
export type FactorStatus = 'usable' | 'watch' | 'reject'
export type DrawdownLevel = 'normal' | 'watch' | 'reduce' | 'risk_off' | 'recovery'

export interface FactorEvaluation {
  key: string
  label: string
  category: string
  description: string
  direction: 'positive' | 'inverse'
  status: FactorStatus
  score: number
  ic: number
  rank_ic: number
  pearson_ic: number
  train_ic: number
  test_ic: number
  rolling_ic_mean: number
  rolling_ic_std: number
  icir: number
  positive_ic_ratio: number
  p_value: number
  decay: Array<{ horizon: number; ic: number }>
  hit_rate: number
  observations: number
  test_observations: number
  stable: boolean
  selected: boolean
  weight: number
}

export interface QuantMethodResult {
  key: string
  label: string
  total_return: number
  annual_return: number
  sharpe: number
  annual_volatility: number
  downside_deviation: number
  sortino: number
  calmar: number
  risk_adjusted_score: number
  max_drawdown: number
  var_95: number
  cvar_95: number
  ulcer_index: number
  profit_factor: number
  max_drawdown_duration: number
  average_holding_period: number
  win_rate: number
  turnover: number
  trades: number
  exposure: number
}

export interface FactorCurvePoint {
  t: string
  asset?: number | null
  multifactor?: number | null
  asset_drawdown?: number | null
  strategy_drawdown?: number | null
  equity?: number | null
}

export interface FactorResearchResp {
  ok: boolean
  error?: string
  symbol: string
  market: string
  interval: string
  source: string
  quality: {
    status: string
    usable: boolean
    row_count: number
    missing_rate: number
    invalid_rows: number
    latest_time: string | null
    reason?: string | null
  }
  summary: {
    rows: number
    train_rows: number
    purged_rows: number
    test_rows: number
    horizon: number
    transaction_cost_bps: number
    usable_factors: number
    selected_factors: string[]
    best_factor: string | null
    best_method: string | null
    evaluation_scope: 'out_of_sample'
  }
  factors: FactorEvaluation[]
  methods: QuantMethodResult[]
  indicators: Array<{
    key: string
    label: string
    value: number | null
    state: 'positive' | 'negative' | 'neutral'
    interpretation: string
  }>
  current_signal: {
    level: DrawdownLevel
    label: string
    drawdown: number
    strategy_drawdown: number
    asset_peak_drawdown: number
    guidance: string
  }
  signal_events: Array<{
    t: string
    level: DrawdownLevel
    label: string
    drawdown: number
    guidance: string
  }>
  latest: {
    close: number
    multifactor_position: number
    multifactor_return: number
  }
  curve: FactorCurvePoint[]
  method_curves: Record<string, FactorCurvePoint[]>
  methodology: {
    split: string
    execution: string
    usable_rule: string
    warning: string
  }
}

// ---- G7 组合管理 ----
export interface PortfolioManageResp {
  allocations: Array<{
    id: string
    strategy: string
    weight: number
    symbol: string | null
    live: boolean
    note: string | null
  }>
  summary: {
    n_alloc: number
    total_weight: number
    live_count: number
    exposure: { long: number; short: number; hold: number; total: number }
    max_weight: number
    concentration: number
  }
}

// ---- G5 实盘（paper）----
export interface LiveResp {
  ok?: boolean
  name: string
  live_capable: boolean
  is_live?: boolean
  mode?: string
  state?: unknown
  note?: string
  error?: string
}

// ---------- PA 分析视图模型（来自 pa_agent.view_models） ----------

export interface PaAnalyzeResp {
  ok: boolean
  research_run_id?: string
  symbol: string
  timeframe: string
  market: string
  error?: string
  decision?: DecisionView
  future?: FutureTrendView
  tree?: DecisionTreeView
  stage1?: Record<string, unknown>
  stage2?: Record<string, unknown>
  meta?: {
    kline_count: number
    stage1_complete: boolean
    stage2_complete: boolean
    gate_shortcircuited: boolean
    usage: Record<string, number>
    validation_retries: number
    validation: Record<string, PaValidationStageReport>
  }
}

export interface PaValidationIssue {
  code: string
  field: string
  message: string
  severity: 'error' | 'warning'
}

export interface PaValidationStageReport {
  stage: 'stage1' | 'stage2'
  valid: boolean
  error_count: number
  warning_count: number
  attempts: number
  source?: string
  issues: PaValidationIssue[]
}

export interface DecisionView {
  trend: string
  trend_color?: string
  cycle: string
  phase: string
  diagnosis_confidence: { score: number | null; color: string | null; reasoning: string }
  order_type: string
  direction: string
  entry: number | null
  tp1: number | null
  tp2: number | null
  sl: number | null
  risk_reward: {
    ratio_text: string
    risk: number
    reward: number
    metrics_ok: boolean
    note: string
  } | null
  estimated_win_rate: string
  trade_confidence: { score: number | null; color: string | null; reasoning: string }
  reasoning: string
  key_factors: string[]
  watch_points: string[]
  risk_assessment: string
}

export interface FutureTrendView {
  next_bar: {
    direction: string
    direction_zh: string
    color: string
    probabilities: { bullish: number; bearish: number; neutral: number }
    reasoning: string
  } | null
  next_cycle: {
    unpredictable: boolean
    direction: string
    direction_zh: string
    color: string
    top3: { label: string; pct: number }[]
    rest: { label: string; pct: number }[]
    reasoning: string
  } | null
}

export interface DecisionTreeView {
  path: {
    step: number
    phase: string
    node: string
    question: string
    answer: string
    basis: string
    reason: string
  }[]
  sections: { id: string; title: string; nodes: { id: string; question: string }[] }[]
  terminal: Record<string, unknown> | null
  gate_result: string | null
  gate_shortcircuited: boolean
}

// ---------- 组合与市场面板 ----------

export interface PortfolioSummary {
  nav: number
  dailyPnl: number
  dailyPnlPct: number
  cash: number
  /** 涨跌派生情绪分（非真实胜率；真实胜率见 DecisionPanel 的 estimated_win_rate）。 */
  chgBasedScore: number
  totalPositions: number
}

export interface PortfolioHolding {
  /** DB 主键（编辑/删除用）；旧数据可能缺失 */
  id?: string
  code: string
  name: string
  price: number
  /** 持仓成本价（用于前端可编辑持仓的盈亏计算）。 */
  cost: number
  chgPct: number
  shares: number
  pnl: number
  /** 涨跌派生情绪分（非真实胜率）。 */
  chgBasedScore: number
  /** 市场标识（a_shares/us_stocks/crypto） */
  market?: string
}

/** 持仓 CRUD 端点返回的结构（POST/PATCH /portfolio/holdings）。 */
export interface HoldingCRUDResp {
  id: string
  code: string
  name: string
  shares: number
  cost: number
  market: string
}

export interface PortfolioResp {
  ok: boolean
  summary: PortfolioSummary
  holdings: PortfolioHolding[]
}

export interface MarketBreadthResp {
  ok: boolean
  /** 是否为样本口径（非全市场）；当前环境无法获取全市场涨跌家数时为 true。 */
  sample?: boolean
  note?: string
  up: number
  flat: number
  down: number
  sectors: { name: string; chgPct: number }[]
}

export interface WatchlistItem {
  /** DB 主键（编辑/删除用）；旧数据可能缺失 */
  id?: string
  sym: string
  name: string
  /** 最新价；无法接入数据源时为 null（如加密货币在当前环境无可用源）。 */
  price: number | null
  /** 涨跌幅(%)；与 price 同为 null 时表示不可用。 */
  chgPct: number | null
  /** 数据源是否可用；false 时前端展示“数据源不可用”，不伪装成 0。 */
  available?: boolean
  market?: string
}

export interface WatchlistResp {
  ok: boolean
  items: WatchlistItem[]
}

/** 关注列表 CRUD 端点返回的结构（POST/PATCH /market/watchlist）。 */
export interface WatchlistCRUDResp {
  id: string
  sym: string
  name: string
  market: string
}

/** 单标的实时报价（/market/quote）。 */
export interface QuoteResp {
  sym: string
  /** 行情源解析出的证券名称；无法解析时为空。 */
  name: string
  market: string
  price: number | null
  chgPct: number | null
  available: boolean
}

// ---------- 算法协同预测（/predict/ensemble） ----------
export interface EnsembleContributor {
  name: string
  kind: 'technical' | 'llm' | 'news'
  direction: string // buy | sell | hold
  score: number
  confidence: number
  weight: number
  available: boolean
  rationale?: string
  metrics?: Record<string, unknown>
}

export interface EnsembleConsensus {
  direction: string // buy | sell | hold
  score: number // 综合强度 0~1
  confidence: number // 共识置信 0~1
  agreement: number // 共识度 0~1
  buy_votes: number
  sell_votes: number
  n: number // 参与算法数
}

export interface EnsembleResp {
  ok: boolean
  research_run_id?: string
  symbol: string
  market?: string
  timeframe?: string
  data_source?: string
  kline_count?: number
  error?: string
  contributors?: EnsembleContributor[]
  consensus?: EnsembleConsensus
  warnings?: string[]
}

// ---------- 配置（API Key 等） ----------

export type LLMProviderId = 'deepseek' | 'openai' | 'custom'

export interface LLMProviderPreset {
  id: LLMProviderId
  label: string
  description: string
  official_url: string
  base_url: string
  model: string
  key_env: string
  configured: boolean
}

export interface LLMConfigResp {
  ok: boolean
  configured: boolean
  provider: LLMProviderId
  provider_label: string
  official_url: string
  key_env: string
  masked: string | null
  base_url: string
  models_endpoint: string
  model: string
  timeout: number
  max_retries: number
  providers: LLMProviderPreset[]
}

export type ApiKeyResp = LLMConfigResp

export interface LLMSettingsUpdate {
  provider: LLMProviderId
  api_key?: string
  base_url: string
  model: string
  timeout: number
  max_retries: number
}

export interface LLMConnectionTestResp {
  ok: boolean
  provider: LLMProviderId
  endpoint: string
  latency_ms: number
  status_code: number | null
  models: string[]
  error: string | null
}

// ---------- Instrument 标的主数据 ----------

export interface Instrument {
  instrument_id: string
  code: string
  market: string
  exchange: string
  name: string
  currency: string
  asset_class: string
}

// ---------- 组合账本 ----------

export interface LedgerTrade {
  id: string
  instrument_id: string
  code: string
  market: string
  direction: 'buy' | 'sell'
  quantity: number
  price: number
  fee: number
  ts: number
  source: string
  note: string
  cash_flow?: number
}

export interface LedgerCashEntry {
  id: string
  direction: 'in' | 'out'
  amount: number
  currency: string
  ts: number
  source: string
  note: string
}

export interface LedgerPosition {
  instrument_id: string
  code: string
  market: string
  quantity: number
  average_cost: number
  realized_pnl: number
  last_price: number
  ts: number
  unrealized_pnl: number
  market_value: number
  cost_basis: number
}

export interface LedgerSummary {
  nav: number
  cash: number
  market_value: number
  cost_basis: number
  realized_pnl: number
  unrealized_pnl: number
  total_pnl: number
  return_pct: number
  n_positions: number
}

export interface LedgerPerformance {
  ok: boolean
  equity_curve: Array<{ t: number | string | null; equity: number }>
  twr_pct: number
  max_drawdown: {
    max_drawdown_pct: number
    peak_equity?: number
    peak_at: number | string | null
    trough_at: number | string | null
  }
  benchmark_excess: {
    portfolio_return_pct: number
    benchmark_return_pct: number
    excess_return_pct: number
    benchmark_name: string
    benchmark_code: string
  } | null
}

export interface LedgerTradeAnalyticsGroup {
  key: string
  count: number
  wins: number
  pnl: number
  win_rate_pct: number
}

export interface LedgerTradeAnalytics {
  ok: boolean
  summary: {
    closed_trades: number
    total_pnl: number
    return_pct: number
    win_rate_pct: number
    profit_factor: number | null
    average_profit_loss_ratio: number | null
    max_consecutive_losses: number
    average_holding_seconds: number
    max_stagnation_days: number
  }
  execution_quality: {
    total_fees: number
    average_fee: number
    fee_drag_pct: number
    slippage_available: boolean
    slippage_note: string
  }
  matching: { open_lot_count: number; open_quantity: number }
  cumulative_curve: Array<{ t: number; pnl: number; drawdown: number }>
  monthly: LedgerTradeAnalyticsGroup[]
  daily: LedgerTradeAnalyticsGroup[]
  directions: LedgerTradeAnalyticsGroup[]
  holding_buckets: Array<{ key: string; count: number; share_pct: number; pnl: number }>
  closed_trade_rows: Array<{
    instrument_id: string
    code: string
    market: string
    direction: 'long' | 'short'
    quantity: number
    entry_price: number
    exit_price: number
    entry_at: number
    exit_at: number
    holding_seconds: number
    gross_pnl: number
    fees: number
    pnl: number
    return_pct: number
    source: string
  }>
}

export interface LedgerExposures {
  ok: boolean
  by_market: Record<string, number>
  by_direction: { long: number; short: number }
  by_symbol: Array<{ code: string; market: string; market_value: number; weight_pct: number }>
  total_market_value: number
  gross_market_value: number
}

export interface LedgerAttributionGroup {
  key: string
  trade_count: number
  notional: number
  fees: number
  cash_flow: number
}

export interface LedgerAttribution {
  ok: boolean
  start_at: number | null
  end_at: number | null
  period: 'day' | 'week' | 'month'
  by_instrument: Array<{
    instrument_id: string
    code: string
    market: string
    realized_pnl: number
    unrealized_pnl: number
    total_pnl: number
    trade_count: number
  }>
  by_strategy: LedgerAttributionGroup[]
  by_direction: LedgerAttributionGroup[]
  by_period: LedgerAttributionGroup[]
}

export interface DecisionTimelineEvent {
  kind: 'research_run' | 'signal' | 'simulation_order' | 'simulation_execution' | 'ledger_trade'
  id: string
  ts: number
  status: string
  label: string
  note?: string | null
  links: Record<string, string | null>
}

export interface PositionDecisionContext {
  ok: boolean
  position: LedgerPosition
  timeline: { ok: boolean; instrument_id: string; count: number; events: DecisionTimelineEvent[] }
}

export interface LedgerBenchmark {
  id: string
  name: string
  code: string
  market: string
  equity_curve: Array<Record<string, unknown>>
  metrics: Record<string, unknown>
  ts: number
}

export interface LedgerCorrection {
  id: string
  entity_type: 'trade' | 'cash' | 'benchmark'
  entity_id: string
  reason: string
  before: Record<string, unknown>
  after: Record<string, unknown>
  created_at: number
}

// ---------- 策略实验室 ----------

export interface StrategyVersion {
  id: string
  definition_id: string
  version: string
  params: Record<string, unknown>
  code_hash: string
  changelog: string
  created_at: number
  archived_at?: number | null
}

export interface StrategyDefinition {
  id: string
  name: string
  strategy_key: string
  market: string
  description: string
  tags: string[]
  created_at: number
  updated_at: number
  archived_at?: number | null
  versions?: StrategyVersion[]
}

export interface StrategyExperiment {
  id: string
  definition_id: string
  symbol: string
  market: string
  timeframe: string
  version_id: string | null
  status: string
  params: Record<string, unknown>
  note: string
  created_at: number
  updated_at?: number
  archived_at?: number | null
}

export interface StrategyLabRun {
  id: string
  experiment_id: string
  symbol: string
  market: string
  timeframe: string
  params: Record<string, unknown>
  data_snapshot: Record<string, unknown>
  initial_capital: number
  equity_curve: Array<Record<string, unknown>>
  trades: Array<Record<string, unknown>>
  metrics: Record<string, unknown>
  seed: string | null
  status: string
  error: string
  started_at: number
  finished_at: number | null
}

export interface StrategyLabComparisonRow {
  run_id: string
  symbol: string
  market: string
  timeframe: string
  initial_capital: number
  seed: string | null
  status: string
  metrics: Record<string, unknown>
  n_trades: number
  data_snapshot_sha256: string | null
  data_snapshot: Record<string, unknown>
  params: Record<string, unknown>
  code_hash: string | null
}

export interface StrategyLabFieldDifference {
  field: string
  before: unknown
  after: unknown
  changed: boolean
}

export interface StrategyLabRunDifference {
  against_run_id: string
  run_id: string
  data_snapshot: StrategyLabFieldDifference[]
  params: StrategyLabFieldDifference[]
  code_hash: { before: string | null; after: string | null; changed: boolean }
  metrics: StrategyLabFieldDifference[]
}

// ---------- 自动化控制台 ----------

export interface AutomationJob {
  name: string
  market: string
  cron: string
  func_name: string
  custom: boolean
  enabled: boolean
  next_run: string | null
  updated_at: number | null
  updated_by: string | null
}

export type AutomationRunStatus = 'queued' | 'running' | 'succeeded' | 'failed'

export interface AutomationRun {
  id: string
  job_name: string
  status: AutomationRunStatus
  trigger_type: 'manual' | 'retry'
  attempt: number
  parent_run_id: string | null
  log: string
  error: string | null
  created_at: number
  started_at: number | null
  finished_at: number | null
  duration_ms: number | null
  acknowledged_at: number | null
  acknowledged_by: string | null
}

export interface AutomationAuditLog {
  id: string
  action: string
  entity_type: string
  entity_id: string
  actor: string
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
  result: string
  error: string | null
  created_at: number
}

// ---------- 访问治理 ----------

export interface GovernanceUser {
  id: string
  username: string
  display_name: string
  active: boolean
  created_at: number
  roles: string[]
  permissions: string[]
}

export interface GovernanceRole {
  id: string
  name: string
  permissions: string[]
}

export interface ApiTokenRecord {
  id: string
  user_id: string
  username: string
  label: string
  expires_at: number | null
  last_used_at: number | null
  created_at: number
  revoked_at: number | null
}

export interface CreatedApiToken {
  id: string
  user_id: string
  label: string
  token: string
  expires_at: number | null
  created_at: number
}

export interface GovernanceAuditLog {
  id: string
  actor_id: string
  action: string
  entity_type: string
  entity_id: string
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
  result: string
  error: string | null
  created_at: number
}

export interface GlobalSearchItem {
  id: string
  group: 'instruments' | 'definitions' | 'experiments' | 'research' | 'signals' | 'orders'
  marker: string
  label: string
  detail: string
  path: string
  secondary_label?: string
  secondary_path?: string
}

export type AlertRuleType =
  | 'price_above'
  | 'price_below'
  | 'change_pct_above'
  | 'change_pct_below'
  | 'volatility_above'
  | 'signal_created'
  | 'evaluation_changed'
  | 'risk_invalidated'

export interface AlertRule {
  id: string
  user_id: string
  name: string
  rule_type: AlertRuleType
  symbol: string
  market: string
  threshold: number | null
  enabled: boolean
  frequency_minutes: number
  quiet_start: string | null
  quiet_end: string | null
  expires_at: number | null
  context: Record<string, unknown>
  last_checked_at: number | null
  last_triggered_at: number | null
  created_at: number
  updated_at: number
}

export interface AlertEvent {
  id: string
  rule_id: string
  status: 'pending' | 'acknowledged'
  message: string
  observed_value: number | null
  related_type: string | null
  related_id: string | null
  delivery: Record<string, boolean>
  triggered_at: number
  acknowledged_at: number | null
  rule_name: string
  symbol: string
  market: string
}

export interface AutomationStatus {
  ok: boolean
  total?: number
  enabled_count?: number
  by_market?: Record<string, number>
  custom_entry_count?: number
  generic_entry_count?: number
  running_count?: number
  failed_count?: number
  unacknowledged_alert_count?: number
  running?: boolean
  note?: string
  error?: string
}

export interface BackupRecord {
  name: string
  path: string
  bytes: number
  modified_at: number
}

export interface BackupStatus {
  ok: boolean
  supported: boolean
  source_path: string
  source_exists: boolean
  backup_directory: string
  backup_count: number
  latest_backup: BackupRecord | null
}

export interface ConfigSystemStatus {
  ok: boolean
  gateway: {
    version: string
    live_trading: boolean
    store_path: string
    deployment_mode: string
    started_at: string
    build_id: string
  }
  live_confirm: { enabled: boolean; mode: string | null; timeout_seconds: number | null }
  llm: { provider: string; configured: boolean; key_env: string }
  capabilities: {
    a_shares: { akshare: boolean }
    news_sentiment: {
      engine: 'transformers' | 'snownlp' | 'keyword'
      snownlp: boolean
      transformers: boolean
      torch: boolean
      model_path: string
      model_available: boolean
    }
  }
  notifications: NotificationStatus
  scheduler: { ok: boolean; total: number; enabled_count: number; running_count: number }
  backups: { supported: boolean; source_exists: boolean; backup_directory: string; backup_count: number; latest_backup: BackupRecord | null }
}

export type NotificationChannelName = 'wecom' | 'webhook' | 'telegram'

export interface NotificationStatus {
  ok: boolean
  enabled: boolean
  channels: Array<{
    channel: NotificationChannelName
    enabled: boolean
    configured: boolean
    fields: Record<string, string | null>
  }>
}

export interface BackupVerification {
  ok: boolean
  integrity: string
  table_count: number
  bytes: number
}

export interface BackupRetentionResult {
  ok: boolean
  directory: string
  keep: number
  matched: number
  deleted: number
  candidates: string[]
  dry_run: boolean
  actor: string
}

export type IncidentSource = 'analysis_task' | 'automation_run' | 'ledger_sync' | 'data_source'

export interface IncidentAction {
  type:
    | 'retry_analysis_task'
    | 'retry_automation_run'
    | 'acknowledge_automation_run'
    | 'retry_ledger_sync'
    | 'open_data_source_status'
    | 'check_data_source'
    | 'acknowledge_data_source_recovery'
  label: string
  task_id?: string
  run_id?: string
  order_id?: string
  execution_id?: string
  incident_id?: string
}

export interface IncidentRecord {
  id: string
  source: IncidentSource
  entity_id: string
  status: string
  occurred_at: number
  error: string
  context: Record<string, string | number | boolean | null>
  actions: IncidentAction[]
}

// ---------- 新闻结构化分析（Phase 1：本地 LM Studio） ----------

/** 提取的命名实体 */
export interface NewsEntity {
  text: string
  type: 'person' | 'org' | 'location'
  start?: number | null
  end?: number | null
}

/** 情绪结果 */
export interface NewsSentiment {
  label: 'positive' | 'negative' | 'neutral'
  score: number // [-1.0, 1.0]
  confidence: number // [0, 1]
}

export interface NewsEventImpact {
  label: 'positive' | 'negative' | 'neutral' | 'uncertain'
  confidence: number
  reason: string
  rule_id: string | null
}

export interface NewsPriceDirection {
  label: 'up' | 'down' | 'flat' | 'uncertain'
  confidence: number
  reason: string
}

/** 单条新闻结构化分析 */
export interface NewsAnalysisItem {
  title: string
  source: string
  url: string | null
  ts: string | null
  symbols: string[]
  entities: NewsEntity[]
  sentiment: NewsSentiment
  event_impact?: NewsEventImpact
  price_direction?: NewsPriceDirection
  topic: string
  summary: string
  engine: string // "semantic" | "semantic+api" | "keyword"
  model: string | null
  latency_ms: number
  error: string | null
}

/** POST /news/analyze 响应 */
export interface NewsAnalyzeResp {
  ok: boolean
  research_run_id?: string
  degraded: boolean
  degraded_reason: string | null
  engine: string
  model: string | null
  total: number
  items: NewsAnalysisItem[]
  topic_dist: Record<string, number>
  sentiment_dist: { positive: number; negative: number; neutral: number }
  event_impact_dist: { positive: number; negative: number; neutral: number; uncertain: number }
  top_entities: { text: string; type: string; count: number }[]
}

/** GET /news/health 响应 */
export interface NewsHealthResp {
  ok: boolean
  engine: string  // transformers / snownlp / keyword（SentimentAnalyzer 实际引擎）
  api_enhancement: boolean  // DeepSeek API 是否可用
  api_provider: string
  model: string | null
}

/** 9 主题受控词表（与后端 NewsTopic 枚举 1:1） */
export interface NewsTopicMeta {
  value: string
  label: string
  color: string
}

export const NEWS_TOPICS: NewsTopicMeta[] = [
  { value: 'macro', label: '宏观经济', color: '#2f81f7' },
  { value: 'monetary', label: '货币政策', color: '#8b5cf6' },
  { value: 'industry', label: '行业动态', color: '#06b6d4' },
  { value: 'company', label: '公司经营', color: '#16c784' },
  { value: 'capital_action', label: '资本运作', color: '#f59e0b' },
  { value: 'regulation', label: '监管政策', color: '#f0b429' },
  { value: 'market_mood', label: '市场情绪', color: '#ec4899' },
  { value: 'international', label: '国际财经', color: '#14b8a6' },
  { value: 'unknown', label: '未分类', color: '#647488' },
]

/** 情绪标签映射 */
export const SENTIMENT_META: Record<
  string,
  { label: string; cls: string }
> = {
  positive: { label: '正面', cls: 'positive' },
  negative: { label: '负面', cls: 'negative' },
  neutral: { label: '中性', cls: 'neutral' },
}

/** 实体类型映射 */
export const ENTITY_META: Record<string, { label: string; cls: string }> = {
  person: { label: '人物', cls: 'person' },
  org: { label: '机构', cls: 'org' },
  location: { label: '地点', cls: 'location' },
}
