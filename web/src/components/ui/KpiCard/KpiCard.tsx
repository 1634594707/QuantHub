// KPI 卡片，内置 Sparkline。
// API：label / value / unit / delta / deltaPct / spark / accent
//
// M2-02：旧 `components/KpiCard.tsx` 与其兼容层 `KpiCardLegacy`（item={Kpi} 形态）
// 已随孤立组件清理一并删除，本文件只保留唯一在用的具名导出。
import { useId } from 'react'
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
  const uid = useId()
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
  // 用 React useId 生成稳定唯一 id，避免 Math.random 造成 SSR/重渲染不一致
  const gid = `qh-spark-${up ? 'up' : 'down'}-${uid.replace(/:/g, '')}`
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
