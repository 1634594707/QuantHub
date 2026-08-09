import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ConfirmActionButton } from './ConfirmActionButton'

afterEach(() => cleanup())

/**
 * M2-08 / Q0-01 真实交互覆盖（P2 缺口修复）。
 *
 * 原 `keyFlows.test.ts` 只断言「导航配置点击深度」，没有真实渲染与点击。
 * 这里对「二次确认」按钮做真实点击 → 弹窗 → 确认/取消 的交互验证，
 * 覆盖下单 / 撤单 / 停机 三类高危操作共用的安全确认机制。
 */
describe('ConfirmActionButton real interaction', () => {
  it('opens the confirm dialog on click and fires onConfirm when confirmed', async () => {
    const onConfirm = vi.fn().mockResolvedValue(undefined)
    render(<ConfirmActionButton label="下单" title="确认下单" description="将以限价提交" onConfirm={onConfirm} />)

    fireEvent.click(screen.getByRole('button', { name: '下单' }))
    expect(screen.queryByText('确认下单')).not.toBeNull()

    fireEvent.click(screen.getByRole('button', { name: '确认执行' }))
    await waitFor(() => expect(onConfirm).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(screen.queryByText('确认下单')).toBeNull())
  })

  it('does NOT fire onConfirm when the user cancels', () => {
    const onConfirm = vi.fn()
    render(<ConfirmActionButton label="撤单" title="确认撤单" description="撤销该订单" onConfirm={onConfirm} />)

    fireEvent.click(screen.getByRole('button', { name: '撤单' }))
    expect(screen.queryByText('确认撤单')).not.toBeNull()

    fireEvent.click(screen.getByRole('button', { name: '返回' }))
    expect(onConfirm).not.toHaveBeenCalled()
    expect(screen.queryByText('确认撤单')).toBeNull()
  })

  it('keeps the trigger disabled when disabled prop is set', () => {
    const onConfirm = vi.fn()
    render(<ConfirmActionButton label="停机" title="确认停机" description="全面停机" disabled onConfirm={onConfirm} />)
    expect((screen.getByRole('button', { name: '停机' }) as HTMLButtonElement).disabled).toBe(true)
  })
})
