import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import FactorResearchPage from './FactorResearchPage'

const response = {
  ok: true,
  symbol: 'AAPL',
  market: 'us_stocks',
  interval: '1d',
  source: 'local_parquet',
  quality: { status: 'ok', usable: true, row_count: 500, missing_rate: 0, invalid_rows: 0, latest_time: '2026-01-01' },
  summary: {
    rows: 500, train_rows: 345, purged_rows: 5, test_rows: 150, horizon: 5, transaction_cost_bps: 10,
    usable_factors: 1, selected_factors: ['trend_strength'], best_factor: 'trend_strength', best_method: 'multifactor',
    evaluation_scope: 'out_of_sample',
  },
  factors: [{
    key: 'trend_strength', label: '趋势强度', category: '趋势', description: '趋势描述', direction: 'positive', status: 'usable',
    score: 18.2, ic: 0.18, rank_ic: 0.18, pearson_ic: 0.16, train_ic: 0.12, test_ic: 0.21,
    rolling_ic_mean: 0.16, rolling_ic_std: 0.08, icir: 2, positive_ic_ratio: 0.72, p_value: 0.02,
    decay: [{ horizon: 1, ic: 0.08 }, { horizon: 3, ic: 0.14 }, { horizon: 5, ic: 0.21 }, { horizon: 10, ic: 0.12 }, { horizon: 20, ic: -0.02 }],
    hit_rate: 0.58, observations: 435, test_observations: 145, stable: true, selected: true, weight: 1,
  }],
  methods: [{
    key: 'multifactor', label: '多因子组合', total_return: 0.24, annual_return: 0.11, sharpe: 1.2,
    annual_volatility: 0.14, downside_deviation: 0.08, sortino: 1.48, calmar: 1.38,
    risk_adjusted_score: 1.34, max_drawdown: -0.08, var_95: -0.012, cvar_95: -0.019,
    ulcer_index: 0.035, profit_factor: 1.42, max_drawdown_duration: 18, average_holding_period: 12.4,
    win_rate: 0.54, turnover: 10, trades: 5, exposure: 0.62,
  }],
  indicators: [
    { key: 'rsi_14', label: 'RSI(14)', value: 42.6, state: 'neutral', interpretation: '中性' },
    { key: 'adx_14', label: 'ADX(14)', value: 28.2, state: 'positive', interpretation: '趋势明确' },
  ],
  current_signal: {
    level: 'recovery', label: '修复', drawdown: -0.03, strategy_drawdown: -0.02,
    asset_peak_drawdown: -0.18, guidance: '等待趋势确认后再恢复仓位',
  },
  signal_events: [],
  latest: { close: 220.5, multifactor_position: 1, multifactor_return: 0.24 },
  curve: [
    { t: '2025-01-01', asset: 1, multifactor: 1, asset_drawdown: 0, strategy_drawdown: 0 },
    { t: '2026-01-01', asset: 1.2, multifactor: 1.24, asset_drawdown: -0.03, strategy_drawdown: -0.02 },
  ],
  method_curves: {},
  methodology: {
    split: '前 70% 样本确定因子方向，后 30% 样本验证',
    execution: '信号延迟一个周期执行',
    usable_rule: '样本外 Rank IC >= 0.03',
    warning: '历史统计不代表未来收益',
  },
} as const

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('FactorResearchPage', () => {
  it('runs research and renders the risk signal and factor result', async () => {
    const request = vi.spyOn(api, 'factorResearch').mockResolvedValue(response as never)
    render(<FactorResearchPage />)

    fireEvent.change(screen.getByPlaceholderText('600519 / AAPL'), { target: { value: 'aapl' } })
    fireEvent.click(screen.getByRole('button', { name: '运行研究' }))

    await waitFor(() => expect(request).toHaveBeenCalledTimes(1))
    expect(request).toHaveBeenCalledWith(expect.objectContaining({ symbol: 'AAPL', market: 'a_shares' }))
    expect(await screen.findByText('修复')).toBeTruthy()
    expect(screen.getAllByText('趋势强度')).toHaveLength(2)
    expect(screen.getByText('多因子组合')).toBeTruthy()
    expect(screen.getByText('RSI(14)')).toBeTruthy()
    expect(screen.getByText('多因子风险诊断')).toBeTruthy()
    expect(screen.getAllByText('1.48')).toHaveLength(2)
    expect(screen.getByText('历史统计不代表未来收益')).toBeTruthy()
  })
})
