import type { ReactNode } from 'react'
import s from './ContextBar.module.css'
import { useLanguage } from '../../i18n'

export interface ContextBarItem {
  label: string
  value: ReactNode
  mono?: boolean
}

export function ContextBar({ items, children }: { items: ContextBarItem[]; children?: ReactNode }) {
  const { t } = useLanguage()
  const translateNode = (value: ReactNode) => typeof value === 'string' ? t(value) : value

  return (
    <section className={s.bar} aria-label={t('当前工作上下文')}>
      <dl className={s.items}>
        {items.map((item) => (
          <div key={item.label}>
            <dt>{t(item.label)}</dt>
            <dd className={item.mono ? s.mono : undefined}>{translateNode(item.value)}</dd>
          </div>
        ))}
      </dl>
      {children && <div className={s.controls}>{children}</div>}
    </section>
  )
}
