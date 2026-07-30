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
  localStorage.clear()
  window.history.replaceState({}, '', '/')
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
    expect(screen.getAllByText('趋势强度').length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText('多因子组合')).toBeTruthy()
    expect(screen.getByText('RSI(14)')).toBeTruthy()
    expect(screen.getByText('多因子风险诊断')).toBeTruthy()
    expect(screen.getAllByText('1.48')).toHaveLength(2)
    expect(screen.getAllByText('历史统计不代表未来收益')).toHaveLength(2)
    expect(screen.getByText('因子组合具备继续研究价值')).toBeTruthy()
    expect(screen.getByText('为什么这样判断')).toBeTruthy()
    expect(screen.getByText('需要注意的风险')).toBeTruthy()
    const professionalDetails = screen.getByText('专业统计与方法细节').closest('details')
    expect(professionalDetails?.open).toBe(false)
    expect(screen.getByRole('link', { name: '设置提醒' }).getAttribute('href')).toContain('symbol=AAPL')
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
    fireEvent.click(screen.getByRole('button', { name: '与上次对比' }))

    const panel = await screen.findByRole('region', { name: '与上次因子研究对比' })
    expect(within(panel).getByText('上次研究')).toBeTruthy()
    expect(within(panel).getByText('10.0%')).toBeTruthy()
    expect(within(panel).getByText('可用 · +0.210')).toBeTruthy()
    expect(within(panel).getByText('未入选 · —')).toBeTruthy()
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

    fireEvent.click(screen.getByRole('tab', { name: '历史记录' }))
    expect(await screen.findByText('因子研究历史')).toBeTruthy()
    fireEvent.click(await screen.findByRole('button', { name: /AAPL.*打开结果/ }))

    expect(await screen.findByText('历史 AI 复核结果。')).toBeTruthy()
    expect(screen.getByText('研究记录已保存')).toBeTruthy()
    expect(window.location.search).toContain('run_id=factor-history-1')
  })
})
