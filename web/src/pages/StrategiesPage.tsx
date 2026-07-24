import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import { useApi } from '../api/useApi'
import type { RunResp, SignalResp, StrategyInfo } from '../api/types'

type MarketKey = 'a_shares' | 'crypto' | 'us_stocks' | 'other'

function marketKey(m: string): MarketKey {
  if (m === 'a_shares' || m === 'crypto' || m === 'us_stocks') return m
  return 'other'
}

function marketBadge(m: StrategyInfo['market']) {
  if (m === 'a_shares') return 'A股'
  if (m === 'crypto') return '加密货币'
  if (m === 'us_stocks') return '美股'
  return m
}

const GROUPS: { key: MarketKey | 'all'; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'a_shares', label: 'A股' },
  { key: 'crypto', label: '加密货币' },
  { key: 'us_stocks', label: '美股' },
  { key: 'other', label: '其他' },
]

function defaultParams(name: string): Record<string, unknown> {
  const map: Record<string, Record<string, unknown>> = {
    sentiment: { symbols: ['300750'], news_limit: 10 },
    selector: { universe: 'hs300', top_n: 5 },
    supertrend: { symbols: ['600519'], timeframe: 'daily' },
    realtime_analyzer: { symbols: ['600519'], with_kline: true, with_indices: true },
    morning_brief: { symbols: ['600519', '000001'] },
    perks_monitor: {},
    news_scanner: {},
    pa_agent: { symbol: '600519', timeframe: '1h' },
    okx_grid: { symbol: 'BTC-USDT-SWAP' },
    alphagpt: { symbol: 'BTC-USDT-SWAP' },
    alphamaster: {},
  }
  return map[name] ?? {}
}

function directionColor(d: string) {
  if (d === 'buy' || d === '做多' || d === 'bullish') return 'var(--up-ink)'
  if (d === 'sell' || d === '做空' || d === 'bearish') return 'var(--down-ink)'
  return 'var(--text-2)'
}

