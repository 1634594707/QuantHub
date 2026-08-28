import { AlertTriangle, RefreshCw } from 'lucide-react'
import type { HealthResp } from '../api/types'
import { useLanguage } from '../i18n'
import s from './ApiRestartNotice.module.css'

interface ApiRestartNoticeProps {
  health: HealthResp | null
  checking: boolean
  onCheck: () => void
}

export function ApiRestartNotice({ health, checking, onCheck }: ApiRestartNoticeProps) {
  const { t } = useLanguage()
  if (!health?.restart_required) return null
  return (
    <aside className={s.notice} role="alert">
      <AlertTriangle size={18} />
      <div>
        <strong>{t('API 源码已变化，需要重启服务')}</strong>
        <span>{t('版本')} {health.version} · {t('运行中')} {health.build_id} · {t('当前源码')} {health.current_source_build_id}</span>
      </div>
      <button type="button" onClick={onCheck} disabled={checking}>
        <RefreshCw size={15} className={checking ? s.spinning : undefined} />
        <span>{t('重新检查')}</span>
      </button>
    </aside>
  )
}
