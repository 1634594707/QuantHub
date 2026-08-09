import { Badge } from '../ui/Badge/Badge'
import type { ContractEnvelope, ContractStatus } from '../../api/types'
import s from './ContractStatusBar.module.css'

/**
 * 统一数据来源与新鲜度状态条（M3-03 / M3-04）。
 *
 * 只读取 apps/api/contracts.py 的响应外壳字段，不认识业务字段，
 * 因此任何接入统一契约的接口都能复用同一套「有数据 / 无数据 / 源异常 / 已过期」表达。
 * 严禁在此处伪造数字或用占位值替代真实状态。
 */

const STATUS_META: Record<ContractStatus, { label: string; variant: 'up' | 'warn' | 'down' | 'neutral' }> = {
  ok: { label: '实时', variant: 'up' },
  stale: { label: '已过期', variant: 'warn' },
  empty: { label: '无数据', variant: 'neutral' },
  error: { label: '源异常', variant: 'down' },
}

const SOURCE_KIND_LABELS: Record<string, string> = {
  runner: 'OKX Runner',
  database: '本地数据库',
  external: '外部数据源',
  derived: '派生计算',
  none: '未配置',
}

function formatObservedAt(value: string | null): string {
  if (!value) return '无观测时间'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString('zh-CN', { hour12: false })
}

function formatAge(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '—'
  if (seconds < 60) return `${Math.round(seconds)} 秒前`
  if (seconds < 3600) return `${Math.round(seconds / 60)} 分钟前`
  return `${(seconds / 3600).toFixed(1)} 小时前`
}

interface Props {
  envelope: ContractEnvelope<unknown> | null
  /** 请求本身失败（网络层/HTTP 层）时的补充说明，与契约外壳并列展示。 */
  transportError?: string | null
  label?: string
}

export function ContractStatusBar({ envelope, transportError, label }: Props) {
  if (transportError) {
    return (
      <div className={`${s.bar} ${s.error}`} role="status">
        <Badge variant="down" dot>网关异常</Badge>
        <span className={s.text}>{label ? `${label}：` : ''}{transportError}</span>
      </div>
    )
  }

  if (!envelope) {
    return (
      <div className={s.bar} role="status">
        <Badge variant="neutral" dot>未读取</Badge>
        <span className={s.text}>{label ? `${label}：` : ''}尚未发起请求</span>
      </div>
    )
  }

  const meta = STATUS_META[envelope.status] ?? STATUS_META.error
  const sourceKind = SOURCE_KIND_LABELS[envelope.source?.kind] ?? envelope.source?.kind ?? '未知来源'
  const environment = envelope.source?.environment

  return (
    <div className={`${s.bar} ${envelope.status === 'error' ? s.error : ''}`} role="status">
      <Badge variant={meta.variant} dot>{meta.label}</Badge>
      {label ? <span className={s.label}>{label}</span> : null}
      <span className={s.text}>
        来源 {sourceKind}
        {envelope.source?.name ? ` · ${envelope.source.name}` : ''}
        {environment ? ` · ${environment}` : ''}
      </span>
      <span className={s.text}>
        观测于 {formatObservedAt(envelope.observed_at)}（{formatAge(envelope.freshness?.age_seconds ?? -1)}）
      </span>
      {envelope.error_code ? (
        <span className={s.code} title={envelope.detail ?? undefined}>
          错误码 {envelope.error_code}
          {envelope.message ? ` · ${envelope.message}` : ''}
        </span>
      ) : null}
      {envelope.hint ? <span className={s.hint}>处理建议：{envelope.hint}</span> : null}
    </div>
  )
}
