// Tooltip：纯 CSS hover 悬浮提示，无 JS 定位开销。
// 通过 side prop 控制方向，content 可为字符串或 ReactNode。
import type { ReactNode } from 'react'
import s from './Tooltip.module.css'

type Side = 'top' | 'right' | 'bottom' | 'left'

interface TooltipProps {
  content: ReactNode
  side?: Side
  children: ReactNode
}

const SIDE_CLASS: Record<Side, string> = {
  top: s.top,
  right: s.right,
  bottom: s.bottom,
  left: s.left,
}

export function Tooltip({ content, side = 'top', children }: TooltipProps) {
  return (
    <span className={s.wrapper}>
      {children}
      <span className={[s.tooltip, SIDE_CLASS[side]].join(' ')} role="tooltip">
        {content}
      </span>
    </span>
  )
}
