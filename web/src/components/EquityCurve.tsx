// 权益曲线（纯 SVG，零依赖）。
// 抽离自 StrategyDetailPage，便于组合管理 / 信号中心等页面未来复用。
// 暂用全局 .bt-equity-svg 类（定义在 styles/strategy-module.css），后续可独立为 module。

export interface EquityPoint {
  t: string | null
  equity: number
}

interface Props {
  /** 权益序列，至少 2 个点才会渲染 */
  points: EquityPoint[]
  /** 初始资金，用作基准虚线与涨跌色判定 */
  initial: number
}

export default function EquityCurve({ points, initial }: Props) {
  const W = 720
  const H = 200
  const pad = 24
  if (points.length < 2) return null

  const eqs = points.map((p) => p.equity)
  const min = Math.min(initial, ...eqs)
  const max = Math.max(initial, ...eqs)
  const span = max - min || 1
  const stepX = (W - pad * 2) / (points.length - 1)
  const y = (v: number) => H - pad - ((v - min) / span) * (H - pad * 2)
  const x = (i: number) => pad + i * stepX
  const d = points
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(p.equity).toFixed(1)}`)
    .join(' ')
  const baseY = y(initial)
  const lastUp = points[points.length - 1].equity >= initial
  const stroke = lastUp ? 'var(--up-ink)' : 'var(--down-ink)'

  return (
    <svg
      className="bt-equity-svg"
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      role="img"
      aria-label="权益曲线"
    >
      <line x1={pad} y1={baseY} x2={W - pad} y2={baseY} stroke="var(--border)" strokeDasharray="3 3" />
      <path d={d} fill="none" stroke={stroke} strokeWidth={2} />
    </svg>
  )
}
