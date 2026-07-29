import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { WatchInput, WatchRow } from '../hooks/useEditableWatchlist'
import { IconChevron } from './icons'
import { Button } from './ui/Button/Button'
import { Input } from './ui/Input/Input'
import { Select } from './ui/Select/Select'
import { IconButton } from './ui/IconButton/IconButton'
import s from './Watchlist.module.css'

const fmt = (n: number) => n.toLocaleString('en-US', { maximumFractionDigits: 2 })

const MARKETS = [
  { value: 'a_shares', label: 'A股' },
  { value: 'us_stocks', label: '美股' },
  { value: 'crypto', label: '加密货币' },
]

const MARKET_LABELS: Record<string, string> = {
  a_shares: 'A股',
  us_stocks: '美股',
  crypto: '加密',
}

const PAGE_SIZE = 5

function researchHref(row: WatchRow): string {
  const timeframe = row.market === 'crypto' ? '1h' : '1d'
  return `/research/${encodeURIComponent(row.sym)}?market=${encodeURIComponent(row.market)}&tf=${timeframe}&view=overview`
}

function lcg(seed: number) {
  let s = seed % 2147483647
  if (s <= 0) s += 2147483646
  return () => {
    s = (s * 16807) % 2147483647
    return (s - 1) / 2147483646
  }
}

