import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import AccountRiskPage from './AccountRiskPage'

afterEach(() => cleanup())

function mockApi() {
  vi.spyOn(api, 'tradingHealth').mockResolvedValue({
    data: { configured: true, reachable: true, environment: 'shadow' },
  } as never)
  vi.spyOn(api, 'tradingSetRiskMode').mockResolvedValue({
    data: { ok: true, mode: 'halted', scope: 'global' },
  } as never)
}

/** Field 用非关联 label 包裹 input，按标签文本定位其输入框。 */
function inputForLabel(labelText: RegExp): HTMLInputElement {
  const label = screen.getByText(
    (_content, element) =>
      Boolean(element?.tagName === 'LABEL' && (element.textContent ?? '').match(labelText)),
  ) as HTMLElement
  const field = label.closest('div') as HTMLElement
  return field.querySelector('input') as HTMLInputElement
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/account-risk']}>
      <AccountRiskPage />
    </MemoryRouter>,
  )
}

/**
 * M2-08 / Q0-01 真实交互覆盖（P2 缺口修复）—— 停机（halt）流程。
 *
 * 验证：渲染账户风控页后，用户在「风险模式」面板填入操作者/原因、把目标模式切到
 * halted、点击「应用风险模式」并二次确认，最终真实驱动 `api.tradingSetRiskMode`
 * 调用。这是「查标的 → 审信号 → 下单 → 撤单 → 停机 → 对账」六项关键流程中
 * 停机环节的真实端到端点击，而非仅断言导航配置深度。
 */
describe('AccountRiskPage halt flow (M2-08)', () => {
  beforeEach(() => mockApi())

  it('drives api.tradingSetRiskMode with halted when confirmed', async () => {
    renderPage()

    await waitFor(() => expect(api.tradingHealth).toHaveBeenCalled())

    fireEvent.change(inputForLabel(/操作者/), { target: { value: 'alice' } })
    fireEvent.change(inputForLabel(/变更原因/), { target: { value: '盘中异常，先行停机' } })
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'halted' } })

    const applyButton = screen.getByRole('button', { name: '应用风险模式' }) as HTMLButtonElement
    await waitFor(() => expect(applyButton.disabled).toBe(false))

    fireEvent.click(applyButton)
    expect(screen.queryByText(/变更风险模式/)).not.toBeNull()

    fireEvent.click(screen.getByRole('button', { name: '确认变更' }))

    await waitFor(() =>
      expect(api.tradingSetRiskMode).toHaveBeenCalledWith({
        scope: 'global',
        mode: 'halted',
        operator: 'alice',
        reason: '盘中异常，先行停机',
      }),
    )
  })
})
