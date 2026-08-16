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
    vi.spyOn(api, 'tradingPreflight').mockResolvedValue(envelope({
      environment: 'demo',
      observed_at: '2026-08-09T15:00:00Z',
      account: { account_level: '2', position_mode: 'net_mode', permissions: ['trade'] },
      ip_whitelist: { field_exposed: true, status: 'not_configured' },
      clock: { server_time_available: true, absolute_drift_ms: 100, within_tolerance: true, tolerance_ms: 5000 },
      instruments: [{
        symbol: 'BTC-USDT-SWAP', exchange_symbol: 'BTC/USDT:USDT', product_type: 'swap', active: true,
        settle_currency: 'USDT', minimum_quantity: 0.01, quantity_step: 0.01, price_tick: 0.1,
        contract_size: 0.01, minimum_notional: 6, minimum_notional_estimated: true,
        maximum_leverage: 100, reference_price: 65000,
      }],
    }) as never)
    vi.spyOn(api, 'tradingDashboard').mockResolvedValue(envelope({
      strategies: [{
        strategy_id: 'okx-demo-minimal', version: '1.0.2', content_hash: 'a'.repeat(64),
        imported_at: '2026-08-09T15:00:00Z', package: {
          signal_frequency: '1h', rebalance_frequency: '4h', risk_limits: { max_leverage: 2 },
        },
      }],
      orders: [], fills: [],
      balances: [{ account_id: 'okx-demo-account', environment: 'demo', currency: 'USDT', total: 1008, available: 900, observed_at: '2026-08-09T15:00:00Z' }],
      positions: [{ account_id: 'okx-demo-account', environment: 'demo', symbol: 'BTC-USDT-SWAP', quantity: 0.01, mark_price: 65000, entry_price: 64000, unrealized_pnl: 10, leverage: 1, position_side: 'long', observed_at: '2026-08-09T15:00:00Z' }],
      account_summary: { accounts: [{ account_id: 'okx-demo-account', environment: 'demo', equity: 1008, initial_equity: 1000, equity_change: 8, realized_pnl: -2, unrealized_pnl: 10, total_pnl: 8, peak_equity: 1010, max_drawdown: -0.01, observed_at: '2026-08-09T15:00:00Z' }] },
      reconciliation_diffs: [],
      risk_states: [{ scope: 'global', mode: 'normal', reason: 'test', updated_at: '2026-08-09T15:00:00Z' }],
      account_status: { environment: 'demo', connected: true, permissions: 'trade', latest_snapshot_at: '2026-08-09T15:00:00Z', stale: false, last_reconciliation_at: null, server_time: '2026-08-09T15:00:00Z' },
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
    vi.spyOn(api, 'tradingClosePosition').mockResolvedValue(envelope({
      order_id: 'close-demo-1',
      status: 'SUBMITTED',
    }) as never)
    vi.spyOn(api, 'tradingAmendOrder').mockResolvedValue(envelope({
      order_id: 'order-demo-1',
      status: 'SUBMITTED',
    }) as never)
  })

  it('submits and cancels through confirmed page interactions', async () => {
    render(
      <MemoryRouter initialEntries={['/trading']}>
        <TradingWorkspacePage />
      </MemoryRouter>,
    )

    await waitFor(() => expect(api.tradingHealth).toHaveBeenCalled())
    fireEvent.change(inputForLabel(/^本地账户账本/), { target: { value: 'demo-account' } })
    fireEvent.change(inputForLabel(/^数量/), { target: { value: '0.01' } })
    fireEvent.change(inputForLabel(/^限价/), { target: { value: '60000' } })

    const submit = screen.getByRole('button', { name: '提交 Demo 订单' }) as HTMLButtonElement
    await waitFor(() => expect(submit.disabled).toBe(false))
    fireEvent.click(submit)
    fireEvent.click(screen.getByRole('button', { name: '确认提交' }))
    await waitFor(() => expect(api.tradingSubmitOrder).toHaveBeenCalledTimes(1))
    expect(api.tradingSubmitOrder).toHaveBeenCalledWith(expect.objectContaining({
      account_id: 'demo-account',
      strategy_id: 'okx-demo-minimal',
      strategy_version: '1.0.2',
      symbol: 'BTC-USDT-SWAP',
      order_type: 'limit',
      quantity: 0.01,
      price: 60000,
    }))

    const lookupInput = screen.getByPlaceholderText('内部订单 ID')
    fireEvent.change(lookupInput, { target: { value: 'order-demo-1' } })
    fireEvent.click(screen.getByRole('button', { name: '查询' }))
    await waitFor(() => expect(api.tradingOrder).toHaveBeenCalledWith('order-demo-1'))

    fireEvent.click(screen.getByRole('button', { name: '撤单' }))
    fireEvent.click(screen.getByRole('button', { name: '确认撤单' }))
    await waitFor(() => expect(api.tradingCancelOrder).toHaveBeenCalledWith('order-demo-1'))
    expect(await screen.findByText(/CANCELLED/)).not.toBeNull()
  })

  it('retains the same intent until the operator explicitly starts a new intent', async () => {
    render(
      <MemoryRouter initialEntries={['/trading']}>
        <TradingWorkspacePage />
      </MemoryRouter>,
    )
    fireEvent.change(inputForLabel(/^限价/), { target: { value: '60000' } })
    const submit = await screen.findByRole('button', { name: '提交 Demo 订单' })
    await waitFor(() => expect((submit as HTMLButtonElement).disabled).toBe(false))

    fireEvent.click(submit)
    fireEvent.click(screen.getByRole('button', { name: '确认提交' }))
    await waitFor(() => expect(api.tradingSubmitOrder).toHaveBeenCalledTimes(1))
    fireEvent.click(submit)
    fireEvent.click(screen.getByRole('button', { name: '确认提交' }))
    await waitFor(() => expect(api.tradingSubmitOrder).toHaveBeenCalledTimes(2))

    const first = vi.mocked(api.tradingSubmitOrder).mock.calls[0][0]
    const second = vi.mocked(api.tradingSubmitOrder).mock.calls[1][0]
    expect(second.intent_id).toBe(first.intent_id)

    fireEvent.click(screen.getByRole('button', { name: '新意图' }))
    expect(inputForLabel(/^订单意图/).value).not.toBe(first.intent_id)
  })

  it('shows synchronized equity, pnl, balances and positions', async () => {
    render(
      <MemoryRouter initialEntries={['/trading']}>
        <TradingWorkspacePage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('1,008.00 USD')).not.toBeNull()
    expect(screen.getByText('8.00 USD')).not.toBeNull()
    expect(screen.getAllByText('BTC-USDT-SWAP').length).toBeGreaterThan(0)
    expect(screen.getByText('64,000.0000')).not.toBeNull()
    expect(screen.getAllByText('USDT').length).toBeGreaterThan(0)
  })

  it('supports market orders without a client price and quick reduce-only close', async () => {
    render(
      <MemoryRouter initialEntries={['/trading']}>
        <TradingWorkspacePage />
      </MemoryRouter>,
    )

    fireEvent.click(await screen.findByRole('tab', { name: '市价' }))
    const submit = screen.getByRole('button', { name: '提交 Demo 订单' }) as HTMLButtonElement
    await waitFor(() => expect(submit.disabled).toBe(false))
    fireEvent.click(submit)
    fireEvent.click(screen.getByRole('button', { name: '确认提交' }))
    await waitFor(() => expect(api.tradingSubmitOrder).toHaveBeenCalledWith(expect.objectContaining({
      order_type: 'market',
      price: null,
    })))

    fireEvent.click(screen.getByRole('button', { name: '平仓' }))
    fireEvent.click(screen.getByRole('button', { name: '确认平仓' }))
    await waitFor(() => expect(api.tradingClosePosition).toHaveBeenCalledWith(
      'okx-demo-account',
      'BTC-USDT-SWAP',
      expect.objectContaining({ order_type: 'market', quantity: 0.01 }),
    ))
  })
})
