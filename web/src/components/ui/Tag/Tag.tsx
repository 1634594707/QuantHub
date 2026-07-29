// 标签：比 Badge 大、可关闭，用于筛选条件、分类标记等。
import type { ReactNode } from 'react'
import s from './Tag.module.css'

type Variant = 'neutral' | 'accent' | 'up' | 'down' | 'warn' | 'info'

interface TagProps {
  variant?: Variant
  closable?: boolean
  onClose?: () => void
  children: ReactNode
  className?: string
}

const VARIANT_CLASS: Record<Variant, string> = {
  neutral: s.neutral,
  accent: s.accent,
  up: s.up,
  down: s.down,
  warn: s.warn,
  info: s.info,
}

/** 可关闭标签 — 比 Badge 更大，适合筛选器 / 分类 */
export function Tag({ variant = 'neutral', closable = false, onClose, children, className }: TagProps) {
  return (
    <span className={`${s.tag} ${VARIANT_CLASS[variant]} ${className ?? ''}`.trim()}>
      <span className={s.label}>{children}</span>
      {closable && (
        <button
          type="button"
          className={s.close}
          onClick={onClose}
          aria-label="移除标签"
          title="移除标签"
        >
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
            <path d="M18 6 6 18M6 6l12 12" />
          </svg>
        </button>
      )}
    </span>
  )
}
