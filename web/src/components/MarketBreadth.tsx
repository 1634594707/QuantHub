import { useState } from 'react'
import type { CSSProperties } from 'react'
import type { MarketBreadthResp } from '../api/types'
import { BREADTH, SECTORS } from '../data/mock'
import s from './MarketBreadth.module.css'

const PREVIEW_COUNT = 4

export default function MarketBreadth({
  data,
}: {
  data?: MarketBreadthResp | null
}) {
  const [expanded, setExpanded] = useState(false)
  const b = data || BREADTH
  const sectors = data?.sectors || SECTORS
  const total = Math.max(1, b.up + b.flat + b.down)
  const pct = (v: number) => ((v / total) * 100).toFixed(1)
  const top = [...sectors].sort((a, c) => c.chgPct - a.chgPct)
  const visible = expanded ? top : top.slice(0, PREVIEW_COUNT)
  const hidden = Math.max(0, top.length - PREVIEW_COUNT)
  const marketTone = b.up > b.down ? '上涨占优' : b.down > b.up ? '下跌占优' : '多空均衡'

  return (
    <div className={`card ${s.card}`}>
      <div className="card-head">
        <div className="card-title">
          市场广度 <span className="sub">{marketTone}</span>
          {b.sample && <span className={`src-pill warn ${s.samplePill}`}>样本</span>}
        </div>
      </div>
      <div className={s.body}>
        {b.note && <div className={s.note} title={b.note}>{b.note}</div>}
        <div
          className={s.bar}
          role="img"
          aria-label={`上涨 ${b.up} 平 ${b.flat} 下跌 ${b.down}`}
        >
          <i
            className={`${s.barSeg} ${s.barSegUp}`}
            style={{ '--w': pct(b.up) + '%' } as CSSProperties}
          />
          <i
            className={`${s.barSeg} ${s.barSegFlat}`}
            style={{ '--w': pct(b.flat) + '%' } as CSSProperties}
          />
          <i
            className={`${s.barSeg} ${s.barSegDown}`}
            style={{ '--w': pct(b.down) + '%' } as CSSProperties}
          />
        </div>
        <div className={s.legend}>
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

        <div className={s.sectors}>
          {visible.map((sec) => {
            const up = sec.chgPct >= 0
            return (
              <div className={s.sector} key={sec.name}>
                <span>{sec.name}</span>
                <span className={`mono ${s.sectorChange} ${up ? 'up' : 'down'}`}>
                  {up ? '+' : ''}
                  {sec.chgPct.toFixed(2)}%
                </span>
              </div>
            )
          })}
        </div>

        {hidden > 0 && (
          <button
            type="button"
            className={s.toggle}
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? '收起行业' : `展开 ${hidden} 个行业`}
          </button>
        )}
      </div>
    </div>
  )
}
