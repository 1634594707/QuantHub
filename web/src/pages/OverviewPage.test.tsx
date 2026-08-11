import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import {
  INTERFACE_MODE_STORAGE_KEY,
  InterfaceModeProvider,
  useInterfaceMode,
} from '../hooks/useInterfaceMode'
import OverviewPage from './OverviewPage'

vi.mock('../components/KlineCard', () => ({ default: () => null }))
vi.mock('../components/DecisionPanel', () => ({ default: () => null }))
vi.mock('../components/HoldingsTable', () => ({ default: () => null }))
vi.mock('../components/Watchlist', () => ({ default: () => null }))
vi.mock('../components/MarketBreadth', () => ({ default: () => null }))
vi.mock('../components/KpiRow', () => ({ default: () => null }))

const ADVANCED_ACTION_METHODS = ['signals', 'incidents', 'factorResearchAttention', 'automationAlerts'] as const

function Harness() {
  const [, setMode] = useInterfaceMode()
  return (
    <>
      <button type="button" onClick={() => setMode('advanced')}>切换完整界面</button>
      <OverviewPage />
    </>
  )
}

function renderOverview() {
  return render(
    <MemoryRouter>
      <InterfaceModeProvider>
        <Harness />
      </InterfaceModeProvider>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  localStorage.setItem(INTERFACE_MODE_STORAGE_KEY, 'beginner')
  localStorage.setItem('quanthub.overview.modules.advanced.v1', JSON.stringify({
    order: ['evaluation', 'market', 'actions', 'account', 'analysis'],
    hidden: ['market', 'account', 'analysis'],
  }))
  vi.spyOn(api, 'marketBreadth').mockResolvedValue({ up: 1, down: 1 } as never)
  vi.spyOn(api, 'watchlist').mockResolvedValue({ items: [] } as never)
  vi.spyOn(api, 'alertEvents').mockResolvedValue({ count: 0, events: [] } as never)
  vi.spyOn(api, 'analysisTasks').mockResolvedValue({ total: 0, tasks: [] } as never)
  vi.spyOn(api, 'simulationOrders').mockResolvedValue({ orders: [] } as never)
  vi.spyOn(api, 'signals').mockResolvedValue({ total: 0, signals: [] } as never)
  vi.spyOn(api, 'incidents').mockResolvedValue({ total: 0, incidents: [] } as never)
  vi.spyOn(api, 'factorResearchAttention').mockResolvedValue({
    counts: { needs_revalidation: 0, invalidated: 0, data_stale: 0 },
    items: [],
    stale_hours: 24,
  } as never)
  vi.spyOn(api, 'automationAlerts').mockResolvedValue({ count: 0, alerts: [] } as never)
})

afterEach(() => {
  cleanup()
  localStorage.clear()
  vi.restoreAllMocks()
})

describe('OverviewPage interface-aware data loading', () => {
  it('opens module controls from an explicit layout settings action', () => {
    renderOverview()

    expect(screen.queryByRole('region', { name: '总览布局设置' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: '布局设置' }))

    expect(screen.getByRole('region', { name: '总览布局设置' })).not.toBeNull()
    expect(screen.getByRole('button', { name: '布局设置' }).getAttribute('aria-expanded')).toBe('true')
  })

  it('loads only compact actions and omits advanced action APIs', async () => {
    renderOverview()

    await waitFor(() => {
      expect(api.alertEvents).toHaveBeenCalledTimes(1)
      expect(api.analysisTasks).toHaveBeenCalledTimes(1)
      expect(api.simulationOrders).toHaveBeenCalledTimes(1)
    })
    ADVANCED_ACTION_METHODS.forEach((method) => expect(api[method]).not.toHaveBeenCalled())
    expect(screen.queryByText('待审核信号')).toBeNull()
    expect(screen.getByText('待确认提醒')).not.toBeNull()
  })

  it('enables advanced action APIs immediately after switching modes', async () => {
    renderOverview()
    await waitFor(() => expect(api.alertEvents).toHaveBeenCalledTimes(1))

    fireEvent.click(screen.getByRole('button', { name: '切换完整界面' }))

    await waitFor(() => {
      ADVANCED_ACTION_METHODS.forEach((method) => expect(api[method]).toHaveBeenCalledTimes(1))
    })
    expect(await screen.findByText('待审核信号')).not.toBeNull()
  })
})
