// 仅图标的方形按钮：必须提供 label（aria-label），替代 .icon-btn。
import type { ButtonHTMLAttributes, ReactNode } from 'react'
import s from './IconButton.module.css'

type Variant = 'default' | 'ghost' | 'accent'
type Size = 'sm' | 'md'

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  /** 无障碍标签（必填） */
  label: string
  children: ReactNode
}

const VARIANT_CLASS: Record<Variant, string> = {
  default: s.default,
  ghost: s.ghost,
  accent: s.accent,
}

const SIZE_CLASS: Record<Size, string> = {
  sm: s.sm,
  md: s.md,
}

export function IconButton({
  variant = 'default',
  size = 'md',
  label,
  className,
  children,
  title,
  ...rest
}: IconButtonProps) {
  return (
    <button
      type="button"
      aria-label={label}
      title={title ?? label}
      className={[
        s.button,
        VARIANT_CLASS[variant],
        SIZE_CLASS[size],
        className ?? '',
      ]
        .filter(Boolean)
        .join(' ')}
      {...rest}
    >
      {children}
    </button>
  )
}
