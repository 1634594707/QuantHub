import type { Kpi } from '../data/mock'

function Sparkline({ data, up }: { data: number[]; up: boolean }) {
  const w = 64
  const h = 26
  const min = Math.min(...data)
  const max = Math.max(...data)
  const span = max - min || 1
  const pts = data
    .map((v, i) => {
      const x = (i / (data.length - 1)) * w
      const y = h - ((v - min) / span) * (h - 4) - 2
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
  const color = up ? 'var(--up)' : 'var(--down)'
  const fillColor = up ? 'var(--up)' : 'var(--down)'
  return (
    <svg className="spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
      <defs>
        <linearGradient id={`sparkFill-${up ? 'up' : 'down'}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={fillColor} stopOpacity="0.25" />
          <stop offset="100%" stopColor={fillColor} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon
        points={`0,${h} ${pts} ${w},${h}`}
        fill={`url(#sparkFill-${up ? 'up' : 'down'})`}
      />
      <polyline points={pts} fill="none" stroke={color} strokeWidth={1.8} strokeLinecap="round" />
    </svg>
  )
}

export default function KpiCard({ item }: { item: Kpi }) {
  const up = item.deltaPct >= 0
  return (
    <div className="card kpi">
      <div className="kpi-label">{item.label}</div>
      <div className="kpi-value mono">
        {item.unit}
        {item.value}
      </div>
      <div className="kpi-foot">
        <span className={`delta ${up ? 'up' : 'down'}`}>
          {up ? '▲' : '▼'} {item.deltaAbs}
        </span>
        <Sparkline data={item.spark} up={up} />
      </div>
    </div>
  )
}
