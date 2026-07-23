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
  return (
    <svg className="spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
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
        <span className={up ? 'up' : 'down'} style={{ fontWeight: 600 }}>
          {up ? '+' : ''}
          {item.deltaPct.toFixed(2)}%
        </span>
        <Sparkline data={item.spark} up={up} />
      </div>
    </div>
  )
}
