import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
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
  it('starts the existing evaluation workflow from the workspace', async () => {
    const createTask = vi.spyOn(api, 'createAnalysisTask').mockResolvedValue({
      ok: true,
      duplicate: false,
      task: { id: 'evaluation-task-1' },
    } as never)
    renderPage()

    fireEvent.click(screen.getByRole('button', { name: '一键评估' }))

    await waitFor(() => expect(createTask).toHaveBeenCalledWith(expect.objectContaining({
      kind: 'evaluation',
      symbol: 'NVDA',
      market: 'us_stocks',
      timeframe: '1d',
      payload: expect.objectContaining({
        modules: ['market', 'pa', 'ensemble'],
        evaluation_profile: 'balanced',
        evaluation_horizon: 'swing',
      }),
    })))
    await waitFor(() => expect(screen.getByLabelText('current location').textContent).toContain(
      'evaluation_task_id=evaluation-task-1',
    ))
  })

  it('keeps the workspace readable when task creation fails', async () => {
    vi.spyOn(api, 'createAnalysisTask').mockRejectedValue(new Error('分析服务不可用'))
    renderPage()

    fireEvent.click(screen.getByRole('button', { name: '一键评估' }))

    expect((await screen.findByRole('alert')).textContent).toContain('分析服务不可用')
    expect(screen.getByText('行情图')).toBeTruthy()
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
})
