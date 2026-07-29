// 通用卡片：替代 .card / .panel / .str-card / .strategy-card 4 套实现。
// 支持 as（语义标签）、padding、hoverable、accentRail（板块强调导轨）、elevation。
import type { ReactNode } from 'react'
import s from './Card.module.css'

type Elevation = 'flat' | 'card' | 'pop'
type Padding = 'none' | 'sm' | 'md' | 'lg'

interface CardProps {
  as?: 'div' | 'section' | 'article' | 'aside'
  padding?: Padding
  hoverable?: boolean
  accentRail?: boolean
  elevation?: Elevation
  className?: string
  children: ReactNode
  onClick?: () => void
}

const ELEVATION_CLASS: Record<Elevation, string> = {
  flat: s.flat,
  card: s.card,
  pop: s.pop,
}

const PADDING_CLASS: Record<Padding, string> = {
  none: s.padNone,
  sm: s.padSm,
  md: s.padMd,
  lg: s.padLg,
}

export function Card({
  as: Tag = 'div',
  padding = 'md',
  hoverable = false,
  accentRail = false,
  elevation = 'card',
  className,
  children,
  onClick,
}: CardProps) {
  return (
    <Tag
      className={[
        s.card,
        ELEVATION_CLASS[elevation],
        PADDING_CLASS[padding],
        hoverable ? s.hoverable : '',
        accentRail ? s.accentRail : '',
        className ?? '',
      ]
        .filter(Boolean)
        .join(' ')}
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (e) => e.key === 'Enter' && onClick() : undefined}
    >
      {children}
    </Tag>
  )
}
