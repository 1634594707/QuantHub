import s from './StatusBar.module.css'
import { CONNECTION_LABELS, type ConnectionState } from '../../api/connection'
import { DATA_FRESHNESS_MS, isDataStale } from '../../api/freshness'

// 终端状态栏：显示连接态、板块、信号策略计数、全局检索入口和本地时钟。
interface StatusBarProps {
  connectionState: ConnectionState
  reconnecting: boolean
  boardLabel: string
  signalCount: number
  strategyCount: number
  clock: Date
  updatedAt: number | null
  onOpenCmdk: () => void
}

export function StatusBar({
  connectionState,
  reconnecting,
  boardLabel,
  signalCount,
  strategyCount,
  clock,
  updatedAt,
  onOpenCmdk,
}: StatusBarProps) {
  const stale = isDataStale(updatedAt, DATA_FRESHNESS_MS.connection, clock.getTime())
  return (
    <footer className={s.bar} aria-label="终端状态栏">
      {connectionState === 'online' ? (
        <span className={s.ok}>
          <span className={s.pulse} /> 实时连接正常
        </span>
      ) : reconnecting ? (
        <span className={s.warn}>
          <span className={s.pulse} /> 重连中…（保留旧数据）
        </span>
      ) : (
        <span className={s.warn}>● {CONNECTION_LABELS[connectionState].detail}</span>
      )}
      <span>当前板块：{boardLabel}</span>
      <span>
        信号 {signalCount} · 策略 {strategyCount}
      </span>
      <button className={s.search} onClick={onOpenCmdk} aria-label="打开命令面板">
        全局检索
      </button>
      <span className={s.clock}>
        {updatedAt ? `${stale ? '状态已过期' : '更新'} ${new Date(updatedAt).toLocaleTimeString('zh-CN', { hour12: false })} · ` : ''}
        {clock.toLocaleTimeString('zh-CN', { hour12: false })} · 本地时间
      </span>
    </footer>
  )
}
