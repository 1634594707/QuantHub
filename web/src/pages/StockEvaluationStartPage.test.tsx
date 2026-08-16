import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { api } from '../api/client'
import StockEvaluationStartPage from './StockEvaluationStartPage'

function LocationProbe() {
  const location = useLocation()
  return <output aria-label="current location">{`${location.pathname}${location.search}`}</output>
}

function renderPage(preferenceOverride?: Record<string, unknown>) {
  vi.spyOn(api, 'health').mockResolvedValue({ ok: true } as never)
  vi.spyOn(api, 'watchlist').mockResolvedValue({ ok: true, items: [] } as never)
  vi.spyOn(api, 'researchPreference').mockResolvedValue({
    ok: true,
    preference: preferenceOverride ?? {
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
    <MemoryRouter initialEntries={['/evaluate']}>
      <StockEvaluationStartPage />
      <LocationProbe />
    </MemoryRouter>,
  )
}

afterEach(() => {
  cleanup()
  localStorage.clear()
  vi.restoreAllMocks()
})

describe('StockEvaluationStartPage', () => {
  it('opens the workspace without creating or looking up an evaluation task', async () => {
    const recentTask = vi.spyOn(api, 'recentAnalysisTask')
    const createTask = vi.spyOn(api, 'createAnalysisTask')
    renderPage()

    fireEvent.click(screen.getByRole('button', { name: '选择示例标的' }))
    fireEvent.click(screen.getByRole('button', { name: '进入评估工作区' }))

    await waitFor(() => {
      expect(screen.getByLabelText('current location').textContent).toBe(
        '/research/600519?market=a_shares&tf=1d&from=evaluate&view=overview&mode=investor',
      )
    })
    expect(recentTask).not.toHaveBeenCalled()
    expect(createTask).not.toHaveBeenCalled()
    expect(screen.getByLabelText('current location').textContent).not.toContain('evaluation_task_id')
  })

  it('creates an evaluation task only after the explicit start action', async () => {
    vi.spyOn(api, 'recentAnalysisTask').mockResolvedValue({ ok: true, task: null })
    const createTask = vi.spyOn(api, 'createAnalysisTask').mockResolvedValue({
      ok: true,
      duplicate: false,
      task: { id: 'evaluation-task-1' },
    } as never)
    renderPage()

    fireEvent.click(screen.getByRole('button', { name: '选择示例标的' }))
    fireEvent.click(screen.getByRole('button', { name: '开始评估' }))

    await waitFor(() => expect(createTask).toHaveBeenCalledTimes(1))
    expect(createTask.mock.calls[0][0].payload).toMatchObject({
      research_mode: 'investor',
      holding_status: 'not_held',
    })
    await waitFor(() => expect(screen.getByLabelText('current location').textContent).toContain(
      'evaluation_task_id=evaluation-task-1',
    ))
  })

  it('adds point-in-time financial and event modules to comprehensive A-share evaluation', async () => {
    vi.spyOn(api, 'recentAnalysisTask').mockResolvedValue({ ok: true, task: null })
    const createTask = vi.spyOn(api, 'createAnalysisTask').mockResolvedValue({
      ok: true,
      duplicate: false,
      task: { id: 'evaluation-task-2' },
    } as never)
    renderPage()

    fireEvent.click(screen.getByRole('button', { name: '选择示例标的' }))
    fireEvent.click(screen.getByRole('tab', { name: '全面评估' }))
    fireEvent.click(screen.getByRole('button', { name: '开始评估' }))

    await waitFor(() => expect(createTask).toHaveBeenCalledTimes(1))
    const request = createTask.mock.calls[0]?.[0]
    expect(request).toBeDefined()
    expect(request?.payload?.modules).toEqual([
      'market', 'news', 'pa', 'ensemble', 'fundamentals', 'valuation', 'announcements', 'macro',
    ])
  })

  it('adds SEC fundamentals and valuation to comprehensive US-stock evaluation', async () => {
    vi.spyOn(api, 'recentAnalysisTask').mockResolvedValue({ ok: true, task: null })
    const createTask = vi.spyOn(api, 'createAnalysisTask').mockResolvedValue({
      ok: true,
      duplicate: false,
      task: { id: 'evaluation-task-us' },
    } as never)
    renderPage({
      user_id: 'local-user', default_mode: 'professional', default_market: 'us_stocks',
      holding_status: 'not_held', research_horizon: 'medium', risk_preference: 'balanced',
      terminology_level: 'technical', updated_at: '2026-08-16T00:00:00Z',
    })

    await waitFor(() => expect(screen.getByRole('tab', { name: '美股' }).getAttribute('aria-selected')).toBe('true'))
    fireEvent.click(screen.getByRole('button', { name: '选择示例标的' }))
    fireEvent.click(screen.getByRole('tab', { name: '全面评估' }))
    fireEvent.click(screen.getByRole('button', { name: '开始评估' }))

    await waitFor(() => expect(createTask).toHaveBeenCalledTimes(1))
    expect(createTask.mock.calls[0]?.[0].payload?.modules).toEqual([
      'market', 'pa', 'ensemble', 'fundamentals', 'valuation',
    ])
  })

  it('hydrates and persists the server-side research preference', async () => {
    renderPage({
      user_id: 'local-user', default_mode: 'quick', default_market: 'a_shares',
      holding_status: 'held', research_horizon: 'medium', risk_preference: 'conservative',
      terminology_level: 'plain', updated_at: '2026-08-16T00:00:00Z',
    })

    await waitFor(() => expect(screen.getByRole('tab', { name: '简明' }).getAttribute('aria-selected')).toBe('true'))
    expect(screen.getByRole('tab', { name: '已持仓' }).getAttribute('aria-selected')).toBe('true')
    fireEvent.click(screen.getByRole('tab', { name: '专业验证' }))

    await waitFor(() => expect(api.updateResearchPreference).toHaveBeenCalledWith(expect.objectContaining({
      default_mode: 'professional', holding_status: 'held', research_horizon: 'medium',
    })))
  })
})
