import { useEffect, useState } from 'react'
import { DATA_FRESHNESS_MS, isDataStale } from '../../../api/freshness'
import { Button } from '../Button/Button'
import s from './RefreshControl.module.css'

interface RefreshControlProps {
  onRefresh: () => void
  refreshing: boolean
  updatedAt: number | null
  label?: string
  variant?: 'secondary' | 'link'
  staleAfterMs?: number
}

function formatUpdatedAt(value: number | null): string {
  if (value === null) return '等待首次更新'
  return `最后更新 ${new Date(value).toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })}`
}

export function RefreshControl({
  onRefresh,
  refreshing,
  updatedAt,
  label = '刷新',
  variant = 'link',
  staleAfterMs = DATA_FRESHNESS_MS.operational,
}: RefreshControlProps) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 15_000)
    return () => window.clearInterval(timer)
  }, [])
  const stale = isDataStale(updatedAt, staleAfterMs, now)
  return (
    <div className={s.control} aria-live="polite">
      <span className={`${s.time} ${stale ? s.stale : ''}`}>
        {stale ? `数据已过期 · ${formatUpdatedAt(updatedAt)}` : formatUpdatedAt(updatedAt)}
      </span>
      <Button variant={variant} size="sm" onClick={onRefresh} loading={refreshing}>
        {label}
      </Button>
    </div>
  )
}
