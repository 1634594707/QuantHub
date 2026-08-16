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
  current_source_build_id: string
  restart_required: boolean
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

export interface UserResearchPreference {
  user_id: string
  default_mode: 'quick' | 'investor' | 'professional' | 'quant'
  default_market: 'a_shares' | 'us_stocks' | 'crypto'
  holding_status: 'not_held' | 'held'
  research_horizon: 'short' | 'swing' | 'medium' | 'long'
  risk_preference: 'conservative' | 'balanced' | 'aggressive'
  terminology_level: 'plain' | 'standard' | 'technical'
  updated_at: string
}

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
  tags: string[]
  archived_at: number | null
  created_at: number
  updated_at: number
  evidence_count: number
  evidence?: ResearchEvidence[]
}

export interface ResearchModuleOpinion {
  module: string
  direction: 'long' | 'short' | 'neutral' | 'insufficient'
  confidence: number | null
  evidence_at: string | null
  status: 'available' | 'stale' | 'failed' | 'missing'
  reason: string
  evidence_id: string | null
}

export interface ResearchDecision {
  direction: 'long' | 'short' | 'neutral' | 'conflicted' | 'insufficient'
  execution_eligible: boolean
  module_opinions: ResearchModuleOpinion[]
  conflicts: Array<{ kind: string; modules: string[]; reason: string; blocking: boolean }>
  invalidation_conditions: string[]
  reevaluate_triggers: string[]
  decision_version: string
  decided_at: string
  input_fingerprint: string
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
  structured_snapshots: Array<{
    direction: string
    execution_eligible: boolean
    conflicts: Array<Record<string, unknown>>
    decision_version: string | null
    module_opinions: Array<Record<string, unknown>>
    metrics: Record<string, number | null>
    levels: Record<string, number | null>
    news_themes: unknown[]
    invalidation_conditions: string[]
    reevaluate_triggers: string[]
  }>
  changes: Array<{
    kind: string
    field: string
    before: unknown
    after: unknown
    delta?: number | null
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
  radar_state?: 'current' | 'expired'
}

export type SignalLifecycleStatus = 'new' | 'accepted' | 'rejected' | 'expired' | 'converted'

export type SimulationOrderStatus = 'pending' | 'partially_filled' | 'filled' | 'cancelled'
export type SimulationLedgerSyncStatus = 'pending' | 'synced' | 'failed' | 'isolated'

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
  theoretical_price: number | null
  simulated_price: number
  slippage_bps: number | null
  signal_time: string | null
  tradable_time: string | null
  rejection_reason: string | null
  capacity_used: number
  live_trading_enabled: false
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
  audit: {
    factor_key?: string | null
    factor_version?: string | null
    research_run_id?: string | null
    rebalance_cycle_id?: string | null
    signal_time?: string | null
    tradable_time?: string | null
    theoretical_price?: number | null
    capacity_used?: number
    rejection_reason?: string | null
    live_trading_enabled: false
  }
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

// ---- 模拟实验室（因子 / 策略回测沙盒）----

/** 数据源：真实 OKX 归档 / 真实 OKX 实时 / 确定性合成 */
export type DemoSourceKey = 'okx_local' | 'okx_live' | 'synthetic'

export interface DemoSourceOption {
  key: DemoSourceKey
  label: string
  description: string
  realtime: boolean
  needs_network: boolean
  intervals: string[]
  symbols: Array<{ symbol: string; label: string }>
  /** 仅本地归档通道有值：每个标的每个周期的行数与覆盖区间 */
  symbol_coverage: Record<
    string,
    Record<string, { rows: number; first: string; last: string; file: string }>
  >
}

export interface DemoFactorOption {
  key: string
  label: string
  description: string
  default_params: Record<string, number>
}

export interface DemoStrategyOption {
  key: string
  label: string
  description: string
  uses_factor: boolean
}

export interface DemoDatasetOption {
  key: string
  label: string
  description: string
  drift: number
  vol: number
  start_price: number
  regime: string
}

export interface DemoCatalog {
  ok: boolean
  sources: DemoSourceOption[]
  datasets: DemoDatasetOption[]
  factors: DemoFactorOption[]
  strategies: DemoStrategyOption[]
  intervals: string[]
  defaults: {
    source: DemoSourceKey
    symbol: string
    dataset: string
    seed: number
    n_bars: number
    interval: string
    start: string | null
    end: string | null
    use_cache: boolean
    initial_capital: number
    commission: number
    position_fraction: number
    strategy: string
    factor: string
  }
}

export interface DemoRunPayload {
  source: DemoSourceKey
  symbol?: string | null
  dataset?: string
  seed?: number
  n_bars: number
  interval: string
  start?: string | null
  end?: string | null
  use_cache?: boolean
  initial_capital: number
  commission: number
  position_fraction: number
  strategy: string
  factor?: string | null
  factor_params?: Record<string, unknown>
  factor_ast?: Record<string, unknown> | null
  factor_label?: string | null
  factor_version?: string | null
}

export interface DemoDataProvenance {
  source: DemoSourceKey
  channel: string
  fingerprint: string
  bars?: number
  symbol?: string
  interval?: string
  offline?: boolean
  reproducible?: string
  cache_hit?: boolean
  cache_written?: boolean
  cache_file?: string
  fetched_at?: string
  ccxt_symbol?: string
  file?: string
  archive_rows?: number
  archive_first?: string
  archive_last?: string
  selected_first?: string
  selected_last?: string
  dataset?: string
  seed?: number
  start?: string
}

export interface DemoRunMetrics {
  annual_return?: number | null
  annual_volatility?: number | null
  sharpe?: number | null
  sortino?: number | null
  calmar?: number | null
  max_drawdown?: number | null
  win_rate?: number | null
  trade_win_rate?: number | null
  trade_count?: number | null
  avg_win?: number | null
  avg_loss?: number | null
  profit_factor?: number | null
  [key: string]: number | null | undefined
}

export interface DemoRunSummaryBlock {
  final_equity: number
  total_return: number
  max_drawdown: number
  engine: string
  n_trades: number
  metrics: DemoRunMetrics
}

export interface DemoEquityPoint {
  datetime: string
  equity: number
}

export interface DemoTrade {
  datetime: string
  side: 'buy' | 'sell'
  price: number
  qty: number
  realized_pnl: number
}

export interface DemoRunLogEntry {
  step: string
  message: string
  at: string
}

export interface DemoRunResult {
  ok: boolean
  run_id: string
  config: Record<string, unknown>
  data_provenance: DemoDataProvenance
  summary: DemoRunSummaryBlock
  equity_curve: DemoEquityPoint[]
  trades: DemoTrade[]
  run_log: DemoRunLogEntry[]
  persisted: boolean
}

export interface DemoRunSummary {
  run_id: string
  created_at: string | null
  source: DemoSourceKey
  symbol: string | null
  interval: string | null
  strategy: string | null
  factor: string | null
  total_return: number | null
  max_drawdown: number | null
  sharpe: number | null
  n_trades: number | null
  fingerprint: string | null
}

export interface DemoRunRecord {
  run_id: string
  created_at: string
  config: Record<string, unknown>
  data_provenance: DemoDataProvenance
  summary: DemoRunSummaryBlock
  equity_curve: DemoEquityPoint[]
  trades: DemoTrade[]
  run_log: DemoRunLogEntry[]
}

export interface SimulationOrderPreviewCheck {
  code: string
  status: 'passed' | 'failed'
  actual: unknown
  limit: unknown
  reevaluate_action: string
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
  gross_exposure_before: number
  gross_exposure_after: number | null
  cash_before: number
  cash_after: number | null
  equity: number
  risk_evaluated: boolean
  can_submit: boolean
  outcome: 'approved' | 'rejected'
  reason_codes: string[]
  checks: SimulationOrderPreviewCheck[]
  evaluated_at: string
  rule_version: string
  input_fingerprint: string
  snapshot: {
    market: Record<string, unknown>
    account: Record<string, unknown>
    open_order_count: number
    cost_profile: Record<string, unknown>
    research_decision: Record<string, unknown> | null
  }
}

export interface SignalsResp {
  count: number
  total: number
  next_cursor: string | null
  signals: SignalResp[]
}

export interface RadarSignalsResp {
  count: number
  current_count: number
  expired_count: number
  scanned: number
  generated_at: number
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
  confidence: number
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
  report?: Record<string, unknown>
  signal_rejection?: {
    code: string
    message: string
    details?: Record<string, unknown>
  }
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
  formula: string
  formula_version: string
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
  adjusted_p_value?: number
  statistically_significant?: boolean
  hypothesis_family?: string
  canonical_factor_key?: string
  is_redundant_alias?: boolean
  decay: Array<{ horizon: number; ic: number }>
  hit_rate: number
  observations: number
  test_observations: number
  effective_observations?: number
  effective_observations_basis?: 'hac_implied'
  p_value_method?: 'newey_west_hac'
  hac_lags?: number
  window_pass_rate?: number
  passed_windows?: number
  window_count?: number
  worst_window_ic?: number
  median_window_ic?: number
  window_ic_iqr?: number
  status_transitions?: number
  direction_flips?: number
  multi_window_consistent?: boolean
  windows?: FactorValidationWindow[]
  stable: boolean
  exploratory_candidate?: boolean
  selection_semantics?: 'exploratory_candidate'
  /** @deprecated Use exploratory_candidate. */
  selected: boolean
  weight: number
}

export interface FactorWindowRange {
  start_index: number
  end_index: number
  start: string | null
  end: string | null
  rows: number
}

export interface FactorValidationWindow {
  fold: number
  mode: 'expanding' | 'rolling'
  train: FactorWindowRange
  purge: FactorWindowRange
  test: FactorWindowRange
  direction?: 'positive' | 'inverse'
  train_observations?: number
  test_observations?: number
  train_ic?: number
  test_ic?: number
  hit_rate?: number
  p_value?: number
  effective_observations?: number
  hac_lags?: number
  status?: 'pass' | 'watch' | 'reject'
}

export interface QuantMethodResult {
  key: string
  label: string
  total_return: number
  annual_return: number
  sharpe: number
  deflated_sharpe_ratio?: number
  expected_max_sharpe?: number
  multiple_testing_trials?: number
  sharpe_observations?: number
  sharpe_skewness?: number
  sharpe_kurtosis?: number
  deflated_sharpe_method?: 'deflated_sharpe_non_normal_multiple_trials'
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
  profit_factor_basis?: 'holding_period_returns' | 'closed_trades'
  max_drawdown_duration: number
  average_holding_period: number
  win_rate: number
  win_rate_basis?: 'holding_period_returns' | 'closed_trades'
  closed_trades?: number
  open_trade?: boolean
  average_trade_return?: number
  average_win?: number
  average_loss?: number
  payoff_ratio?: number
  turnover: number
  trades: number
  exposure: number
  constructed?: boolean
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
  run_id?: string
  saved?: boolean
  saved_at?: number
  persistence_error?: string
  compatibility?: {
    current_engine_version: string
    record_engine_version: string | null
    legacy_engine_record: boolean
    policy: 'historical_result_preserved_read_only' | 'current_engine'
  }
  symbol: string
  market: string
  interval: string
  source: string
  requested_period?: {
    start_date: string | null
    end_date: string | null
  }
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
    walk_forward_test_rows?: number
    horizon: number
    availability_lag?: number
    purge_embargo_periods?: number
    transaction_cost_bps: number
    significance_level?: number
    usable_factors: number
    effective_factor_hypotheses?: number
    multiple_testing_trials?: number
    deflated_sharpe_method?: 'deflated_sharpe_non_normal_multiple_trials'
    reality_check_method?: 'white_reality_check_moving_block_bootstrap'
    selected_factors: string[]
    exploratory_candidates?: string[]
    selected_factors_semantics?: 'deprecated_alias_of_exploratory_candidates'
    multifactor_constructed?: boolean
    best_factor: string | null
    best_method: string | null
    evaluation_scope: 'out_of_sample' | 'walk_forward_out_of_sample'
    significance_method?: 'newey_west_hac_benjamini_hochberg'
    walk_forward_mode?: 'expanding' | 'rolling'
    requested_walk_forward_folds?: number
    walk_forward_folds?: number
    window_pass_requirement?: 'strict_majority'
    engine_version?: string
    factor_formula_version?: string
    data_fingerprint?: string
    research_period?: { start: string; end: string }
    thresholds?: Record<string, number | string>
    windows?: FactorValidationWindow[]
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
  cost_analysis?: {
    available?: boolean
    basis: 'multifactor_final_out_of_sample_window'
    reason?: string
    curve: Array<{ transaction_cost_bps: number; total_return: number }>
    breakeven_transaction_cost_bps: number | null
  }
  reality_check?: FactorRealityCheck
  methodology: {
    split: string
    execution: string
    usable_rule: string
    warning: string
    metric_definitions?: Array<{
      key: string
      label: string
      formula: string
      unit: string
      source: string
    }>
  }
}

export interface FactorRealityCheck {
  available: boolean
  reason?: string
  method?: 'white_reality_check_moving_block_bootstrap'
  benchmark?: 'provided_returns' | 'zero_return'
  best_candidate?: string
  observed_max_statistic?: number
  p_value?: number
  observations?: number
  candidate_count?: number
  block_size?: number
  bootstrap_samples?: number
  seed?: number
}

export interface FactorAiReviewResp {
  ok: boolean
  error?: string
  run_id?: string
  saved?: boolean
  review?: {
    verdict: '支持继续研究' | '谨慎复核' | '证据不足'
    confidence: number
    statistical_alignment: '一致' | '部分一致' | '冲突'
    summary: string
    overfitting_risk: { level: '低' | '中' | '高'; reasons: string[] }
    regime_risk: { level: '低' | '中' | '高'; reasons: string[] }
    factor_reviews: Array<{
      factor_key: string
      label: string
      statistical_status: FactorStatus
      assessment: string
      evidence: string[]
      risks: string[]
      regime_fit: string[]
      next_test: string
    }>
    portfolio_review: { strengths: string[]; risks: string[] }
    experiments: Array<{
      title: string
      hypothesis: string
      design: string
      success_criteria: string
    }>
    uncertainties: string[]
  }
  meta?: {
    provider?: string
    model?: string
    generated_at?: string
    input_fingerprint?: string
    attempts: number
    usage?: Record<string, number>
    statistical_conclusions_locked?: boolean
  }
}

export interface FactorResearchRunsResp {
  ok: boolean
  runs: ResearchRun[]
  total: number
  next_cursor: string | null
}

export interface FactorResearchRunDetailResp {
  ok: boolean
  run: ResearchRun
  result: FactorResearchResp | null
  ai_review: FactorAiReviewResp | null
}

export interface FactorDefinitionRecord {
  id: string
  key: string
  factor_key: string
  label: string
  market: 'a_shares' | 'us_stocks' | 'crypto' | 'mt5' | 'all'
  input_fields: string[]
  ast: Record<string, unknown>
  direction: 'positive' | 'inverse'
  horizon: number
  availability_lag: number
  rationale: string
  family: string
  version: string
  parameters: Record<string, unknown>
  formula_hash: string
  definition_hash: string
  validation: {
    unit: string
    shape: 'series'
    fields: string[]
    depth: number
    operators: number
  }
  created_at: number
}

export type FactorLifecycleState =
  | 'draft'
  | 'exploratory'
  | 'research_passed'
  | 'trading_validated'
  | 'degraded'
  | 'retired'

export interface FactorLifecycleEvent {
  id: string
  factor_definition_id: string
  event_sequence: number
  state: FactorLifecycleState
  target_market: 'a_shares' | 'us_stocks' | 'crypto' | 'mt5' | 'all'
  actor_type: 'system' | 'researcher' | 'ai'
  actor: string
  rule: string
  evidence: Record<string, unknown>
  created_at: number
}

export interface FactorLifecycleRecord {
  ok: boolean
  factor_key: string
  version: string
  definition_hash: string
  current_by_market: Record<string, FactorLifecycleEvent>
  events: FactorLifecycleEvent[]
}

export type FactorFactoryRunStatus =
  | 'discovering'
  | 'no_qualified_factor'
  | 'no_research_passed_factor'
  | 'paper_observing'
  | 'paper_rejected'
  | 'trading_validated'
  | 'degraded'
  | 'failed'

export interface FactorFactoryRunRecord {
  id: string
  research_plan_id: string
  status: FactorFactoryRunStatus
  config: Record<string, unknown>
  result: Record<string, unknown>
  selected_factor_key: string | null
  selected_factor_version: string | null
  selected_experiment_id: string | null
  error: string | null
  started_at: number
  updated_at: number
  observation_started_at: number | null
  observation_ends_at: number | null
}

export interface FactorFactoryCandidateRecord {
  id: string
  run_id: string
  factor_key: string
  factor_version: string
  source: 'human' | 'ai' | 'template' | 'random_dsl' | 'symbolic_regression' | 'parameter_search'
  experiment_id: string | null
  status: string
  rank: number | null
  metrics: Record<string, unknown>
  gate: Record<string, unknown>
  definition?: FactorDefinitionRecord | null
  created_at: number
  updated_at: number
}

export interface FactorFactoryObservationRecord {
  id: string
  run_id: string
  observed_at: number
  market_time: string
  price: number
  signal: number
  position_weight: number
  gross_return: number
  cost: number
  net_return: number
  equity: number
  drawdown: number
  fill_rate: number
  payload: Record<string, unknown>
}

export interface FactorFactoryRunResponse {
  ok: boolean
  idempotent_replay?: boolean
  run: FactorFactoryRunRecord
  candidates: FactorFactoryCandidateRecord[]
  observations: FactorFactoryObservationRecord[]
  simulation_orders: SimulationOrder[]
  observation_summary: {
    count: number
    latest_equity: number | null
    after_cost_return: number | null
    max_drawdown: number
  }
  market_data_status?: {
    event_time: string
    bar_open_time: string | null
    bar_close_time: string | null
    fetched_at: string
    received_at: string
    is_closed: boolean
    age_ms: number
    source: string
    quality_status: string
    event_kind: string
    forming_bars_excluded: number
    research_signal_allowed: boolean
    market_open: boolean
    adjustment?: string | null
  } | null
  cohort?: {
    definition: Record<string, unknown>
    status: string
    engine_version: string
    start_market_time: string
    latest_report: {
      ranking: Array<{ member_key: string; metrics: Record<string, number | boolean | string | string[]> }>
      ledgers: Record<string, Record<string, unknown>>
      comparison: Record<string, number | boolean | string | Record<string, unknown>>
      fairness: Record<string, boolean | number>
      benchmark_pool: Record<string, unknown>
      execution_policy?: Record<string, unknown>
      replay_verification?: Record<string, unknown>
      regime_analysis?: Record<string, Record<string, Record<string, number>>>
      grid_risk?: Record<string, {
        mode: string
        levels: number
        range: { lower: number; center: number; upper: number }
        inventory_quantity: number
        inventory_notional: number
        inventory_risk: number
        capital_utilization: number
        trade_count: number
        fee_share_of_initial_capital: number
        outside_range: boolean
        outside_range_loss: number
        idle_cash_ratio: number
        preregistered: boolean
        exit_rule: string
      }>
    }
    program_gate: {
      passed: boolean
      checks: Record<string, boolean>
      violations: string[]
      allowed_transition: string | null
      manual_approval_required: boolean
      live_trading_enabled: false
    }
    ai_review?: Record<string, unknown> | null
    live_request?: Record<string, unknown> | null
    manual_approval?: Record<string, unknown> | null
    manual_approval_validity?: {
      valid: boolean
      reasons: string[]
      current_binding_hash: string
      approved_binding_hash: string | null
      live_trading_enabled: false
    } | null
    live_trading_enabled: false
  } | null
  live_trading_enabled: false
}

export interface FactorFactoryArchiveRunEvidence {
  run_id: string
  research_plan_id: string
  status: FactorFactoryRunStatus
  started_at: number
  updated_at: number
  observation_started_at: number | null
  observation_ends_at: number | null
  scope: {
    source: string | null
    symbol: string | null
    interval: string | null
    paper_target: string | null
  }
  candidate: FactorFactoryCandidateRecord
  data_provenance: Record<string, unknown>
  data_split: Record<string, unknown>
  confirmation_gate: Record<string, unknown>
  research_metrics: Record<string, unknown>
  simulation_validation: Record<string, unknown>
  paper_evidence: Record<string, unknown>
  observation_summary: {
    count: number
    first_id: string | null
    latest_id: string | null
    observed_from: string | null
    observed_to: string | null
    latest_equity: number | null
    after_cost_return: number | null
    maximum_drawdown: number
    minimum_fill_rate: number | null
  }
  simulation_orders: Array<{
    id: string
    status: string
    side: string
    quantity: number
    filled_quantity: number
    created_at: number
    updated_at: number
    execution_ids: string[]
  }>
}

export interface FactorFactoryArchiveRecord {
  archive_id: string
  definition: FactorDefinitionRecord
  verified: boolean
  eligible_for_archive: boolean
  archive_gate: {
    eligible: boolean
    required_observation_days: number
    observed_seconds: number
    observed_days: number
    qualifying_run_id: string | null
    checks: Record<string, boolean>
    violations: string[]
  }
  lifecycle: {
    current_state: FactorLifecycleState
    current_event: FactorLifecycleEvent | null
    events: FactorLifecycleEvent[]
  }
  scope: {
    market: FactorDefinitionRecord['market']
    symbol: string | null
    interval: string | null
    horizon: number
    data_source: string | null
  }
  preregistration: {
    definition_hypothesis: string
    invalidation_condition: string | null
    experiments: Array<{
      experiment_id: string
      research_plan_id: string
      attempt_number: number
      hypothesis: string
      source: FactorExperimentRecord['source']
      data_window: { start: string | null; end: string | null }
      parameter_grid: Record<string, unknown>
      parameter_combinations: number
      estimated_compute_units: number
      proposal: FactorExperimentRecord['proposal']
      pre_registration: FactorPreRegistration
      provenance: Record<string, unknown>
      created_at: number
    }>
  }
  post_study_evidence: {
    decision: {
      state: FactorLifecycleState
      rule: string
      evidence: Record<string, unknown>
      created_at: number
    }
    experiments: Array<{
      experiment_id: string
      research_plan_id: string
      attempt_number: number
      status: FactorExperimentRecord['status']
      events: FactorExperimentEvent[]
      result_provenance: Record<string, unknown>
    }>
    runs: FactorFactoryArchiveRunEvidence[]
    latest_run: FactorFactoryArchiveRunEvidence | null
  }
  remaining_risks: string[]
  evidence_chain: {
    definition_id: string
    definition_hash: string
    formula_hash: string
    lifecycle_event_ids: string[]
    experiment_ids: string[]
    experiment_event_ids: string[]
    run_ids: string[]
    data_snapshot_hashes: string[]
    simulation_order_ids: string[]
  }
  live_trading_enabled: false
}

export interface FactorFactoryArchiveResponse {
  ok: boolean
  count: number
  total: number
  research_record_count: number
  ineligible_count: number
  verified_count: number
  eligible_only: boolean
  archives: FactorFactoryArchiveRecord[]
  live_trading_enabled: false
}

export interface FactorFactoryStartPayload {
  experiment_nonce?: string
  market?: 'crypto' | 'a_shares'
  source: 'okx_local' | 'okx_live' | 'akshare_live' | 'synthetic'
  symbol: string
  dataset?: string
  seed?: number
  interval: '1h' | '4h' | '1d'
  n_bars: number
  candidate_budget: number
  candidate_mode?: 'brain' | 'library' | 'manual'
  alpha_brief?: string
  use_ai?: boolean
  ai_provider?: LLMProviderId
  ai_candidate_count?: number
  maximum_ai_tokens?: number
  manual_candidates?: Array<{
    candidate_id?: string
    label?: string
    family?: string
    expression?: string
    formula_ast?: Record<string, unknown>
    hypothesis?: string
    invalidation?: string
    falsification_tests?: string[]
  }>
  horizon: number
  commission_bps?: number
  cost_profile_id?: string
  cost_profile_version?: string
  initial_capital: number
  observation_days: number
  paper_target?: 'simulation_orders' | 'okx_demo'
  maximum_demo_exposure?: number
  maximum_demo_loss?: number
  thresholds?: Record<string, number>
}

export interface AlphaDslCatalog {
  version: string
  fields: Array<{ name: string; label: string; unit: string }>
  operators: Array<{ name: string; signature: string; description: string; example: string }>
  parameters: Array<{ name: string; description: string }>
  limits: {
    periods_min: number
    periods_max: number
    window_min: number
    window_max: number
    max_depth: number
    max_operators: number
    winsor_lower_min: number
    winsor_upper_max: number
  }
}

export interface FactorPreRegistration {
  primary_metric: string
  secondary_metrics: string[]
  pass_criteria: Record<string, unknown>
  maximum_candidates: number
  maximum_llm_tokens: number
  confirmation_set_openings: number
}

export interface FactorResearchDataPartition {
  start: string
  end: string
  data_fingerprint: string
}

export interface FactorResearchDataSplit {
  discovery: FactorResearchDataPartition
  rolling_validation: FactorResearchDataPartition
  locked_confirmation: FactorResearchDataPartition
  purge_periods: number
  embargo_periods: number
}

export interface FactorConfirmationSetOpening {
  id: string
  research_plan_id: string
  experiment_id: string
  confirmation_data_fingerprint: string
  opened_by: string
  irreversible_ack: true
  created_at: number
}

export interface FactorResearchPlanRecord {
  id: string
  title: string
  target_market: 'a_shares' | 'us_stocks' | 'crypto' | 'mt5'
  budget: {
    maximum_candidates: number
    maximum_compute_units: number
    maximum_llm_tokens: number
    maximum_confirmation_set_openings: number
    maximum_round_candidates: number
    maximum_formula_complexity: number
    maximum_duplicate_rate: number
    stop_conditions: Record<string, unknown>
    data_split: FactorResearchDataSplit | null
  }
  usage?: {
    candidates: number
    compute_units: number
    llm_tokens: number
    confirmation_set_openings: number
    confirmation_set_openings_reserved: number
    experiments: number
  }
  created_at: number
}

export type FactorFailureCode =
  | 'duplicate_formula'
  | 'future_information'
  | 'insufficient_coverage'
  | 'cost_too_high'
  | 'unstable_regime'
  | 'target_market_mismatch'
  | 'invalid_syntax'
  | 'complexity_budget'
  | 'execution_constraint'
  | 'other'

export interface FactorExperimentEvent {
  id: string
  experiment_id: string
  event_sequence: number
  status: 'draft' | 'queued' | 'running' | 'succeeded' | 'failed' | 'rejected' | 'cancelled'
  result: Record<string, unknown>
  failure_reason: string | null
  failure_code: FactorFailureCode | null
  evidence: Record<string, unknown>
  created_at: number
}

export interface FactorAiProposalContext {
  research_plan: Pick<FactorResearchPlanRecord, 'id' | 'title' | 'target_market'>
  data_catalog: Array<{ field: string; unit: string }>
  existing_factor_definitions: Array<{
    key: string
    version: string
    family: string
    market: FactorDefinitionRecord['market']
    input_fields: string[]
    formula_hash: string
    rationale: string
  }>
  redundancy_clusters: {
    formula_hash: Array<{ formula_hash: string; definitions: string[] }>
    family: Array<{ family: string; definitions: string[] }>
  }
  failure_feedback: Record<string, {
    count: number
    reasons: string[]
    factor_keys: string[]
  }>
  plan_usage: NonNullable<FactorResearchPlanRecord['usage']>
  ai_search_usage: FactorAiSearchUsage
  remaining_budget: {
    candidates: number
    compute_units: number
    llm_tokens: number
    confirmation_set_openings: number
    maximum_round_candidates: number
    maximum_formula_complexity: number
    maximum_duplicate_rate: number
  }
  stop_conditions: Record<string, unknown>
  confirmation_labels_exposed: false
}

export interface FactorAiSearchUsage {
  rounds: number
  candidates: number
  duplicates: number
  llm_tokens: number
  stopped_rounds: number
}

export interface FactorAiSearchRoundRecord {
  id: string
  research_plan_id: string
  round_id: string
  candidate_count: number
  duplicate_count: number
  duplicate_rate: number
  max_formula_complexity: number
  llm_tokens: number
  input_fingerprint: string
  status: 'allowed' | 'stopped'
  allowed: boolean
  stopped: boolean
  stop_reason: string | null
  created_at: number
}

export interface FactorExperimentRecord {
  id: string
  research_plan_id: string
  hypothesis: string
  source: 'human' | 'ai' | 'template' | 'random_dsl' | 'symbolic_regression' | 'parameter_search'
  parent_experiment_id: string | null
  factor_definition_id: string
  candidate_validation_id: string
  factor_key: string
  factor_version: string
  factor_family: string
  target_market: 'a_shares' | 'us_stocks' | 'crypto' | 'mt5'
  data_start: string | null
  data_end: string | null
  parameter_grid: Record<string, unknown>
  parameter_combinations: number
  estimated_compute_units: number
  model: Record<string, unknown>
  prompt: Record<string, unknown>
  proposal: {
    applicable_regimes: string[]
    invalidation_conditions: string[]
    falsification_tests: string[]
    ai_trace: Record<string, unknown>
  }
  pre_registration: FactorPreRegistration
  attempt_number: number
  status: FactorExperimentEvent['status']
  created_at: number
  provenance: {
    schema_version: 'factor-experiment-provenance-v1'
    formula: { version: string; formula_hash: string; definition_hash: string }
    data: { version: string; snapshot_hash: string }
    experiment: { version: string; hash: string }
    model: { version: string; hash: string }
    prompt: { version: string; hash: string }
    cost: { version: string; hash: string }
    result: { version: string; hash: string; status: FactorExperimentEvent['status'] }
  }
  events?: FactorExperimentEvent[]
}

export interface FactorUniverse {
  id: string
  name: string
  market: 'a_shares' | 'us_stocks' | 'crypto' | 'mt5'
  description: string
  current_version_id: string | null
  created_at: number
  updated_at: number
}

export interface FactorUniverseVersion {
  id: string
  universe_id: string
  version: number
  parent_version_id: string | null
  source: string
  snapshot_hash: string
  members: FactorUniverseMember[]
  created_at: number
}

export interface FactorUniverseBatchDiff {
  additions: Array<Record<string, unknown>>
  updates: Array<{ before: Record<string, unknown>; after: Record<string, unknown> }>
  conflicts: Array<Record<string, unknown>>
  ignored: Array<Record<string, unknown>>
  counts: { additions: number; updates: number; conflicts: number; ignored: number; invalid: number }
}

export interface FactorUniverseMember {
  id: string
  universe_id: string
  instrument_id: string
  symbol: string
  effective_from: string
  effective_to: string | null
  status: 'active' | 'suspended' | 'delisted'
  industry: string
  market_cap: number | null
  beta: number | null
  is_st: boolean
  listed_at: string | null
  delisted_at: string | null
  created_at: number
  updated_at: number
}

export interface FactorResearchJob {
  id: string
  name: string
  universe_id: string
  cron: string
  enabled: boolean
  request: {
    universe_id: string
    factor_key: string
    interval: '1d'
    limit: number
    horizon: number
    transaction_cost_bps: number
    participation_rate: number
    portfolio_mode?: 'cohort' | 'non_overlapping'
  }
  created_at: number
  updated_at: number
  updated_by: string
}

export interface CrossSectionResearchResp {
  ok: boolean
  error?: string
  run_id: string
  engine_version?: string
  universe?: FactorUniverse
  loaded_symbols?: number
  failed_symbols?: number
  failures: Array<{ symbol: string; attempts: number; error: string }>
  factor?: {
    key: string
    label: string
    category: string
    description: string
    formula: string
    formula_version: string
    status: FactorStatus
  }
  summary?: {
    dates: number
    rank_ic_mean: number
    raw_return_rank_ic_mean?: number
    primary_label?: 'market_industry_neutral_residual_return'
    auxiliary_label?: 'raw_forward_return'
    rank_ic_median: number
    rank_ic_std: number
    icir: number
    rank_ic_p_value?: number
    rank_ic_p_value_method?: 'newey_west_hac_mean_test'
    rank_ic_hac_lags?: number
    effective_dates?: number
    positive_rank_ic_ratio: number
    portfolio_mode?: 'cohort' | 'non_overlapping'
    portfolio_return_horizon?: number
    portfolio_observations?: number
    gross_long_short_total_return?: number
    net_long_short_total_return?: number
    long_short_total_return: number
    long_only_total_return?: number
    benchmark_total_return?: number
    long_only_excess_total_return?: number
    primary_portfolio_key?: 'long_only_excess' | 'theoretical_long_short'
    primary_total_return?: number
    portfolio_variants?: Record<string, {
      available: boolean
      executable: boolean
      total_return: number | null
      benchmark?: string
      reason?: string
    }>
    coverage: number
    missing_rate: number
    average_turnover: number
    average_long_turnover?: number
    median_capacity: number
    median_crowding_hhi: number
    neutralization_failures: number
    minimum_valid_assets: number
    median_valid_assets: number
    data_fingerprint: string
  }
  quantile_returns?: Array<{ quantile: number; mean_forward_return: number }>
  stability?: {
    labels: CrossSectionStabilityRow[]
    time: CrossSectionStabilityRow[]
    cross_section: Record<'industry' | 'market_cap' | 'liquidity' | 'listing_age', CrossSectionStabilityRow[]>
    regime_definition: Record<string, string>
  }
  series?: Array<{
    date: string
    eligible_assets: number
    valid_assets: number
    coverage: number
    rank_ic: number
    raw_return_rank_ic?: number | null
    label_rank_ics?: Record<string, number>
    long_short_return: number
    net_long_short_return: number | null
    portfolio_gross_return?: number | null
    portfolio_net_return?: number | null
    portfolio_active_cohorts?: number
    long_only_net_return?: number | null
    benchmark_return?: number | null
    long_only_excess_return?: number | null
    turnover: number
    long_turnover?: number
    capacity: number
    crowding_hhi: number | null
    long_symbols: string[]
    short_symbols: string[]
    portfolio_long_symbols?: string[]
    portfolio_short_symbols?: string[]
    portfolio_benchmark_symbols?: string[]
  }>
  methodology?: Record<string, unknown>
}

export interface CrossSectionStabilityRow {
  segment: string
  observations: number
  rank_ic_mean: number
  positive_ratio: number
  direction_consistent: boolean
}

export interface CrossMarketFactorStatus {
  ok: boolean
  factor_key: string
  target_market: string | null
  trading_validation_status: 'passed' | 'insufficient_evidence' | 'target_market_required'
  trading_validation_passed: boolean
  required_markets: string[]
  transfer_markets: string[]
  rule: string
  rows: Array<{
    market: string
    state: 'passed' | 'failed' | 'missing'
    run_id: string | null
    run_status: string | null
    factor_status: FactorStatus | null
    dates: number | null
    effective_dates: number | null
    minimum_valid_assets: number | null
    validation_thresholds: {
      minimum_effective_dates: number
      minimum_valid_assets: number
    }
    rank_ic_mean: number | null
    coverage: number | null
    updated_at: number | null
  }>
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
  latest_research_run_id?: string | null
  research_direction?: string | null
  research_execution_eligible?: boolean
  research_updated_at?: number | null
  evidence_age_hours?: number | null
  next_event?: Record<string, unknown> | null
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
  source: string
  observed_at: string
  freshness: 'live' | 'daily_close' | 'unavailable'
  status: 'available' | 'unavailable'
  error: string | null
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
  timeout?: number
  max_retries?: number
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

export interface OkxSwapInstrument extends Instrument {
  base: string
  quote: string
  settle: string
  contract_size: number | null
  price_precision: number | null
  amount_precision: number | null
  minimum_amount: number | null
  linear: boolean
  verified: boolean
  research_ready?: boolean
  trading_ready?: boolean
  available_intervals?: string[]
  last_market_time?: string | null
}

export interface OkxSwapCatalogResponse {
  ok: boolean
  source: 'okx_public' | 'okx_public_cache' | 'okx_local_cache' | 'unavailable'
  degraded?: boolean
  warning?: string | null
  query: string
  count: number
  total: number
  cache_age_seconds: number | null
  cache_ttl_seconds: number
  fetched_at: number | null
  error: string | null
  trading_ready_count?: number
  instruments: OkxSwapInstrument[]
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

export interface LedgerPerformanceAttributionGroup {
  key: string
  trade_count: number
  wins: number
  win_rate_pct: number
  gross_pnl: number
  fees: number
  net_pnl: number
  fee_drag_pct: number
  average_holding_seconds: number
  max_drawdown: number
  links: Array<{
    research_run_id?: string | null
    signal_id?: string | null
    simulation_order_id?: string | null
    execution_id?: string | null
  }>
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
  by_factor: LedgerPerformanceAttributionGroup[]
  by_factor_version: LedgerPerformanceAttributionGroup[]
  by_research_run: LedgerPerformanceAttributionGroup[]
  by_strategy_performance: LedgerPerformanceAttributionGroup[]
  by_signal: LedgerPerformanceAttributionGroup[]
  by_market_regime: LedgerPerformanceAttributionGroup[]
  unknown_attribution: LedgerPerformanceAttributionGroup[]
  conservation: {
    closed_trade_net_pnl: number
    factor_group_net_pnl: number
    balanced: boolean
    matching: { open_lot_count: number; open_quantity: number }
  }
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
  research_run_id?: string | null
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
  trigger_type: 'manual' | 'scheduled' | 'retry'
  attempt: number
  parent_run_id: string | null
  log: string
  error: string | null
  created_at: number
  started_at: number | null
  finished_at: number | null
  duration_ms: number | null
  result_type: string | null
  result_id: string | null
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
  | 'earnings_released'
  | 'valuation_band_crossed'
  | 'major_company_event'
  | 'macro_calendar'
  | 'risk_invalidated'
  | 'factor_status_changed'
  | 'factor_ic_decay'
  | 'factor_drawdown_breach'
  | 'factor_data_stale'

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
  related_modules?: string[]
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

export type IncidentSource = 'analysis_task' | 'automation_run' | 'ledger_sync' | 'data_source' | 'research_run' | 'research_persistence'

export interface IncidentAction {
  type:
    | 'retry_analysis_task'
    | 'retry_automation_run'
    | 'acknowledge_automation_run'
    | 'retry_ledger_sync'
    | 'open_data_source_status'
    | 'check_data_source'
    | 'acknowledge_data_source_recovery'
    | 'open_research_result'
  label: string
  task_id?: string
  run_id?: string
  order_id?: string
  execution_id?: string
  incident_id?: string
  research_run_id?: string
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

export interface FactorStatusMatrixRow {
  dimension: 'window' | 'cross_symbol' | 'market'
  key: string
  label: string
  state: 'passed' | 'failed' | 'missing'
  rule: string
  evidence: Record<string, unknown>
  run_id: string | null
  updated_at: number | null
}

export interface FactorStatusMatrix {
  ok: boolean
  factor_key: string
  dimensions: string[]
  rows: FactorStatusMatrixRow[]
  counts: Record<'passed' | 'failed' | 'missing', number>
}

export interface FactorResearchAttentionItem {
  run_id: string
  symbol: string
  market: string
  timeframe: string
  states: Array<'needs_revalidation' | 'invalidated' | 'data_stale'>
  updated_at: number
  age_hours: number
  evidence: {
    watch_factors: string[]
    inconsistent_factors: string[]
    rejected_factors: string[]
  }
}

export interface FactorResearchAttention {
  ok: boolean
  stale_hours: number
  rules: Record<string, string>
  counts: Record<'needs_revalidation' | 'invalidated' | 'data_stale', number>
  items: FactorResearchAttentionItem[]
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

export type NewsResearchEventType =
  | 'earnings_guidance'
  | 'earnings_revision'
  | 'share_repurchase'
  | 'shareholder_change'
  | 'dividend'
  | 'regulatory_penalty'
  | 'major_contract'
  | 'trading_status'

export interface NewsEventExtraction {
  event_type: NewsResearchEventType | 'unclassified'
  direction: 'positive' | 'negative' | 'neutral' | 'uncertain'
  strength: number
  confidence: number
  evidence_excerpt: string
  taxonomy_version: 'news-event-taxonomy-1.0.0'
  extraction_method: 'llm_fixed_taxonomy' | 'deterministic_rules'
  price_prediction_allowed: false
}

export interface NewsResearchEvent {
  event_id: string
  entity_id: string
  entity_name: string
  symbol: string
  market: 'a_shares' | 'us_stocks' | 'crypto' | 'mt5'
  event_type: NewsResearchEventType
  direction: 'positive' | 'negative' | 'neutral' | 'uncertain'
  strength: number
  confidence: number
  evidence_excerpt: string
  event_time: string
  published_time: string
  collected_time: string
  revised_time?: string | null
  available_time: string
  source: string
  source_document_id: string
  source_url?: string | null
  content_fingerprint: string
  entity_matches_target: boolean
  publication_time_verified: boolean
  restricted_data?: boolean
  extractor?: Record<string, unknown>
  taxonomy_version?: string
}

export interface NewsEventOutcome {
  event_id: string
  forward_returns: Record<'1' | '3' | '5' | '10' | '20', number>
  market_returns: Record<'1' | '3' | '5' | '10' | '20', number>
  industry_returns: Record<'1' | '3' | '5' | '10' | '20', number>
  price_state: 'trend_up' | 'trend_down' | 'oversold' | 'range'
  volume_state: 'expanding' | 'normal' | 'contracting'
  liquidity_state: 'high' | 'medium' | 'low'
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
  research_event?: NewsEventExtraction
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

// ---- M1/M2 交易域（/api/trading/*）----
// 统一数据来源契约外壳，对应 apps/api/contracts.py 的 envelope()。
export type ContractStatus = 'ok' | 'stale' | 'empty' | 'error'

export interface ContractSource {
  name: string
  kind: string
  environment: string | null
}

export interface ContractFreshness {
  age_seconds: number
  ttl_seconds: number | null
  expired: boolean
}

export interface ContractEnvelope<T> {
  status: ContractStatus
  source: ContractSource
  observed_at: string | null
  freshness: ContractFreshness
  error_code: string | null
  message?: string | null
  detail?: string | null
  hint?: string | null
  retryable?: boolean
  data: T | null
}

export type TradingEnvironment = 'shadow' | 'demo' | 'live'
export type RiskMode = 'normal' | 'cancel_only' | 'halted'

export interface TradingHealth {
  configured: boolean
  reachable: boolean
  environment: TradingEnvironment | null
  trading_enabled: boolean
  live_approved: boolean
  runner: Record<string, unknown> | null
}

export interface OkxDemoCredentialStatus {
  ok: boolean
  available?: boolean
  configured: boolean
  environment: 'demo'
  source: 'local_vault'
  protection_scope?: 'windows_current_user'
  runtime_identity?: string | null
  fingerprint: string | null
  updated_at: string | null
  validated_at: string | null
  error_code?: string | null
  error?: string | null
  recovery_action?: string | null
}

export interface OkxDemoConnectionTest extends OkxDemoCredentialStatus {
  latency_ms?: number
  currency_count?: number
  nonzero_currency_count?: number
  permission?: 'read_only_test'
  error_code?: string | null
  error?: string | null
  diagnostic_stage?: string | null
  diagnostic_type?: string | null
  exchange_code?: string | null
}

export interface TradingOrderIntent {
  strategy_id: string
  strategy_version: string
  intent_id: string
  account_id: string
  symbol: string
  side: 'buy' | 'sell'
  order_type: 'limit' | 'market'
  quantity: number
  price?: number | null
  leverage?: number
  reduce_only?: boolean
  stop_loss?: TradingProtectionOrder | null
  take_profit?: TradingProtectionOrder | null
}

export interface TradingProtectionOrder {
  trigger_price: number
  order_price?: number | null
}

export interface TradingOrderAmendment {
  quantity: number
  price?: number | null
  stop_loss?: TradingProtectionOrder | null
  take_profit?: TradingProtectionOrder | null
}

export interface TradingClosePositionIntent {
  strategy_id: string
  strategy_version: string
  intent_id: string
  quantity?: number | null
  order_type?: 'limit' | 'market'
  price?: number | null
}

export interface TradingInstrumentRule {
  symbol: string
  exchange_symbol: string
  product_type: string
  active: boolean
  settle_currency: string
  minimum_quantity: number
  quantity_step: number
  price_tick: number
  contract_size: number | null
  minimum_notional: number | null
  minimum_notional_estimated: boolean
  maximum_leverage: number
  reference_price: number | null
}

export interface TradingPreflight {
  environment: TradingEnvironment
  observed_at: string
  account: {
    account_level: string | null
    position_mode: string | null
    permissions: string[]
  }
  ip_whitelist: {
    field_exposed: boolean
    status: string
  }
  clock: {
    server_time_available: boolean
    absolute_drift_ms: number | null
    within_tolerance: boolean
    tolerance_ms: number
  }
  instruments: TradingInstrumentRule[]
}

export interface TradingStrategyRecord {
  strategy_id: string
  version: string
  content_hash: string
  imported_at: string
  package: {
    product_type?: string
    signal_frequency?: string
    rebalance_frequency?: string
    approved_by?: string
    risk_limits?: {
      max_leverage?: number
      max_symbol_exposure?: number
      max_total_exposure?: number
    }
  }
}

export interface TradingOrderRecord {
  order_id: string
  client_order_id: string
  strategy_id: string
  strategy_version: string
  account_id: string
  environment: TradingEnvironment
  symbol: string
  side: 'buy' | 'sell'
  order_type: 'limit' | 'market'
  quantity: number
  price: number | null
  leverage: number
  reduce_only?: boolean
  external_order_id: string | null
  status: string
  filled_quantity: number
  average_price: number | null
  created_at: string
  updated_at: string
  idempotent_replay?: boolean
}

export interface TradingRiskState {
  scope: string
  mode: RiskMode
  reason: string
  updated_at: string
}

export interface TradingBalanceRecord {
  id?: number
  account_id: string
  environment: TradingEnvironment
  currency: string
  total: number
  available: number
  observed_at: string
}

export interface TradingPositionRecord {
  id?: number
  account_id: string
  environment: TradingEnvironment
  symbol: string
  quantity: number
  mark_price: number
  entry_price?: number | null
  unrealized_pnl?: number
  leverage?: number | null
  position_side?: string | null
  observed_at: string
}

export interface TradingAccountSummary {
  account_id: string
  environment: TradingEnvironment
  equity_currency?: string
  equity: number
  initial_equity: number
  equity_change: number
  realized_pnl: number
  unrealized_pnl: number
  total_pnl: number
  peak_equity: number
  max_drawdown: number
  observed_at: string
}

export interface TradingReconciliationDiffRecord {
  diff_id: string
  account_id: string
  kind: string
  key: string
  status: 'open' | 'resolved'
  owner: string | null
  resolution: string | null
  created_at: string
  resolved_at: string | null
}

export interface TradingDashboard {
  strategies: TradingStrategyRecord[]
  orders: TradingOrderRecord[]
  fills: Array<Record<string, unknown>>
  balances: TradingBalanceRecord[]
  positions: TradingPositionRecord[]
  account_summary: { accounts: TradingAccountSummary[] }
  reconciliation_diffs: TradingReconciliationDiffRecord[]
  risk_states: TradingRiskState[]
  account_status: {
    environment: TradingEnvironment
    connected: boolean
    permissions: string
    latest_snapshot_at: string | null
    stale: boolean
    last_reconciliation_at: string | null
    server_time: string
  }
}

export interface TradingOrderDetail extends TradingOrderRecord {
  events: Array<{
    sequence: number
    from_status: string | null
    to_status: string
    created_at: string
  }>
  fills: Array<Record<string, unknown>>
  risk_decisions: Array<{
    outcome: string
    reason: string | null
    created_at: string
  }>
}
