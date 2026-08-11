import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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
    usable_factors: 1, selected_factors: ['trend_strength'], multifactor_constructed: true,
    best_factor: 'trend_strength', best_method: 'multifactor',
    evaluation_scope: 'walk_forward_out_of_sample', walk_forward_mode: 'expanding', walk_forward_folds: 3,
    engine_version: '2.0.0', factor_formula_version: '1.0.0', data_fingerprint: 'a'.repeat(64),
    research_period: { start: '2024-01-01T00:00:00', end: '2026-01-01T00:00:00' },
  },
  factors: [{
    key: 'trend_strength', label: '趋势强度', category: '趋势', description: '趋势描述', direction: 'positive', status: 'usable',
    score: 18.2, ic: 0.18, rank_ic: 0.18, pearson_ic: 0.16, train_ic: 0.12, test_ic: 0.21,
    rolling_ic_mean: 0.16, rolling_ic_std: 0.08, icir: 2, positive_ic_ratio: 0.72, p_value: 0.02,
    window_pass_rate: 0.3333, passed_windows: 1, window_count: 3, worst_window_ic: -0.02,
    median_window_ic: 0.21, window_ic_iqr: 0.12, status_transitions: 1, direction_flips: 0,
    multi_window_consistent: false,
    decay: [{ horizon: 1, ic: 0.08 }, { horizon: 3, ic: 0.14 }, { horizon: 5, ic: 0.21 }, { horizon: 10, ic: 0.12 }, { horizon: 20, ic: -0.02 }],
    hit_rate: 0.58, observations: 435, test_observations: 145, stable: true, selected: true, weight: 1,
  }],
  methods: [{
    key: 'multifactor', label: '多因子组合', total_return: 0.24, annual_return: 0.11, sharpe: 1.2,
    annual_volatility: 0.14, downside_deviation: 0.08, sortino: 1.48, calmar: 1.38,
    risk_adjusted_score: 1.34, max_drawdown: -0.08, var_95: -0.012, cvar_95: -0.019,
    ulcer_index: 0.035, profit_factor: 1.42, max_drawdown_duration: 18, average_holding_period: 12.4,
    profit_factor_basis: 'closed_trades', win_rate: 0.54, win_rate_basis: 'closed_trades',
    closed_trades: 4, open_trade: true, average_trade_return: 0.03, average_win: 0.08,
    average_loss: -0.04, payoff_ratio: 2, turnover: 10, trades: 5, exposure: 0.62,
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
  cost_analysis: {
    available: true,
    basis: 'multifactor_final_out_of_sample_window',
    curve: [{ transaction_cost_bps: 0, total_return: 0.25 }, { transaction_cost_bps: 20, total_return: 0.22 }],
    breakeven_transaction_cost_bps: 146.25,
  },
  methodology: {
    split: '前 70% 样本确定因子方向，后 30% 样本验证',
    execution: '信号延迟一个周期执行',
    usable_rule: '样本外 Rank IC >= 0.03',
    warning: '历史统计不代表未来收益',
    metric_definitions: [{
      key: 'transaction_cost_bps', label: '单边交易成本',
      formula: '每单位换手扣除 transaction_cost_bps / 10000',
      unit: 'basis_points_per_side', source: '研究请求参数',
    }],
  },
} as const

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  localStorage.clear()
  window.history.replaceState({}, '', '/')
})

