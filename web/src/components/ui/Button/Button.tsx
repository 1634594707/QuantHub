// 通用按钮：5 变体 × 3 尺寸，支持 loading / icon / iconRight / fullWidth。
// 替代现有 6 套按钮实现（.run-btn / .strat-btn / .period-tab / .link-btn / .src-pill / .icon-btn 部分）。
import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { Spinner } from '../Spinner/Spinner'
import s from './Button.module.css'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'link'
type Size = 'sm' | 'md' | 'lg'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  loading?: boolean
  icon?: ReactNode
  iconRight?: ReactNode
  fullWidth?: boolean
}

const VARIANT_CLASS: Record<Variant, string> = {
  primary: s.primary,
  secondary: s.secondary,
  ghost: s.ghost,
  danger: s.danger,
  link: s.link,
}

const SIZE_CLASS: Record<Size, string> = {
  sm: s.sm,
  md: s.md,
  lg: s.lg,
}

export function Button({
  variant = 'secondary',
  size = 'md',
  loading = false,
  icon,
  iconRight,
  fullWidth = false,
  disabled,
  className,
  children,
  ...rest
}: ButtonProps) {
  const isLink = variant === 'link'
  return (
    <button
      className={[
        isLink ? s.linkBtn : s.button,
        VARIANT_CLASS[variant],
        SIZE_CLASS[size],
        fullWidth ? s.fullWidth : '',
        className ?? '',
      ]
        .filter(Boolean)
        .join(' ')}
      disabled={disabled || loading}
      {...rest}
    >
      {loading && (
        <span aria-hidden="true">
          <Spinner size="sm" className={s.spinner} />
        </span>
      )}
      {!loading && icon && <span className={s.icon}>{icon}</span>}
      {children && <span className={s.label}>{children}</span>}
      {iconRight && <span className={s.iconRight}>{iconRight}</span>}
    </button>
  )
}
