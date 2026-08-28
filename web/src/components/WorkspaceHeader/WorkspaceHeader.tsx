import type { ReactNode } from 'react'
import s from './WorkspaceHeader.module.css'
import { useLanguage } from '../../i18n'

export interface WorkspaceHeaderMetric {
  label: ReactNode
  value: ReactNode
}

interface Props {
  context: string
  title: ReactNode
  description?: ReactNode
  metrics?: WorkspaceHeaderMetric[]
  action?: ReactNode
  ariaLabel?: string
}

export function WorkspaceHeader({
  context,
  title,
  description,
  metrics = [],
  action,
  ariaLabel,
}: Props) {
  const { t } = useLanguage()
  const translateNode = (value: ReactNode) => typeof value === 'string' ? t(value) : value

  return (
    <header className={s.header} aria-label={t(ariaLabel ?? context)}>
      <div className={s.identity}>
        <span className={s.context}>{t(context)}</span>
        <div className={s.titleLine}>
          <h1>{translateNode(title)}</h1>
          {description ? <p>{translateNode(description)}</p> : null}
        </div>
      </div>

      {metrics.length > 0 ? (
        <dl className={s.metrics}>
          {metrics.map((metric, index) => (
            <div key={index} className={s.metric}>
              <dt>{translateNode(metric.label)}</dt>
              <dd>{translateNode(metric.value)}</dd>
            </div>
          ))}
        </dl>
      ) : null}

      {action ? <div className={s.action}>{action}</div> : null}
    </header>
  )
}
