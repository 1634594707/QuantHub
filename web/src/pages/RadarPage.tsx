import { useMemo, useState } from 'react'
import { api } from '../api/client'
import { useApi } from '../api/useApi'
import type { QuoteResp, SignalResp } from '../api/types'
import { WorkspaceHeader } from '../components/WorkspaceHeader/WorkspaceHeader'

const DIR_FROM_SIGNAL: Record<string, 'up' | 'down' | 'flat'> = {
  buy: 'up',
  sell: 'down',
  hold: 'flat',
}
const DIR_LABEL: Record<'up' | 'down' | 'flat', string> = {
  up: '预期上行',
  down: '预期下行',
  flat: '观望',
}

type PoolItem = { sym: string; name: string; market: string }

function instrumentKey(market: string, symbol: string) {
  return `${market.trim().toLowerCase()}:${symbol.trim().toUpperCase()}`
}

function formatTime(value: string | number | null | undefined) {
  if (value == null) return '时间未知'
  const date = new Date(typeof value === 'number' ? value * 1000 : value)
  if (Number.isNaN(date.getTime())) return '时间未知'
  return date.toLocaleString('zh-CN', { hour12: false })
}

function clamp(value: number) {
  return Math.max(0, Math.min(1, value))
}

function RadarDonut({ pct, color }: { pct: number; color: string }) {
  const radius = 52
  const centerX = 64
  const centerY = 62
  const length = Math.PI * radius
  const dash = length * clamp(pct)
  return (
    <svg width="128" height="74" viewBox="0 0 128 74" role="img" aria-label={`把握度 ${Math.round(pct * 100)}%`}>
      <path d={`M ${centerX - radius} ${centerY} A ${radius} ${radius} 0 0 1 ${centerX + radius} ${centerY}`} fill="none" stroke="var(--border-strong)" strokeWidth="12" strokeLinecap="round" />
      <path d={`M ${centerX - radius} ${centerY} A ${radius} ${radius} 0 0 1 ${centerX + radius} ${centerY}`} fill="none" stroke={color} strokeWidth="12" strokeLinecap="round" strokeDasharray={`${dash} ${length}`} />
      <text x={centerX} y={centerY - 6} textAnchor="middle" fontSize="20" fontWeight="800" fontFamily="var(--font-mono)" fill={color}>
        {Math.round(pct * 100)}%
      </text>
      <text x={centerX} y={centerY + 11} textAnchor="middle" fontSize="9" fill="var(--text-3)">
        把握度
      </text>
    </svg>
  )
}

async function loadQuotes(pool: PoolItem[]): Promise<QuoteResp[]> {
  return Promise.all(pool.map(async (item) => {
    try {
      return await api.quote(item.sym, item.market)
    } catch (error) {
      return {
        sym: item.sym,
        name: item.name,
        market: item.market,
        price: null,
        chgPct: null,
        available: false,
        source: 'api-gateway',
        observed_at: new Date().toISOString(),
        freshness: 'unavailable',
        status: 'unavailable',
        error: error instanceof Error ? error.message : String(error),
      }
    }
  }))
}

