import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { api } from '../api/client'
import SimulationOrdersPage from './SimulationOrdersPage'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('SimulationOrdersPage risk gate', () => {
  it('keeps create disabled and exposes server reason codes when risk rejects', async () => {
    vi.spyOn(api, 'simulationOrders').mockResolvedValue({
      ok: true, count: 0, total: 0, next_cursor: null, orders: [],
    })
    vi.spyOn(api, 'simulationAccount').mockResolvedValue({
      ok: true,
      mode: 'paper',
      starting_cash: 1_000_000,
      cash: 1_000_000,
      market_value: 0,
      equity: 1_000_000,
      total_fees: 0,
      realized_pnl: 0,
      unrealized_pnl: 0,
      positions: [],
      order_count: 0,
      execution_count: 0,
      reconciled: true,
      reconciliation_issues: [],
    })
    vi.spyOn(api, 'previewSimulationOrder').mockResolvedValue({
      ok: true,
      preview: {
        symbol: 'AAPL', market: 'us_stocks', side: 'buy', quantity: 100,
        price: null, order_notional: null, current_quantity: 0, projected_quantity: 100,
        gross_exposure_before: 0, gross_exposure_after: null, cash_before: 1_000_000,
        cash_after: null, equity: 1_000_000, risk_evaluated: true, can_submit: false,
        outcome: 'rejected', reason_codes: ['MARKET_PRICE_MISSING'],
        checks: [{ code: 'MARKET_PRICE_MISSING', status: 'failed', actual: null, limit: null, reevaluate_action: '刷新行情后重新预览' }],
        snapshot: { market: {}, account: {}, open_order_count: 0, cost_profile: {}, research_decision: null },
        evaluated_at: '2026-08-16T00:00:00Z', rule_version: 'simulation-risk-v1', input_fingerprint: 'a'.repeat(64),
      },
    })
    const create = vi.spyOn(api, 'createSimulationOrder')

    render(
      <MemoryRouter initialEntries={['/simulation?symbol=AAPL&market=us_stocks']}>
        <SimulationOrdersPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('MARKET_PRICE_MISSING')).toBeTruthy()
    expect(screen.getByText('刷新行情后重新预览')).toBeTruthy()
    const button = screen.getByRole('button', { name: '创建模拟订单' }) as HTMLButtonElement
    await waitFor(() => expect(button.disabled).toBe(true))
    expect(create).not.toHaveBeenCalled()
  })
})
