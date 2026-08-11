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
  const toneRank = { danger: 2, warning: 1, default: 0 } as const
  const activeItems = items
    .filter((item) => item.count > 0)
    .sort((a, b) => {
      const severity = toneRank[b.tone ?? 'default'] - toneRank[a.tone ?? 'default']
      return severity || b.count - a.count || a.label.localeCompare(b.label, 'zh-CN')
    })
  const zeroItems = items.filter((item) => item.count === 0)

  return (
    <section className={s.queue} aria-label="待处理事项">
      <header>
        <div><strong>行动队列</strong><span>信号、任务、订单与运行异常</span></div>
        <b>{total}</b>
      </header>
      <div className={s.items}>
        {activeItems.map((item) => (
          <Link className={`${s.item} ${item.tone ? s[item.tone] : ''}`} to={item.to} key={item.id}>
            <span>{item.label}</span>
            <b>{item.count}</b>
            <small>{item.detail}</small>
          </Link>
        ))}
        {activeItems.length === 0 ? <p className={s.empty}>当前无待处理事项</p> : null}
      </div>
      {zeroItems.length > 0 ? (
        <details className={s.zeroItems}>
          <summary>{zeroItems.length} 类队列当前为 0</summary>
          <div>
            {zeroItems.map((item) => <Link to={item.to} key={item.id}>{item.label}</Link>)}
          </div>
        </details>
      ) : null}
    </section>
  )
}
