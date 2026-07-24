import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { useApi } from '../api/useApi'
import type { StrategyInfo } from '../api/types'
import { useStrategyRuns } from '../hooks/useStrategyRuns'
import { marketBadge, marketKey, defaultParams } from '../components/StrategyShared'
import { formatRelativeTime } from '../lib/time'

type MarketKey = 'a_shares' | 'crypto' | 'us_stocks' | 'other'

const GROUPS: { key: MarketKey | 'all'; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'a_shares', label: 'A股' },
  { key: 'crypto', label: '加密货币' },
  { key: 'us_stocks', label: '美股' },
  { key: 'other', label: '其他' },
]

export default function StrategiesPage() {
  const navigate = useNavigate()
  const strategies = useApi(() => api.strategies(), [])
  const { lastRun, addRun } = useStrategyRuns()
  const [filter, setFilter] = useState<MarketKey | 'all'>('all')
  const [liveOnly, setLiveOnly] = useState(false)
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState<'default' | 'name' | 'recent'>('default')
  const [running, setRunning] = useState<Set<string>>(new Set())

  const list = strategies.data?.strategies ?? []

  const filtered = useMemo(() => {
    let out = list
    if (filter !== 'all') out = out.filter((st) => marketKey(st.market) === filter)
    if (liveOnly) out = out.filter((st) => st.live_capable)
    const q = search.trim().toLowerCase()
    if (q) {
      out = out.filter(
        (st) =>
          st.name.toLowerCase().includes(q) || st.description.toLowerCase().includes(q),
      )
    }
    if (sort === 'name') return [...out].sort((a, b) => a.name.localeCompare(b.name))
    if (sort === 'recent') {
      return [...out].sort((a, b) => {
        const ta = new Date(lastRun(a.name)?.ts ?? 0).getTime()
        const tb = new Date(lastRun(b.name)?.ts ?? 0).getTime()
        return tb - ta
      })
    }
    return out
  }, [list, filter, liveOnly, search, sort, lastRun])

  const grouped = useMemo<Record<MarketKey | '', StrategyInfo[]>>(() => {
    if (filter !== 'all' || search.trim()) return { '': filtered } as Record<MarketKey | '', StrategyInfo[]>
    const map: Record<MarketKey, StrategyInfo[]> = {
      a_shares: [],
      crypto: [],
      us_stocks: [],
      other: [],
    }
    filtered.forEach((st) => map[marketKey(st.market)].push(st))
    return map as Record<MarketKey | '', StrategyInfo[]>
  }, [filtered, filter, search])

  async function handleQuickRun(e: React.MouseEvent, name: string) {
    e.stopPropagation()
    setRunning((prev) => new Set([...prev, name]))
    try {
      const params = defaultParams(name)
      const resp = await api.runStrategy(name, params)
      addRun(name, params, resp)
    } finally {
      setRunning((prev) => {
        const n = new Set(prev)
        n.delete(name)
        return n
      })
    }
  }

  return (
    <div className="card">
      <div className="card-head">
        <div className="card-title">
          策略模块
          <span className="sub">已注册 · 共 {list.length} 个</span>
        </div>
        <button className="link-btn" onClick={() => strategies.refetch()} disabled={strategies.loading}>
          {strategies.loading ? '刷新中…' : '刷新'}
        </button>
      </div>

      <div style={{ padding: 'var(--sp-3)' }}>
        {/* 工具栏 */}
        <div className="strategy-toolbar">
          <input
            className="edit-input"
            style={{ minWidth: 180, maxWidth: 280 }}
            placeholder="搜索策略名称或描述…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <div style={{ display: 'flex', gap: 'var(--sp-2)', flexWrap: 'wrap' }}>
            {GROUPS.map((g) => {
              const count = g.key === 'all' ? list.length : list.filter((s) => marketKey(s.market) === g.key).length
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
                  <span style={{ marginLeft: '6px', opacity: 0.75, fontSize: 'var(--fs-12)' }}>{count}</span>
                </button>
              )
            })}
          </div>
          <div style={{ display: 'flex', gap: 'var(--sp-2)', alignItems: 'center', flexWrap: 'wrap' }}>
            <label className="toggle-label">
              <input
                type="checkbox"
                checked={liveOnly}
                onChange={(e) => setLiveOnly(e.target.checked)}
              />
              仅可实盘
            </label>
            <select
              className="edit-input"
              style={{ width: 110, flex: '0 0 auto' }}
              value={sort}
              onChange={(e) => setSort(e.target.value as typeof sort)}
            >
              <option value="default">默认排序</option>
              <option value="name">按名称</option>
              <option value="recent">最近运行</option>
            </select>
          </div>
        </div>

        {filtered.length === 0 && (
          <div className="muted" style={{ textAlign: 'center', padding: 'var(--sp-5)' }}>
            {strategies.loading ? '加载中…' : '没有匹配的策略'}
          </div>
        )}

        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-4)' }}>
          {(Object.keys(grouped) as (MarketKey | '')[])
            .filter((k) => grouped[k].length > 0)
            .map((key) => (
              <section key={key || 'results'}>
                {filter === 'all' && !search.trim() && (
                  <div className="strategy-group-title">
                    {GROUPS.find((g) => g.key === key)?.label}
                    <span className="sub" style={{ fontWeight: 400 }}>
                      {grouped[key].length} 个
                    </span>
                  </div>
                )}
                <div className="strategy-grid">
                  {grouped[key].map((st) => (
                    <StrategyCard
                      key={st.name}
                      st={st}
                      last={lastRun(st.name)}
                      running={running.has(st.name)}
                      onClick={() => navigate(`/strategies/${st.name}`)}
                      onRun={(e) => handleQuickRun(e, st.name)}
                    />
                  ))}
                </div>
              </section>
            ))}
        </div>
      </div>
    </div>
  )
}

function StrategyCard({
  st,
  last,
  running,
  onClick,
  onRun,
}: {
  st: StrategyInfo
  last?: { result: { ok: boolean; count: number; error?: string }; ts: string }
  running: boolean
  onClick: () => void
  onRun: (e: React.MouseEvent) => void
}) {
  const recent = last
    ? last.result.ok
      ? `最近运行 ${last.result.count} 条信号 · ${formatRelativeTime(last.ts)}`
      : `最近运行失败 · ${formatRelativeTime(last.ts)}`
    : '未运行过'

  return (
    <div className="strategy-card" onClick={onClick}>
      <div className="strategy-card-head">
        <div className="strategy-card-title">
          <span>{st.name}</span>
          <span className="strategy-card-badge market">{marketBadge(st.market)}</span>
          {st.live_capable && <span className="strategy-card-badge live">可实盘</span>}
        </div>
      </div>
      <p className="strategy-card-desc">{st.description || '暂无描述'}</p>
      <div className="strategy-card-foot">
        <span className={`strategy-card-status ${last ? (last.result.ok ? 'ok' : 'err') : 'muted'}`}>
          {recent}
        </span>
        <div style={{ display: 'flex', gap: 'var(--sp-2)', marginTop: 'auto', paddingTop: 'var(--sp-2)' }}>
          <button
            className="period-tab"
            onClick={onRun}
            disabled={running}
            style={{ background: 'var(--accent)', color: '#fff' }}
          >
            {running ? '运行中…' : '快速运行'}
          </button>
          <button className="link-btn">详情 →</button>
        </div>
      </div>
    </div>
  )
}
