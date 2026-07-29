import type { CSSProperties } from 'react'
import type { SignalResp } from '../api/types'
import { directionColor } from './StrategyShared'
import s from './SignalStats.module.css'

function directionLabel(d: string) {
  if (d === 'buy' || d === 'bullish') return '做多'
  if (d === 'sell' || d === 'bearish') return '做空'
  return '观望'
}

interface Props {
  signals: SignalResp[]
}

export default function SignalStats({ signals }: Props) {
  if (signals.length === 0) return null

  const buy = signals.filter((sig) => sig.direction === 'buy' || sig.direction === 'bullish').length
  const sell = signals.filter((sig) => sig.direction === 'sell' || sig.direction === 'bearish').length
  const hold = signals.length - buy - sell
  const avgScore = signals.reduce((a, sig) => a + sig.score, 0) / signals.length
  const avgConf = signals.reduce((a, sig) => a + sig.confidence, 0) / signals.length

  const rows = [
    { label: '做多', count: buy, color: 'var(--up)' },
    { label: '做空', count: sell, color: 'var(--down)' },
    { label: '观望', count: hold, color: 'var(--text-3)' },
  ]

  return (
    <div className="signal-stats">
      {rows.map((r) => {
        const pct = signals.length ? (r.count / signals.length) * 100 : 0
        return (
          <div className="signal-stat" key={r.label}>
            <div className="signal-stat-head">
              <span className="signal-stat-label">{r.label}</span>
              <span className="signal-stat-value mono">{r.count}</span>
            </div>
            <div className="signal-stat-bar">
              <div
                className={s.barFill}
                style={{ '--w': `${pct}%`, '--c': r.color } as CSSProperties}
              />
            </div>
          </div>
        )
      })}
      <div className="signal-stat metric">
        <span className="k">平均分数</span>
        <span className="v mono">{avgScore.toFixed(2)}</span>
      </div>
      <div className="signal-stat metric">
        <span className="k">平均置信度</span>
        <span className="v mono">{(avgConf * 100).toFixed(0)}%</span>
      </div>
    </div>
  )
}

export function directionFilterColor(d: string) {
  return directionColor(d)
}
