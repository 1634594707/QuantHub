// 统一空态组件：升级现有 components/EmptyState.tsx，props 向后兼容。
// 新增 variant: default / error / no-data / loading，替代 ErrorState。
// 旧 import 路径（../EmptyState）继续可用；新代码请用 ui/EmptyState。
import type { ReactNode } from 'react'
import { Button } from '../Button/Button'
import { Spinner } from '../Spinner/Spinner'
import s from './EmptyState.module.css'

type Variant = 'default' | 'error' | 'no-data' | 'loading'

interface ActionButton {
  label: string
  onClick: () => void
  loading?: boolean
  disabled?: boolean
}

interface EmptyStateProps {
  variant?: Variant
  title: ReactNode
  desc?: ReactNode
  action?: ActionButton
  icon?: ReactNode
  className?: string
}

/** variant 值到 CSS Module 类名的映射（variant 用 kebab-case，CSS 类用 camelCase） */
const VARIANT_CLASS: Record<Variant, string> = {
  default: '',
  error: s.error,
  'no-data': s.noData,
  loading: s.loading,
}

/** 空态 / 错误态 / 无数据 / 加载中 — 统一组件 */
export function EmptyState({
  variant = 'default',
  title,
  desc,
  action,
  icon,
  className,
}: EmptyStateProps) {
  if (variant === 'loading') {
    return (
      <div className={[s.wrap, s.loading, className ?? ''].filter(Boolean).join(' ')}>
        <Spinner size="lg" />
        <div className={s.title}>{title}</div>
      </div>
    )
  }

  return (
    <div
      className={[s.wrap, VARIANT_CLASS[variant], className ?? ''].filter(Boolean).join(' ')}
      role={variant === 'error' ? 'alert' : undefined}
    >
      {icon && <div className={s.icon}>{icon}</div>}
      <div className={s.title}>{title}</div>
      {desc && <div className={s.desc}>{desc}</div>}
      {action && (
        <Button
          variant={variant === 'error' ? 'danger' : 'primary'}
          size="sm"
          onClick={action.onClick}
          loading={action.loading}
          disabled={action.disabled}
          className={s.action}
        >
          {action.label}
        </Button>
      )}
    </div>
  )
}

/** 向后兼容：ErrorState 作为 variant='error' 的快捷别名 */
export function ErrorState({
  message,
  onRetry,
  retrying,
  className,
}: {
  message: string
  onRetry?: () => void
  retrying?: boolean
  className?: string
}) {
  return (
    <EmptyState
      variant="error"
      title="⚠ 请求失败"
      desc={message}
      action={onRetry ? { label: '重试', onClick: onRetry, loading: retrying } : undefined}
      className={className}
    />
  )
}
