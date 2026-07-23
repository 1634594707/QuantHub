import type { WatchlistItem } from '../api/types'
import { WATCH } from '../data/mock'

const fmt = (n: number) => n.toLocaleString('en-US', { maximumFractionDigits: 2 })

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

export default function Watchlist({ items }: { items?: WatchlistItem[] }) {
  const data = items && items.length > 0 ? items : WATCH
  return (
    <div className="card">
      <div className="card-head">
        <div className="card-title">关注列表</div>
        <button className="link-btn">管理</button>
      </div>
      <div className="watch">
        {data.map((w) => {
          const up = w.chgPct >= 0
          return (
            <div className="watch-item" key={w.sym}>
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
                    {w.chgPct.toFixed(2)}%
                  </div>
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
