import { Fragment, useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import { useApi } from '../api/useApi'
import type { SignalResp } from '../api/types'
import { SignalRow } from '../components/StrategyShared'
import { DirectionDonut, ScoreHistogram, SourceBars } from '../components/SignalViz'
import { dirBucket, dirLabel, matchDir } from '../lib/signal-utils'

type Dir = 'all' | 'buy' | 'sell' | 'hold'
type View = 'table' | 'group'

function fmtTs(ts: string | null) {
  if (!ts) return '-'
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return ts
  return d.toLocaleString('zh-CN', { hour12: false })
}

function relTime(d: Date | null) {
  if (!d) return '—'
  const s = Math.floor((Date.now() - d.getTime()) / 1000)
  if (s < 60) return `${s} 秒前`
  if (s < 3600) return `${Math.floor(s / 60)} 分钟前`
  return `${Math.floor(s / 3600)} 小时前`
}

/** 方向 → CSS 类适配器（语义归一到 lib/signal-utils，呈现层映射为 long/short/hold）。 */
function dirClass(d: string): 'long' | 'short' | 'hold' {
  const b = dirBucket(d)
  return b === 'buy' ? 'long' : b === 'sell' ? 'short' : 'hold'
}

function csvEscape(v: string | number) {
  const s = String(v)
  return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s
}

function exportCsv(rows: SignalResp[]) {
  const headers = ['标的', '方向', '得分', '置信度', '周期', '市场', '来源', '标签', '时间']
  const lines = rows.map((s) =>
    [
      s.symbol,
      dirLabel(s.direction),
      s.score.toFixed(2),
      (s.confidence * 100).toFixed(1) + '%',
      s.timeframe,
      s.market,
      s.source,
      s.tags.join('|'),
      s.ts ?? '',
    ]
      .map(csvEscape)
      .join(','),
  )
  const csv = '﻿' + [headers.join(','), ...lines].join('\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `signals_${Date.now()}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

export default function SignalsPage() {
  const signals = useApi(() => api.signals(200), [])
  const rows = signals.data?.signals ?? []
  const isReal = signals.data != null

  // —— 更新空间：记录最后拉取时间，并为自动/增量刷新预留开关 ——
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  const [auto, setAuto] = useState(false)
  useEffect(() => {
    if (signals.data != null) setLastUpdated(new Date())
  }, [signals.data])

  const [q, setQ] = useState('')
  const [dir, setDir] = useState<Dir>('all')
  const [market, setMarket] = useState('all')
  const [source, setSource] = useState('all')
  const [minScore, setMinScore] = useState(0)
  const [view, setView] = useState<View>('table')
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [filling, setFilling] = useState(false)

  const markets = useMemo(
    () => Array.from(new Set(rows.map((r) => r.market))).sort(),
    [rows],
  )
  const sources = useMemo(
    () => Array.from(new Set(rows.map((r) => r.source))).sort(),
    [rows],
  )

  const filtered = useMemo(() => {
    const kw = q.trim().toLowerCase()
    return rows.filter((s) => {
      if (!matchDir(s.direction, dir)) return false
      if (market !== 'all' && s.market !== market) return false
      if (source !== 'all' && s.source !== source) return false
      if (s.score < minScore) return false
      if (kw) {
        const hay = (s.symbol + ' ' + s.tags.join(' ') + ' ' + s.source).toLowerCase()
        if (!hay.includes(kw)) return false
      }
      return true
    })
  }, [rows, dir, market, source, minScore, q])

  const agg = useMemo(() => {
    const buy = filtered.filter((s) => dirClass(s.direction) === 'long').length
    const sell = filtered.filter((s) => dirClass(s.direction) === 'short').length
    const hold = filtered.length - buy - sell
    const avgScore = filtered.length
      ? filtered.reduce((a, s) => a + s.score, 0) / filtered.length
      : 0
    const avgConf = filtered.length
      ? filtered.reduce((a, s) => a + s.confidence, 0) / filtered.length
      : 0
    const top = filtered.reduce<SignalResp | null>(
      (best, s) => (!best || s.score > best.score ? s : best),
      null,
    )
    return { buy, sell, hold, avgScore, avgConf, top }
  }, [filtered])

  const groups = useMemo(() => {
    const map = new Map<string, SignalResp[]>()
    filtered.forEach((s) => {
      if (!map.has(s.source)) map.set(s.source, [])
      map.get(s.source)!.push(s)
    })
    return Array.from(map.entries()).sort((a, b) => b[1].length - a[1].length)
  }, [filtered])

  const hasFilter =
    dir !== 'all' || market !== 'all' || source !== 'all' || minScore > 0 || q.trim() !== ''

  function toggleExpand(key: string) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  function clearFilters() {
    setQ('')
    setDir('all')
    setMarket('all')
    setSource('all')
    setMinScore(0)
  }

  function doRefresh() {
    void signals.refetch()
    // 预留：自动刷新 interval / WebSocket 增量推送可在此挂接，
    // 当前 auto 仅为 UI 占位，避免空数据下的无意义轮询。
  }

  // 开箱即用：运行真实策略 supertrend 把信号写入总线（与工作台同源），
  // 让信号中心首次打开即有数据可看，不必手动去工作台跑一遍。
  async function runDefaultScan() {
    setFilling(true)
    try {
      await api.runStrategy('supertrend', {})
    } catch {
      // 即便运行报错也继续刷新，避免卡在 loading
    } finally {
      await signals.refetch()
      setFilling(false)
    }
  }

  return (
    <div className="card" data-board="signals">
      <div className="card-head">
        <div className="card-title">
          信号中心
          <span className="sub">
            {isReal ? '实时' : '模拟'} · 共 {rows.length} 条 · 筛选后 {filtered.length} 条
          </span>
        </div>
        <div
          style={{ display: 'flex', gap: 'var(--sp-2)', alignItems: 'center', flexWrap: 'wrap' }}
        >
          <div className="seg" role="tablist" aria-label="视图切换">
            <button className={view === 'table' ? 'active' : ''} onClick={() => setView('table')}>
              表格
            </button>
            <button className={view === 'group' ? 'active' : ''} onClick={() => setView('group')}>
              分组
            </button>
          </div>
          <button className="link-btn" onClick={doRefresh} disabled={signals.loading}>
            {signals.loading ? '刷新中…' : '刷新'}
          </button>
          <button
            className="link-btn"
            onClick={() => exportCsv(filtered)}
            disabled={filtered.length === 0}
          >
            导出 CSV
          </button>
        </div>
      </div>

      {/* 更新状态栏：表达「信号是流动的」，为实时/增量刷新预留空间 */}
      <div className="update-bar">
        <span className="ub-dot" data-live={auto} />
        <span className="ub-text">最后更新 {relTime(lastUpdated)}</span>
        <label className="ub-toggle">
          <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
          <span>自动刷新</span>
        </label>
        <span className="ub-note">（实时 / 增量刷新接口预留）</span>
      </div>

      <div className="signals-layout">
        {/* 左：筛选栏 */}
        <aside className="signals-filters">
          <div className="filter-block">
            <label className="filter-label">搜索（标的 / 标签 / 来源）</label>
            <input
              className="filter-input"
              placeholder="如 600519、突破"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>
          <div className="filter-block">
            <span className="filter-label">方向</span>
            <div className="seg">
              {(
                [
                  ['all', '全部'],
                  ['buy', '做多'],
                  ['sell', '做空'],
                  ['hold', '观望'],
                ] as const
              ).map(([k, l]) => (
                <button key={k} className={dir === k ? 'active' : ''} onClick={() => setDir(k)}>
                  {l}
                </button>
              ))}
            </div>
          </div>
          <div className="filter-block">
            <label className="filter-label">市场</label>
            <select
              className="filter-select"
              value={market}
              onChange={(e) => setMarket(e.target.value)}
            >
              <option value="all">全部市场</option>
              {markets.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </div>
          <div className="filter-block">
            <label className="filter-label">来源策略</label>
            <select
              className="filter-select"
              value={source}
              onChange={(e) => setSource(e.target.value)}
            >
              <option value="all">全部来源</option>
              {sources.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
          <div className="filter-block">
            <label className="filter-label">最低得分 ≥ {minScore.toFixed(2)}</label>
            <input
              className="filter-input"
              type="number"
              min={0}
              max={1}
              step={0.05}
              value={minScore}
              onChange={(e) =>
                setMinScore(Math.max(0, Math.min(1, Number(e.target.value) || 0)))
              }
            />
          </div>
          <button
            className="link-btn"
            onClick={clearFilters}
            disabled={!hasFilter}
            style={{ alignSelf: 'flex-start' }}
          >
            清空筛选
          </button>
        </aside>

        {/* 右：主区 */}
        <div>
          {/* 聚合概览条 */}
          <div className="signals-agg">
            <div className="agg-chip">
              <span className="k">信号总数</span>
              <span className="v">{filtered.length}</span>
            </div>
            <div className="agg-chip long">
              <span className="k">做多</span>
              <span className="v">{agg.buy}</span>
            </div>
            <div className="agg-chip short">
              <span className="k">做空</span>
              <span className="v">{agg.sell}</span>
            </div>
            <div className="agg-chip">
              <span className="k">观望</span>
              <span className="v">{agg.hold}</span>
            </div>
            <div className="agg-chip accent">
              <span className="k">平均分数</span>
              <span className="v">{agg.avgScore.toFixed(2)}</span>
            </div>
            <div className="agg-chip accent">
              <span className="k">平均置信度</span>
              <span className="v">{(agg.avgConf * 100).toFixed(0)}%</span>
            </div>
            <div className="agg-chip">
              <span className="k">最高分</span>
              <span className="v" style={{ fontSize: 'var(--fs-14)' }}>
                {agg.top ? `${agg.top.symbol} ${agg.top.score.toFixed(2)}` : '-'}
              </span>
            </div>
          </div>

          {signals.loading && rows.length === 0 && <div className="empty-hint">加载中…</div>}
          {!signals.loading && rows.length === 0 && (
            <div className="empty-hint onboarding">
              <div>信号总线当前为空。</div>
              <div style={{ marginTop: 'var(--sp-2)', lineHeight: 1.6 }}>
                运行任意策略即会把信号写入总线（与策略工作台同源）。点击下方按钮，
                用真实策略 <code>supertrend</code> 灌入示例信号，立即体验信号中心。
              </div>
              <button
                className="period-tab"
                onClick={runDefaultScan}
                disabled={filling}
                style={{ background: 'var(--accent)', color: '#fff', marginTop: 'var(--sp-3)' }}
              >
                {filling ? '生成中…' : '运行默认扫描填充信号'}
              </button>
            </div>
          )}
          {!signals.loading && rows.length > 0 && filtered.length === 0 && (
            <div className="empty-hint">没有符合条件的信号</div>
          )}

          {/* 表格视图（可展开行） */}
          {filtered.length > 0 && view === 'table' && (
            <div className="table-wrap">
              <table className="tbl">
                <thead>
                  <tr>
                    <th>标的</th>
                    <th>方向</th>
                    <th>得分</th>
                    <th>置信度</th>
                    <th>周期</th>
                    <th>来源</th>
                    <th>时间</th>
                    <th aria-hidden="true"></th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((s, i) => {
                    const key = `${s.symbol}-${s.ts ?? i}`
                    const open = expanded.has(key)
                    return (
                      <Fragment key={key}>
                        <tr className="sig-row-expand" onClick={() => toggleExpand(key)}>
                          <td>
                            <div className="sym">
                              <div className="sym-badge">{s.symbol.slice(0, 2)}</div>
                              <div>
                                <div className="sym-name">{s.symbol}</div>
                                <div className="sym-code">{s.market}</div>
                              </div>
                            </div>
                          </td>
                          <td>
                            <span className={`dir-pill ${dirClass(s.direction)}`}>
                              {dirLabel(s.direction)}
                            </span>
                          </td>
                          <td className="mono">{s.score.toFixed(2)}</td>
                          <td className="mono">{(s.confidence * 100).toFixed(1)}%</td>
                          <td>{s.timeframe}</td>
                          <td>{s.source}</td>
                          <td className="muted">{fmtTs(s.ts)}</td>
                          <td className="muted" style={{ textAlign: 'right' }}>
                            {open ? '▾' : '▸'}
                          </td>
                        </tr>
                        {open && (
                          <tr>
                            <td className="sig-detail-cell" colSpan={8}>
                              <SignalRow sig={s} />
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}

          {/* 分组视图（按来源策略） */}
          {filtered.length > 0 && view === 'group' && (
            <div>
              {groups.map(([src, list]) => (
                <div className="sig-group" key={src}>
                  <div className="sig-group-head">
                    <span className="sig-group-title">{src}</span>
                    <span className="sig-group-count">{list.length} 条</span>
                  </div>
                  <div className="sig-group-list">
                    {list.map((s, i) => (
                      <SignalRow key={`${s.symbol}-${s.ts ?? i}`} sig={s} />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* 分布可视化：方向环图 + 分数分布 + 跨策略来源分布（信号中心专属） */}
          {filtered.length > 0 && (
            <div style={{ marginTop: 'var(--sp-4)' }}>
              <div className="detail-section-title" style={{ marginBottom: 'var(--sp-2)' }}>
                分布可视化
              </div>
              <DirectionDonut signals={filtered} />
              <div style={{ marginTop: 'var(--sp-3)' }}>
                <ScoreHistogram signals={filtered} />
              </div>
              <SourceBars signals={filtered} />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
