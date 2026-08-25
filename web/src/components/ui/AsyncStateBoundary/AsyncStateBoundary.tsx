import type { ReactNode } from 'react'
import { Button } from '../Button/Button'
import { Skeleton } from '../Skeleton/Skeleton'
import { EmptyState } from '../EmptyState/EmptyState'
import s from './AsyncStateBoundary.module.css'

interface AsyncStateAction {
  label: string
  onClick: () => void
  loading?: boolean
  disabled?: boolean
}

interface AsyncStateBoundaryProps {
  loading: boolean
  error: string | null
  reconnecting: boolean
  hasData: boolean
  isEmpty: boolean
  onRetry?: () => void
  loadingTitle?: string
  /** 首次加载占位骨架；提供时替代默认 loading 空态 */
  loadingSkeleton?: boolean
  skeletonRows?: number
  emptyTitle: string
  emptyDescription?: string
  emptyAction?: AsyncStateAction
  children: ReactNode
}

/**
 * 页面级请求的统一四态：首次加载、保留旧数据更新、确定失败和空数据。
 * 有旧数据时始终保留 children，只在其上方显示紧凑状态条。
 */
export function AsyncStateBoundary({
  loading,
  error,
  reconnecting,
  hasData,
  isEmpty,
  onRetry,
  loadingTitle = '正在读取数据…',
  loadingSkeleton = false,
  skeletonRows = 3,
  emptyTitle,
  emptyDescription,
  emptyAction,
  children,
}: AsyncStateBoundaryProps) {
  if (!hasData && loading) {
    if (loadingSkeleton) {
      return (
        <div role="status" aria-label={loadingTitle}>
          {Array.from({ length: skeletonRows }, (_, i) => (
            <Skeleton key={i} variant="text" width={`${88 - i * 14}%`} height={34} />
          ))}
        </div>
      )
    }
    return <EmptyState variant="loading" title={loadingTitle} />
  }

  if (!hasData && error) {
    return (
      <EmptyState
        variant="error"
        title="数据读取失败"
        desc={`原因：${error}。影响：本区域尚未加载可用数据。处理：请重新读取；若持续失败，检查 API 与数据源状态。`}
        action={onRetry ? { label: '重新读取', onClick: onRetry } : undefined}
      />
    )
  }

  const notice = hasData && (loading || reconnecting || error)
    ? (
      <div
        className={`${s.notice} ${error ? s.warning : ''}`}
        role={error && !reconnecting ? 'alert' : 'status'}
        aria-live="polite"
      >
        <span>
          {reconnecting
            ? '连接中断，正在重试；当前显示上次成功数据'
            : error
              ? '更新失败；影响范围仅限本次刷新，当前仍显示上次成功数据'
              : '正在更新；当前数据仍可操作'}
        </span>
        {error && <small>原因：{error} · 处理：重新读取或前往运行故障页检查</small>}
        {onRetry && !loading && !reconnecting && (
          <Button variant="link" size="sm" onClick={onRetry}>重新读取</Button>
        )}
      </div>
    )
    : null

  return (
    <>
      {notice}
      {isEmpty ? (
        <EmptyState
          variant="no-data"
          title={emptyTitle}
          desc={emptyDescription}
          action={emptyAction}
        />
      ) : children}
    </>
  )
}
