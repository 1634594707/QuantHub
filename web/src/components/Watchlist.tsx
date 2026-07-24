import type { WatchInput, WatchRow } from '../hooks/useEditableWatchlist'

const fmt = (n: number) => n.toLocaleString('en-US', { maximumFractionDigits: 2 })

const MARKETS = [
  { value: 'a_shares', label: 'A股' },
  { value: 'us_stocks', label: '美股' },
  { value: 'crypto', label: '加密货币' },
]

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
  onRemove: (id: string) => void
  onToggleEdit: () => void
}

export default function Watchlist({ rows, editing, onAdd, onUpdate, onRemove, onToggleEdit }: Props) {
  return (
    <div className="card">
      <div className="card-head">
        <div className="card-title">
          关注列表 <span className="sub">{rows.length} 个</span>
        </div>
        {editing ? (
          <div style={{ display: 'flex', gap: 'var(--sp-2)' }}>
            <button className="link-btn" onClick={onAdd}>
              + 添加
            </button>
            <button
              className="period-tab"
              style={{ background: 'var(--accent)', color: '#fff' }}
              onClick={onToggleEdit}
            >
              完成
            </button>
          </div>
        ) : (
          <button className="link-btn" onClick={onToggleEdit}>
            管理
          </button>
        )}
      </div>

      {editing ? (
        <div className="edit-list">
          {rows.map((w) => (
            <div className="edit-row" key={w.id}>
              <input
                className="edit-input"
                placeholder="代码/标的"
                value={w.sym}
                onChange={(e) => onUpdate(w.id, { sym: e.target.value })}
              />
              <input
                className="edit-input"
                placeholder="名称"
                value={w.name}
                onChange={(e) => onUpdate(w.id, { name: e.target.value })}
              />
              <select
                className="edit-input"
                value={w.market}
                onChange={(e) => onUpdate(w.id, { market: e.target.value })}
              >
                {MARKETS.map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label}
                  </option>
                ))}
              </select>
              <button className="icon-btn" title="删除关注" onClick={() => onRemove(w.id)}>
                ✕
              </button>
            </div>
          ))}
          {rows.length === 0 && (
            <div className="muted" style={{ padding: 'var(--sp-3)' }}>
              暂无关注，点击「+ 添加」新增
            </div>
          )}
        </div>
      ) : (
        <div className="watch">
          {rows.map((w) => {
            if (w.available === false || w.price == null) {
              return (
                <div className="watch-item" key={w.id}>
                  <div className="watch-left">
                    <span className="watch-sym mono">{w.sym}</span>
                    <span className="watch-price">{w.name}</span>
                  </div>
                  <div className="watch-right">
                    <span className="watch-unavail">数据源不可用</span>
                  </div>
                </div>
              )
            }
            const up = (w.chgPct ?? 0) >= 0
            return (
              <div className="watch-item" key={w.id}>
                <div className="watch-left">
                  <span className="watch-sym mono">{w.sym}</span>
                  <span className="watch-price">{w.name}</span>
                </div>
                <div className="watch-right">
                  <MiniSpark sym={w.sym} up={up} />
                  <div>
                    <div className="watch-sym mono" style={{ textAlign: 'right', fontSize: 13 }}>
                      {fmt(w.price)}
                    </div>
                    <div className={`watch-chg ${up ? 'up' : 'down'}`}>
                      {up ? '+' : ''}
                      {(w.chgPct ?? 0).toFixed(2)}%
                    </div>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
