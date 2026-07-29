import type { ReactNode } from 'react'
import s from './WorkspaceHeader.module.css'

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
  return (
    <header className={s.header} aria-label={ariaLabel ?? context}>
      <div className={s.identity}>
        <span className={s.context}>{context}</span>
        <div className={s.titleLine}>
          <h1>{title}</h1>
          {description ? <p>{description}</p> : null}
        </div>
      </div>

      {metrics.length > 0 ? (
        <dl className={s.metrics}>
          {metrics.map((metric, index) => (
            <div key={index} className={s.metric}>
              <dt>{metric.label}</dt>
              <dd>{metric.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}

      {action ? <div className={s.action}>{action}</div> : null}
    </header>
  )
}
