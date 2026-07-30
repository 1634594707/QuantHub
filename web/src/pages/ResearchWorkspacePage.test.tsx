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

function renderPage(path = '/research/NVDA?market=us_stocks&tf=1d&from=evaluate&view=overview') {
  vi.spyOn(api, 'researchRuns').mockResolvedValue({
    ok: true,
    count: 0,
    total: 0,
    next_cursor: null,
    runs: [],
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
})
