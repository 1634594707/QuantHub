import { useMemo, useState } from 'react'
import { api } from '../api/client'
import { useApi } from '../api/useApi'
import type { SignalResp } from '../api/types'
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

function clamp(v: number, lo: number, hi: number) {
  return Math.max(lo, Math.min(hi, v))
}

// 半弧仪表盘：pct ∈ [0,1]；无后端信号时 pct=null，渲染「暂无数据」灰弧。
function RadarDonut({ pct, color }: { pct: number | null; color: string }) {
  const r = 52
  const cx = 64
  const cy = 62
  const len = Math.PI * r // 半圆弧长
  const has = pct != null
  const dash = has ? len * clamp(pct, 0, 1) : 0
  return (
    <svg width="128" height="74" viewBox="0 0 128 74" role="img" aria-label={has ? `把握度 ${Math.round(pct * 100)}` : '暂无数据'}>
      <path d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`} fill="none" stroke="var(--border-strong)" strokeWidth="12" strokeLinecap="round" />
      {has ? (
        <>
          <path d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`} fill="none" stroke={color} strokeWidth="12" strokeLinecap="round" strokeDasharray={`${dash} ${len}`} />
          <text x={cx} y={cy - 6} textAnchor="middle" fontSize="20" fontWeight="800" fontFamily="var(--font-mono)" fill={color}>
            {Math.round(pct * 100)}
          </text>
          <text x={cx} y={cy + 11} textAnchor="middle" fontSize="9" fill="var(--text-3)">
            把握度
          </text>
        </>
      ) : (
        <text x={cx} y={cy - 2} textAnchor="middle" fontSize="13" fontWeight="700" fill="var(--text-3)">
          暂无数据
        </text>
      )}
    </svg>
  )
}

