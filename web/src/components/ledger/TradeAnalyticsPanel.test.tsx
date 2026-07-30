import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import type { LedgerTradeAnalytics } from '../../api/types'
import { TradeAnalyticsPanel } from './TradeAnalyticsPanel'

const report: LedgerTradeAnalytics = {
  ok: true,
  summary: {
    closed_trades: 2, total_pnl: 46, return_pct: 2.3, win_rate_pct: 50, profit_factor: 1.88,
    average_profit_loss_ratio: 1.88, max_consecutive_losses: 1, average_holding_seconds: 3600, max_stagnation_days: 2,
  },
  execution_quality: {
    total_fees: 4, average_fee: 2, fee_drag_pct: 2.67, slippage_available: false,
    slippage_note: '账本未记录预期成交价，无法可靠计算滑点',
  },
  matching: { open_lot_count: 1, open_quantity: 3 },
  cumulative_curve: [{ t: 1, pnl: 98, drawdown: 0 }, { t: 2, pnl: 46, drawdown: -52 }],
  monthly: [{ key: '2026-07', count: 2, wins: 1, pnl: 46, win_rate_pct: 50 }],
  daily: [{ key: '2026-07-30', count: 2, wins: 1, pnl: 46, win_rate_pct: 50 }],
  directions: [
    { key: 'long', count: 1, wins: 1, pnl: 98, win_rate_pct: 100 },
    { key: 'short', count: 1, wins: 0, pnl: -52, win_rate_pct: 0 },
  ],
  holding_buckets: [
    { key: '≤15分钟', count: 0, share_pct: 0, pnl: 0 },
    { key: '15–60分钟', count: 2, share_pct: 100, pnl: 46 },
  ],
  closed_trade_rows: [{
    instrument_id: 'us_stocks:AAPL', code: 'AAPL', market: 'us_stocks', direction: 'long', quantity: 10,
    entry_price: 100, exit_price: 110, entry_at: 1, exit_at: 3601, holding_seconds: 3600,
    gross_pnl: 100, fees: 2, pnl: 98, return_pct: 9.8, source: 'pa_agent',
  }],
}

afterEach(cleanup)

describe('TradeAnalyticsPanel', () => {
  it('renders closed-trade quality metrics without inventing slippage', () => {
    render(<TradeAnalyticsPanel data={report} />)

    expect(screen.getByText('交易质量分析')).toBeTruthy()
    expect(screen.getByText('50.0%')).toBeTruthy()
    expect(screen.getAllByText('1.88')).toHaveLength(2)
    expect(screen.getByText('账本未记录预期成交价，无法可靠计算滑点')).toBeTruthy()
    expect(screen.getByText('最近闭合交易')).toBeTruthy()
    expect(screen.getByText('AAPL')).toBeTruthy()
  })
})
