import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { FactorFactoryRunResponse } from '../api/types'
import { FactorCohortPanel } from './FactorCohortPanel'

const curve = (base: number) => [
  { t: '2026-08-12T00:00:00Z', equity: base },
  { t: '2026-08-12T01:00:00Z', equity: base * 1.01 },
  { t: '2026-08-12T02:00:00Z', equity: base * 1.02 },
]

const run = {
  ok: true,
  run: {
    id: 'run-1', research_plan_id: 'plan-1', status: 'paper_observing', config: {}, result: {},
    selected_factor_key: 'candidate', selected_factor_version: '1.0.0', selected_experiment_id: 'exp-1',
    error: null, started_at: 1, updated_at: 1, observation_started_at: 1, observation_ends_at: 2,
  },
  candidates: [], observations: [], simulation_orders: [],
  observation_summary: { count: 0, latest_equity: null, after_cost_return: null, max_drawdown: 0 },
  market_data_status: {
    event_time: '2026-08-12T02:00:00Z', bar_open_time: '2026-08-12T01:00:00Z',
    bar_close_time: '2026-08-12T02:00:00Z', fetched_at: '2026-08-12T02:00:01Z',
    received_at: '2026-08-12T02:00:01Z', is_closed: true, age_ms: 1000, source: 'okx_public_ws',
    quality_status: 'fresh', event_kind: 'closed_bar_live', forming_bars_excluded: 1,
    research_signal_allowed: true, market_open: true,
  },
  cohort: {
    definition: { cohort_id: 'cohort-1' }, status: 'cohort_observing', engine_version: '1.1.0',
    start_market_time: '2026-08-12T00:00:00Z',
    latest_report: {
      ranking: [
        { member_key: 'candidate:1.0.0', metrics: { after_cost_return: 0.02, sharpe: 1.2, max_drawdown: 0.03, final_equity: 102000, capital_utilization: 0.5, turnover: 1.2, trade_count: 3, fees: 20, slippage_cost: 4, funding_pnl: -1 } },
        { member_key: 'buy_hold', metrics: { after_cost_return: 0.015, sharpe: 0.9, max_drawdown: 0.04, final_equity: 101500, capital_utilization: 1, turnover: 1, trade_count: 1, fees: 10, slippage_cost: 2, funding_pnl: 0 } },
        { member_key: 'grid_arithmetic', metrics: { after_cost_return: 0.01, sharpe: 0.7, max_drawdown: 0.02, final_equity: 101000, capital_utilization: 0.4, turnover: 2, trade_count: 8, fees: 30, slippage_cost: 5, funding_pnl: 0 } },
        { member_key: 'cash', metrics: { after_cost_return: 0, sharpe: 0, max_drawdown: 0 } },
      ],
      ledgers: {
        'candidate:1.0.0': { equity_curve: curve(100000), orders: [], executions: [], risk_events: [] },
        buy_hold: { equity_curve: curve(100000), orders: [], executions: [], risk_events: [] },
        grid_arithmetic: { equity_curve: curve(100000), orders: [], executions: [], risk_events: [] },
        cash: { equity_curve: curve(100000), orders: [], executions: [], risk_events: [] },
      },
      comparison: { candidate_key: 'candidate:1.0.0', candidate_rank: 1, random_percentile: 0.9, excess_vs_buy_hold: 0.005, excess_vs_grid_median: 0.01, market_tailwind: true },
      fairness: { independent_ledgers: true }, benchmark_pool: {},
      grid_risk: {
        grid_arithmetic: { mode: 'arithmetic', levels: 8, range: { lower: 90, center: 100, upper: 110 }, inventory_quantity: 2, inventory_notional: 200, inventory_risk: 0.02, capital_utilization: 0.4, trade_count: 8, fee_share_of_initial_capital: 0.0003, outside_range: true, outside_range_loss: 12, idle_cash_ratio: 0.6, preregistered: true, exit_rule: 'return_to_center_or_cohort_end' },
      },
    },
    program_gate: { passed: false, checks: { minimum_observation_days: false, random_distribution: true }, violations: ['minimum_observation_days'], allowed_transition: null, manual_approval_required: true, live_trading_enabled: false },
    ai_review: { effective_recommendation: 'continue_observation', review: { remaining_risks: ['真实七日观察尚未完成'] } },
    live_trading_enabled: false,
  },
  live_trading_enabled: false,
} as unknown as FactorFactoryRunResponse

describe('FactorCohortPanel', () => {
  it('switches from ranking to ledger evidence and keeps live submission disabled', () => {
    render(<FactorCohortPanel run={run} busy="" onReview={vi.fn()} onRequest={vi.fn()} onApprove={vi.fn()} />)

    expect(screen.getByText('真实七日观察尚未完成')).toBeTruthy()
    expect(screen.getAllByText('观察自然日')).toHaveLength(2)
    expect((screen.getByRole('button', { name: '提交人工审批' }) as HTMLButtonElement).disabled).toBe(true)

    fireEvent.click(screen.getByRole('button', { name: /grid_arithmetic/ }))

    expect(screen.getByRole('tab', { name: '账本详情' }).getAttribute('aria-selected')).toBe('true')
    expect(screen.getByRole('img', { name: '候选、买入持有与当前账本权益曲线' })).toBeTruthy()
    const gridRisk = screen.getByText('网格预注册风险').closest('div')
    expect(gridRisk).not.toBeNull()
    const gridRiskView = within(gridRisk as HTMLElement)
    expect(gridRiskView.getByText('区间外')).toBeTruthy()
    expect(gridRiskView.getByText('90.00 – 110.00')).toBeTruthy()
    expect(gridRiskView.getByText('8')).toBeTruthy()
  })
})