export default function RadarPage() {
  // —— 信号来源筛选状态 ——
  // null = "全部"（隐式全选，对应服务端下发的 source 集合）
  // Set<string> = 显式选择（可为空 → 所有卡信号区显示「暂无数据」，符合铁律）
  const [selectedSourcesRaw, setSelectedSourcesRaw] = useState<Set<string> | null>(null)

  // 拉取后端真实信号台账：故意不带 source/market 参数，让前端拿全量再分桶，
  // 避免每点一个 chip 都触发后端往返。limit=200 覆盖当前 92 条全量。
  const signals = useApi(
    () => api.signals(200, undefined, undefined, undefined),
    [],
  )

  // 标的池：自选（/market/watchlist） + 综合评估收藏（/research/runs?favorite=true）
  // 两者合并去重 — 这是用户在导航"研究"区主动关心的标的集合。
  // 不再硬编码默认池，避免出现"暂无数据"的空卡。
  const watchlist = useApi(() => api.watchlist(), [])
  const favorites = useApi(() => api.researchRuns(undefined, undefined, 100, true), [])

  // 真实数据里的来源分布（按 count 倒序）。空数据 → 空数组 → 不渲染筛选行。
  const sourceDistribution = useMemo(() => {
    const m = new Map<string, number>()
    for (const s of signals.data?.signals ?? []) {
      m.set(s.source, (m.get(s.source) ?? 0) + 1)
    }
    return Array.from(m.entries()).sort((a, b) => b[1] - a[1])
  }, [signals.data])

  // 生效选择：raw===null 时等于 sourceDistribution 全集
  const effectiveSelection = useMemo(() => {
    if (selectedSourcesRaw === null) return new Set(sourceDistribution.map(([k]) => k))
    return selectedSourcesRaw
  }, [selectedSourcesRaw, sourceDistribution])

  // 标的池构造。自选优先（含 name），favorite 研究运行补全（用 symbol 兜底 name）。
  // key 用 `${market}:${sym}`，避免同名不同市场（如 002842 同时存在 a_shares/hk）的去重错位。
  const pool = useMemo(() => {
    const m = new Map<string, { sym: string; name: string; market: string }>()
    const add = (sym: string, name: string | undefined, market: string) => {
      if (!sym) return
      const normSym = sym.toUpperCase()
      const normMarket = market || 'a_shares'
      const key = `${normMarket}:${normSym}`
      if (m.has(key)) return
      m.set(key, { sym: normSym, name: name && name.trim() ? name : normSym, market: normMarket })
    }
    for (const w of watchlist.data?.items ?? []) add(w.sym, w.name, w.market ?? 'a_shares')
    for (const r of favorites.data?.runs ?? []) add(r.symbol, undefined, r.market)
    return Array.from(m.values())
  }, [watchlist.data, favorites.data])

  // pool 来源计数（用于 WorkspaceHeader metrics，让用户看到池子组成）
  const poolStats = useMemo(() => {
    const items = watchlist.data?.items ?? []
    const runs = favorites.data?.runs ?? []
    return { watchCount: items.length, favoriteCount: runs.length, total: pool.length }
  }, [watchlist.data, favorites.data, pool.length])

  // poolKey 稳定字符串：pool 变化时驱动 useApi 重取报价
  const poolKey = pool.map((p) => `${p.sym}:${p.market}`).join(',')

  // 报价：依赖 poolKey，pool 变化时重取；useApi 失败保留旧 data，UI 不闪烁
  const quotes = useApi(
    () => Promise.all(pool.map((p) => api.quote(p.sym, p.market))),
    [poolKey],
  )

  // 过滤后的 sigMap（symbol → 最新命中信号；过滤后 last-wins 语义同原实现）
  const sigMap = useMemo(() => {
    const m: Record<string, SignalResp> = {}
    for (const s of signals.data?.signals ?? []) {
      if (!effectiveSelection.has(s.source)) continue
      m[s.symbol] = s
    }
    return m
  }, [signals.data, effectiveSelection])

  const best = useMemo(() => {
    const arr = (quotes.data ?? []).filter((q) => q.available && typeof q.chgPct === 'number')
    if (arr.length === 0) return null
    return arr.reduce((a, b) => ((b.chgPct ?? 0) > (a.chgPct ?? 0) ? b : a))
  }, [quotes.data])

  const cards = (quotes.data ?? []).map((q) => {
    const chg = q.chgPct ?? 0
    const sig = sigMap[q.sym]
    const hasSignal = Boolean(sig)
    // 方向：仅取后端信号方向；无信号时统一为 flat（仅用于配色，文本显示「暂无数据」）。
    const dir: 'up' | 'down' | 'flat' = hasSignal
      ? (DIR_FROM_SIGNAL[sig!.direction] ?? 'flat')
      : 'flat'
    const color = hasSignal
      ? (dir === 'up' ? 'var(--up)' : dir === 'down' ? 'var(--down)' : 'var(--text-3)')
      : 'var(--text-3)'
    // 把握度：仅取后端信号 confidence；无信号则为 null（展示「暂无数据」，绝不本地伪造）。
    const pct = hasSignal ? clamp(sig!.confidence, 0.04, 0.99) : null
    return { q, chg, dir, color, pct, sig, hasSignal }
  })

  const sigCount = cards.filter((c) => c.hasSignal).length
  const totalSignals = signals.data?.signals?.length ?? 0
  const filterActive = selectedSourcesRaw !== null && effectiveSelection.size > 0
  const filterLabel = !filterActive
    ? '全部'
    : effectiveSelection.size === 0
      ? '已清空'
      : `${effectiveSelection.size}/${sourceDistribution.length}`

  return (
    <div className="rm-page" data-board="radar">
      <WorkspaceHeader
        context="研究 · 行情雷达"
        title="标的信号雷达"
        description="一屏监控你的自选 + 综合评估收藏标的的实时涨跌与后端信号。报价为真实数据（tencent 源）；后端信号缺失时该字段不出现在卡片中，不伪造占位。信号来源 chip 按真实数据动态生成。"
        metrics={[
          { label: '标的池', value: pool.length },
          { label: '其中自选', value: poolStats.watchCount },
          { label: '其中收藏', value: poolStats.favoriteCount },
          { label: '可用报价', value: cards.filter((c) => c.q.available).length },
          { label: '后端信号', value: sigCount },
          { label: '信源筛选', value: filterLabel },
          { label: '最佳表现', value: best ? `${best.sym} ${best.chgPct?.toFixed(2)}%` : '—' },
        ]}
      />

      <div className="rm-toolbar">
        <span className="rm-source-tag live">报价源：tencent · 信号源：后端 /signals</span>
        <span className="rm-note">把握度/方向仅取后端真实信号；无信号的字段自动隐藏，不伪造占位。</span>
      </div>

      {/* —— 信号来源筛选 —— 仅在真实数据存在时渲染（无数据不渲染伪造选项） */}
      {sourceDistribution.length > 0 ? (
        <div className="rm-source-filter" role="group" aria-label="信号来源筛选">
          <span className="rm-source-filter-label">信号来源</span>
          <button
            type="button"
            className={`rm-source-chip ${!filterActive ? 'active' : ''}`}
            onClick={() => setSelectedSourcesRaw(null)}
            aria-pressed={!filterActive}
            title="重置为全选"
          >
            全部 · {totalSignals}
          </button>
          {sourceDistribution.map(([src, count]) => {
            const active = effectiveSelection.has(src)
            return (
              <button
                key={src}
                type="button"
                className={`rm-source-chip ${active ? 'active' : ''}`}
                onClick={() => {
                  // 基于 effectiveSelection 增量切换，保留用户已点选状态
                  const next = new Set(effectiveSelection)
                  if (active) next.delete(src)
                  else next.add(src)
                  setSelectedSourcesRaw(next)
                }}
                aria-pressed={active}
                title={active ? `点击取消 ${src}` : `点击启用 ${src}`}
              >
                {src} · {count}
              </button>
            )
          })}
        </div>
      ) : null}

      {quotes.loading && cards.length === 0 && pool.length === 0 ? (
        <div className="radar-grid">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={`skel-${i}`} className="radar-skeleton" />
          ))}
        </div>
      ) : pool.length === 0 ? (
        <div className="rm-empty">
          <div className="rm-empty-title">雷达池尚无内容</div>
          <div className="rm-empty-desc">
            你可以在「策略中心 → 关注列表」加入想监控的标的，或在「综合评估」对某次研究运行点击收藏（favorite）。
            一旦加入，这里会自动开始跟踪它的实时报价与后端信号 —— 当前没有任何真实数据可展示。
          </div>
        </div>
      ) : (
        <div className="radar-grid">
          {cards.map(({ q, chg, dir, color, pct, sig, hasSignal }) => (
            <article key={q.sym} className={`radar-card ${hasSignal ? 'has-signal' : 'no-signal'}`}>
              <div className="radar-card-head">
                <div>
                  <div className="radar-sym">{q.sym}</div>
                  <div className="radar-name">{q.name || '—'}</div>
                </div>
                <div className={`radar-chg ${dir}`}>
                  {q.available ? `${chg > 0 ? '+' : ''}${chg.toFixed(2)}%` : '不可用'}
                </div>
              </div>

              <div className="radar-donut-wrap">
                <RadarDonut pct={pct} color={color} />
              </div>

              {/* dl 按需渲染：没数据的字段整行不出现，不用「暂无数据」占位 */}

              {hasSignal ? (
                <dl className="radar-meta">
                  <dt>方向</dt>
                  <dd>{DIR_LABEL[dir]}</dd>
                  <dt>把握度</dt>
                  <dd>{Math.round((sig!.confidence ?? 0) * 100)}</dd>
                  {sig!.status ? (
                    <>
                      <dt>状态</dt>
                      <dd>{sig!.status}</dd>
                    </>
                  ) : null}
                  {sig!.tags && sig!.tags.length > 0 ? (
                    <>
                      <dt>标签</dt>
                      <dd>{sig!.tags.join(' · ')}</dd>
                    </>
                  ) : null}
                </dl>
              ) : (
                <div className="radar-empty-row">
                  该标的后端尚无信号 — 仅展示实时报价
                </div>
              )}

              {hasSignal ? (
                <div className="radar-note">
                  <span>{sig!.source}</span>
                  <span style={{ opacity: 0.5 }}> · ID </span>
                  <code>{sig!.id}</code>
                </div>
              ) : (
                <div className="radar-note muted">仅实时报价 · 信号待生成</div>
              )}
            </article>
          ))}
        </div>
      )}

      {quotes.error ? (
        <div className="rm-note" style={{ color: 'var(--down-ink)' }}>
          报价拉取失败：{quotes.error}。请确认后端网关已启动且 tencent 源可用。
        </div>
      ) : null}
      {signals.error ? (
        <div className="rm-note" style={{ color: 'var(--down-ink)' }}>
          后端信号拉取失败：{signals.error}。
        </div>
      ) : null}
    </div>
  )
}
