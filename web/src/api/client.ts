// QuantHub 前端 API 客户端。
// 统一收口对后端网关（apps/api）的调用，所有组件经此层取数，便于统一错误处理、降级与换 Base URL。
//
// Base URL 优先级（运行时动态读取，ConfigPage 改完即生效，无需重建）:
//   1. localStorage['quanthub:api-base']  — ConfigPage「高级覆盖」写入
//   2. import.meta.env.VITE_API_BASE      — 构建期注入
//   3. '/api'                              — 相对路径，走 vite dev proxy / 生产同源反代
//
// 开发态：vite.config.ts 已配 server.proxy['/api'] → http://localhost:8001
// 生产态：前后端同源反代到 /api/* 即可，无需 CORS 放开。

import type {
  ApiKeyResp,
  AnalysisTask,
  ContractEnvelope,
  RiskMode,
  TradingHealth,
  TradingDashboard,
  TradingClosePositionIntent,
  TradingOrderAmendment,
  TradingOrderDetail,
  TradingOrderIntent,
  TradingPreflight,
  OkxDemoCredentialStatus,
  OkxDemoConnectionTest,
  OkxSwapCatalogResponse,
  AnalysisTaskKind,
  AnalysisTaskStatus,
  AlertEvent,
  AlertRule,
  AlertRuleType,
  AlphaDslCatalog,
  AutomationAuditLog,
  AutomationJob,
  AutomationRun,
  AutomationRunStatus,
  AutomationStatus,
  BacktestResp,
  BackupRecord,
  BackupRetentionResult,
  BackupStatus,
  BackupVerification,
  ConfigSystemStatus,
  DataSourceStatusResp,
  DataSourceCheckResult,
  DataSourceOperation,
  DemoRunRecord,
  DemoRunSummary,
  CreatedApiToken,
  EnsembleResp,
  FactorResearchResp,
  FactorAiProposalContext,
  FactorAiSearchRoundRecord,
  FactorAiSearchUsage,
  FactorConfirmationSetOpening,
  FactorDefinitionRecord,
  FactorFactoryArchiveResponse,
  FactorFactoryRunResponse,
  FactorFactoryStartPayload,
  FactorLifecycleRecord,
  FactorExperimentRecord,
  FactorFailureCode,
  FactorPreRegistration,
  FactorResearchPlanRecord,
  FactorResearchDataSplit,
  FactorRealityCheck,
  FactorAiReviewResp,
  FactorResearchRunDetailResp,
  FactorResearchRunsResp,
  FactorUniverse,
  FactorUniverseMember,
  FactorResearchJob,
  FactorResearchAttention,
  FactorStatusMatrix,
  CrossSectionResearchResp,
  CrossMarketFactorStatus,
  HealthResp,
  HoldingCRUDResp,
  Instrument,
  ApiTokenRecord,
  GovernanceAuditLog,
  GovernanceRole,
  GovernanceUser,
  GlobalSearchItem,
  IncidentRecord,
  KlineResp,
  LiveResp,
  LedgerBenchmark,
  LedgerAttribution,
  LedgerCashEntry,
  LedgerCorrection,
  LedgerExposures,
  LedgerPerformance,
  LedgerPosition,
  LedgerSummary,
  LedgerTrade,
  LedgerTradeAnalytics,
  LLMConfigResp,
  LLMConnectionTestResp,
  LLMSettingsUpdate,
  PositionDecisionContext,
  MarketBreadthResp,
  NewsAnalyzeResp,
  NewsEventOutcome,
  NewsHealthResp,
  NewsResearchEvent,
  NotificationChannelName,
  NotificationStatus,
  PaAnalyzeResp,
  PortfolioManageResp,
  PortfolioResp,
  Preset,
  PublishSignalReq,
  QuoteResp,
  ResearchEvidence,
  ResearchComparison,
  ResearchRun,
  ResearchRunsResp,
  ResearchVerification,
  ResearchStatus,
  UserResearchPreference,
  RunRecord,
  RunResp,
  SignalLifecycleStatus,
  SignalResp,
  RadarSignalsResp,
  SignalsResp,
  SimulationAccount,
  SimulationOrder,
  SimulationOrdersResp,
  SimulationOrderPreview,
  SimulationOrderStatus,
  StrategiesResp,
  StrategyDefinition,
  StrategyExperiment,
  StrategyLabComparisonRow,
  StrategyLabRunDifference,
  StrategyLabRun,
  StrategyVersion,
  WatchlistCRUDResp,
  WatchlistResp,
  WorkspaceConfigResp,
  WorkspaceProfile,
  ResearchReport,
  ResearchReportEvent,
} from './types'

const LS_KEY = 'quanthub:api-base'
const TOKEN_LS_KEY = 'quanthub:api-token'
const DEFAULT_BASE = '/api'

/** 运行时解析 Base URL，允许 ConfigPage 热切换。 */
export function getBase(): string {
  try {
    const ls = typeof localStorage !== 'undefined' ? localStorage.getItem(LS_KEY) : null
    if (ls && ls.trim()) return ls.trim().replace(/\/+$/, '')
  } catch {
    /* localStorage 不可用时回退 */
  }
  const env = (import.meta.env.VITE_API_BASE as string | undefined) || ''
  return env ? env.replace(/\/+$/, '') : DEFAULT_BASE
}

export function getApiToken(): string {
  try {
    return typeof localStorage === 'undefined'
      ? ''
      : localStorage.getItem(TOKEN_LS_KEY)?.trim() ?? ''
  } catch {
    return ''
  }
}

export function setApiToken(token: string): void {
  if (typeof localStorage === 'undefined') return
  const normalized = token.trim()
  if (normalized) localStorage.setItem(TOKEN_LS_KEY, normalized)
  else localStorage.removeItem(TOKEN_LS_KEY)
}

/** 错误类型：区分网络层（可重试）与 HTTP 业务层（4xx 不重试）。 */
export class NetworkError extends Error {
  constructor(msg: string) {
    super(msg)
    this.name = 'NetworkError'
  }
}
export class HttpError extends Error {
  status: number
  constructor(status: number, msg: string) {
    super(msg)
    this.name = 'HttpError'
    this.status = status
  }
}

async function getJSON<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    const headers = new Headers(init?.headers)
    const token = getApiToken()
    if (token && !headers.has('Authorization')) headers.set('Authorization', `Bearer ${token}`)
    res = await fetch(`${getBase()}${path}`, { ...init, headers })
  } catch (e) {
    if (e instanceof Error && e.name === 'AbortError') throw e
    // 网络层失败（后端未启动 / DNS / 断网）→ 抛 NetworkError，useApi 可重试
    throw new NetworkError(`无法连接网关 (${getBase()})：${e instanceof Error ? e.message : String(e)}`)
  }
  if (!res.ok) {
    let detail = ''
    try {
      const j = (await res.json()) as { detail?: string; error?: string }
      detail = j.detail || j.error || ''
    } catch {
      /* 忽略解析失败 */
    }
    const msg = `请求失败 ${res.status}${detail ? ' · ' + detail : ''}`
    // 4xx 为确定性业务错误（如策略不存在/参数非法），不重试；5xx 视为可重试
    throw new HttpError(res.status, msg)
  }
  return (await res.json()) as T
}