describe('FactorResearchPage', () => {
  it('restores the last asset view on a bare factor-research route', async () => {
    window.history.replaceState({}, '', '/factor-research')
    const history = vi.spyOn(api, 'factorResearchRuns').mockResolvedValue({
      ok: true, runs: [], total: 0, next_cursor: null,
    } as never)
    const first = render(<FactorResearchPage />)

    fireEvent.change(screen.getByLabelText('研究资产'), { target: { value: 'history' } })
    await waitFor(() => expect(history).toHaveBeenCalledTimes(1))
    expect(localStorage.getItem('quanthub.factor-research.last-view.v1')).toBe('history')

    first.unmount()
    render(<FactorResearchPage />)
    expect(await screen.findByRole('region', { name: '因子研究历史记录' })).not.toBeNull()
  })

  it('runs research and renders the risk signal and factor result', async () => {
    const request = vi.spyOn(api, 'factorResearch').mockResolvedValue(response as never)
    render(<FactorResearchPage />)

    fireEvent.change(screen.getByPlaceholderText('600519 / AAPL'), { target: { value: 'aapl' } })
    fireEvent.click(screen.getByRole('button', { name: '运行研究' }))

    await waitFor(() => expect(request).toHaveBeenCalledTimes(1))
    expect(request).toHaveBeenCalledWith(expect.objectContaining({ symbol: 'AAPL', market: 'a_shares' }))
    expect(await screen.findByText('修复')).toBeTruthy()
    expect(screen.getAllByText('趋势强度').length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText('多因子组合')).toBeTruthy()
    expect(screen.getByText('RSI(14)')).toBeTruthy()
    expect(screen.getByText('多因子风险诊断')).toBeTruthy()
    expect(screen.getByRole('region', { name: '交易成本敏感度' })).toBeTruthy()
    expect(screen.getByText('交易指标定义')).toBeTruthy()
    expect(screen.getByText('每单位换手扣除 transaction_cost_bps / 10000')).toBeTruthy()
    expect(screen.getByText('1/3')).toBeTruthy()
    expect(screen.getAllByText('1.48')).toHaveLength(2)
    expect(screen.getAllByText('历史统计不代表未来收益')).toHaveLength(2)
    expect(screen.getByText('因子组合具备继续研究价值')).toBeTruthy()
    expect(screen.getByText('为什么这样判断')).toBeTruthy()
    expect(screen.getByText('需要注意的风险')).toBeTruthy()
    const professionalDetails = screen.getByText('专业统计与方法细节').closest('details')
    expect(professionalDetails?.open).toBe(false)
    expect(screen.getByRole('link', { name: '设置提醒' }).getAttribute('href')).toContain('symbol=AAPL')
  })

  it('opens strategy lab with the exact saved research run id', async () => {
    vi.spyOn(api, 'factorResearch').mockResolvedValue({
      ...response,
      run_id: 'factor-run-for-strategy',
      saved: true,
    } as never)
    render(<FactorResearchPage />)

    fireEvent.click(screen.getByRole('button', { name: '运行研究' }))

    const link = await screen.findByRole('link', { name: '策略实验' })
    expect(link.getAttribute('href')).toBe(
      '/strategy-lab?action=create_experiment&symbol=AAPL&market=us_stocks&timeframe=1d&research_run_id=factor-run-for-strategy',
    )
  })

  it('blocks strategy experiments when no factor passes the statistical gate', async () => {
    vi.spyOn(api, 'factorResearch').mockResolvedValue({
      ...response,
      summary: {
        ...response.summary,
        usable_factors: 0,
        selected_factors: [],
        multifactor_constructed: false,
      },
      factors: response.factors.map((factor) => ({
        ...factor,
        status: 'watch',
        selected: false,
        weight: 0,
      })),
      cost_analysis: {
        available: false,
        basis: 'multifactor_final_out_of_sample_window',
        reason: '没有因子通过样本外统计门禁，多因子组合未构建',
        curve: [],
        breakeven_transaction_cost_bps: null,
      },
    } as never)
    render(<FactorResearchPage />)

    fireEvent.click(screen.getByRole('button', { name: '运行研究' }))

    const experiment = await screen.findByRole('button', { name: '策略实验' })
    expect((experiment as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getAllByText('未发现合格因子').length).toBeGreaterThan(0)
    expect(screen.queryByRole('region', { name: '交易成本敏感度' })).toBeNull()
  })

  it('runs cross-sectional research from a point-in-time universe', async () => {
    const universe = {
      id: 'universe-1', name: '美股历史池', market: 'us_stocks', description: '历史成分',
      created_at: 1_785_400_000, updated_at: 1_785_400_000,
    }
    const members = Array.from({ length: 5 }, (_, index) => ({
      id: `member-${index}`, universe_id: universe.id, instrument_id: `us_stocks:S${index}`,
      symbol: `S${index}`, effective_from: '2024-01-01', effective_to: null,
      status: 'active', industry: index % 2 ? '科技' : '金融', market_cap: 1_000_000_000 + index,
      beta: 1, is_st: false, listed_at: '2020-01-01', delisted_at: null,
      created_at: 1_785_400_000, updated_at: 1_785_400_000,
    }))
    vi.spyOn(api, 'factorUniverses').mockResolvedValue({ ok: true, count: 1, universes: [universe] } as never)
    vi.spyOn(api, 'factorUniverseMembers').mockResolvedValue({ ok: true, universe, count: 5, members } as never)
    const run = vi.spyOn(api, 'crossSectionResearch').mockResolvedValue({
      ok: true, run_id: 'cross-run-1', engine_version: '1.0.0', universe,
      loaded_symbols: 5, failed_symbols: 0, failures: [],
      factor: {
        key: 'trend_strength', label: '趋势强度', category: '趋势', description: '趋势描述',
        formula: 'EMA(close,20) / EMA(close,60) - 1', formula_version: '1.0.0', status: 'usable',
      },
      summary: {
        dates: 30, rank_ic_mean: 0.08, rank_ic_median: 0.07, rank_ic_std: 0.04, icir: 1.4,
        rank_ic_p_value: 0.01, rank_ic_p_value_method: 'newey_west_hac_mean_test',
        rank_ic_hac_lags: 4, effective_dates: 24, positive_rank_ic_ratio: 0.7,
        portfolio_mode: 'cohort', portfolio_return_horizon: 1, portfolio_observations: 30,
        gross_long_short_total_return: 0.14, net_long_short_total_return: 0.12,
        long_short_total_return: 0.12, coverage: 0.95,
        missing_rate: 0.05, average_turnover: 0.2, median_capacity: 2_000_000,
        median_crowding_hhi: 0.24, neutralization_failures: 0, minimum_valid_assets: 5,
        median_valid_assets: 5, data_fingerprint: 'f'.repeat(64),
      },
      quantile_returns: [
        { quantile: 1, mean_forward_return: -0.01 },
        { quantile: 5, mean_forward_return: 0.02 },
      ],
      series: [], methodology: {},
    } as never)
    const insufficientStatus = vi.spyOn(api, 'crossMarketFactorStatus').mockResolvedValue({
      ok: true,
      factor_key: 'trend_strength',
      target_market: 'us_stocks',
      trading_validation_status: 'insufficient_evidence',
      trading_validation_passed: false,
      required_markets: ['us_stocks'],
      transfer_markets: ['a_shares', 'crypto', 'mt5'],
      rule: '四个市场最新横截面结果均为 usable，且每个市场至少 20 个有效日期、每日最少 3 个有效标的',
      rows: [
        { market: 'a_shares', state: 'passed', run_id: 'a-run', run_status: 'succeeded', factor_status: 'usable', dates: 30, minimum_valid_assets: 5, rank_ic_mean: 0.08, coverage: 0.95, updated_at: 1 },
        { market: 'us_stocks', state: 'missing', run_id: null, run_status: null, factor_status: null, dates: null, minimum_valid_assets: null, rank_ic_mean: null, coverage: null, updated_at: null },
        { market: 'crypto', state: 'missing', run_id: null, run_status: null, factor_status: null, dates: null, minimum_valid_assets: null, rank_ic_mean: null, coverage: null, updated_at: null },
        { market: 'mt5', state: 'missing', run_id: null, run_status: null, factor_status: null, dates: null, minimum_valid_assets: null, rank_ic_mean: null, coverage: null, updated_at: null },
      ],
    } as never)
    render(<FactorResearchPage />)

    fireEvent.change(screen.getByLabelText('研究资产'), { target: { value: 'cross_section' } })
    expect(await screen.findByText('历史股票池')).toBeTruthy()
    await waitFor(() => expect(api.factorUniverseMembers).toHaveBeenCalledWith('universe-1'))
    fireEvent.submit(screen.getByRole('button', { name: '运行横截面研究' }).closest('form') as HTMLFormElement)

    await waitFor(() => expect(run).toHaveBeenCalledWith(expect.objectContaining({
      universe_id: 'universe-1', factor_key: 'trend_strength', interval: '1d',
      neutralize_industry: true, neutralize_market_cap: true, neutralize_beta: true,
    })))
    expect(await screen.findByText('0.080')).toBeTruthy()
    expect(screen.getAllByText('12.00%')).toHaveLength(2)
    expect(screen.getByText('95.00%')).toBeTruthy()
    expect(screen.getByText('目标市场证据不足')).toBeTruthy()
    expect(insufficientStatus).toHaveBeenCalledWith('trend_strength', 'us_stocks')

    insufficientStatus.mockResolvedValue({
      ok: true,
      factor_key: 'trend_strength',
      target_market: 'us_stocks',
      trading_validation_status: 'passed',
      trading_validation_passed: true,
      required_markets: ['us_stocks'],
      transfer_markets: ['a_shares', 'crypto', 'mt5'],
      rule: '四个市场最新横截面结果均为 usable，且每个市场至少 20 个有效日期、每日最少 3 个有效标的',
      rows: ['a_shares', 'us_stocks', 'crypto', 'mt5'].map((market) => ({
        market, state: 'passed', run_id: `${market}-run`, run_status: 'succeeded', factor_status: 'usable', dates: 30,
        minimum_valid_assets: 5, rank_ic_mean: 0.08, coverage: 0.95, updated_at: 1,
      })),
    } as never)
    fireEvent.submit(screen.getByRole('button', { name: '运行横截面研究' }).closest('form') as HTMLFormElement)
    expect(await screen.findByText('交易验证通过')).toBeTruthy()
  })

  it('applies beginner research templates without exposing raw cycle codes first', async () => {
    const request = vi.spyOn(api, 'factorResearch').mockResolvedValue(response as never)
    render(<FactorResearchPage />)

    fireEvent.click(screen.getByRole('tab', { name: '短线' }))
    expect(screen.getByText('未来 3 个交易日 · 300 根日线')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '运行研究' }))

    await waitFor(() => expect(request).toHaveBeenCalledTimes(1))
    expect(request).toHaveBeenCalledWith(expect.objectContaining({
      interval: '1d', horizon: 3, limit: 300, transaction_cost_bps: 10,
    }))
  })

  it('submits date range and rolling walk-forward settings exactly', async () => {
    const request = vi.spyOn(api, 'factorResearch').mockResolvedValue(response as never)
    render(<FactorResearchPage />)

    fireEvent.change(screen.getByLabelText('开始日期'), { target: { value: '2024-01-01' } })
    fireEvent.change(screen.getByLabelText('结束日期'), { target: { value: '2025-12-31' } })
    fireEvent.change(screen.getByLabelText('验证模式'), { target: { value: 'rolling' } })
    fireEvent.change(screen.getByLabelText(/^验证窗口/), { target: { value: '5' } })
    fireEvent.click(screen.getByRole('button', { name: '运行研究' }))

    await waitFor(() => expect(request).toHaveBeenCalledWith(expect.objectContaining({
      start_date: '2024-01-01',
      end_date: '2025-12-31',
      walk_forward_mode: 'rolling',
      walk_forward_folds: 5,
    })))
  })

  it('provides purpose templates, examples, term help, and a permanently dismissible first guide', async () => {
    const request = vi.spyOn(api, 'factorResearch').mockResolvedValue(response as never)
    const first = render(<FactorResearchPage />)

    expect(screen.getByRole('complementary', { name: '第一次阅读顺序' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '永久关闭首次阅读引导' }))
    expect(screen.queryByRole('complementary', { name: '第一次阅读顺序' })).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: /回撤检查/ }))
    fireEvent.click(screen.getByRole('button', { name: '运行研究' }))
    await waitFor(() => expect(request).toHaveBeenCalledWith(expect.objectContaining({
      limit: 1000, horizon: 20, transaction_cost_bps: 15,
    })))
    expect(screen.getByText('正常')).toBeTruthy()
    expect(screen.getByRole('region', { name: '量化术语速查' })).toBeTruthy()
    expect(screen.getAllByText('查看中文解释')).toHaveLength(6)

    first.unmount()
    render(<FactorResearchPage />)
    expect(screen.queryByRole('complementary', { name: '第一次阅读顺序' })).toBeNull()
  })

  it('compares the current saved run with the previous research snapshot', async () => {
    vi.spyOn(api, 'factorResearch').mockResolvedValue({
      ...response, run_id: 'current-run', saved: true, saved_at: 1_785_400_200,
    } as never)
    const currentRun = {
      id: 'current-run', symbol: 'AAPL', market: 'us_stocks', timeframe: '1d', status: 'succeeded',
      modules: ['factor_research'], input: {}, summary: {}, error: null, note: '', favorite: false,
      created_at: 1_785_400_200, updated_at: 1_785_400_200, evidence_count: 1,
    }
    const previousRun = { ...currentRun, id: 'previous-run', created_at: 1_785_300_000, updated_at: 1_785_300_000 }
    vi.spyOn(api, 'factorResearchRuns').mockResolvedValue({
      ok: true, runs: [currentRun, previousRun], total: 2, next_cursor: null,
    } as never)
    vi.spyOn(api, 'factorResearchRun').mockResolvedValue({
      ok: true,
      run: previousRun,
      result: {
        ...response,
        run_id: 'previous-run',
        saved: true,
        summary: { ...response.summary, selected_factors: [], usable_factors: 0 },
        factors: [],
        methods: [{ ...response.methods[0], total_return: 0.1, sharpe: 0.8 }],
        current_signal: { ...response.current_signal, strategy_drawdown: -0.05 },
      },
      ai_review: null,
    } as never)
    render(<FactorResearchPage />)

    fireEvent.click(screen.getByRole('button', { name: '运行研究' }))
    await screen.findByText('因子组合具备继续研究价值')
    fireEvent.click(screen.getByRole('button', { name: '选择历史对比' }))
    expect(await screen.findByLabelText('对比记录')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '开始对比' }))

    const panel = await screen.findByRole('region', { name: '历史因子研究对比' })
    expect(within(panel).getByText('所选研究')).toBeTruthy()
    expect(within(panel).getByText('10.0%')).toBeTruthy()
    expect(within(panel).getByText('可用 · +0.210')).toBeTruthy()
    expect(within(panel).getByText('非探索候选 · —')).toBeTruthy()
  })

  it('runs a constrained AI review after statistical research', async () => {
    vi.spyOn(api, 'factorResearch').mockResolvedValue({
      ...response,
      run_id: 'factor-run-1',
      saved: true,
      saved_at: 1_785_400_000,
    } as never)
    const aiRequest = vi.spyOn(api, 'factorAiReview').mockResolvedValue({
      ok: true,
      review: {
        verdict: '谨慎复核', confidence: 78, statistical_alignment: '一致', summary: '样本外证据可继续研究。',
        overfitting_risk: { level: '中', reasons: ['单标的'] },
        regime_risk: { level: '中', reasons: ['趋势依赖'] },
        factor_reviews: [{
          factor_key: 'trend_strength', label: '趋势强度', statistical_status: 'usable', assessment: '具备研究价值',
          evidence: ['样本外 IC 为正'], risks: ['跨标的未知'], regime_fit: ['趋势市场'], next_test: '执行滚动样本外检验',
        }],
        portfolio_review: { strengths: ['方向一致'], risks: ['样本有限'] },
        experiments: [{ title: '滚动验证', hypothesis: '跨窗口稳定', design: '使用 walk-forward', success_criteria: '多数窗口 IC 为正' }],
        uncertainties: ['跨标的泛化未知'],
      },
      meta: { model: 'advanced-ai', attempts: 1, input_fingerprint: 'abc123', statistical_conclusions_locked: true },
    } as never)
    render(<FactorResearchPage />)

    fireEvent.click(screen.getByRole('button', { name: '运行研究' }))
    await screen.findByText('AI 科研复核')
    fireEvent.click(screen.getByRole('button', { name: '启动 AI 复核' }))

    await waitFor(() => expect(aiRequest).toHaveBeenCalledTimes(1))
    expect(aiRequest).toHaveBeenCalledWith(expect.objectContaining({ run_id: 'factor-run-1' }))
    expect(await screen.findByText('谨慎复核')).toBeTruthy()
    expect(screen.getByText('执行滚动样本外检验')).toBeTruthy()
    expect(screen.getByText('模型 advanced-ai · 输出 1 次 · 指纹 abc123')).toBeTruthy()
  })

  it('shows a deep-review state while waiting for the AI provider', async () => {
    vi.spyOn(api, 'factorResearch').mockResolvedValue(response as never)
    vi.spyOn(api, 'factorAiReview').mockReturnValue(new Promise(() => {}) as never)
    render(<FactorResearchPage />)

    fireEvent.click(screen.getByRole('button', { name: '运行研究' }))
    await screen.findByText('AI 科研复核')
    fireEvent.click(screen.getByRole('button', { name: '启动 AI 复核' }))

    expect(await screen.findByRole('button', { name: 'AI 深度复核中' })).toBeTruthy()
  })

  it('keeps the statistical result readable when the AI review fails', async () => {
    vi.spyOn(api, 'factorResearch').mockResolvedValue({ ...response, run_id: 'factor-run-failed-ai', saved: true } as never)
    vi.spyOn(api, 'factorAiReview').mockRejectedValue(new Error('模型网关超时'))
    render(<FactorResearchPage />)

    fireEvent.click(screen.getByRole('button', { name: '运行研究' }))
    await screen.findByText('因子组合具备继续研究价值')
    fireEvent.click(screen.getByRole('button', { name: '启动 AI 复核' }))

    expect(await screen.findByText('统计研究已完成，AI 复核未完成')).toBeTruthy()
    expect(screen.getByText('模型网关超时')).toBeTruthy()
    expect(screen.getByText('AI 复核未完成，统计结果已保留，过拟合风险仍需复核')).toBeTruthy()
  })

  it('lists saved factor runs and restores a complete result', async () => {
    const savedResult = {
      ...response,
      run_id: 'factor-history-1',
      saved: true,
      saved_at: 1_785_400_100,
    }
    const savedAi = {
      ok: true,
      run_id: 'factor-history-1',
      saved: true,
      review: {
        verdict: '谨慎复核', confidence: 82, statistical_alignment: '一致', summary: '历史 AI 复核结果。',
        overfitting_risk: { level: '中', reasons: ['单标的'] },
        regime_risk: { level: '低', reasons: ['当前稳定'] },
        factor_reviews: [{
          factor_key: 'trend_strength', label: '趋势强度', statistical_status: 'usable', assessment: '可继续研究',
          evidence: ['样本外 IC 为正'], risks: ['跨标的未知'], regime_fit: ['趋势市场'], next_test: '执行多标的验证',
        }],
        portfolio_review: { strengths: ['方向一致'], risks: ['样本有限'] },
        experiments: [{ title: '跨标的', hypothesis: '具备泛化能力', design: '增加股票池', success_criteria: '多数标的 IC 为正' }],
        uncertainties: ['跨市场表现未知'],
      },
      meta: { model: 'gpt-5.6-sol', attempts: 1, input_fingerprint: 'history-1', statistical_conclusions_locked: true },
    }
    const run = {
      id: 'factor-history-1', symbol: 'AAPL', market: 'us_stocks', timeframe: '1d', status: 'succeeded',
      modules: ['factor_research'],
      input: { factor_research: { symbol: 'AAPL', market: 'us_stocks', interval: '1d', limit: 500, horizon: 5, transaction_cost_bps: 10 } },
      summary: {
        factor_research: { selected_factors: ['trend_strength'], drawdown: -0.03, best_method: 'multifactor' },
        factor_ai_review: { ok: true, verdict: '谨慎复核' },
      },
      error: null, note: '', favorite: false, created_at: 1_785_400_000, updated_at: 1_785_400_100, evidence_count: 2,
    }
    vi.spyOn(api, 'factorResearchRuns').mockResolvedValue({ ok: true, runs: [run], total: 1, next_cursor: null } as never)
    vi.spyOn(api, 'factorResearchRun').mockResolvedValue({ ok: true, run, result: savedResult, ai_review: savedAi } as never)
    render(<FactorResearchPage />)

    fireEvent.change(screen.getByLabelText('研究资产'), { target: { value: 'history' } })
    expect(await screen.findByRole('region', { name: '因子研究历史记录' })).toBeTruthy()
    fireEvent.click(await screen.findByRole('button', { name: /AAPL.*打开结果/ }))

    expect(await screen.findByText('历史 AI 复核结果。')).toBeTruthy()
    expect(screen.getByText('研究记录已保存')).toBeTruthy()
    expect(window.location.search).toContain('run_id=factor-history-1')
  })

  it('filters history by saved run fields and research parameters', async () => {
    const request = vi.spyOn(api, 'factorResearchRuns').mockResolvedValue({
      ok: true, runs: [], total: 0, next_cursor: null,
    } as never)
    render(<FactorResearchPage />)

    fireEvent.change(screen.getByLabelText('研究资产'), { target: { value: 'history' } })
    await waitFor(() => expect(request).toHaveBeenCalledTimes(1))
    fireEvent.change(screen.getByLabelText('标的'), { target: { value: 'aapl' } })
    fireEvent.change(screen.getByLabelText('市场'), { target: { value: 'us_stocks' } })
    fireEvent.change(screen.getByLabelText('周期'), { target: { value: '1d' } })
    fireEvent.change(screen.getByLabelText('状态'), { target: { value: 'succeeded' } })
    fireEvent.click(screen.getByLabelText('仅显示收藏'))
    fireEvent.change(screen.getByLabelText('创建日期起'), { target: { value: '2025-01-01' } })
    fireEvent.change(screen.getByLabelText('创建日期止'), { target: { value: '2025-12-31' } })
    fireEvent.change(screen.getByLabelText('历史长度'), { target: { value: '500' } })
    fireEvent.change(screen.getByLabelText('预测窗口'), { target: { value: '5' } })
    fireEvent.change(screen.getByLabelText('单边成本'), { target: { value: '10' } })
    fireEvent.change(screen.getByLabelText('验证模式'), { target: { value: 'rolling' } })
    fireEvent.change(screen.getByLabelText('验证窗口'), { target: { value: '4' } })
    fireEvent.click(screen.getByRole('button', { name: '应用筛选' }))

    await waitFor(() => expect(request).toHaveBeenLastCalledWith({
      symbol: 'aapl',
      market: 'us_stocks',
      interval: '1d',
      status: 'succeeded',
      favorite: true,
      created_from: '2025-01-01',
      created_to: '2025-12-31',
      research_limit: 500,
      horizon: 5,
      transaction_cost_bps: 10,
      walk_forward_mode: 'rolling',
      walk_forward_folds: 4,
    }, 20, undefined))
  })

  it('favorites a saved run and edits its note from factor history', async () => {
    const run = {
      id: 'factor-history-meta', symbol: 'AAPL', market: 'us_stocks', timeframe: '1d', status: 'succeeded',
      modules: ['factor_research'], input: {},
      summary: { factor_research: { selected_factors: [], drawdown: -0.02, best_method: 'multifactor' } },
      error: null, note: '', favorite: false, tags: [], archived_at: null,
      created_at: 1_785_400_000, updated_at: 1_785_400_100, evidence_count: 1,
    }
    vi.spyOn(api, 'factorResearchRuns').mockResolvedValue({
      ok: true, runs: [run], total: 1, next_cursor: null,
    } as never)
    const update = vi.spyOn(api, 'updateResearchRun').mockImplementation(async (_id, patch) => ({
      ok: true, run: { ...run, ...patch },
    }) as never)
    render(<FactorResearchPage />)

    fireEvent.change(screen.getByLabelText('研究资产'), { target: { value: 'history' } })
    fireEvent.click(await screen.findByRole('button', { name: '收藏 AAPL' }))
    await waitFor(() => expect(update).toHaveBeenCalledWith('factor-history-meta', { favorite: true }))

    fireEvent.click(screen.getByRole('button', { name: '编辑 AAPL 备注' }))
    fireEvent.change(screen.getByLabelText('AAPL 研究备注'), { target: { value: '等待跨市场复验' } })
    fireEvent.click(screen.getByRole('button', { name: '保存备注与标签' }))
    await waitFor(() => expect(update).toHaveBeenLastCalledWith('factor-history-meta', { note: '等待跨市场复验', tags: [] }))
  })

  it('filters by tag and batch updates tags before archiving selected history', async () => {
    const run = {
      id: 'factor-history-batch', symbol: 'AAPL', market: 'us_stocks', timeframe: '1d', status: 'succeeded',
      modules: ['factor_research'], input: {},
      summary: { factor_research: { selected_factors: [], drawdown: -0.02, best_method: 'multifactor' } },
      error: null, note: '', favorite: false, tags: [], archived_at: null,
      created_at: 1_785_400_000, updated_at: 1_785_400_100, evidence_count: 1,
    }
    const list = vi.spyOn(api, 'factorResearchRuns').mockResolvedValue({
      ok: true, runs: [run], total: 1, next_cursor: null,
    } as never)
    const batch = vi.spyOn(api, 'updateResearchRunsBatch').mockImplementation(async (_ids, patch) => ({
      ok: true, count: 1, runs: [{ ...run, ...patch, archived_at: patch.archived ? 1_785_500_000 : null }],
    }) as never)
    render(<FactorResearchPage />)

    fireEvent.change(screen.getByLabelText('研究资产'), { target: { value: 'history' } })
    await screen.findByRole('checkbox', { name: '选择 AAPL 研究记录' })
    fireEvent.change(screen.getByLabelText('标签'), { target: { value: '待复验' } })
    fireEvent.click(screen.getByRole('button', { name: '应用筛选' }))
    await waitFor(() => expect(list).toHaveBeenLastCalledWith(
      expect.objectContaining({ tag: '待复验' }), 20, undefined,
    ))

    fireEvent.click(screen.getByRole('checkbox', { name: '选择 AAPL 研究记录' }))
    fireEvent.change(screen.getByLabelText('批量标签'), { target: { value: '待复验, 趋势' } })
    fireEvent.click(screen.getByRole('button', { name: '应用标签' }))
    await waitFor(() => expect(batch).toHaveBeenCalledWith(
      ['factor-history-batch'], { tags: ['待复验', '趋势'] },
    ))

    fireEvent.click(screen.getByRole('checkbox', { name: '选择 AAPL 研究记录' }))
    fireEvent.click(screen.getByRole('button', { name: '归档所选' }))
    await waitFor(() => expect(batch).toHaveBeenLastCalledWith(
      ['factor-history-batch'], { archived: true },
    ))
    expect(screen.queryByRole('checkbox', { name: '选择 AAPL 研究记录' })).toBeNull()
  })
})
