// 小徽标：用于状态标记（如「实时」「涨」「跌」），比 Tag 更紧凑。
import type { ReactNode } from 'react'
import s from './Badge.module.css'

type Variant = 'neutral' | 'accent' | 'up' | 'down' | 'warn' | 'info' | 'live'

interface BadgeProps {
  variant?: Variant
  dot?: boolean
  children?: ReactNode
  className?: string
}

const VARIANT_CLASS: Record<Variant, string> = {
  neutral: s.neutral,
  accent: s.accent,
  up: s.up,
  down: s.down,
  warn: s.warn,
  info: s.info,
  live: s.live,
}

/** 紧凑徽标 — 支持前置圆点 + 7 种语义变体 */
export function Badge({ variant = 'neutral', dot = false, children, className }: BadgeProps) {
  return (
    <span className={`${s.badge} ${VARIANT_CLASS[variant]} ${className ?? ''}`.trim()}>
      {dot && <span className={s.dot} aria-hidden="true" />}
      {children}
    </span>
  )
}