export const api = {
  /** 当前 Base URL（动态读取，ConfigPage 显示用）。 */
  get base() {
    return getBase()
  },

  health: () => getJSON<HealthResp>('/health'),
  configSystemStatus: () => getJSON<ConfigSystemStatus>('/config/status'),
  notificationStatus: () => getJSON<NotificationStatus>('/config/notifications'),
  updateNotificationsEnabled: (enabled: boolean) => getJSON<NotificationStatus>('/config/notifications', {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled }),
  }),
  updateNotificationChannel: (channel: NotificationChannelName, payload: {
    enabled: boolean
    webhook_url?: string
    mentioned_mobile?: string
    url?: string
    bot_token?: string
    chat_id?: string
  }) => getJSON<NotificationStatus>(`/config/notifications/${channel}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
  testNotificationChannel: (channel: NotificationChannelName) => getJSON<{ ok: boolean; channel: string; sent: boolean }>(`/config/notifications/${channel}/test`, { method: 'POST' }),
  globalSearch: (query: string, limitPerGroup = 6) => {
    const params = new URLSearchParams({ q: query, limit_per_group: String(limitPerGroup) })
    return getJSON<{ ok: boolean; query: string; count: number; items: GlobalSearchItem[] }>(`/search?${params.toString()}`)
  },
  alertRules: () => getJSON<{ ok: boolean; count: number; rules: AlertRule[] }>('/alerts/rules'),
  createAlertRule: (payload: {
    name: string
    rule_type: AlertRuleType
    symbol: string
    market: string
    threshold?: number | null
    enabled?: boolean
    frequency_minutes?: number
    quiet_start?: string | null
    quiet_end?: string | null
    expires_at?: number | null
    context?: Record<string, unknown>
  }) => getJSON<{ ok: boolean; rule: AlertRule }>('/alerts/rules', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
  updateAlertRule: (ruleId: string, patch: Partial<Pick<AlertRule, 'name' | 'enabled' | 'threshold' | 'frequency_minutes' | 'quiet_start' | 'quiet_end' | 'expires_at'>>) =>
    getJSON<{ ok: boolean; rule: AlertRule }>(`/alerts/rules/${encodeURIComponent(ruleId)}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(patch),
    }),
  deleteAlertRule: (ruleId: string) => getJSON<{ ok: boolean }>(`/alerts/rules/${encodeURIComponent(ruleId)}`, { method: 'DELETE' }),
  checkAlertRule: (ruleId: string) => getJSON<{ ok: boolean; checked: boolean; triggered: boolean; event: AlertEvent | null }>(`/alerts/rules/${encodeURIComponent(ruleId)}/check`, { method: 'POST' }),
  checkAllAlerts: () => getJSON<{ ok: boolean; count: number }>('/alerts/check', { method: 'POST' }),
  alertEvents: (pendingOnly = false, limit = 200) => getJSON<{ ok: boolean; count: number; events: AlertEvent[] }>(`/alerts/events?pending_only=${pendingOnly}&limit=${limit}`),
  acknowledgeAlertEvent: (eventId: string) => getJSON<{ ok: boolean; event: AlertEvent }>(`/alerts/events/${encodeURIComponent(eventId)}/acknowledge`, { method: 'POST' }),

  governanceSession: () => getJSON<{ ok: boolean; user: GovernanceUser }>('/auth/session'),
  governanceUsers: () =>
    getJSON<{ ok: boolean; count: number; users: GovernanceUser[] }>('/auth/users'),
  governanceRoles: () =>
    getJSON<{ ok: boolean; count: number; roles: GovernanceRole[] }>('/auth/roles'),
  createGovernanceUser: (payload: { username: string; display_name: string; roles: string[] }) =>
    getJSON<{ ok: boolean; user: GovernanceUser }>('/auth/users', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    }),
  updateGovernanceUserRoles: (userId: string, roles: string[]) =>
    getJSON<{ ok: boolean; user: GovernanceUser }>(`/auth/users/${encodeURIComponent(userId)}/roles`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ roles }),
    }),
  updateGovernanceUserStatus: (userId: string, active: boolean) =>
    getJSON<{ ok: boolean; user: GovernanceUser }>(`/auth/users/${encodeURIComponent(userId)}/status`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ active }),
    }),
  governanceTokens: () =>
    getJSON<{ ok: boolean; count: number; tokens: ApiTokenRecord[] }>('/auth/tokens'),
  createGovernanceToken: (payload: { user_id: string; label: string; expires_at: number | null }) =>
    getJSON<{ ok: boolean; token: CreatedApiToken }>('/auth/tokens', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    }),
  revokeGovernanceToken: (tokenId: string) =>
    getJSON<{ ok: boolean; token: ApiTokenRecord }>(`/auth/tokens/${encodeURIComponent(tokenId)}`, {
      method: 'DELETE',
    }),
  governanceAudit: (limit = 200, cursor?: string) => {
    const params = new URLSearchParams({ limit: String(limit) })
    if (cursor) params.set('cursor', cursor)
    return getJSON<{ ok: boolean; count: number; total: number; next_cursor: string | null; audit: GovernanceAuditLog[] }>(`/auth/audit?${params.toString()}`)
  },

  dataSourceStatus: () => getJSON<DataSourceStatusResp>('/market-data/status'),
  checkDataSource: (payload: {
    market: string
    source: string
    operation: DataSourceOperation
    symbol: string
    interval: string
  }) => getJSON<DataSourceCheckResult>('/market-data/check', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }),

  createAnalysisTask: (payload: {
    kind: AnalysisTaskKind
    symbol: string
    market: string
    timeframe: string
    payload?: Record<string, unknown>
    timeout_seconds?: number
  }) => getJSON<{ ok: boolean; duplicate: boolean; task: AnalysisTask }>('/analysis/tasks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }),

  analysisTasks: (status?: AnalysisTaskStatus, kind?: AnalysisTaskKind, limit = 50, cursor?: string) => {
    const params = new URLSearchParams({ limit: String(limit) })
    if (status) params.set('status', status)
    if (kind) params.set('kind', kind)
    if (cursor) params.set('cursor', cursor)
    return getJSON<{ ok: boolean; count: number; total: number; next_cursor: string | null; tasks: AnalysisTask[] }>(
      `/analysis/tasks?${params.toString()}`,
    )
  },

  analysisTask: (id: string) =>
    getJSON<{ ok: boolean; task: AnalysisTask }>(`/analysis/tasks/${encodeURIComponent(id)}`),

  recentAnalysisTask: (
    kind: AnalysisTaskKind, symbol: string, market: string, timeframe: string, withinSeconds = 900,
  ) => {
    const params = new URLSearchParams({
      kind, symbol, market, timeframe, within_seconds: String(withinSeconds),
    })
    return getJSON<{ ok: boolean; task: AnalysisTask | null }>(`/analysis/tasks/recent?${params.toString()}`)
  },

  cancelAnalysisTask: (id: string) =>
    getJSON<{ ok: boolean; task: AnalysisTask }>(`/analysis/tasks/${encodeURIComponent(id)}/cancel`, {
      method: 'POST',
    }),

  retryAnalysisTask: (id: string) =>
    getJSON<{ ok: boolean; task: AnalysisTask }>(`/analysis/tasks/${encodeURIComponent(id)}/retry`, {
      method: 'POST',
    }),

  // ---- 可追溯研究运行（ResearchRun / Evidence）----
  researchPreference: () =>
    getJSON<{ ok: boolean; preference: UserResearchPreference }>('/research/preferences/me'),

  updateResearchPreference: (preference: Omit<UserResearchPreference, 'user_id' | 'updated_at'>) =>
    getJSON<{ ok: boolean; preference: UserResearchPreference }>('/research/preferences/me', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(preference),
    }),

  createResearchRun: (payload: {
    symbol: string
    market?: string
    timeframe?: string
    modules?: string[]
    input?: Record<string, unknown>
  }) =>
    getJSON<{ ok: boolean; run: ResearchRun }>('/research/runs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  researchRuns: (symbol?: string, status?: ResearchStatus, limit = 50, favorite?: boolean, cursor?: string) => {
    const params = new URLSearchParams({ limit: String(limit) })
    if (symbol) params.set('symbol', symbol)
    if (status) params.set('status', status)
    if (favorite !== undefined) params.set('favorite', String(favorite))
    if (cursor) params.set('cursor', cursor)
    return getJSON<ResearchRunsResp>(
      `/research/runs?${params.toString()}`,
    )
  },

  researchRun: (id: string) =>
    getJSON<{ ok: boolean; run: ResearchRun }>(`/research/runs/${encodeURIComponent(id)}`),

  researchExport: (id: string) =>
    getJSON<{ ok: boolean; export_version: string; exported_at: number; data_cutoff: string; method_versions: string[]; evidence_manifest: Array<Record<string, unknown>>; disclaimer: string; run: ResearchRun }>(
      `/research/runs/${encodeURIComponent(id)}/export`,
    ),

  researchVerify: (id: string) =>
    getJSON<ResearchVerification>(`/research/runs/${encodeURIComponent(id)}/verify`),

  compareResearchRuns: (runIds: string[]) =>
    getJSON<ResearchComparison>('/research/compare', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ run_ids: runIds }),
    }),

  updateResearchRun: (
    id: string,
    patch: {
      status?: ResearchStatus
      summary?: Record<string, unknown>
      error?: string | null
      note?: string
      favorite?: boolean
      tags?: string[]
      archived?: boolean
    },
  ) =>
    getJSON<{ ok: boolean; run: ResearchRun }>(`/research/runs/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    }),

  updateResearchRunsBatch: (
    runIds: string[],
    patch: { tags?: string[]; archived?: boolean },
  ) =>
    getJSON<{ ok: boolean; count: number; runs: ResearchRun[] }>('/research/runs/batch', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ run_ids: runIds, ...patch }),
    }),

  workspaceConfig: () => getJSON<WorkspaceConfigResp>('/workspace/config'),
  updateWorkspaceConfig: (payload: {
    profile: WorkspaceProfile
    hidden_workspaces?: string[]
    hidden_modules?: string[]
    pinned_routes?: string[]
    default_home?: string
    default_market?: string
    recent_routes?: string[]
    version?: number
  }) => getJSON<WorkspaceConfigResp>('/workspace/config', {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
  workspaceConfigAudit: (limit = 100) => getJSON<{ ok: boolean; count: number; audit: Array<Record<string, unknown>> }>(`/workspace/config/audit?limit=${limit}`),
  createResearchReport: (runId: string, mode: ResearchReport['mode'], taskId?: string) => getJSON<{ ok: boolean; report: ResearchReport }>(`/workspace/research-runs/${encodeURIComponent(runId)}/reports`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode, task_id: taskId }),
  }),
  researchReport: (reportId: string) => getJSON<{ ok: boolean; report: ResearchReport }>(`/workspace/reports/${encodeURIComponent(reportId)}`),
  researchReportEvents: (reportId: string, afterSequence = 0) => getJSON<{ ok: boolean; events: ResearchReportEvent[]; next_sequence: number }>(`/workspace/reports/${encodeURIComponent(reportId)}/events?after_sequence=${afterSequence}`),
  cancelResearchReport: (reportId: string) => getJSON<{ ok: boolean; report: ResearchReport }>(`/workspace/reports/${encodeURIComponent(reportId)}/cancel`, { method: 'POST' }),
  regenerateResearchReportSection: (reportId: string, sectionKey: string) => getJSON<{ ok: boolean; report: ResearchReport }>(`/workspace/reports/${encodeURIComponent(reportId)}/sections/regenerate`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ section_key: sectionKey }),
  }),

  addResearchEvidence: (
    id: string,
    evidence: {
      kind: string
      source: string
      title?: string
      uri?: string | null
      payload?: Record<string, unknown>
    },
  ) =>
    getJSON<{ ok: boolean; evidence: ResearchEvidence }>(
      `/research/runs/${encodeURIComponent(id)}/evidence`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(evidence),
      },
    ),

  // ---- 算法协同预测（/predict/ensemble）----
  ensemble: (
    symbol: string,
    market = 'a_shares',
    timeframe = '1d',
    limit = 200,
    researchRunId?: string,
  ) =>
    getJSON<EnsembleResp>('/predict/ensemble', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        symbol,
        market,
        timeframe,
        limit,
        research_run_id: researchRunId,
      }),
    }),

  strategies: () => getJSON<StrategiesResp>('/strategies'),
  alphamasterEngine: () => getJSON<{ ok: boolean; engine: {
    available: boolean
    vocab_version: string | null
    vocab_schema: string | null
    feature_count: number
    operator_count: number
    fallback_formulas: Array<{ tokens: number[]; expression: string; warnings: string[] }>
    reason?: string
    install_command?: string
  } }>('/strategies/alphamaster/engine'),

  signals: (limit = 50, source?: string, status?: SignalLifecycleStatus, market?: string, cursor?: string) => {
    const p = new URLSearchParams({ limit: String(limit) })
    if (source) p.set('source', source)
    if (status) p.set('status', status)
    if (market) p.set('market', market)
    if (cursor) p.set('cursor', cursor)
    return getJSON<SignalsResp>(`/signals?${p.toString()}`)
  },

  radarSignals: () => getJSON<RadarSignalsResp>('/signals/radar'),

  updateSignalStatus: (
    id: string,
    payload: { status: 'accepted' | 'rejected'; note?: string },
  ) =>
    getJSON<{ ok: boolean; signal: SignalResp }>(
      `/signals/${encodeURIComponent(id)}/status`,
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      },
    ),

  createSimulationOrder: (payload: {
    intent_id?: string
    signal_id?: string
    symbol?: string
    market?: string
    side?: 'buy' | 'sell'
    order_type?: 'market' | 'limit'
    quantity: number
    limit_price?: number
    account_id?: string
    factor_key?: string
    factor_version?: string
    research_run_id?: string
    rebalance_cycle_id?: string
    signal_time?: string
    tradable_time?: string
    theoretical_price?: number
    capacity_used?: number
    strategy_id?: string
    strategy_version?: string
    market_regime_id?: string
    cost_profile_id?: string
    cost_profile_version?: string
    reduce_only?: boolean
  }) =>
    getJSON<{ ok: boolean; order: SimulationOrder }>('/simulation/orders', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  simulationOrders: (status?: SimulationOrderStatus, symbol?: string, limit = 100, cursor?: string) => {
    const params = new URLSearchParams({ limit: String(limit) })
    if (status) params.set('status', status)
    if (symbol) params.set('symbol', symbol)
    if (cursor) params.set('cursor', cursor)
    return getJSON<SimulationOrdersResp>(
      `/simulation/orders?${params.toString()}`,
    )
  },

  simulationOrder: (id: string) =>
    getJSON<{ ok: boolean; order: SimulationOrder }>(
      `/simulation/orders/${encodeURIComponent(id)}`,
    ),

  fillSimulationOrder: (
    id: string,
    payload: { price: number; quantity?: number; fee_rate?: number },
  ) => getJSON<{ ok: boolean; order: SimulationOrder }>(
    `/simulation/orders/${encodeURIComponent(id)}/fills`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  ),

  retrySimulationLedgerSync: (orderId: string, executionId: string) =>
    getJSON<{ ok: boolean; order: SimulationOrder }>(
      `/simulation/orders/${encodeURIComponent(orderId)}/executions/${encodeURIComponent(executionId)}/ledger-sync`,
      { method: 'POST' },
    ),

  cancelSimulationOrder: (id: string, rejectionReason = 'user_cancelled') =>
    getJSON<{ ok: boolean; order: SimulationOrder }>(
      `/simulation/orders/${encodeURIComponent(id)}/cancel`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rejection_reason: rejectionReason }),
      },
    ),

  simulationAccount: () => getJSON<SimulationAccount>('/simulation/account'),

  // ---- 历史模拟实验记录（只读兼容）----
  demoRuns: (limit = 20) =>
    getJSON<{ ok: boolean; runs: DemoRunSummary[] }>(`/simulation/demo/runs?limit=${limit}`),
  demoRunDetail: (runId: string) =>
    getJSON<{ ok: boolean; run: DemoRunRecord }>(
      `/simulation/demo/runs/${encodeURIComponent(runId)}`,
    ),

  kline: (symbol: string, market = 'a_shares', interval = '1h', limit = 240) =>
    getJSON<KlineResp>(
      `/data/kline?symbol=${encodeURIComponent(symbol)}&market=${encodeURIComponent(
        market,
      )}&interval=${encodeURIComponent(interval)}&limit=${limit}`,
    ),

  runStrategy: (name: string, params: Record<string, unknown> = {}) =>
    getJSON<RunResp>(`/strategies/${encodeURIComponent(name)}/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ params }),
    }),

  analyzePa: (
    symbol: string,
    timeframe = '1h',
    market?: string,
    signal?: AbortSignal,
    researchRunId?: string,
  ) =>
    getJSON<PaAnalyzeResp>(
      `/strategies/pa_agent/analyze?symbol=${encodeURIComponent(symbol)}` +
        `&timeframe=${encodeURIComponent(timeframe)}` +
        (market ? `&market=${encodeURIComponent(market)}` : '') +
        (researchRunId ? `&research_run_id=${encodeURIComponent(researchRunId)}` : ''),
      { method: 'POST', signal },
    ),

  portfolio: () => getJSON<PortfolioResp>('/portfolio'),

  // ---- 持仓明细 CRUD（后端持久化，跨设备/清缓存不丢）----
  addHolding: (payload: { code: string; name?: string; shares?: number; cost?: number; market?: string }) =>
    getJSON<{ ok: boolean; holding: HoldingCRUDResp }>('/portfolio/holdings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  updateHolding: (id: string, patch: Record<string, unknown>) =>
    getJSON<{ ok: boolean; holding: HoldingCRUDResp }>(`/portfolio/holdings/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    }),
  deleteHolding: (id: string) =>
    getJSON<{ ok: boolean }>(`/portfolio/holdings/${encodeURIComponent(id)}`, { method: 'DELETE' }),

  marketBreadth: () => getJSON<MarketBreadthResp>('/market/breadth'),

  watchlist: () => getJSON<WatchlistResp>('/market/watchlist'),

  // ---- 关注列表 CRUD（后端持久化）----
  addWatch: (payload: { sym: string; name?: string; market?: string }) =>
    getJSON<{ ok: boolean; watch: WatchlistCRUDResp }>('/market/watchlist', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  updateWatch: (id: string, patch: Record<string, unknown>) =>
    getJSON<{ ok: boolean; watch: WatchlistCRUDResp }>(`/market/watchlist/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    }),
  deleteWatch: (id: string) =>
    getJSON<{ ok: boolean }>(`/market/watchlist/${encodeURIComponent(id)}`, { method: 'DELETE' }),

  quote: (symbol: string, market = 'a_shares') =>
    getJSON<QuoteResp>(
      `/market/quote?symbol=${encodeURIComponent(symbol)}&market=${encodeURIComponent(market)}`,
    ),

  // ---- G2 预设 / 运行历史（后端持久化）----
  strategyPresets: () => getJSON<{ presets: Record<string, Preset[]> }>('/strategies/presets'),
  savePreset: (name: string, presetName: string, params: Record<string, unknown>) =>
    getJSON<{ ok: boolean; preset: Preset }>(`/strategies/${encodeURIComponent(name)}/presets`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: presetName, params }),
    }),
  deletePreset: (name: string, id: string) =>
    getJSON<{ ok: boolean }>(`/strategies/${encodeURIComponent(name)}/presets/${id}`, {
      method: 'DELETE',
    }),
  strategyRuns: () => getJSON<{ runs: RunRecord[] }>('/strategies/runs'),
  saveRun: (name: string, params: Record<string, unknown>, result: RunResp) =>
    getJSON<{ ok: boolean; run: RunRecord }>(`/strategies/${encodeURIComponent(name)}/runs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ params, result }),
    }),

  // ---- G6 回测 ----
  backtest: (name: string, payload: Record<string, unknown>) =>
    getJSON<BacktestResp>(`/strategies/${encodeURIComponent(name)}/backtest`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  factorResearch: (payload: {
    symbol: string
    market: string
    interval: string
    limit: number
    horizon: number
    transaction_cost_bps: number
    cost_profile_id?: string
    cost_profile_version?: string
    start_date?: string
    end_date?: string
    walk_forward_mode: 'expanding' | 'rolling'
    walk_forward_folds: number
    availability_lag?: number
  }) => getJSON<FactorResearchResp>('/factor-research/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }),
  factorAiReview: (payload: {
    symbol: string
    market: string
    interval: string
    limit: number
    horizon: number
    transaction_cost_bps: number
    cost_profile_id?: string
    cost_profile_version?: string
    start_date?: string
    end_date?: string
    walk_forward_mode: 'expanding' | 'rolling'
    walk_forward_folds: number
    availability_lag?: number
    review_focus?: string
    run_id: string
  }) => getJSON<FactorAiReviewResp>('/factor-research/ai-review', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }),
  factorResearchRuns: (filters: {
    symbol?: string
    market?: string
    interval?: string
    status?: string
    favorite?: boolean
    archived?: boolean
    tag?: string
    created_from?: string
    created_to?: string
    research_limit?: number
    horizon?: number
    transaction_cost_bps?: number
    walk_forward_mode?: 'expanding' | 'rolling'
    walk_forward_folds?: number
  } = {}, limit = 20, cursor?: string) => {
    const params = new URLSearchParams({ limit: String(limit) })
    if (filters.symbol?.trim()) params.set('symbol', filters.symbol.trim().toUpperCase())
    if (filters.market) params.set('market', filters.market)
    if (filters.interval) params.set('interval', filters.interval)
    if (filters.status) params.set('status', filters.status)
    if (filters.favorite !== undefined) params.set('favorite', String(filters.favorite))
    if (filters.archived !== undefined) params.set('archived', String(filters.archived))
    if (filters.tag?.trim()) params.set('tag', filters.tag.trim())
    if (filters.created_from) params.set('created_from', filters.created_from)
    if (filters.created_to) params.set('created_to', filters.created_to)
    if (filters.research_limit !== undefined) params.set('research_limit', String(filters.research_limit))
    if (filters.horizon !== undefined) params.set('horizon', String(filters.horizon))
    if (filters.transaction_cost_bps !== undefined) params.set('transaction_cost_bps', String(filters.transaction_cost_bps))
    if (filters.walk_forward_mode) params.set('walk_forward_mode', filters.walk_forward_mode)
    if (filters.walk_forward_folds !== undefined) params.set('walk_forward_folds', String(filters.walk_forward_folds))
    if (cursor) params.set('cursor', cursor)
    return getJSON<FactorResearchRunsResp>(`/factor-research/runs?${params.toString()}`)
  },
  factorResearchRun: (runId: string) =>
    getJSON<FactorResearchRunDetailResp>(`/factor-research/runs/${encodeURIComponent(runId)}`),
  factorStatusMatrix: (factorKey: string) =>
    getJSON<FactorStatusMatrix>(`/factor-research/status-matrix/${encodeURIComponent(factorKey)}`),
  factorResearchAttention: (staleHours = 24, limit = 100) =>
    getJSON<FactorResearchAttention>(`/factor-research/attention?stale_hours=${staleHours}&limit=${limit}`),
  registerFactorDefinition: (payload: {
    key: string
    label: string
    market: 'a_shares' | 'us_stocks' | 'crypto' | 'mt5' | 'all'
    ast: Record<string, unknown>
    direction?: 'positive' | 'inverse'
    horizon?: number
    availability_lag?: number
    rationale?: string
    family?: string
    version?: string
    parameters?: Record<string, unknown>
  }) => getJSON<{ ok: boolean; definition: FactorDefinitionRecord }>('/factor-research/definitions', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
  startFactorFactory: (payload: FactorFactoryStartPayload) =>
    getJSON<FactorFactoryRunResponse>('/factor-factory/runs', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    }),
  alphaDslCatalog: () => getJSON<AlphaDslCatalog & { ok: true }>('/factor-factory/alpha-dsl'),
  factorFactoryRuns: (
    limit = 50,
    filters?: { market?: 'crypto' | 'a_shares'; symbol?: string; interval?: '1h' | '4h' | '1d' },
  ) => {
    const params = new URLSearchParams({ limit: String(limit) })
    if (filters?.market) params.set('market', filters.market)
    if (filters?.symbol) params.set('symbol', filters.symbol)
    if (filters?.interval) params.set('interval', filters.interval)
    return getJSON<{ ok: boolean; count: number; runs: FactorFactoryRunResponse['run'][]; live_trading_enabled: false }>(
      `/factor-factory/runs?${params.toString()}`,
    )
  },
  factorFactoryArchive: (lifecycleState?: string, limit = 100, eligibleOnly = true) => {
    const params = new URLSearchParams({
      limit: String(limit),
      eligible_only: String(eligibleOnly),
    })
    if (lifecycleState) params.set('lifecycle_state', lifecycleState)
    return getJSON<FactorFactoryArchiveResponse>(`/factor-factory/archive?${params.toString()}`)
  },
  factorFactoryRun: (runId: string) =>
    getJSON<FactorFactoryRunResponse>(`/factor-factory/runs/${encodeURIComponent(runId)}`),
  observeFactorFactory: (runId: string, forceRefresh = false) =>
    getJSON<FactorFactoryRunResponse>(`/factor-factory/runs/${encodeURIComponent(runId)}/observe`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ force_refresh: forceRefresh }),
    }),
  reviewFactorFactoryCohort: (runId: string, provider?: 'deepseek' | 'openai' | 'custom') =>
    getJSON<FactorFactoryRunResponse>(`/factor-factory/runs/${encodeURIComponent(runId)}/cohort/review`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ provider: provider || null }),
    }),
  requestFactorFactorySmallLive: (runId: string, actor: string, reason: string) =>
    getJSON<FactorFactoryRunResponse>(`/factor-factory/runs/${encodeURIComponent(runId)}/cohort/live-request`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ actor, reason }),
    }),
  approveFactorFactorySmallLive: (runId: string, payload: {
    actor: string
    symbol: string
    interval: '1h' | '4h' | '1d'
    factor_version: string
    strategy_version?: string
    maximum_capital: number
    maximum_exposure: number
    maximum_loss: number
    valid_until: string
    risks_acknowledged: boolean
  }) => getJSON<FactorFactoryRunResponse>(`/factor-factory/runs/${encodeURIComponent(runId)}/cohort/manual-approval`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
  seedBuiltinFactorDefinitions: () => getJSON<{
    ok: boolean
    count: number
    definitions: FactorDefinitionRecord[]
    formula_version: string
  }>('/factor-research/definitions/seed-builtins', { method: 'POST' }),
  importTokenFormulaDefinitions: (payload: {
    engine: 'alphagpt' | 'alphamaster'
    formulas: number[][]
    key_prefix?: string
    label_prefix?: string
    version?: string
    horizon?: number
    availability_lag?: number
    rationale?: string
  }) => getJSON<{
    ok: boolean
    engine: 'alphagpt' | 'alphamaster'
    count: number
    definitions: FactorDefinitionRecord[]
  }>('/factor-research/definitions/import-token-formulas', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
  factorDefinitions: (market?: string, family?: string) => {
    const params = new URLSearchParams()
    if (market) params.set('market', market)
    if (family) params.set('family', family)
    const query = params.toString()
    return getJSON<{ ok: boolean; count: number; definitions: FactorDefinitionRecord[] }>(
      `/factor-research/definitions${query ? `?${query}` : ''}`,
    )
  },
  factorDefinition: (factorKey: string, version: string) =>
    getJSON<{ ok: boolean; definition: FactorDefinitionRecord }>(
      `/factor-research/definitions/${encodeURIComponent(factorKey)}/${encodeURIComponent(version)}`,
    ),
  factorLifecycle: (factorKey: string, version: string, targetMarket?: string) => {
    const params = new URLSearchParams()
    if (targetMarket) params.set('target_market', targetMarket)
    const query = params.toString()
    return getJSON<FactorLifecycleRecord>(
      `/factor-research/definitions/${encodeURIComponent(factorKey)}/${encodeURIComponent(version)}/lifecycle${query ? `?${query}` : ''}`,
    )
  },
  transitionFactorLifecycle: (factorKey: string, version: string, payload: {
    state: 'exploratory' | 'research_passed' | 'trading_validated' | 'degraded' | 'retired'
    target_market: 'a_shares' | 'us_stocks' | 'crypto' | 'mt5'
    actor_type?: 'system' | 'researcher' | 'ai'
    actor: string
    rule: string
    evidence: Record<string, unknown>
  }) => getJSON<{
    ok: boolean
    factor_key: string
    version: string
    previous_state: string
    current_state: string
    event: FactorLifecycleRecord['events'][number]
  }>(`/factor-research/definitions/${encodeURIComponent(factorKey)}/${encodeURIComponent(version)}/lifecycle/transitions`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
  validateFactorCandidateData: (payload: {
    factor_key: string
    factor_version?: string
    rows: Array<Record<string, unknown>>
    minimum_data_coverage?: number
  }) => getJSON<{
    ok: boolean
    validation: {
      id: string
      factor_definition_id: string
      data_fingerprint: string
      report: {
        coverage: number
        valid_values: number
        eligible_values: number
        warmup_rows: number
        minimum_data_coverage: number
        definition_hash: string
      }
      created_at: number
    }
  }>('/factor-research/candidate-validations', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
  analyzeFactorRedundancy: (payload: {
    definitions: Array<{ key: string; version?: string }>
    rows: Array<Record<string, unknown>>
    minimum_observations?: number
    high_correlation_threshold?: number
    monotonic_threshold?: number
    tail_quantile?: number
    regime_field?: string
  }) => getJSON<{
    ok: boolean
    definition_count: number
    redundant_count: number
    correlation_scope: { tail_quantile: number; regime_field: string | null }
    correlation_pairs: Array<{
      left_key: string
      right_key: string
      relation: 'exact_duplicate' | 'constant_multiple' | 'monotonic_equivalent' | 'high_correlation' | 'distinct'
      direction: 'same' | 'inverse'
      observations: number
      pearson: number
      spearman: number
      tail_pearson: number | null
      tail_observations: number
      regime_correlations: Array<{
        regime: string
        observations: number
        pearson: number
        spearman: number
      }>
      scale: number | null
    }>
    redundant_pairs: Array<{
      left_key: string
      right_key: string
      relation: 'exact_duplicate' | 'constant_multiple' | 'monotonic_equivalent' | 'high_correlation'
      direction: 'same' | 'inverse'
      observations: number
      pearson: number
      spearman: number
      tail_pearson: number | null
      tail_observations: number
      regime_correlations: Array<{
        regime: string
        observations: number
        pearson: number
        spearman: number
      }>
      scale: number | null
    }>
  }>('/factor-research/redundancy/analyze', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
  analyzeFactorRobustness: (payload: {
    factor: Array<number | null>
    label: Array<number | null>
    liquidity?: Array<number | null>
    deployed_factors?: Record<string, Array<number | null>>
    parameter_results?: Array<Record<string, unknown>>
    parameter_name?: string
    parameter_metric?: string
    parameter_threshold?: number
    pareto_candidates?: Array<Record<string, unknown>>
    pareto_objectives?: Record<string, 'maximize' | 'minimize'>
    factor_returns?: Record<string, Array<number | null>>
    expected_ics?: Record<string, number>
    candidate_portfolio_returns?: Array<number | null>
    benchmark_portfolio_returns?: Array<number | null>
    candidate_turnover?: Array<number | null>
    benchmark_turnover?: Array<number | null>
    candidate_capacity?: Array<number | null>
    benchmark_capacity?: Array<number | null>
    transaction_cost_bps?: number
    risk_constraints?: Record<string, number>
    nonlinear_features?: Record<string, Array<number | null>>
    nonlinear_label?: Array<number | null>
    nonlinear_minimum_improvement?: number
    seed?: number
  }) => getJSON<{
    ok: boolean
    seed: number
    reports: Record<string, unknown>
    deterministic: true
    dynamic_code_execution: false
  }>('/factor-research/robustness/analyze', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
  validateFactorPortfolioConstraints: (payload: {
    market: 'a_shares' | 'us_stocks' | 'crypto' | 'mt5'
    weights: Record<string, number>
    industries?: Record<string, string>
    benchmark_industry_weights?: Record<string, number>
    average_daily_values?: Record<string, number>
    proposed_trade_values?: Record<string, number>
    turnover: number
    overrides?: Record<string, number | boolean>
  }) => getJSON<{
    ok: boolean
    validation: {
      passed: boolean
      market: string
      profile: Record<string, number | boolean | string | null>
      violations: string[]
      overweight_symbols: string[]
      industry_weights: Record<string, number>
      industry_deviations: Record<string, number>
      participation_rates: Record<string, number>
      turnover: number
    }
  }>('/factor-research/portfolio-constraints/validate', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
  factorCandidateInbox: (payload: {
    candidates: Array<{
      candidate_id: string
      source: 'human' | 'ai' | 'template' | 'random_dsl' | 'symbolic_regression'
      economic_hypothesis: string
      formula_ast: Record<string, unknown>
      data_requirements: string[]
      duplicate_risk: 'low' | 'medium' | 'high' | 'confirmed_duplicate'
      future_information_check_passed: boolean
      causal_check_passed: boolean
      data_check_passed: boolean
      estimated_compute_units: number
      exploration_score?: number
      research_status?: string
      trading_status?: string
      ai_review?: Record<string, unknown>
      approved_by?: string
      budget_approved?: boolean
    }>
  }) => getJSON<{ ok: boolean; inbox: Record<string, unknown> }>('/factor-research/candidates/inbox', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
  previewFactorRetirementImpact: (payload: {
    factor_key: string
    replacement_factor_key?: string
    strategies?: Array<Record<string, unknown>>
    portfolio_allocations?: Array<Record<string, unknown>>
  }) => getJSON<{ ok: boolean; preview: Record<string, unknown> }>('/factor-research/retirement/impact-preview', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
  factorLineage: (factorKey: string, version: string, targetMarket?: string) => getJSON<{
    ok: boolean
    factor_key: string
    version: string
    target_market: string
    definition: {
      definition_hash: string
      formula_hash: string
      ast: Record<string, unknown>
      input_fields: string[]
      rationale: string
      parameters: Record<string, unknown>
    }
    trace: {
      ai_hypothesis: Array<Record<string, unknown>>
      dsl: Record<string, unknown>
      data_validation: Array<Record<string, unknown>>
      experiments: Array<Record<string, unknown>>
      statistics: Array<Record<string, unknown>>
      portfolio_decisions: Array<Record<string, unknown>>
      simulation: Array<Record<string, unknown>>
    }
    current_state: string
    evidence_complete: boolean
    historical_definition_preserved: boolean
  }>(`/factor-research/lineage/${encodeURIComponent(factorKey)}/${encodeURIComponent(version)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(targetMarket ? { target_market: targetMarket } : {}),
  }),
  monitorFactorDrift: (payload: {
    factor_key: string
    reference_values: number[]
    current_values: number[]
    reference_ic: number
    current_ic: number
    reference_coverage: number
    current_coverage: number
    current_cost_bps: number
    current_capacity_ratio: number
    reference_correlated_factors?: Record<string, number[]>
    current_correlated_factors?: Record<string, number[]>
    thresholds: Record<string, number>
    affected_strategies?: Array<Record<string, unknown>>
  }) => getJSON<{ ok: boolean; monitoring: Record<string, unknown> }>('/factor-research/monitoring/drift', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
  validateFactorSimulation: (payload: {
    completed_rebalance_cycles: number
    after_cost_return: number
    fill_rate: number
    capacity_ratio: number
    thresholds: Record<string, number>
    execution_records: Array<Record<string, unknown>>
  }) => getJSON<{ ok: boolean; validation: Record<string, unknown> }>('/factor-research/simulation/validate', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
  attributeFactorSimulationGap: (payload: {
    research_returns: number[]
    simulation_returns: number[]
    signal_decay: number[]
    data_delay: number[]
    execution: number[]
    costs: number[]
    portfolio_constraints: number[]
    research_metrics: Record<string, number>
    simulation_metrics: Record<string, number>
  }) => getJSON<{ ok: boolean; attribution: Record<string, unknown> }>('/factor-research/simulation/attribute-gap', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
  compareFactorDiscoveryEfficiency: (payload: {
    candidates: Array<{
      candidate_id: string
      source: 'ai' | 'template' | 'random_dsl' | 'symbolic_regression'
      validation_passed: boolean
      duplicate: boolean
      research_passed?: boolean
      compute_units?: number
      llm_tokens?: number
    }>
    per_source_budget: number
  }) => getJSON<{
    ok: boolean
    report: {
      fixed_candidate_budget: number
      requested_candidate_budget: number
      sources: Array<Record<string, number | string | null>>
      winner: 'ai' | 'template' | 'random_dsl' | 'symbolic_regression'
      primary_metric: 'novel_valid_rate'
      deterministic: true
      selection_bias_warning: string
    }
  }>('/factor-research/efficiency/compare', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
  createFactorResearchPlan: (payload: {
    id: string
    title: string
    target_market: FactorResearchPlanRecord['target_market']
    maximum_candidates: number
    maximum_compute_units: number
    maximum_llm_tokens?: number
    maximum_confirmation_set_openings?: number
    maximum_round_candidates?: number
    maximum_formula_complexity?: number
    maximum_duplicate_rate?: number
    stop_conditions?: Record<string, unknown>
    data_split?: FactorResearchDataSplit
  }) => getJSON<{ ok: boolean; plan: FactorResearchPlanRecord }>(
    '/factor-research/plans',
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) },
  ),
  factorResearchPlans: (targetMarket?: string) =>
    getJSON<{ ok: boolean; count: number; plans: FactorResearchPlanRecord[] }>(
      `/factor-research/plans${targetMarket ? `?target_market=${encodeURIComponent(targetMarket)}` : ''}`,
    ),
  factorConfirmationSet: (planId: string) => getJSON<{
    ok: boolean
    opened: boolean
    opening: FactorConfirmationSetOpening | null
  }>(`/factor-research/plans/${encodeURIComponent(planId)}/confirmation-set`),
  openFactorConfirmationSet: (planId: string, payload: {
    experiment_id: string
    confirmation_data_fingerprint: string
    opened_by: string
    irreversible_ack: true
  }) => getJSON<{
    ok: boolean
    opened: true
    opening: FactorConfirmationSetOpening
    idempotent_replay: boolean
    further_experiments_blocked: true
  }>(`/factor-research/plans/${encodeURIComponent(planId)}/confirmation-set/open`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
  factorPlanMultipleTesting: (planId: string) => getJSON<{
    ok: boolean
    research_plan_id: string
    target_market: string
    cumulative_experiments: number
    cumulative_registered_candidates: number
    corrected_candidates: number
    pending_candidates: number
    method: string
    rows: Array<{
      experiment_id: string
      attempt_number: number
      source: FactorExperimentRecord['source']
      factor_key: string
      factor_family: string
      candidate_key: string
      experiment_status: FactorExperimentRecord['status']
      raw_p_value: number
      batch_adjusted_p_value: number
      global_adjusted_p_value: number
      effective_sample_size: number | null
      return_series_basis?: 'excess_returns' | 'strategy_returns'
      return_observations?: number
      deflated_sharpe?: {
        probability: number
        observed_sharpe: number
        expected_max_sharpe: number
        observations: number
        trials: number
        skewness: number
        kurtosis: number
        method: 'deflated_sharpe_non_normal_multiple_trials'
      }
    }>
    deflated_sharpe_method: 'deflated_sharpe_non_normal_multiple_trials'
    reality_check: FactorRealityCheck
  }>(`/factor-research/plans/${encodeURIComponent(planId)}/multiple-testing`),
  factorAiProposalContext: (planId: string) => getJSON<{
    ok: boolean
    context: FactorAiProposalContext
    context_fingerprint: string
  }>(`/factor-research/plans/${encodeURIComponent(planId)}/ai-proposal-context`),
  createFactorAiSearchRound: (planId: string, payload: {
    round_id: string
    candidate_count: number
    duplicate_count?: number
    formula_complexities: number[]
    llm_tokens?: number
    input_fingerprint: string
    approved_by: string
    approved_candidate_ids: string[]
    budget_approved_ack: true
  }) => getJSON<{
    ok: boolean
    round: FactorAiSearchRoundRecord
    gate_violations?: string[]
    usage?: FactorAiSearchUsage
    idempotent_replay?: boolean
  }>(`/factor-research/plans/${encodeURIComponent(planId)}/ai-search-rounds`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
  factorAiSearchRounds: (planId: string) => getJSON<{
    ok: boolean
    count: number
    rounds: FactorAiSearchRoundRecord[]
    usage: FactorAiSearchUsage
  }>(`/factor-research/plans/${encodeURIComponent(planId)}/ai-search-rounds`),
  createFactorExperiment: (payload: {
    research_plan_id: string
    hypothesis: string
    source: FactorExperimentRecord['source']
    parent_experiment_id?: string
    factor_key: string
    factor_version?: string
    candidate_validation_id: string
    target_market: FactorExperimentRecord['target_market']
    data_start?: string
    data_end?: string
    parameter_grid?: Record<string, unknown>
    estimated_compute_units?: number
    model?: Record<string, unknown>
    prompt?: Record<string, unknown>
    applicable_regimes?: string[]
    invalidation_conditions?: string[]
    falsification_tests?: string[]
    ai_trace?: Record<string, unknown>
    pre_registration: FactorPreRegistration
  }) => getJSON<{ ok: boolean; experiment: FactorExperimentRecord; statistical_status_locked: true }>(
    '/factor-research/experiments',
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) },
  ),
  factorExperiments: (researchPlanId?: string, status?: FactorExperimentRecord['status']) => {
    const params = new URLSearchParams()
    if (researchPlanId) params.set('research_plan_id', researchPlanId)
    if (status) params.set('status', status)
    const query = params.toString()
    return getJSON<{
      ok: boolean
      count: number
      cumulative_attempts: number | null
      experiments: FactorExperimentRecord[]
    }>(`/factor-research/experiments${query ? `?${query}` : ''}`)
  },
  appendFactorExperimentEvent: (experimentId: string, payload: {
    status: Exclude<FactorExperimentRecord['status'], 'draft'>
    result?: Record<string, unknown>
    failure_reason?: string
    failure_code?: FactorFailureCode
    evidence?: Record<string, unknown>
  }) => getJSON<{ ok: boolean; experiment: FactorExperimentRecord; statistical_status_locked: true }>(
    `/factor-research/experiments/${encodeURIComponent(experimentId)}/events`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) },
  ),
  factorUniverses: (market?: string) =>
    getJSON<{ ok: boolean; count: number; universes: FactorUniverse[] }>(
      `/factor-research/universes${market ? `?market=${encodeURIComponent(market)}` : ''}`,
    ),
  createFactorUniverse: (payload: { name: string; market: string; description?: string }) =>
    getJSON<{ ok: boolean; universe: FactorUniverse; error?: string }>('/factor-research/universes', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    }),
  factorUniverseMembers: (universeId: string, asOf?: string) =>
    getJSON<{ ok: boolean; universe: FactorUniverse; count: number; members: FactorUniverseMember[]; versions: import('./types').FactorUniverseVersion[] }>(
      `/factor-research/universes/${encodeURIComponent(universeId)}/members${asOf ? `?as_of=${encodeURIComponent(asOf)}` : ''}`,
    ),
  upsertFactorUniverseMember: (universeId: string, payload: {
    symbol: string
    effective_from: string
    effective_to?: string | null
    status: 'active' | 'suspended' | 'delisted'
    industry?: string
    market_cap?: number | null
    beta?: number | null
    is_st?: boolean
    listed_at?: string | null
    delisted_at?: string | null
  }) => getJSON<{ ok: boolean; member: FactorUniverseMember; error?: string }>(
    `/factor-research/universes/${encodeURIComponent(universeId)}/members`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) },
  ),
  previewFactorUniverseBatch: (universeId: string, payload: {
    idempotency_key: string; source: string; filename: string; content_base64: string
  }) => getJSON<{ ok: boolean; diff: import('./types').FactorUniverseBatchDiff; errors: Array<Record<string, unknown>> }>(
    `/factor-research/universes/${encodeURIComponent(universeId)}/batch/preview`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) },
  ),
  applyFactorUniverseBatch: (universeId: string, payload: {
    idempotency_key: string; source: string; filename: string; content_base64: string
  }) => getJSON<{ ok: boolean; idempotent_replay: boolean; batch: Record<string, unknown>; version?: import('./types').FactorUniverseVersion }>(
    `/factor-research/universes/${encodeURIComponent(universeId)}/batch/apply`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) },
  ),
  rollbackFactorUniverse: (universeId: string, versionId: string, reason: string) =>
    getJSON<{ ok: boolean; universe: FactorUniverse; version: import('./types').FactorUniverseVersion }>(
      `/factor-research/universes/${encodeURIComponent(universeId)}/rollback`,
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ version_id: versionId, reason }) },
    ),
  crossSectionResearch: (payload: {
    run_id?: string
    universe_id: string
    factor_key: string
    interval: '1d'
    limit: number
    horizon: number
    start_date?: string
    end_date?: string
    quantiles: number
    min_assets: number
    portfolio_mode: 'cohort' | 'non_overlapping'
    transaction_cost_bps: number
    cost_profile_id?: string
    cost_profile_version?: string
    participation_rate: number
    neutralize_industry: boolean
    neutralize_market_cap: boolean
    neutralize_beta: boolean
    retry_attempts: number
  }) => getJSON<CrossSectionResearchResp>('/factor-research/cross-sectional/analyze', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
  crossSectionResearchRun: (runId: string) => getJSON<{
    ok: boolean
    run: ResearchRun
    result: CrossSectionResearchResp | null
    universe_snapshot: Record<string, unknown> | null
    market_snapshots: ResearchEvidence[]
  }>(`/factor-research/cross-sectional/runs/${encodeURIComponent(runId)}`),
  crossMarketFactorStatus: (factorKey: string, targetMarket?: string) => {
    const query = targetMarket ? `?target_market=${encodeURIComponent(targetMarket)}` : ''
    return getJSON<CrossMarketFactorStatus>(`/factor-research/cross-sectional/status/${encodeURIComponent(factorKey)}${query}`)
  },

  // ---- G7 组合管理 ----
  portfolioManage: () => getJSON<PortfolioManageResp>('/portfolio/manage'),
  saveAlloc: (payload: Record<string, unknown>) =>
    getJSON<{ ok: boolean; alloc: unknown }>('/portfolio/manage/allocations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  deleteAlloc: (id: string) =>
    getJSON<{ ok: boolean }>(`/portfolio/manage/allocations/${id}`, { method: 'DELETE' }),
  setAllocLive: (id: string, live: boolean) =>
    getJSON<{ ok: boolean }>(`/portfolio/manage/allocations/${id}/live?live=${live}`, {
      method: 'POST',
    }),

  // ---- G5 实盘（paper）----
  liveStatus: (name: string) =>
    getJSON<LiveResp>(`/strategies/${encodeURIComponent(name)}/live`),
  liveTick: (name: string) =>
    getJSON<LiveResp>(`/strategies/${encodeURIComponent(name)}/live/tick`, { method: 'POST' }),

  // ---- 信号发布（POST /signals/publish）----
  publishSignal: (req: PublishSignalReq) =>
    getJSON<{ ok: boolean; signal: SignalResp }>('/signals/publish', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    }),

  // ---- 信号删除（DELETE /signals/{id}，持久化删除）----
  deleteSignal: (id: string) =>
    getJSON<{ ok: boolean }>(`/signals/${encodeURIComponent(id)}`, { method: 'DELETE' }),

  getApiKey: () => getJSON<ApiKeyResp>('/config/apikey'),

  setApiKey: (apiKey: string) =>
    getJSON<ApiKeyResp>('/config/apikey', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key: apiKey }),
    }),

  llmConfig: () => getJSON<LLMConfigResp>('/config/llm'),

  updateLLMConfig: (payload: LLMSettingsUpdate) =>
    getJSON<LLMConfigResp>('/config/llm', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  removeLLMKey: () => getJSON<LLMConfigResp>('/config/llm/key', { method: 'DELETE' }),

  testLLMConnection: () =>
    getJSON<LLMConnectionTestResp>('/config/llm/test', { method: 'POST' }),

  okxDemoCredentialStatus: () =>
    getJSON<OkxDemoCredentialStatus>('/config/okx-demo'),

  saveOkxDemoCredentials: (payload: { api_key: string; secret_key: string; passphrase: string }) =>
    getJSON<OkxDemoCredentialStatus>('/config/okx-demo', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  testOkxDemoConnection: () =>
    getJSON<OkxDemoConnectionTest>('/config/okx-demo/test', { method: 'POST' }),

  deleteOkxDemoCredentials: () =>
    getJSON<OkxDemoCredentialStatus>('/config/okx-demo', { method: 'DELETE' }),

  // ---- Instrument 标的主数据 ----
  instruments: (q = '', limit = 50, market?: string) => {
    const params = new URLSearchParams({ q, limit: String(limit) })
    if (market) params.set('market', market)
    return getJSON<{ count: number; instruments: Instrument[] }>(`/instruments?${params.toString()}`)
  },
  okxSwapCatalog: (q = '', limit = 100, refresh = false) => {
    const params = new URLSearchParams({ q, limit: String(limit), refresh: String(refresh) })
    return getJSON<OkxSwapCatalogResponse>(`/instruments/okx-swaps?${params.toString()}`)
  },
  resolveInstrument: (code: string, market = 'a_shares', name = '') => {
    const params = new URLSearchParams({ market, name })
    return getJSON<{ ok: boolean; instrument: Instrument }>(
      `/instruments/${encodeURIComponent(code)}?${params.toString()}`,
    )
  },
  registerInstrument: (payload: {
    code: string
    market?: string | null
    name?: string
    exchange?: string
    currency?: string
    asset_class?: string
  }) => getJSON<{ ok: boolean; instrument: Instrument }>('/instruments', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }),

  previewSimulationOrder: (payload: {
    signal_id?: string
    symbol?: string
    market?: string
    side?: 'buy' | 'sell'
    order_type?: 'market' | 'limit'
    quantity: number
    limit_price?: number | null
    account_id?: string
    research_run_id?: string
    cost_profile_id?: string
    cost_profile_version?: string
    reduce_only?: boolean
  }) =>
    getJSON<{ ok: boolean; preview: SimulationOrderPreview }>('/simulation/orders/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  // ---- 组合账本 ----
  ledgerSummary: () => getJSON<{ ok: boolean; summary: LedgerSummary }>('/ledger/summary'),
  ledgerPositions: () => getJSON<{ count: number; positions: LedgerPosition[] }>('/ledger/positions'),
  ledgerTrades: (instrumentId?: string, limit = 200, cursor?: string) => {
    const params = new URLSearchParams({ limit: String(limit) })
    if (instrumentId) params.set('instrument_id', instrumentId)
    if (cursor) params.set('cursor', cursor)
    return getJSON<{ count: number; total: number; next_cursor: string | null; trades: LedgerTrade[] }>(`/ledger/trades?${params.toString()}`)
  },
  recordLedgerTrade: (payload: {
    instrument_id: string
    code: string
    market: string
    direction: 'buy' | 'sell'
    quantity: number
    price: number
    fee?: number
    source?: string
    note?: string
  }) => getJSON<{ ok: boolean; trade: LedgerTrade }>('/ledger/trades', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }),
  ledgerCash: (limit = 200, cursor?: string) => {
    const params = new URLSearchParams({ limit: String(limit) })
    if (cursor) params.set('cursor', cursor)
    return getJSON<{ count: number; total: number; next_cursor: string | null; entries: LedgerCashEntry[] }>(`/ledger/cash?${params.toString()}`)
  },
  recordLedgerCash: (payload: {
    direction: 'in' | 'out'
    amount: number
    currency?: string
    source?: string
    note?: string
  }) => getJSON<{ ok: boolean; entry: LedgerCashEntry }>('/ledger/cash', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }),
  ledgerPerformance: () => getJSON<LedgerPerformance>('/ledger/performance'),
  ledgerTradeAnalytics: () => getJSON<LedgerTradeAnalytics>('/ledger/trade-analytics'),
  ledgerAttribution: (period: 'day' | 'week' | 'month' = 'month', startAt?: number, endAt?: number) => {
    const params = new URLSearchParams({ period })
    if (startAt !== undefined) params.set('start_at', String(startAt))
    if (endAt !== undefined) params.set('end_at', String(endAt))
    return getJSON<LedgerAttribution>(`/ledger/attribution?${params.toString()}`)
  },
  ledgerPositionDecisionContext: (instrumentId: string) =>
    getJSON<PositionDecisionContext>(
      `/ledger/positions/${encodeURIComponent(instrumentId)}/decision-context`,
    ),
  ledgerExposures: () => getJSON<LedgerExposures>('/ledger/exposures'),
  ledgerBenchmarks: () =>
    getJSON<{ count: number; benchmarks: LedgerBenchmark[] }>('/ledger/benchmarks'),
  registerLedgerBenchmark: (payload: {
    name: string
    code: string
    market?: string
    equity_curve?: Array<Record<string, unknown>>
    metrics?: Record<string, unknown>
  }) => getJSON<{ ok: boolean; benchmark: LedgerBenchmark }>('/ledger/benchmarks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }),
  correctLedgerTrade: (tradeId: string, payload: {
    reason: string
    instrument_id: string
    code: string
    market: string
    direction: 'buy' | 'sell'
    quantity: number
    price: number
    fee: number
    source: string
    note: string
  }) => getJSON<{ ok: boolean; trade: LedgerTrade; correction: LedgerCorrection }>(
    `/ledger/trades/${encodeURIComponent(tradeId)}`,
    { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) },
  ),
  correctLedgerCash: (entryId: string, payload: {
    reason: string
    direction: 'in' | 'out'
    amount: number
    currency: string
    source: string
    note: string
  }) => getJSON<{ ok: boolean; entry: LedgerCashEntry; correction: LedgerCorrection }>(
    `/ledger/cash/${encodeURIComponent(entryId)}`,
    { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) },
  ),
  correctLedgerBenchmark: (benchmarkId: string, payload: {
    reason: string
    name: string
    code: string
    market: string
    equity_curve: Array<Record<string, unknown>>
    metrics: Record<string, unknown>
  }) => getJSON<{ ok: boolean; benchmark: LedgerBenchmark; correction: LedgerCorrection }>(
    `/ledger/benchmarks/${encodeURIComponent(benchmarkId)}`,
    { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) },
  ),
  ledgerCorrections: (entityType?: string, entityId?: string, limit = 200) => {
    const params = new URLSearchParams({ limit: String(limit) })
    if (entityType) params.set('entity_type', entityType)
    if (entityId) params.set('entity_id', entityId)
    return getJSON<{ ok: boolean; count: number; corrections: LedgerCorrection[] }>(
      `/ledger/corrections?${params.toString()}`,
    )
  },

  // ---- 策略实验室 ----
  strategyLabDefinitions: (limit = 100) =>
    getJSON<{ count: number; definitions: StrategyDefinition[] }>(`/strategy-lab/definitions?limit=${limit}`),
  strategyLabDefinition: (id: string) =>
    getJSON<{ ok: boolean; definition: StrategyDefinition }>(`/strategy-lab/definitions/${encodeURIComponent(id)}`),
  createStrategyDefinition: (payload: {
    name: string
    strategy_key: string
    market?: string
    description?: string
    tags?: string[]
  }) => getJSON<{ ok: boolean; definition: StrategyDefinition }>('/strategy-lab/definitions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }),
  updateStrategyDefinition: (id: string, payload: {
    name: string
    strategy_key: string
    market: string
    description: string
    tags: string[]
  }) => getJSON<{ ok: boolean; definition: StrategyDefinition }>(
    `/strategy-lab/definitions/${encodeURIComponent(id)}`,
    { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) },
  ),
  copyStrategyDefinition: (id: string, name: string) =>
    getJSON<{ ok: boolean; definition: StrategyDefinition }>(
      `/strategy-lab/definitions/${encodeURIComponent(id)}/copy`,
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) },
    ),
  archiveStrategyDefinition: (id: string) =>
    getJSON<{ ok: boolean; definition: StrategyDefinition }>(
      `/strategy-lab/definitions/${encodeURIComponent(id)}/archive`, { method: 'POST' },
    ),
  createStrategyVersion: (definitionId: string, payload: {
    version: string
    params?: Record<string, unknown>
    code_hash?: string
    changelog?: string
  }) => getJSON<{ ok: boolean; version: unknown }>(
    `/strategy-lab/definitions/${encodeURIComponent(definitionId)}/versions`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  ),
  updateStrategyVersion: (versionId: string, payload: {
    version: string
    params: Record<string, unknown>
    code_hash?: string
    changelog: string
  }) => getJSON<{ ok: boolean; version: StrategyVersion }>(
    `/strategy-lab/versions/${encodeURIComponent(versionId)}`,
    { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) },
  ),
  copyStrategyVersion: (versionId: string, version: string) =>
    getJSON<{ ok: boolean; version: StrategyVersion }>(
      `/strategy-lab/versions/${encodeURIComponent(versionId)}/copy`,
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ version }) },
    ),
  archiveStrategyVersion: (versionId: string) =>
    getJSON<{ ok: boolean; version: StrategyVersion }>(
      `/strategy-lab/versions/${encodeURIComponent(versionId)}/archive`, { method: 'POST' },
    ),
  strategyLabExperiments: (definitionId?: string, limit = 100) => {
    const params = new URLSearchParams({ limit: String(limit) })
    if (definitionId) params.set('definition_id', definitionId)
    return getJSON<{ count: number; experiments: StrategyExperiment[] }>(
      `/strategy-lab/experiments?${params.toString()}`,
    )
  },
  createStrategyExperiment: (definitionId: string, payload: {
    symbol: string
    market?: string
    timeframe?: string
    version_id?: string | null
    research_run_id?: string | null
    params?: Record<string, unknown>
    note?: string
  }) => getJSON<{ ok: boolean; experiment: StrategyExperiment }>(
    `/strategy-lab/experiments?definition_id=${encodeURIComponent(definitionId)}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  ),
  updateStrategyExperiment: (experimentId: string, payload: {
    symbol: string
    market: string
    timeframe: string
    version_id: string | null
    research_run_id?: string | null
    params: Record<string, unknown>
    note: string
  }) => getJSON<{ ok: boolean; experiment: StrategyExperiment }>(
    `/strategy-lab/experiments/${encodeURIComponent(experimentId)}`,
    { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) },
  ),
  copyStrategyExperiment: (experimentId: string, note: string) =>
    getJSON<{ ok: boolean; experiment: StrategyExperiment }>(
      `/strategy-lab/experiments/${encodeURIComponent(experimentId)}/copy`,
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ note }) },
    ),
  archiveStrategyExperiment: (experimentId: string) =>
    getJSON<{ ok: boolean; experiment: StrategyExperiment }>(
      `/strategy-lab/experiments/${encodeURIComponent(experimentId)}/archive`, { method: 'POST' },
    ),
  runStrategyExperiment: (experimentId: string, payload: {
    initial_capital?: number
    limit?: number
    seed?: string | null
  }) => getJSON<{ ok: boolean; run_id?: string; run?: StrategyLabRun; error?: string }>(
    `/strategy-lab/experiments/${encodeURIComponent(experimentId)}/backtest`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  ),
  strategyLabRuns: (experimentId: string) =>
    getJSON<{ count: number; runs: StrategyLabRun[] }>(
      `/strategy-lab/experiments/${encodeURIComponent(experimentId)}/runs`,
    ),
  compareStrategyLabRuns: (runIds: string[]) => {
    const params = new URLSearchParams()
    runIds.forEach((id) => params.append('run_ids', id))
    return getJSON<{ ok: boolean; comparison: StrategyLabComparisonRow[]; differences: StrategyLabRunDifference[] }>(
      `/strategy-lab/compare?${params.toString()}`,
    )
  },

  // ---- 自动化控制台 ----
  automationStatus: () => getJSON<AutomationStatus>('/automation/status'),
  automationJobs: () => getJSON<{ ok: boolean; count: number; jobs: AutomationJob[]; error?: string }>('/automation/jobs'),
  factorResearchJobs: () => getJSON<{ ok: boolean; count: number; jobs: FactorResearchJob[]; timezone: string }>('/automation/factor-research-jobs'),
  createFactorResearchJob: (payload: {
    name: string
    frequency: 'daily' | 'weekly' | 'monthly'
    hour: number
    minute: number
    day_of_week?: number
    day_of_month?: number
    enabled?: boolean
    request: {
      universe_id: string
      factor_key: string
      interval: '1d'
      limit: number
      horizon: number
      transaction_cost_bps: number
      participation_rate: number
      quantiles: number
      min_assets: number
      portfolio_mode?: 'cohort' | 'non_overlapping'
      neutralize_industry: boolean
      neutralize_market_cap: boolean
      neutralize_beta: boolean
      retry_attempts: number
    }
    actor?: string
  }) => getJSON<{ ok: boolean; job: FactorResearchJob }>('/automation/factor-research-jobs', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
  updateAutomationJob: (
    name: string,
    payload: { enabled?: boolean; cron?: string; actor?: string },
  ) => getJSON<{ ok: boolean; job: AutomationJob }>(`/automation/jobs/${encodeURIComponent(name)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }),
  runAutomationJob: (name: string, actor = 'local-user') =>
    getJSON<{ ok: boolean; run: AutomationRun }>(
      `/automation/jobs/${encodeURIComponent(name)}/run`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ actor }),
      },
    ),
  automationRuns: (jobName?: string, status?: AutomationRunStatus, limit = 100, cursor?: string) => {
    const params = new URLSearchParams({ limit: String(limit) })
    if (jobName) params.set('job_name', jobName)
    if (status) params.set('status', status)
    if (cursor) params.set('cursor', cursor)
    return getJSON<{ ok: boolean; count: number; total: number; next_cursor: string | null; runs: AutomationRun[] }>(
      `/automation/runs?${params.toString()}`,
    )
  },
  retryAutomationRun: (runId: string, actor = 'local-user') =>
    getJSON<{ ok: boolean; run: AutomationRun }>(
      `/automation/runs/${encodeURIComponent(runId)}/retry`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ actor }),
      },
    ),
  acknowledgeAutomationRun: (runId: string, actor = 'local-user') =>
    getJSON<{ ok: boolean; run: AutomationRun }>(
      `/automation/runs/${encodeURIComponent(runId)}/acknowledge`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ actor }),
      },
    ),
  automationAlerts: (limit = 100) =>
    getJSON<{ ok: boolean; count: number; alerts: AutomationRun[] }>(
      `/automation/alerts?limit=${limit}`,
    ),
  automationAudit: (limit = 100, cursor?: string) => {
    const params = new URLSearchParams({ limit: String(limit) })
    if (cursor) params.set('cursor', cursor)
    return getJSON<{ ok: boolean; count: number; total: number; next_cursor: string | null; audit: AutomationAuditLog[] }>(
      `/automation/audit?${params.toString()}`,
    )
  },

  // ---- 数据库备份与恢复 ----
  backupStatus: () => getJSON<BackupStatus>('/backups/status'),
  backups: () => getJSON<{ ok: boolean; count: number; backups: BackupRecord[] }>('/backups'),
  createBackup: (actor = 'local-user') =>
    getJSON<{ ok: boolean; actor: string; backup: BackupRecord; verification: BackupVerification }>(
      '/backups',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ actor }),
      },
    ),
  verifyBackup: (name: string, actor = 'local-user') =>
    getJSON<{ ok: boolean; actor: string; backup: BackupRecord; verification: BackupVerification }>(
      `/backups/${encodeURIComponent(name)}/verify`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ actor }),
      },
    ),
  restoreBackup: (name: string, confirmName: string, actor = 'local-user') =>
    getJSON<{
      ok: boolean
      actor: string
      restored_from: BackupRecord
      safety_backup: BackupRecord
      result: BackupVerification & { source: string; target: string; safety_backup: string }
    }>(`/backups/${encodeURIComponent(name)}/restore`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ actor, confirm_name: confirmName }),
    }),
  previewBackupRetention: (keep: number, actor = 'local-user') =>
    getJSON<BackupRetentionResult>('/backups/retention/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ keep, actor }),
    }),
  applyBackupRetention: (keep: number, confirmFiles: string[], actor = 'local-user') =>
    getJSON<BackupRetentionResult>('/backups/retention/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ keep, confirm_files: confirmFiles, actor }),
    }),

  incidents: (limit = 100, cursor?: string) => {
    const params = new URLSearchParams({ limit: String(limit) })
    if (cursor) params.set('cursor', cursor)
    return getJSON<{ ok: boolean; count: number; total: number; next_cursor: string | null; incidents: IncidentRecord[] }>(
      `/incidents?${params.toString()}`,
    )
  },
  checkIncidentDataSource: (payload: {
    incident_id: string
    market: string
    source: string
    operation: DataSourceOperation
    symbol: string
    interval: string
  }) => getJSON<{ ok: boolean; check: DataSourceCheckResult; incident: Record<string, unknown> }>(
    '/incidents/data-sources/check',
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) },
  ),
  acknowledgeDataSourceRecovery: (incidentId: string, resolution: string) =>
    getJSON<{ ok: boolean; incident: Record<string, unknown> }>(
      `/incidents/data-sources/${encodeURIComponent(incidentId)}/acknowledge`,
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ resolution }) },
    ),

  // ---- 新闻结构化分析（FinBERT2 + 配置 LLM）----
  newsHealth: () => getJSON<NewsHealthResp>('/news/health'),

  newsAnalyze: (
    symbol: string,
    limit = 20,
    market = 'a_shares',
    timeframe = '1d',
    researchRunId?: string,
  ) =>
    getJSON<NewsAnalyzeResp>('/news/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        symbol: symbol.trim(),
        limit,
        market,
        timeframe,
        research_run_id: researchRunId,
      }),
    }),
  validateNewsResearchEvents: (payload: {
    events: NewsResearchEvent[]
    target_entity_id: string
    minimum_confidence?: number
    duplicate_similarity?: number
  }) => getJSON<{
    ok: boolean
    report: Record<string, unknown>
    prediction_generated: false
  }>('/news/events/validate', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
  researchNewsEvents: (payload: {
    events: NewsResearchEvent[]
    outcomes: NewsEventOutcome[]
    target_entity_id: string
    minimum_confidence?: number
    duplicate_similarity?: number
  }) => getJSON<{
    ok: boolean
    report: {
      validation: Record<string, unknown>
      horizons: Array<Record<string, unknown>>
      conditional_effects: Array<Record<string, unknown>>
      evidence_index: Array<Record<string, unknown>>
      matched_outcomes: number
      prediction_generated: false
      dynamic_code_execution: false
      method_version: string
    }
  }>('/news/events/research', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),

  // ---- 交易域（M1-02）：浏览器唯一通往 OKX Runner 的通路 ----
  // 前端不得直接配置 / 访问 Runner URL 与 Runner Token，全部经 /api/trading/*。
  tradingHealth: () => getJSON<ContractEnvelope<TradingHealth>>('/trading/health'),

  tradingDashboard: () =>
    getJSON<ContractEnvelope<TradingDashboard>>('/trading/dashboard'),

  tradingPreflight: (symbols?: string[]) => {
    const params = new URLSearchParams()
    if (symbols?.length) params.set('symbols', symbols.join(','))
    const query = params.toString()
    return getJSON<ContractEnvelope<TradingPreflight>>(`/trading/preflight${query ? `?${query}` : ''}`)
  },

  tradingAccount: (accountId: string) =>
    getJSON<ContractEnvelope<Record<string, unknown>>>(
      '/trading/accounts/' + encodeURIComponent(accountId),
    ),

  tradingOrder: (orderId: string) =>
    getJSON<ContractEnvelope<TradingOrderDetail>>(
      '/trading/orders/' + encodeURIComponent(orderId),
    ),

  tradingSubmitOrder: (intent: TradingOrderIntent) =>
    getJSON<ContractEnvelope<TradingOrderDetail>>('/trading/orders', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(intent),
    }),

  tradingCancelOrder: (orderId: string) =>
    getJSON<ContractEnvelope<TradingOrderDetail>>(
      '/trading/orders/' + encodeURIComponent(orderId) + '/cancel',
      { method: 'POST' },
    ),

  tradingAmendOrder: (orderId: string, amendment: TradingOrderAmendment) =>
    getJSON<ContractEnvelope<TradingOrderDetail>>(
      '/trading/orders/' + encodeURIComponent(orderId) + '/amend',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(amendment),
      },
    ),

  tradingClosePosition: (
    accountId: string,
    symbol: string,
    intent: TradingClosePositionIntent,
  ) => getJSON<ContractEnvelope<TradingOrderDetail>>(
    `/trading/positions/${encodeURIComponent(accountId)}/${encodeURIComponent(symbol)}/close`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(intent),
    },
  ),

  tradingRecoverOrders: () =>
    getJSON<ContractEnvelope<Record<string, unknown>>>('/trading/recovery/orders', { method: 'POST' }),

  tradingReconcile: (accountId: string) =>
    getJSON<ContractEnvelope<Record<string, unknown>>>(
      '/trading/reconciliation/' + encodeURIComponent(accountId),
      { method: 'POST' },
    ),

  tradingReconciliationDiff: (diffId: string) =>
    getJSON<ContractEnvelope<Record<string, unknown>>>(
      '/trading/reconciliation/diffs/' + encodeURIComponent(diffId),
    ),

  tradingResolveDiff: (diffId: string, payload: { owner: string; resolution: string }) =>
    getJSON<ContractEnvelope<Record<string, unknown>>>(
      '/trading/reconciliation/diffs/' + encodeURIComponent(diffId) + '/resolve',
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) },
    ),

  tradingSetRiskMode: (payload: { scope?: string; mode: RiskMode; reason: string; operator: string }) =>
    getJSON<ContractEnvelope<Record<string, unknown>>>('/trading/risk/mode', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scope: 'global', ...payload }),
    }),
}
