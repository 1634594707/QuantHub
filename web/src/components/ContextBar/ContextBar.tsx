import type { ReactNode } from 'react'
import s from './ContextBar.module.css'

export interface ContextBarItem {
  label: string
  value: ReactNode
  mono?: boolean
}

export function ContextBar({ items, children }: { items: ContextBarItem[]; children?: ReactNode }) {
  return (
    <section className={s.bar} aria-label="当前工作上下文">
      <dl className={s.items}>
        {items.map((item) => (
          <div key={item.label}>
            <dt>{item.label}</dt>
            <dd className={item.mono ? s.mono : undefined}>{item.value}</dd>
          </div>
        ))}
      </dl>
      {children && <div className={s.controls}>{children}</div>}
    </section>
  )
}
