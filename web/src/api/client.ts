// QuantHub 前端 API 客户端。
// 统一收口对后端网关（apps/api，默认 http://localhost:8000）的调用，
// 所有组件经此层取数，便于统一错误处理、降级与换 Base URL。
//
// 切换后端地址：在 web/.env 设置 VITE_API_BASE=http://your-host:8000
// （网关已放开 CORS，浏览器可跨端口直连）。

import type {
  ApiKeyResp,
  HealthResp,
  KlineResp,
  MarketBreadthResp,
  PaAnalyzeResp,
  PortfolioResp,
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

  signals: (limit = 50) => getJSON<SignalsResp>(`/signals?limit=${limit}`),

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

  getApiKey: () => getJSON<ApiKeyResp>('/config/apikey'),

  setApiKey: (apiKey: string) =>
    getJSON<ApiKeyResp>('/config/apikey', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key: apiKey }),
    }),
}
