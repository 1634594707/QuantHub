// 后端 API 网关（apps/api，端口 8000）的类型契约。
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
}

export interface HealthResp {
  status: string
  time: string
  strategies: number
  live_trading: boolean
  version: string
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
}

export interface SignalsResp {
  count: number
  signals: SignalResp[]
}

export interface RunResp {
  ok: boolean
  name: string
  count: number
  signals: SignalResp[]
  error?: string
}

// ---------- PA 分析视图模型（来自 pa_agent.view_models） ----------

export interface PaAnalyzeResp {
  ok: boolean
  symbol: string
  timeframe: string
  market: string
  error?: string
  decision: DecisionView
  future: FutureTrendView
  tree: DecisionTreeView
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
  winRate: number
  totalPositions: number
}

export interface PortfolioHolding {
  code: string
  name: string
  price: number
  chgPct: number
  shares: number
  pnl: number
  winRate: number
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

// ---------- 配置（API Key 等） ----------

export interface ApiKeyResp {
  ok: boolean
  configured: boolean
  provider: string
  key_env: string
  masked: string | null
}