export default function RadarPage() {
  const [selectedSource, setSelectedSource] = useState('all')
  const signals = useApi(() => api.radarSignals(), [])
  const watchlist = useApi(() => api.watchlist(), [])
  const favorites = useApi(() => api.researchRuns(undefined, undefined, 100, true), [])

  const pool = useMemo(() => {
    const items = new Map<string, PoolItem>()
    const add = (sym: string, name: string | undefined, market: string) => {
      if (!sym) return
      const normalizedSymbol = sym.toUpperCase()
      const normalizedMarket = market || 'a_shares'
      const key = instrumentKey(normalizedMarket, normalizedSymbol)
      if (!items.has(key)) {
        items.set(key, {
          sym: normalizedSymbol,
          name: name?.trim() || normalizedSymbol,
          market: normalizedMarket,
        })
      }
    }
    for (const item of watchlist.data?.items ?? []) add(item.sym, item.name, item.market ?? 'a_shares')
    for (const run of favorites.data?.runs ?? []) add(run.symbol, undefined, run.market)
    return Array.from(items.values())
  }, [watchlist.data, favorites.data])

  const poolKey = pool.map((item) => instrumentKey(item.market, item.sym)).join(',')
  const quotes = useApi(() => loadQuotes(pool), [poolKey], { resetKey: poolKey })

  const sourceDistribution = useMemo(() => {
    const counts = new Map<string, number>()
    for (const signal of signals.data?.signals ?? []) {
      counts.set(signal.source, (counts.get(signal.source) ?? 0) + 1)
    }
    return Array.from(counts.entries()).sort((left, right) => right[1] - left[1])
  }, [signals.data])

  const signalMap = useMemo(() => {
    const byInstrument = new Map<string, SignalResp>()
    for (const signal of signals.data?.signals ?? []) {
      if (selectedSource !== 'all' && signal.source !== selectedSource) continue
      const key = instrumentKey(signal.market, signal.symbol)
      if (!byInstrument.has(key)) byInstrument.set(key, signal)
    }
    return byInstrument
  }, [selectedSource, signals.data])

  const cards = pool.map((item, index) => {
    const quote = quotes.data?.[index]
    const signal = signals.error ? undefined : signalMap.get(instrumentKey(item.market, item.sym))
    const expired = signal?.radar_state === 'expired'
    const currentSignal = signal && !expired ? signal : undefined
    const direction = currentSignal ? (DIR_FROM_SIGNAL[currentSignal.direction] ?? 'flat') : 'flat'
    const color = direction === 'up' ? 'var(--up)' : direction === 'down' ? 'var(--down)' : 'var(--text-3)'
    return { item, quote, signal, expired, currentSignal, direction, color }
  })

  const availableQuotes = cards.filter((card) => card.quote?.available).length
  const currentSignals = cards.filter((card) => card.currentSignal).length
  const expiredSignals = cards.filter((card) => card.expired).length
  const loading = (watchlist.loading || favorites.loading || quotes.loading) && pool.length === 0
  const quoteSources = Array.from(new Set(cards.map((card) => card.quote?.source).filter(Boolean))).join(' · ')

  return (
    <div className="rm-page" data-board="radar">
      <WorkspaceHeader
        context="研究 · 信号雷达"
        title="标的信号雷达"
        description="核验自选与研究收藏标的的报价、最新有效信号及缺失原因。"
        metrics={[
          { label: '监控标的', value: pool.length },
          { label: '可用报价', value: availableQuotes },
          { label: '当前信号', value: currentSignals },
          { label: '过期信号', value: expiredSignals },
        ]}
      />

      <div className="rm-toolbar" aria-label="雷达数据来源">
        <span className="rm-source-tag live">报价源：{quoteSources || '等待响应'}</span>
        <span className="rm-source-tag">信号快照：{formatTime(signals.data?.generated_at)}</span>
        {signals.reconnecting ? <span className="rm-source-tag rm-source-pending">信号服务重连中</span> : null}
      </div>

      {sourceDistribution.length > 0 ? (
        <label className="rm-source-select">
          <span>信号来源</span>
          <select value={selectedSource} onChange={(event) => setSelectedSource(event.target.value)}>
            <option value="all">全部来源 · {signals.data?.count ?? 0}</option>
            {sourceDistribution.map(([source, count]) => (
              <option key={source} value={source}>{source} · {count}</option>
            ))}
          </select>
        </label>
      ) : null}

      {signals.error ? (
        <div className="rm-state-banner error" role="alert">
          <div><strong>信号服务失败</strong><span>{signals.error}</span></div>
          <button type="button" onClick={signals.refetch}>重试信号</button>
        </div>
      ) : null}

      {loading ? (
        <div className="radar-grid" aria-label="雷达加载中">
          {Array.from({ length: 6 }).map((_, index) => <div key={index} className="radar-skeleton" />)}
        </div>
      ) : pool.length === 0 ? (
        <div className="rm-empty">
          <div className="rm-empty-title">雷达池尚无标的</div>
          <div className="rm-empty-desc">在总览加入自选，或收藏一次标的研究运行后，雷达会开始核验对应报价与信号。</div>
        </div>
      ) : (
        <div className="radar-grid">
          {cards.map(({ item, quote, signal, expired, currentSignal, direction, color }) => {
            const cardState = !quote?.available
              ? 'quote-error'
              : signals.error
                ? 'signal-error'
                : expired
                  ? 'expired-signal'
                  : currentSignal
                    ? 'has-signal'
                    : 'quote-only'
            return (
              <article key={instrumentKey(item.market, item.sym)} className={`radar-card ${cardState}`}>
                <div className="radar-card-head">
                  <div>
                    <div className="radar-sym">{item.sym}</div>
                    <div className="radar-name">{quote?.name || item.name} · {item.market}</div>
                  </div>
                  <div className={`radar-chg ${quote?.available ? (Number(quote.chgPct) > 0 ? 'up' : Number(quote.chgPct) < 0 ? 'down' : 'flat') : 'flat'}`}>
                    {quote?.available && typeof quote.chgPct === 'number' ? `${quote.chgPct > 0 ? '+' : ''}${quote.chgPct.toFixed(2)}%` : '报价不可用'}
                  </div>
                </div>

                {!quote?.available ? (
                  <div className="radar-state-detail error">
                    <strong>报价不可用</strong>
                    <span>{quote?.source || '行情网关'} · {quote?.error || '未返回失败原因'}</span>
                    <button type="button" onClick={quotes.refetch}>重试报价</button>
                  </div>
                ) : currentSignal ? (
                  <>
                    <div className="radar-donut-wrap"><RadarDonut pct={currentSignal.confidence} color={color} /></div>
                    <dl className="radar-meta">
                      <dt>方向</dt><dd className={direction}>{DIR_LABEL[direction]}</dd>
                      <dt>把握度</dt><dd>{Math.round(currentSignal.confidence * 100)}%</dd>
                      <dt>来源</dt><dd>{currentSignal.source}</dd>
                      <dt>信号时间</dt><dd>{formatTime(currentSignal.ts)}</dd>
                    </dl>
                  </>
                ) : expired && signal ? (
                  <div className="radar-state-detail stale">
                    <strong>信号已过期</strong>
                    <span>最后信号：{formatTime(signal.ts)}</span>
                    <span>失效时间：{formatTime(signal.expires_at)}</span>
                    <span>来源：{signal.source} · ID {signal.id || '未知'}</span>
                  </div>
                ) : signals.error ? (
                  <div className="radar-state-detail error">
                    <strong>信号服务失败</strong>
                    <span>报价仍可用；当前不展示缓存信号。</span>
                  </div>
                ) : (
                  <div className="radar-state-detail quote-only">
                    <strong>仅实时报价</strong>
                    <span>当前没有符合生命周期要求的信号。</span>
                  </div>
                )}

                <div className="radar-note">
                  报价：{quote?.source || '未知来源'} · {formatTime(quote?.observed_at)}
                  {currentSignal ? <> · 信号 ID <code>{currentSignal.id || '未知'}</code></> : null}
                </div>
              </article>
            )
          })}
        </div>
      )}
    </div>
  )
}
