// 通用表格：columns/rows API + render prop，替代 .tbl / .data-source-row / .simulation-row / .tasks-row 4 套。
import type { ReactNode } from 'react'
import { EmptyState } from '../EmptyState/EmptyState'
import s from './Table.module.css'

type Density = 'comfortable' | 'compact'
type Align = 'left' | 'center' | 'right'

export interface Column<T> {
  key: string
  header: ReactNode
  render?: (row: T, index: number) => ReactNode
  width?: string | number
  align?: Align
}

interface TableProps<T> {
  columns: Column<T>[]
  rows: T[]
  rowKey?: (row: T, index: number) => string
  density?: Density
  stickyHeader?: boolean
  onRowClick?: (row: T, index: number) => void
  activeRowKey?: string | null
  empty?: ReactNode
  className?: string
}

const ALIGN_CLASS: Record<Align, string> = {
  left: s.alignLeft,
  center: s.alignCenter,
  right: s.alignRight,
}

export function Table<T>({
  columns,
  rows,
  rowKey,
  density = 'comfortable',
  stickyHeader = false,
  onRowClick,
  activeRowKey,
  empty,
  className,
}: TableProps<T>) {
  if (rows.length === 0) {
    return (
      <div className={s.emptyWrap}>
        {empty ?? <EmptyState variant="no-data" title="暂无数据" />}
      </div>
    )
  }

  return (
    <div className={[s.scrollWrap, className ?? ''].filter(Boolean).join(' ')}>
      <table className={[s.table, density === 'compact' ? s.compact : s.comfortable].join(' ')}>
        <thead className={stickyHeader ? s.stickyHead : undefined}>
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                className={ALIGN_CLASS[col.align ?? 'left']}
                style={col.width ? { width: col.width } : undefined}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => {
            const key = rowKey ? rowKey(row, i) : String(i)
            const active = activeRowKey === key
            return (
              <tr
                key={key}
                className={[onRowClick ? s.clickable : '', active ? s.selected : ''].filter(Boolean).join(' ')}
                aria-selected={active || undefined}
                onClick={onRowClick ? () => onRowClick(row, i) : undefined}
              >
                {columns.map((col) => (
                  <td key={col.key} className={ALIGN_CLASS[col.align ?? 'left']}>
                    {col.render ? col.render(row, i) : String((row as Record<string, unknown>)[col.key] ?? '')}
                  </td>
                ))}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
