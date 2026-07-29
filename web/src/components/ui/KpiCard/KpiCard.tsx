// KPI 卡片：升级现有 components/KpiCard.tsx，合并 Sparkline。
// 新 API：label / value / unit / delta / deltaPct / spark / accent
// 向后兼容：接受 item={Kpi} 旧 props。
import type { Kpi } from '../../../data/mock'
import s from './KpiCard.module.css'

interface KpiCardProps {
  /** 标签 */
  label: string
  /** 主值 */
  value: string | number
  /** 单位（前置显示，如 ¥ / $） */
  unit?: string
  /** 绝对变动值（如 +120.5） */
  delta?: string | number
  /** 百分比变动（正为涨） */
  deltaPct?: number
  /** 迷你折线图数据 */
  spark?: number[]
  /** 强调色覆盖（默认跟随 --board / --accent） */
  accent?: string
  className?: string
}

function Sparkline({ data, up }: { data: number[]; up: boolean }) {
  if (!data || data.length < 2) return null
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
  const gid = `qh-spark-${up ? 'up' : 'down'}-${Math.random().toString(36).slice(2, 7)}`
  return (
    <svg className={s.spark} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.25" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon points={`0,${h} ${pts} ${w},${h}`} fill={`url(#${gid})`} />
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  )
}

/** 新 API KpiCard */
export function KpiCard({
  label,
  value,
  unit,
  delta,
  deltaPct,
  spark,
  accent,
  className,
}: KpiCardProps) {
  const up = (deltaPct ?? 0) >= 0
  return (
    <div
      className={[s.kpi, className ?? ''].filter(Boolean).join(' ')}
      style={accent ? ({ '--board': accent } as React.CSSProperties) : undefined}
    >
      <div className={s.label}>{label}</div>
      <div className={s.value}>
        {unit && <span className={s.unit}>{unit}</span>}
        <span className={s.num}>{value}</span>
      </div>
      {(delta !== undefined || deltaPct !== undefined) && (
        <div className={s.foot}>
          {delta !== undefined && (
            <span className={[s.delta, up ? s.up : s.down].join(' ')}>
              {up ? '▲' : '▼'} {delta}
            </span>
          )}
          {spark && <Sparkline data={spark} up={up} />}
        </div>
      )}
    </div>
  )
}

/** 向后兼容：接受旧 item={Kpi} prop */
export function KpiCardLegacy({ item }: { item: Kpi }) {
  return (
    <KpiCard
      label={item.label}
      value={item.value}
      unit={item.unit}
      delta={item.deltaAbs}
      deltaPct={item.deltaPct}
      spark={item.spark}
    />
  )
}

/** 默认导出兼容旧代码：import KpiCard from '../KpiCard' */
export default KpiCardLegacy
