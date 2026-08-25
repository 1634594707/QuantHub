import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Table } from './Table'

afterEach(() => {
  cleanup()
})

const rows = [
  { id: 'a', name: 'Alpha' },
  { id: 'b', name: 'Beta' },
]

function baseColumns() {
  return [
    { key: 'name', header: '名称' as const, render: (r: (typeof rows)[number]) => r.name },
    { key: 'op', header: '操作' as const, render: () => <button type="button">动作</button> },
  ]
}

describe('Table', () => {
  it('渲染表头与单元格 render 结果', () => {
    render(<Table rows={rows} rowKey={(r) => r.id} columns={baseColumns()} />)
    expect(screen.getByText('名称')).toBeTruthy()
    expect(screen.getByText('Alpha')).toBeTruthy()
    expect(screen.getByText('Beta')).toBeTruthy()
  })

  it('点击行触发 onRowClick', () => {
    const onRowClick = vi.fn()
    render(<Table rows={rows} rowKey={(r) => r.id} columns={baseColumns()} onRowClick={onRowClick} />)
    fireEvent.click(screen.getByText('Beta'))
    expect(onRowClick).toHaveBeenCalledWith(rows[1], 1)
  })

  it('键盘 ↓ 移动聚焦，Enter 触发 onRowActivate 并回传行数据与索引', () => {
    const onRowActivate = vi.fn()
    render(<Table rows={rows} rowKey={(r) => r.id} columns={baseColumns()} onRowActivate={onRowActivate} />)
    const first = screen.getByText('Alpha').closest('tr') as HTMLTableRowElement
    const second = screen.getByText('Beta').closest('tr') as HTMLTableRowElement
    expect(first.getAttribute('tabindex')).toBe('0')
    first.focus()
    fireEvent.keyDown(first, { key: 'ArrowDown' })
    expect(document.activeElement).toBe(second)
    fireEvent.keyDown(second, { key: 'Enter' })
    expect(onRowActivate).toHaveBeenCalledWith(rows[1], 1)
  })

  it('expandedRow 受 isRowExpanded 控制并渲染整行内容', () => {
    render(
      <Table
        rows={rows}
        rowKey={(r) => r.id}
        columns={baseColumns()}
        expandedRow={(r) => '详情-' + r.name}
        isRowExpanded={(r) => r.id === 'a'}
      />,
    )
    expect(screen.getByText('详情-Alpha')).toBeTruthy()
    expect(screen.queryByText('详情-Beta')).toBeNull()
    const expandedTd = screen.getByText('详情-Alpha').closest('td') as HTMLTableCellElement
    expect(expandedTd.colSpan).toBe(2)
  })

  it('仅传 expandedRow 未传谓词时不渲染展开行', () => {
    render(
      <Table rows={rows} rowKey={(r) => r.id} columns={baseColumns()} expandedRow={(r) => '详情-' + r.name} />,
    )
    expect(screen.queryByText(/详情-/)).toBeNull()
  })

  it('空行且未传 empty 时展示默认空态', () => {
    render(<Table rows={[]} columns={baseColumns()} />)
    expect(screen.getByText('暂无数据')).toBeTruthy()
  })
})
