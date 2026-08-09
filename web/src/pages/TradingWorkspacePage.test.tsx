import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import TradingWorkspacePage from './TradingWorkspacePage'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

function envelope<T>(data: T) {
  return {
    status: 'ok' as const,
    source: { kind: 'runner', name: 'okx_runner', environment: 'demo' },
    observed_at: '2026-08-09T15:00:00Z',
    freshness: { age_seconds: 1, ttl_seconds: 30, expired: false },
    error_code: null,
    data,
  }
}

function inputForLabel(labelText: RegExp): HTMLInputElement {
  const label = screen.getByText(
    (_content, element) =>
      Boolean(element?.tagName === 'LABEL' && (element.textContent ?? '').match(labelText)),
  ) as HTMLElement
  return label.closest('div')?.querySelector('input') as HTMLInputElement
}

describe('TradingWorkspacePage order and cancel flow (M2-08)', () => {
  beforeEach(() => {
    vi.spyOn(api, 'tradingHealth').mockResolvedValue(envelope({
      configured: true,
      reachable: true,
      environment: 'demo',
      trading_enabled: true,
      live_approved: false,
    }) as never)
    vi.spyOn(api, 'tradingSubmitOrder').mockResolvedValue(envelope({
      order_id: 'order-demo-1',
      client_order_id: 'client-demo-1',
      status: 'SUBMITTED',
    }) as never)
    vi.spyOn(api, 'tradingOrder').mockResolvedValue(envelope({
      order_id: 'order-demo-1',
      status: 'SUBMITTED',
    }) as never)
    vi.spyOn(api, 'tradingCancelOrder').mockResolvedValue(envelope({
      order_id: 'order-demo-1',
      status: 'CANCELLED',
    }) as never)
  })

  it('submits and cancels through confirmed page interactions', async () => {
    render(
      <MemoryRouter initialEntries={['/trading']}>
        <TradingWorkspacePage />
      </MemoryRouter>,
    )

    await waitFor(() => expect(api.tradingHealth).toHaveBeenCalled())
    fireEvent.change(inputForLabel(/^账户 ID/), { target: { value: 'demo-account' } })
    fireEvent.change(inputForLabel(/^策略 ID/), { target: { value: 'okx-momentum-1h' } })
    fireEvent.change(inputForLabel(/^策略版本/), { target: { value: '1.0.0' } })
    fireEvent.change(inputForLabel(/^数量/), { target: { value: '0.1' } })
    fireEvent.change(inputForLabel(/^价格/), { target: { value: '60000' } })

    const submit = screen.getByRole('button', { name: '提交订单' }) as HTMLButtonElement
    await waitFor(() => expect(submit.disabled).toBe(false))
    fireEvent.click(submit)
    fireEvent.click(screen.getByRole('button', { name: '确认提交' }))
    await waitFor(() => expect(api.tradingSubmitOrder).toHaveBeenCalledTimes(1))
    expect(api.tradingSubmitOrder).toHaveBeenCalledWith(expect.objectContaining({
      account_id: 'demo-account',
      strategy_id: 'okx-momentum-1h',
      strategy_version: '1.0.0',
      symbol: 'BTC-USDT-SWAP',
      order_type: 'limit',
      quantity: 0.1,
      price: 60000,
    }))

    const lookupInput = screen.getByPlaceholderText('订单 ID 或 client_order_id')
    fireEvent.change(lookupInput, { target: { value: 'order-demo-1' } })
    fireEvent.click(screen.getByRole('button', { name: '查询' }))
    await waitFor(() => expect(api.tradingOrder).toHaveBeenCalledWith('order-demo-1'))

    fireEvent.click(screen.getByRole('button', { name: '撤单' }))
    fireEvent.click(screen.getByRole('button', { name: '确认撤单' }))
    await waitFor(() => expect(api.tradingCancelOrder).toHaveBeenCalledWith('order-demo-1'))
    expect(await screen.findByText(/CANCELLED/)).not.toBeNull()
  })
})
