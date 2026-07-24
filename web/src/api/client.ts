// QuantHub 前端 API 客户端。
// 统一收口对后端网关（apps/api，默认 http://localhost:8000）的调用，
// 所有组件经此层取数，便于统一错误处理、降级与换 Base URL。
//
// 切换后端地址：在 web/.env 设置 VITE_API_BASE=http://your-host:8000
// （网关已放开 CORS，浏览器可跨端口直连）。

import type {
  ApiKeyResp,
  BacktestResp,
  HealthResp,
  KlineResp,
  LiveResp,
  MarketBreadthResp,
  PaAnalyzeResp,
  PortfolioManageResp,
  PortfolioResp,
  Preset,
  QuoteResp,
  RunRecord,
  RunResp,
  SignalsResp,
  StrategiesResp,
  WatchlistResp,
} from './types'

const BASE: string =
  (import.meta.env.VITE_API_BASE as string | undefined) || 'http://localhost:8000'

async function getJSON<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, init)
  } catch (e) {
    // 网络层失败（后端未启动等）→ 抛出可被 useApi 捕获的错误
    throw new Error(`无法连接网关 (${BASE})：${e instanceof Error ? e.message : String(e)}`)
  }
  if (!res.ok) {
    let detail = ''
    try {
      const j = (await res.json()) as { detail?: string; error?: string }
      detail = j.detail || j.error || ''
    } catch {
      /* 忽略解析失败 */
    }
    throw new Error(`请求失败 ${res.status}${detail ? ' · ' + detail : ''}`)
  }
  return (await res.json()) as T
}

export const api = {
  base: BASE,

  health: () => getJSON<HealthResp>('/health'),

  strategies: () => getJSON<StrategiesResp>('/strategies'),

  signals: (limit = 50, source?: string) => {
    const p = new URLSearchParams({ limit: String(limit) })
    if (source) p.set('source', source)
    return getJSON<SignalsResp>(`/signals?${p.toString()}`)
  },

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

  analyzePa: (symbol: string, timeframe = '1h', market?: string) =>
    getJSON<PaAnalyzeResp>(
      `/strategies/pa_agent/analyze?symbol=${encodeURIComponent(symbol)}` +
        `&timeframe=${encodeURIComponent(timeframe)}` +
        (market ? `&market=${encodeURIComponent(market)}` : ''),
      { method: 'POST' },
    ),

  portfolio: () => getJSON<PortfolioResp>('/portfolio'),

  marketBreadth: () => getJSON<MarketBreadthResp>('/market/breadth'),

  watchlist: () => getJSON<WatchlistResp>('/market/watchlist'),

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

  getApiKey: () => getJSON<ApiKeyResp>('/config/apikey'),

  setApiKey: (apiKey: string) =>
    getJSON<ApiKeyResp>('/config/apikey', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key: apiKey }),
    }),
}
