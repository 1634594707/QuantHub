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
  AnalysisTaskKind,
  AnalysisTaskStatus,
  AlertEvent,
  AlertRule,
  AlertRuleType,
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
  CreatedApiToken,
  EnsembleResp,
  FactorResearchResp,
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
  LLMConfigResp,
  LLMConnectionTestResp,
  LLMSettingsUpdate,
  PositionDecisionContext,
  MarketBreadthResp,
  NewsAnalyzeResp,
  NewsHealthResp,
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
  RunRecord,
  RunResp,
  SignalLifecycleStatus,
  SignalResp,
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
    getJSON<{ ok: boolean; export_version: string; exported_at: number; run: ResearchRun }>(
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
    },
  ) =>
    getJSON<{ ok: boolean; run: ResearchRun }>(`/research/runs/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
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
    signal_id?: string
    symbol?: string
    market?: string
    side?: 'buy' | 'sell'
    order_type?: 'market' | 'limit'
    quantity: number
    limit_price?: number
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

  cancelSimulationOrder: (id: string) =>
    getJSON<{ ok: boolean; order: SimulationOrder }>(
      `/simulation/orders/${encodeURIComponent(id)}/cancel`,
      { method: 'POST' },
    ),

  simulationAccount: () => getJSON<SimulationAccount>('/simulation/account'),

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
  resetHoldings: () =>
    getJSON<{ ok: boolean; holdings: HoldingCRUDResp[] }>('/portfolio/holdings/reset', { method: 'POST' }),

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
  }) => getJSON<FactorResearchResp>('/factor-research/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }),

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

  // ---- Instrument 标的主数据 ----
  instruments: (q = '', limit = 50, market?: string) => {
    const params = new URLSearchParams({ q, limit: String(limit) })
    if (market) params.set('market', market)
    return getJSON<{ count: number; instruments: Instrument[] }>(`/instruments?${params.toString()}`)
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

  previewSimulationOrder: (signalId: string, quantity: number) =>
    getJSON<{ ok: boolean; preview: SimulationOrderPreview }>('/simulation/orders/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ signal_id: signalId, quantity }),
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

  // ---- G8 新闻结构化分析（Phase 1：本地 LM Studio）----
  newsHealth: () => getJSON<NewsHealthResp>('/news/health'),

  newsAnalyze: (
    symbol: string,
    limit = 20,
    market = 'a_shares',
    useApi = true,
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
        use_api: useApi,
        research_run_id: researchRunId,
      }),
    }),
}