function MiniSpark({ sym, up }: { sym: string; up: boolean }) {
  const rnd = lcg(sym.split('').reduce((a, c) => a + c.charCodeAt(0), 0))
  const points: number[] = []
  let v = 50
  for (let i = 0; i < 18; i++) {
    v = Math.max(10, Math.min(90, v + (rnd() - 0.48) * 30))
    points.push(v)
  }
  const min = Math.min(...points)
  const max = Math.max(...points)
  const range = Math.max(1, max - min)
  const W = 56
  const H = 22
  const coords = points.map((p, i) => {
    const x = (i / (points.length - 1)) * W
    const y = H - ((p - min) / range) * H
    return `${x},${y}`
  })
  const color = up ? 'var(--up)' : 'var(--down)'
  return (
    <svg className="watch-mini" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${sym} 走势`}>
      <polyline fill="none" stroke={color} strokeWidth={1.5} points={coords.join(' ')} />
    </svg>
  )
}

interface Props {
  rows: WatchRow[]
  editing: boolean
  onAdd: () => void
  onUpdate: (id: string, patch: Partial<WatchInput>) => void
  onResolveName: (id: string, symbol: string, market: string) => void
  onRemove: (id: string) => void
  onToggleEdit: () => void
  saving?: boolean
  saveError?: string
  resolvingIds?: ReadonlySet<string>
}

export default function Watchlist({
  rows,
  editing,
  onAdd,
  onUpdate,
  onResolveName,
  onRemove,
  onToggleEdit,
  saving = false,
  saveError = '',
  resolvingIds = new Set(),
}: Props) {
  const [page, setPage] = useState(0)
  const pageCount = Math.max(1, Math.ceil(rows.length / PAGE_SIZE))
  const currentPage = Math.min(page, pageCount - 1)
  const pageStart = currentPage * PAGE_SIZE
  const visibleRows = rows.slice(pageStart, pageStart + PAGE_SIZE)

  return (
    <div className={`card ${s.card}`}>
      <div className="card-head">
        <div className="card-title">
          关注列表 <span className="sub">{rows.length} 个</span>
        </div>
        <div className={s.headActions}>
          {!editing && pageCount > 1 && (
            <div className={s.headerPagination} aria-label="关注列表分页">
              <IconButton
                variant="ghost"
                size="sm"
                label="上一页"
                disabled={currentPage === 0}
                onClick={() => setPage((value) => Math.max(0, value - 1))}
              >
                <IconChevron size={15} className={s.previousIcon} />
              </IconButton>
              <span>{currentPage + 1} / {pageCount}</span>
              <IconButton
                variant="ghost"
                size="sm"
                label="下一页"
                disabled={currentPage >= pageCount - 1}
                onClick={() => setPage((value) => Math.min(pageCount - 1, value + 1))}
              >
                <IconChevron size={15} />
              </IconButton>
            </div>
          )}
          {editing ? (
            <>
              <Button variant="link" size="sm" onClick={onAdd}>
                + 添加
              </Button>
              <Button
                variant="primary"
                size="sm"
                onClick={onToggleEdit}
                loading={saving}
                disabled={saving}
              >
                {saving ? '保存中…' : '完成'}
              </Button>
            </>
          ) : (
            <Button variant="link" size="sm" onClick={onToggleEdit}>
              管理
            </Button>
          )}
        </div>
      </div>

      {editing ? (
        <div className={`edit-list ${s.editList}`}>
          {rows.map((w) => (
            <div className={`edit-row ${s.editRow}`} key={w.id}>
              <Input
                className="edit-input"
                placeholder="代码/标的"
                value={w.sym}
                onChange={(e) => {
                  const sym = e.target.value.toUpperCase()
                  onUpdate(w.id, { sym, name: '' })
                  onResolveName(w.id, sym, w.market)
                }}
              />
              <Input
                className="edit-input"
                placeholder={resolvingIds.has(w.id) ? '识别中…' : '名称'}
                value={w.name}
                aria-busy={resolvingIds.has(w.id)}
                onChange={(e) => onUpdate(w.id, { name: e.target.value })}
              />
              <Select
                className="edit-input"
                options={MARKETS}
                value={w.market}
                onChange={(e) => {
                  const market = e.target.value
                  onUpdate(w.id, { market, name: '' })
                  onResolveName(w.id, w.sym, market)
                }}
              />
              <IconButton
                variant="ghost"
                size="sm"
                label="删除关注"
                title="删除关注"
                onClick={() => onRemove(w.id)}
              >
                ✕
              </IconButton>
            </div>
          ))}
          {rows.length === 0 && (
            <div className={`muted ${s.emptyHint}`}>
              暂无关注
            </div>
          )}
          {saveError && <div className="edit-save-error" role="alert">{saveError}</div>}
        </div>
      ) : (
        <div className={s.watch} role="list" aria-label="关注标的行情">
          <div className={s.columnHead} aria-hidden="true">
            <span>标的</span>
            <span>市场</span>
            <span>日内走势</span>
            <span>最新价</span>
            <span>涨跌</span>
            <span />
          </div>
          {visibleRows.map((w) => {
            if (w.available === false || w.price == null) {
              return (
                <Link className={s.row} to={researchHref(w)} key={w.id} role="listitem">
                  <div className={s.asset}>
                    <span className={`mono ${s.symbol}`}>{w.sym}</span>
                    <span className={s.name}>{w.name}</span>
                  </div>
                  <span className={s.market}>{MARKET_LABELS[w.market] ?? w.market}</span>
                  <span className={s.noTrend}>暂无走势</span>
                  <span className={s.unavailable}>行情不可用</span>
                  <span className={s.noChange}>--</span>
                  <span className={s.openAction} aria-label={`评估 ${w.sym}`}>
                    <span>评估</span><IconChevron size={15} />
                  </span>
                </Link>
              )
            }
            const up = (w.chgPct ?? 0) >= 0
            return (
              <Link className={s.row} to={researchHref(w)} key={w.id} role="listitem">
                <div className={s.asset}>
                  <span className={`mono ${s.symbol}`}>{w.sym}</span>
                  <span className={s.name}>{w.name}</span>
                </div>
                <span className={s.market}>{MARKET_LABELS[w.market] ?? w.market}</span>
                <MiniSpark sym={w.sym} up={up} />
                <span className={`mono ${s.price}`}>{fmt(w.price)}</span>
                <span className={`mono ${s.change} ${up ? 'up' : 'down'}`}>
                  {up ? '+' : ''}{(w.chgPct ?? 0).toFixed(2)}%
                </span>
                <span className={s.openAction} aria-label={`评估 ${w.sym}`}>
                  <span>评估</span><IconChevron size={15} />
                </span>
              </Link>
            )
          })}
          {rows.length === 0 && <div className={s.emptyState}>还没有关注标的，点击“管理”添加。</div>}
        </div>
      )}
    </div>
  )
}
