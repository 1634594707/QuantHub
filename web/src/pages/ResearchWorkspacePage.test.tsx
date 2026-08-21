import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { api } from '../api/client'
import ResearchWorkspacePage from './ResearchWorkspacePage'

vi.mock('../components/KlineCard', () => ({ default: () => <div>行情图</div> }))

function LocationProbe() {
  const location = useLocation()
  return <output aria-label="current location">{`${location.pathname}${location.search}`}</output>
}

function renderPage(
  path = '/research/NVDA?market=us_stocks&tf=1d&from=evaluate&view=overview',
  runs: Array<Record<string, unknown>> = [],
) {
  vi.spyOn(api, 'researchRuns').mockResolvedValue({
    ok: true,
    count: runs.length,
    total: runs.length,
    next_cursor: null,
    runs,
  } as never)
  vi.spyOn(api, 'instruments').mockResolvedValue({ ok: true, instruments: [] } as never)
  vi.spyOn(api, 'researchPreference').mockResolvedValue({
    ok: true,
    preference: {
      user_id: 'local-user', default_mode: 'investor', default_market: 'a_shares',
      holding_status: 'not_held', research_horizon: 'swing', risk_preference: 'balanced',
      terminology_level: 'standard', updated_at: '2026-08-16T00:00:00Z',
    },
  } as never)
  vi.spyOn(api, 'updateResearchPreference').mockResolvedValue({
    ok: true,
    preference: {
      user_id: 'local-user', default_mode: 'investor', default_market: 'a_shares',
      holding_status: 'not_held', research_horizon: 'swing', risk_preference: 'balanced',
      terminology_level: 'standard', updated_at: '2026-08-16T00:00:00Z',
    },
  } as never)
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/research/:symbol" element={<><ResearchWorkspacePage /><LocationProbe /></>} />
      </Routes>
    </MemoryRouter>,
  )
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('ResearchWorkspacePage', () => {
  const reportRun = {
    id: 'run-report', symbol: '600519', market: 'a_shares', timeframe: '1d',
    status: 'succeeded', modules: ['market', 'fundamentals', 'valuation', 'announcements', 'macro'],
    input: { evaluation_profile: 'comprehensive' },
    summary: {
      market: {
        latest_price: 1518, latest_time: '2026-08-15T07:00:00Z', source: 'akshare',
        quantitative: {
          confidence: 'high', data_quality: 'complete',
          metrics: { return_20_pct: 4.2, annualized_volatility_pct: 18.6, max_drawdown_pct: -7.1, rsi_14: 57.4 },
          dimensions: { trend: { label: '趋势', signal: 'positive', evidence: '收盘价位于长期均线上方' } },
          strategies: [], has_strategy_disagreement: false,
        },
      },
      fundamentals: { financial_quality: 'strong', earnings_trend: 'improving', cash_flow_quality: 'healthy' },
      valuation: { valuation_range: 'fair', valuation_percentile: 0.42, confidence: 0.88 },
      announcements: {
        reason: '公司公告与可信事件方向汇总', direction: 'long', verified_count: 1,
        events: [{
          event_id: 'company-event-1', title: '贵州茅台净利润增长', category: 'earnings',
          direction: 'positive', verification_status: 'verified',
          provenance: { published_at: '2026-08-15T15:59:59Z' },
        }],
      },
      macro: {
        reason: '宏观事件与标的可靠暴露传导汇总', direction: 'negative',
        reliable_transmission_count: 1,
        events: [{
          event_id: 'macro-event-1', title: '美联储利率决议', state: 'released',
          direction: 'negative', actual_value: 5.25, expected_value: 5,
          provenance: { published_at: '2026-08-14T15:59:59Z' },
        }],
        transmissions: [{ channel: 'rates', order: 'direct', horizon: 'medium', direction: 'negative', strength: 0.72 }],
      },
      action_guidance: {
        status: 'research_further', primary_reasons: ['盈利与现金流趋势改善'],
        disclaimer: '研究参考，不是收益承诺。',
      },
      research_decision: {
        direction: 'long', execution_eligible: false, decision_version: 'research-decision-v1',
        module_opinions: [
          { module: 'fundamentals', direction: 'long', status: 'available', reason: '盈利质量改善' },
          { module: 'valuation', direction: 'neutral', status: 'available', reason: '估值处于合理区间' },
        ],
        conflicts: [], invalidation_conditions: ['盈利增速连续两个季度转负'],
        reevaluate_triggers: ['下一次财报公告'],
      },
      evidence_fusion: {
        fundamental: { covered: true }, valuation: { covered: true },
        company_events: { covered: true }, macro: { covered: true },
        factor: { covered: false, missing_fields: ['factor_snapshot'] }, holding: { available: false },
      },
    },
    error: null, note: '', favorite: false, tags: [], archived_at: null,
    created_at: 1, updated_at: 1, evidence_count: 1,
    evidence: [{
      id: 'evidence-financial', kind: 'financial_snapshot', title: '财务快照', source: 'akshare',
      captured_at: 1, uri: null, payload: { model: 'fundamental-v1', raw_metric: 42 },
    }],
  }

  it('starts the existing evaluation workflow from the workspace', async () => {
    const createTask = vi.spyOn(api, 'createAnalysisTask').mockResolvedValue({
      ok: true,
      duplicate: false,
      task: { id: 'evaluation-task-1' },
    } as never)
    renderPage()

    fireEvent.click(screen.getByRole('button', { name: '运行全面评估' }))

    await waitFor(() => expect(createTask).toHaveBeenCalledWith(expect.objectContaining({
      kind: 'evaluation',
      symbol: 'NVDA',
      market: 'us_stocks',
      timeframe: '1d',
      payload: expect.objectContaining({
        modules: ['market', 'pa', 'ensemble', 'fundamentals', 'valuation'],
        evaluation_profile: 'comprehensive',
        evaluation_horizon: 'swing',
      }),
    })))
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
  })

  it('keeps the workspace readable when task creation fails', async () => {
    vi.spyOn(api, 'createAnalysisTask').mockRejectedValue(new Error('分析服务不可用'))
    renderPage()

    fireEvent.click(screen.getByRole('button', { name: '运行全面评估' }))

    expect((await screen.findByRole('alert')).textContent).toContain('分析服务不可用')
    expect(screen.getByText('行情图')).toBeTruthy()
  })

  it('starts a comprehensive A-share evaluation with financial and event modules', async () => {
    const createTask = vi.spyOn(api, 'createAnalysisTask').mockResolvedValue({
      ok: true, duplicate: false, task: { id: 'evaluation-task-a-share' },
    } as never)
    renderPage('/research/600519?market=a_shares&tf=1d&view=overview')

    fireEvent.click(screen.getByRole('button', { name: '运行全面评估' }))

    await waitFor(() => expect(createTask).toHaveBeenCalledWith(expect.objectContaining({
      payload: expect.objectContaining({
        modules: ['market', 'news', 'pa', 'ensemble', 'fundamentals', 'valuation', 'announcements', 'macro'],
        evaluation_profile: 'comprehensive',
        market_limit: 480,
      }),
    })))
  })

  it('uses the saved unified decision and blocks simulation on conflicts', async () => {
    const run = {
      id: 'run-conflicted', symbol: 'NVDA', market: 'us_stocks', timeframe: '1d',
      status: 'succeeded', modules: ['market', 'pa', 'ensemble'], input: {},
      summary: {
        market: { latest_price: 180, latest_time: '2026-08-16T00:00:00Z', source: 'fixture' },
        research_decision: {
          direction: 'conflicted', execution_eligible: false, decision_version: 'research-decision-v1',
          module_opinions: [
            { module: 'price_structure', direction: 'long', status: 'available', reason: 'trend up' },
            { module: 'model_consensus', direction: 'short', status: 'available', reason: 'model down' },
          ],
          conflicts: [{ kind: 'opposite_direction', modules: ['price_structure', 'model_consensus'], reason: '有效模块同时包含做多与做空意见', blocking: true }],
          invalidation_conditions: [], reevaluate_triggers: ['等待方向重新一致'],
        },
        evidence_fusion: {},
      },
      error: null, note: '', favorite: false, tags: [], archived_at: null,
      created_at: 1, updated_at: 1, evidence_count: 0, evidence: [],
    }
    vi.spyOn(api, 'researchRun').mockResolvedValue({ ok: true, run } as never)
    vi.spyOn(api, 'researchVerify').mockResolvedValue({
      ok: true, run_id: run.id, snapshot_count: 0, snapshots_valid: false,
      has_analysis_output: true, replay_ready: false, checks: [],
    })
    renderPage('/research/NVDA?market=us_stocks&tf=1d&view=history&run_id=run-conflicted', [run])

    expect((await screen.findAllByText(/方向分歧/)).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/有效模块同时包含做多与做空意见/).length).toBeGreaterThan(0)
    const simulation = screen.getByRole('button', { name: '进入模拟交易' }) as HTMLButtonElement
    expect(simulation.disabled).toBe(true)
    expect(screen.getByText(/不展示入场、止损和止盈动作/)).toBeTruthy()
  })

  it('renders action guidance together with fundamental and valuation summaries', async () => {
    vi.spyOn(api, 'researchRun').mockResolvedValue({ ok: true, run: reportRun } as never)
    vi.spyOn(api, 'researchVerify').mockResolvedValue({
      ok: true, run_id: reportRun.id, snapshot_count: 1, snapshots_valid: true,
      has_analysis_output: true, replay_ready: true, checks: [],
    })
    renderPage('/research/600519?market=a_shares&tf=1d&view=history&run_id=run-report&mode=investor', [reportRun])

    const moduleRail = screen.getByRole('region', { name: '财务、估值与事件状态' })
    expect(await within(moduleRail).findByText('质量稳健 · 盈利改善')).toBeTruthy()
    expect(within(moduleRail).getByText('合理区间 · 历史分位 42%')).toBeTruthy()
    expect(within(moduleRail).getByText('1 条已核实事件')).toBeTruthy()
    expect(within(moduleRail).getByText('1 条可靠传导')).toBeTruthy()
    expect(await screen.findByText('值得深入研究')).toBeTruthy()
    expect(screen.getByText('盈利与现金流趋势改善')).toBeTruthy()
    expect(screen.getByText('strong')).toBeTruthy()
    expect(screen.getByText('fair')).toBeTruthy()
    expect(screen.getByText(/自身历史分位 42%/)).toBeTruthy()
    expect(screen.getByText('事件时间线')).toBeTruthy()
    expect(screen.getByText('贵州茅台净利润增长')).toBeTruthy()
    expect(screen.getByText('美联储利率决议')).toBeTruthy()
    expect(screen.getByText('rates → 600519')).toBeTruthy()
    expect(screen.getByText('公司事件 · 已覆盖')).toBeTruthy()
    expect(screen.getByText('宏观传导 · 已覆盖')).toBeTruthy()
  })

  it('shows the latest completed research modules on the default overview', async () => {
    renderPage('/research/600519?market=a_shares&tf=1d&view=overview', [reportRun])

    const moduleRail = screen.getByRole('region', { name: '财务、估值与事件状态' })
    expect(await within(moduleRail).findByText('质量稳健 · 盈利改善')).toBeTruthy()
    expect(within(moduleRail).getByText('合理区间 · 历史分位 42%')).toBeTruthy()
    expect(within(moduleRail).getAllByText('已覆盖')).toHaveLength(4)
  })

  it('does not treat an unrelated factor run as missing deep-research data', async () => {
    const factorRun = {
      ...reportRun,
      id: 'factor-run',
      modules: ['factor_research'],
      summary: { factor_research: { ok: true } },
    }
    renderPage('/research/600519?market=a_shares&tf=1d&view=overview', [factorRun])

    const moduleRail = screen.getByRole('region', { name: '财务、估值与事件状态' })
    await waitFor(() => expect(within(moduleRail).getAllByText('待评估')).toHaveLength(4))
    expect(within(moduleRail).queryByText('数据缺口')).toBeNull()
  })

  it('keeps the selected run while switching modes and hides raw detail in quick mode', async () => {
    vi.spyOn(api, 'researchRun').mockResolvedValue({ ok: true, run: reportRun } as never)
    vi.spyOn(api, 'researchVerify').mockResolvedValue({
      ok: true, run_id: reportRun.id, snapshot_count: 1, snapshots_valid: true,
      has_analysis_output: true, replay_ready: true, checks: [],
    })
    renderPage('/research/600519?market=a_shares&tf=1d&view=history&run_id=run-report&mode=professional', [reportRun])

    expect(await screen.findByText('分析依据与版本')).toBeTruthy()
    fireEvent.change(screen.getByLabelText('研究查看方式'), { target: { value: 'quick' } })

    await waitFor(() => expect(screen.getByLabelText('current location').textContent).toContain('run_id=run-report'))
    expect(screen.getByLabelText('current location').textContent).toContain('mode=quick')
    expect(screen.queryByText('分析依据与版本')).toBeNull()
    expect(screen.queryByText('可解释量化评估')).toBeNull()
    expect(screen.queryByText(/raw_metric/)).toBeNull()
    expect(screen.getByText('模型结果仅用于研究，不构成交易建议。')).toBeTruthy()
    expect(screen.getByText('下一次财报公告')).toBeTruthy()
  })
})
