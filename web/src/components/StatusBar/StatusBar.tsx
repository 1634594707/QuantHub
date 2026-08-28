import s from './StatusBar.module.css'
import { CONNECTION_LABELS, type ConnectionState } from '../../api/connection'
import { DATA_FRESHNESS_MS, isDataStale } from '../../api/freshness'
import { useLanguage } from '../../i18n'

// 上下文状态栏只在交易、重连或异常场景挂载，不重复常驻顶栏信息。
interface StatusBarProps {
  connectionState: ConnectionState
  reconnecting: boolean
  boardLabel: string
  updatedAt: number | null
}

export function StatusBar({
  connectionState,
  reconnecting,
  boardLabel,
  updatedAt,
}: StatusBarProps) {
  const { locale, t } = useLanguage()
  const stale = isDataStale(updatedAt, DATA_FRESHNESS_MS.connection, Date.now())
  return (
    <footer className={s.bar} aria-label={t('终端状态栏')}>
      {connectionState === 'online' ? (
        <span className={s.ok}>
          <span className={s.pulse} /> {t('实时连接正常')}
        </span>
      ) : reconnecting ? (
        <span className={s.warn}>
          <span className={s.pulse} /> {t('重连中…')}
        </span>
      ) : (
        <span className={s.warn}>● {t(CONNECTION_LABELS[connectionState].detail)}</span>
      )}
      <span>{t('当前上下文：')}{boardLabel}</span>
      <span className={s.clock}>
        {updatedAt ? `${t(stale ? '状态已过期' : '更新')} ${new Date(updatedAt).toLocaleTimeString(locale, { hour12: false })} · ` : ''}
        {new Date().toLocaleTimeString(locale, { hour12: false })}
      </span>
    </footer>
  )
}
