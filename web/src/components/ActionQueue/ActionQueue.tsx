import { Link } from 'react-router-dom'
import s from './ActionQueue.module.css'

export interface ActionQueueItem {
  id: string
  label: string
  count: number
  detail: string
  to: string
  tone?: 'default' | 'warning' | 'danger'
}

export function ActionQueue({ items }: { items: ActionQueueItem[] }) {
  const total = items.reduce((sum, item) => sum + item.count, 0)
  return (
    <section className={s.queue} aria-label="待处理事项">
      <header>
        <div><strong>行动队列</strong><span>信号、任务、订单与运行异常</span></div>
        <b>{total}</b>
      </header>
      <div className={s.items}>
        {items.map((item) => (
          <Link className={`${s.item} ${item.tone ? s[item.tone] : ''}`} to={item.to} key={item.id}>
            <span>{item.label}</span>
            <b>{item.count}</b>
            <small>{item.detail}</small>
          </Link>
        ))}
      </div>
    </section>
  )
}
