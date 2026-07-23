import type { MarketBreadthResp } from '../api/types'
import { BREADTH, SECTORS } from '../data/mock'

export default function MarketBreadth({
  data,
}: {
  data?: MarketBreadthResp | null
}) {
  const b = data || BREADTH
  const sectors = data?.sectors || SECTORS
  const total = b.up + b.flat + b.down
  const pct = (v: number) => ((v / total) * 100).toFixed(1)
  const top = [...sectors].sort((a, c) => c.chgPct - a.chgPct)

  return (
    <div className="card">
      <div className="card-head">
        <div className="card-title">
          市场广度 <span className="sub">全市涨跌分布</span>
        </div>
      </div>
      <div className="breadth">
        <div className="breadth-bar" role="img" aria-label={`上涨 ${b.up} 平 ${b.flat} 下跌 ${b.down}`}>
          <i style={{ width: pct(b.up) + '%', background: 'var(--up)' }} />
          <i style={{ width: pct(b.flat) + '%', background: 'var(--text-3)' }} />
          <i style={{ width: pct(b.down) + '%', background: 'var(--down)' }} />
        </div>
        <div className="breadth-legend">
          <span className="up">
            涨 <b>{b.up}</b> ({pct(b.up)}%)
          </span>
          <span className="sec">
            平 <b>{b.flat}</b>
          </span>
          <span className="down">
            跌 <b>{b.down}</b> ({pct(b.down)}%)
          </span>
        </div>

        <div className="breadth-sectors">
          {top.map((s) => {
            const up = s.chgPct >= 0
            return (
              <div className="breadth-sector" key={s.name}>
                <span className="name">{s.name}</span>
                <span className={`chg mono ${up ? 'up' : 'down'}`}>
                  {up ? '+' : ''}
                  {s.chgPct.toFixed(2)}%
                </span>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
