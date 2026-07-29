import type { ReactNode } from 'react'
import { Button } from '../Button/Button'
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
  emptyTitle,
  emptyDescription,
  emptyAction,
  children,
}: AsyncStateBoundaryProps) {
  if (!hasData && loading) {
    return <EmptyState variant="loading" title={loadingTitle} />
  }

  if (!hasData && error) {
    return (
      <EmptyState
        variant="error"
        title="数据读取失败"
        desc={error}
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
              ? '更新失败；当前显示上次成功数据'
              : '正在更新；当前数据仍可操作'}
        </span>
        {error && <small>{error}</small>}
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
