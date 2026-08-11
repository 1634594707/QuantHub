import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { ActionQueue } from './ActionQueue'

afterEach(cleanup)

describe('ActionQueue priority', () => {
  it('sorts active work by severity and count, then collapses zero-count categories', () => {
    render(
      <MemoryRouter>
        <ActionQueue items={[
          { id: 'largest', label: '普通十项', count: 10, detail: '普通', to: '/normal' },
          { id: 'warning', label: '警告五项', count: 5, detail: '警告', to: '/warning', tone: 'warning' },
          { id: 'danger', label: '故障一项', count: 1, detail: '故障', to: '/danger', tone: 'danger' },
          { id: 'zero', label: '无需处理', count: 0, detail: '已清空', to: '/zero' },
        ]} />
      </MemoryRouter>,
    )

    const queue = screen.getByRole('region', { name: '待处理事项' })
    const links = Array.from(queue.querySelectorAll('a')).map((link) => link.textContent)
    expect(links.slice(0, 3)).toEqual([
      '故障一项1故障',
      '警告五项5警告',
      '普通十项10普通',
    ])
    const zeroSummary = screen.getByText('1 类队列当前为 0')
    expect(zeroSummary.closest('details')?.open).toBe(false)
  })
})
