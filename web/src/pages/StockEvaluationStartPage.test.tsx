import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { api } from '../api/client'
import StockEvaluationStartPage from './StockEvaluationStartPage'

function LocationProbe() {
  const location = useLocation()
  return <output aria-label="current location">{`${location.pathname}${location.search}`}</output>
}

function renderPage() {
  vi.spyOn(api, 'health').mockResolvedValue({ ok: true } as never)
  vi.spyOn(api, 'watchlist').mockResolvedValue({ ok: true, items: [] } as never)
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
        '/research/600519?market=a_shares&tf=1d&from=evaluate&view=overview',
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
    expect(screen.getByLabelText('current location').textContent).toContain(
      'evaluation_task_id=evaluation-task-1',
    )
  })
})
