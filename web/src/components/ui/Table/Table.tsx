// 通用表格：columns/rows API + render prop。支持行点击、键盘激活（↑↓/Home/End + Enter/Space）与展开行。
// 已替代：.tbl（2026-08-25 随五处裸 <table> 迁移删除）；.data-source-row / .simulation-row / .tasks-row 三套 div 网格随 F-2 迁移退役。
import { Fragment, type KeyboardEvent, type ReactNode } from 'react'
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
  /** 键盘激活：提供后行可聚焦，↑↓/Home/End 移动、Enter/Space 触发 */
  onRowActivate?: (row: T, index: number) => void
  /** 展开行内容；与 isRowExpanded 成对使用，仅对谓词为真的行渲染 */
  expandedRow?: (row: T, index: number) => ReactNode
  /** 行展开谓词（受控）；未提供时即使传了 expandedRow 也不展开 */
  isRowExpanded?: (row: T, index: number) => boolean
  activeRowKey?: string | null
  empty?: ReactNode
  className?: string
}

const ALIGN_CLASS: Record<Align, string> = {
  left: s.alignLeft,
  center: s.alignCenter,
  right: s.alignRight,
}

function handleRowActivateKeyDown<T>(
  event: KeyboardEvent<HTMLTableRowElement>,
  rows: T[],
  index: number,
  onRowActivate: (row: T, index: number) => void,
) {
  const tbody = event.currentTarget.closest('tbody')
  const rowEls = tbody ? Array.from(tbody.querySelectorAll<HTMLTableRowElement>('tr[data-row-index]')) : []
  let target: number | null = null
  if (event.key === 'ArrowDown') target = Math.min(index + 1, rowEls.length - 1)
  else if (event.key === 'ArrowUp') target = Math.max(index - 1, 0)
  else if (event.key === 'Home') target = 0
  else if (event.key === 'End') target = rowEls.length - 1
  else if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    onRowActivate(rows[index], index)
    return
  } else {
    return
  }
  event.preventDefault()
  rowEls[target]?.focus()
}

export function Table<T>({
  columns,
  rows,
  rowKey,
  density = 'comfortable',
  stickyHeader = false,
  onRowClick,
  onRowActivate,
  expandedRow,
  isRowExpanded,
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
              <Fragment key={key}>
                <tr
                  data-row-index={i}
                  tabIndex={onRowActivate ? 0 : undefined}
                  onKeyDown={onRowActivate ? (event) => handleRowActivateKeyDown(event, rows, i, onRowActivate) : undefined}
                  className={[onRowClick ? s.clickable : '', onRowActivate ? s.rowActivate : '', active ? s.selected : ''].filter(Boolean).join(' ')}
                  aria-selected={active || undefined}
                  onClick={onRowClick ? () => onRowClick(row, i) : undefined}
                >
                  {columns.map((col) => (
                    <td key={col.key} className={ALIGN_CLASS[col.align ?? 'left']}>
                      {col.render ? col.render(row, i) : String((row as Record<string, unknown>)[col.key] ?? '')}
                    </td>
                  ))}
                </tr>
                {expandedRow && isRowExpanded && isRowExpanded(row, i) ? (
                  <tr className={s.expandedRow}>
                    <td colSpan={columns.length}>{expandedRow(row, i)}</td>
                  </tr>
                ) : null}
              </Fragment>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