export default function StrategiesPage() {
  const strategies = useApi(() => api.strategies(), [])
  const [selected, setSelected] = useState<StrategyInfo | null>(null)
  const [params, setParams] = useState<Record<string, unknown>>({})
  const [runResult, setRunResult] = useState<RunResp | null>(null)
  const [running, setRunning] = useState(false)
  const [runError, setRunError] = useState('')
  const [filter, setFilter] = useState<MarketKey | 'all'>('all')

  const list = strategies.data?.strategies ?? []

  const grouped = useMemo(() => {
    const map: Record<MarketKey, StrategyInfo[]> = {
      a_shares: [],
      crypto: [],
      us_stocks: [],
      other: [],
    }
    list.forEach((st) => map[marketKey(st.market)].push(st))
    return map
  }, [list])

  const visibleGroups = useMemo(() => {
    if (filter === 'all') return (Object.keys(grouped) as MarketKey[]).filter((k) => grouped[k].length > 0)
    return grouped[filter].length > 0 ? [filter] : []
  }, [filter, grouped])

  function openStrategy(st: StrategyInfo) {
    setSelected(st)
    setParams(defaultParams(st.name))
    setRunResult(null)
    setRunError('')
  }

  async function handleRun(name: string) {
    setRunning(true)
    setRunError('')
    setRunResult(null)
    try {
      const resp = await api.runStrategy(name, params)
      setRunResult(resp)
    } catch (err) {
      setRunError(err instanceof Error ? err.message : '运行失败')
    } finally {
      setRunning(false)
    }
  }

  function closeDrawer() {
    setSelected(null)
    setRunResult(null)
    setRunError('')
  }

  return (
    <div className="card">
      <div className="card-head">
        <div className="card-title">
          策略模块
          <span className="sub">已注册 · 共 {list.length} 个</span>
        </div>
        <button
          className="link-btn"
          onClick={() => strategies.refetch()}
          disabled={strategies.loading}
        >
          {strategies.loading ? '刷新中…' : '刷新'}
        </button>
      </div>

      <div style={{ padding: 'var(--sp-3)' }}>
        <div
          style={{
            display: 'flex',
            gap: 'var(--sp-2)',
            marginBottom: 'var(--sp-3)',
            flexWrap: 'wrap',
          }}
        >
          {GROUPS.map((g) => {
            const count = g.key === 'all' ? list.length : grouped[g.key].length
            const active = filter === g.key
            return (
              <button
                key={g.key}
                onClick={() => setFilter(g.key)}
                className="period-tab"
                style={{
                  background: active ? 'var(--accent)' : 'var(--bg-subtle)',
                  color: active ? '#fff' : 'var(--text-1)',
                  border: active ? '1px solid var(--accent)' : '1px solid var(--border)',
                }}
              >
                {g.label}
                <span
                  style={{
                    marginLeft: '6px',
                    opacity: 0.75,
                    fontSize: 'var(--fs-12)',
                  }}
                >
                  {count}
                </span>
              </button>
            )
          })}
        </div>

        {visibleGroups.length === 0 && (
          <div className="muted" style={{ textAlign: 'center', padding: 'var(--sp-5)' }}>
            {strategies.loading ? '加载中…' : '该分类下暂无策略'}
          </div>
        )}

        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-4)' }}>
          {visibleGroups.map((key) => (
            <section key={key}>
              {filter === 'all' && (
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 'var(--sp-2)',
                    marginBottom: 'var(--sp-2)',
                    fontWeight: 600,
                    fontSize: 'var(--fs-14)',
                    color: 'var(--text-1)',
                  }}
                >
                  {GROUPS.find((g) => g.key === key)?.label}
                  <span className="sub" style={{ fontWeight: 400 }}>
                    {grouped[key].length} 个
                  </span>
                </div>
              )}
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
                  gap: 'var(--sp-3)',
                }}
              >
                {grouped[key].map((st) => (
                  <StrategyCard key={st.name} st={st} onClick={() => openStrategy(st)} />
                ))}
              </div>
            </section>
          ))}
        </div>
      </div>

      {selected && (
        <div
          onClick={closeDrawer}
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.35)',
            zIndex: 100,
            display: 'flex',
            justifyContent: 'flex-end',
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              width: 'min(480px, 90vw)',
              height: '100%',
              background: 'var(--bg-elevated)',
              borderLeft: '1px solid var(--border)',
              padding: 'var(--sp-4)',
              display: 'flex',
              flexDirection: 'column',
              gap: 'var(--sp-4)',
              overflowY: 'auto',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
              <div>
                <h3 style={{ margin: 0, fontSize: 'var(--fs-18)', fontWeight: 700 }}>{selected.name}</h3>
                <div style={{ display: 'flex', gap: 'var(--sp-2)', marginTop: 'var(--sp-2)' }}>
                  <span
                    style={{
                      fontSize: 'var(--fs-12)',
                      padding: '2px 8px',
                      borderRadius: 'var(--r-pill)',
                      background: 'var(--accent-weak)',
                      color: 'var(--accent-strong)',
                    }}
                  >
                    {marketBadge(selected.market)}
                  </span>
                  {selected.live_capable && (
                    <span
                      style={{
                        fontSize: 'var(--fs-12)',
                        padding: '2px 8px',
                        borderRadius: 'var(--r-pill)',
                        background: 'rgba(22,199,132,0.14)',
                        color: 'var(--up-ink)',
                      }}
                    >
                      可实盘
                    </span>
                  )}
                </div>
              </div>
              <button
                onClick={closeDrawer}
                style={{
                  background: 'none',
                  border: 'none',
                  color: 'var(--text-2)',
                  fontSize: 'var(--fs-18)',
                  cursor: 'pointer',
                }}
              >
                ✕
              </button>
            </div>

            <p style={{ margin: 0, color: 'var(--text-2)', fontSize: 'var(--fs-14)', lineHeight: 1.6 }}>
              {selected.description || '暂无描述'}
            </p>

            <ParamsEditor name={selected.name} params={params} onChange={setParams} />

            <div>
              <button
                className="period-tab"
                onClick={() => handleRun(selected.name)}
                disabled={running}
                style={{
                  background: 'var(--accent)',
                  color: '#fff',
                  opacity: running ? 0.7 : 1,
                }}
              >
                {running ? '运行中…' : '运行策略'}
              </button>
            </div>

            {runError && (
              <div style={{ color: 'var(--down-ink)', fontSize: 'var(--fs-13)' }}>{runError}</div>
            )}

            {runResult && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-3)' }}>
                <div style={{ fontSize: 'var(--fs-14)', fontWeight: 600 }}>
                  运行结果
                  <span className="sub" style={{ marginLeft: 'var(--sp-2)' }}>
                    {runResult.ok ? `产出 ${runResult.count} 条信号` : '失败'}
                  </span>
                </div>
                {!runResult.ok && runResult.error && (
                  <div style={{ color: 'var(--down-ink)', fontSize: 'var(--fs-13)' }}>{runResult.error}</div>
                )}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-2)' }}>
                  {runResult.signals.map((sig, idx) => (
                    <SignalRow key={`${sig.symbol}-${idx}`} sig={sig} />
                  ))}
                  {runResult.signals.length === 0 && (
                    <div className="muted" style={{ fontSize: 'var(--fs-13)' }}>未产出信号</div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function ParamsEditor({
  name,
  params,
  onChange,
}: {
  name: string
  params: Record<string, unknown>
  onChange: (p: Record<string, unknown>) => void
}) {
  const [jsonText, setJsonText] = useState(() => JSON.stringify(params, null, 2))
  const [jsonError, setJsonError] = useState('')

  // 当切换策略时同步外部 params；用户编辑过程中不再反向覆盖
  useEffect(() => {
    setJsonText(JSON.stringify(params, null, 2))
    setJsonError('')
  }, [name])

  if (name === 'sentiment') {
    const symbols = Array.isArray(params.symbols) ? (params.symbols as string[]).join(', ') : ''
    const newsLimit = typeof params.news_limit === 'number' ? params.news_limit : 10
    return (
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 'var(--sp-3)',
          padding: 'var(--sp-3)',
          borderRadius: 'var(--r-md)',
          border: '1px solid var(--border)',
          background: 'var(--bg-subtle)',
        }}
      >
        <div style={{ fontSize: 'var(--fs-14)', fontWeight: 600 }}>运行参数</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-1)' }}>
          <label style={{ fontSize: 'var(--fs-12)', color: 'var(--text-2)' }}>股票代码（逗号分隔）</label>
          <input
            type="text"
            value={symbols}
            onChange={(e) => {
              const codes = e.target.value
                .split(/[,，]/)
                .map((s) => s.trim())
                .filter(Boolean)
              onChange({ ...params, symbols: codes })
            }}
            style={{
              padding: 'var(--sp-2)',
              borderRadius: 'var(--r-sm)',
              border: '1px solid var(--border)',
              background: 'var(--bg-elevated)',
              color: 'var(--text-1)',
              fontSize: 'var(--fs-14)',
            }}
          />
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-1)' }}>
          <label style={{ fontSize: 'var(--fs-12)', color: 'var(--text-2)' }}>新闻条数</label>
          <input
            type="number"
            min={1}
            max={100}
            value={newsLimit}
            onChange={(e) => {
              const n = parseInt(e.target.value || '10', 10)
              onChange({ ...params, news_limit: Number.isNaN(n) ? 10 : n })
            }}
            style={{
              padding: 'var(--sp-2)',
              borderRadius: 'var(--r-sm)',
              border: '1px solid var(--border)',
              background: 'var(--bg-elevated)',
              color: 'var(--text-1)',
              fontSize: 'var(--fs-14)',
            }}
          />
        </div>
      </div>
    )
  }

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 'var(--sp-2)',
        padding: 'var(--sp-3)',
        borderRadius: 'var(--r-md)',
        border: '1px solid var(--border)',
        background: 'var(--bg-subtle)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ fontSize: 'var(--fs-14)', fontWeight: 600 }}>运行参数（JSON）</span>
        {jsonError && <span style={{ fontSize: 'var(--fs-12)', color: 'var(--down-ink)' }}>{jsonError}</span>}
      </div>
      <textarea
        value={jsonText}
        onChange={(e) => {
          setJsonText(e.target.value)
          try {
            const parsed = JSON.parse(e.target.value)
            if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
              onChange(parsed as Record<string, unknown>)
              setJsonError('')
            } else {
              setJsonError('参数必须是对象')
            }
          } catch {
            setJsonError('JSON 格式错误')
          }
        }}
        rows={6}
        style={{
          padding: 'var(--sp-2)',
          borderRadius: 'var(--r-sm)',
          border: `1px solid ${jsonError ? 'var(--down-ink)' : 'var(--border)'}`,
          background: 'var(--bg-elevated)',
          color: 'var(--text-1)',
          fontFamily: 'monospace',
          fontSize: 'var(--fs-13)',
          resize: 'vertical',
        }}
      />
    </div>
  )
}

