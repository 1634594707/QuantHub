import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import StrategyLabPage from './StrategyLabPage'

const definition = {
  id: 'definition-1',
  name: '研究策略',
  strategy_key: 'alphamaster',
  market: 'us_stocks',
  description: '',
  tags: ['factor'],
  created_at: 1_785_400_000,
  updated_at: 1_785_400_000,
  versions: [],
}

const linkedExperiment = {
  id: 'experiment-1',
  definition_id: definition.id,
  research_run_id: 'factor-run-locked',
  symbol: 'AAPL',
  market: 'us_stocks',
  timeframe: '1d',
  version_id: null,
  status: 'pending',
  params: { cost_rate: 0.0001, slippage_rate: 0.0001 },
  note: '',
  created_at: 1_785_400_100,
  updated_at: 1_785_400_100,
}

function mockBaseApi(experiments = [] as typeof linkedExperiment[]) {
  vi.spyOn(api, 'strategyLabDefinitions').mockResolvedValue({
    count: 1,
    definitions: [definition],
  } as never)
  vi.spyOn(api, 'strategyLabDefinition').mockResolvedValue({
    ok: true,
    definition,
  } as never)
  vi.spyOn(api, 'strategyLabExperiments').mockResolvedValue({
    count: experiments.length,
    experiments,
  } as never)
  vi.spyOn(api, 'strategyLabRuns').mockResolvedValue({ count: 0, runs: [] } as never)
  vi.spyOn(api, 'strategies').mockResolvedValue({
    strategies: [{ name: 'alphamaster', market: 'mt5', live_capable: false, description: '' }],
  } as never)
}

function renderPage(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <StrategyLabPage />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  HTMLElement.prototype.scrollIntoView = vi.fn()
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('StrategyLabPage research contract', () => {
  it('submits the research run id from the factor research entry unchanged', async () => {
    mockBaseApi()
    const create = vi.spyOn(api, 'createStrategyExperiment').mockResolvedValue({
      ok: true,
      experiment: linkedExperiment,
    } as never)
    renderPage(
      '/strategy-lab?definition_id=definition-1&action=create_experiment&symbol=AAPL&market=us_stocks&timeframe=1d&research_run_id=factor-run-locked',
    )

    expect(await screen.findByDisplayValue('factor-run-locked')).toBeTruthy()
    expect((screen.getByLabelText('标的') as HTMLInputElement).disabled).toBe(true)
    expect(screen.getAllByLabelText('市场').some((field) => (field as HTMLSelectElement).disabled)).toBe(true)
    expect(screen.getAllByLabelText('周期').some((field) => (field as HTMLInputElement).disabled)).toBe(true)
    const createButton = screen.getByRole('button', { name: '创建实验' })
    fireEvent.submit(createButton.closest('form') as HTMLFormElement)

    await waitFor(() => expect(create).toHaveBeenCalledWith(
      'definition-1',
      expect.objectContaining({
        symbol: 'AAPL',
        market: 'us_stocks',
        timeframe: '1d',
        research_run_id: 'factor-run-locked',
      }),
    ))
  })

  it('shows the fixed research backlink and locks linked experiment context', async () => {
    mockBaseApi([linkedExperiment])
    renderPage('/strategy-lab?definition_id=definition-1&experiment_id=experiment-1')

    expect(await screen.findByText('研究上下文已锁定')).toBeTruthy()
    const links = screen.getAllByRole('link', { name: '返回因子研究' })
    expect(links.some((link) => link.getAttribute('href') === '/factor-research?run_id=factor-run-locked')).toBe(true)
    expect((screen.getByLabelText('实验标的') as HTMLInputElement).disabled).toBe(true)
    expect(screen.getAllByLabelText('市场').some((field) => (field as HTMLSelectElement).disabled)).toBe(true)
    expect(screen.getAllByLabelText('周期').some((field) => (field as HTMLInputElement).disabled)).toBe(true)
  })
})