function StrategyCard({ st, onClick }: { st: StrategyInfo; onClick: () => void }) {
  return (
    <div
      onClick={onClick}
      style={{
        padding: 'var(--sp-3)',
        borderRadius: 'var(--r-md)',
        border: '1px solid var(--border)',
        background: 'var(--bg-subtle)',
        display: 'flex',
        flexDirection: 'column',
        gap: 'var(--sp-2)',
        cursor: 'pointer',
        transition: 'transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.transform = 'translateY(-2px)'
        e.currentTarget.style.boxShadow = '0 8px 24px rgba(0,0,0,0.08)'
        e.currentTarget.style.borderColor = 'var(--accent)'
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.transform = 'none'
        e.currentTarget.style.boxShadow = 'none'
        e.currentTarget.style.borderColor = 'var(--border)'
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)' }}>
        <span style={{ fontWeight: 700, fontSize: 'var(--fs-15)' }}>{st.name}</span>
        <span
          style={{
            fontSize: 'var(--fs-12)',
            padding: '2px 8px',
            borderRadius: 'var(--r-pill)',
            background: 'var(--accent-weak)',
            color: 'var(--accent-strong)',
          }}
        >
          {marketBadge(st.market)}
        </span>
        {st.live_capable && (
          <span
            style={{
              fontSize: 'var(--fs-12)',
              padding: '2px 8px',
              borderRadius: 'var(--r-pill)',
              background: 'rgba(22,199,132,0.14)',
              color: 'var(--up-ink)',
            }}
          >
            可实盘
          </span>
        )}
      </div>
      <p style={{ margin: 0, color: 'var(--text-2)', fontSize: 'var(--fs-13)', lineHeight: 1.5 }}>
        {st.description || '暂无描述'}
      </p>
      <div style={{ marginTop: 'auto', paddingTop: 'var(--sp-2)', fontSize: 'var(--fs-12)', color: 'var(--accent)' }}>
        点击查看详情与运行 →
      </div>
    </div>
  )
}

function SignalRow({ sig }: { sig: SignalResp }) {
  return (
    <div
      style={{
        padding: 'var(--sp-3)',
        borderRadius: 'var(--r-md)',
        border: '1px solid var(--border)',
        background: 'var(--bg-subtle)',
        display: 'flex',
        flexDirection: 'column',
        gap: '4px',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)', fontSize: 'var(--fs-14)', fontWeight: 600 }}>
        <span>{sig.symbol}</span>
        <span style={{ color: directionColor(sig.direction) }}>{sig.direction.toUpperCase()}</span>
        <span className="muted" style={{ fontSize: 'var(--fs-12)', marginLeft: 'auto' }}>score {sig.score.toFixed(2)}</span>
      </div>
      <div style={{ fontSize: 'var(--fs-12)', color: 'var(--text-2)' }}>
        {sig.market} · {sig.timeframe} · 置信度 {sig.confidence.toFixed(2)}
      </div>
      {sig.tags.length > 0 && (
        <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap', marginTop: '2px' }}>
          {sig.tags.map((t) => (
            <span
              key={t}
              style={{
                fontSize: 'var(--fs-11)',
                padding: '2px 6px',
                borderRadius: 'var(--r-pill)',
                background: 'var(--accent-weak)',
                color: 'var(--accent-strong)',
              }}
            >
              {t}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
