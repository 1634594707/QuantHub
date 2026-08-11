import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import RadarPage from './RadarPage'

const quote = {
  sym: '600519',
  name: '贵州茅台',
  market: 'a_shares',
  price: 1688,
  chgPct: 1.25,
  available: true,
  source: 'tencent',
  observed_at: '2026-08-11T10:00:00Z',
  freshness: 'live',
  status: 'available',
  error: null,
} as const

const currentSignal = {
  id: 'signal-current',
  symbol: '600519',
  market: 'a_shares',
  timeframe: '1h',
  direction: 'buy',
  score: 0.74,
  confidence: 0.81,
  source: 'structured_model',
  tags: [],
  meta: {},
  ts: '2026-08-11T09:58:00Z',
  status: 'new',
  expires_at: 4_000_000_000,
  radar_state: 'current',
} as const

function mockPool() {
  vi.spyOn(api, 'watchlist').mockResolvedValue({
    items: [{ id: 'watch-1', sym: '600519', name: '贵州茅台', market: 'a_shares' }],
  } as never)
  vi.spyOn(api, 'researchRuns').mockResolvedValue({ ok: true, count: 0, total: 0, next_cursor: null, runs: [] } as never)
  vi.spyOn(api, 'quote').mockResolvedValue(quote as never)
}

function mockRadar(signals: unknown[]) {
  vi.spyOn(api, 'radarSignals').mockResolvedValue({
    count: signals.length,
    current_count: signals.filter((item) => (item as { radar_state?: string }).radar_state === 'current').length,
    expired_count: signals.filter((item) => (item as { radar_state?: string }).radar_state === 'expired').length,
    scanned: signals.length,
    generated_at: 1_786_440_000,
    signals,
  } as never)
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/radar']}>
      <RadarPage />
    </MemoryRouter>,
  )
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('RadarPage truthful data states', () => {
  beforeEach(() => mockPool())

  it('renders a current confidence only from the selected signal', async () => {
    mockRadar([currentSignal])
    renderPage()

    expect(await screen.findByRole('img', { name: '把握度 81%' })).not.toBeNull()
    expect(screen.getByText('structured_model')).not.toBeNull()
    expect(screen.queryByText('30%')).toBeNull()
  })

  it('renders quote-only without reserving an empty confidence gauge', async () => {
    mockRadar([])
    renderPage()

    expect(await screen.findByText('仅实时报价')).not.toBeNull()
    expect(screen.queryByRole('img', { name: /把握度/ })).toBeNull()
  })

  it('renders an expired signal without showing its former confidence as current', async () => {
    mockRadar([{ ...currentSignal, id: 'signal-expired', confidence: 0.93, radar_state: 'expired', status: 'expired' }])
    renderPage()

    expect(await screen.findByText('信号已过期')).not.toBeNull()
    expect(screen.queryByRole('img', { name: /把握度/ })).toBeNull()
    expect(screen.getByText(/ID signal-expired/)).not.toBeNull()
  })

  it('keeps the quote visible when the signal service fails', async () => {
    vi.spyOn(api, 'radarSignals').mockRejectedValue(new Error('signals upstream unavailable'))
    renderPage()

    await waitFor(() => expect(screen.getAllByText('信号服务失败').length).toBeGreaterThan(0))
    expect(await screen.findByText('+1.25%')).not.toBeNull()
    expect(screen.getByText('报价仍可用；当前不展示缓存信号。')).not.toBeNull()
  })

  it('shows the exact quote failure and retry action', async () => {
    mockRadar([currentSignal])
    vi.mocked(api.quote).mockRejectedValue(new Error('quote gateway timeout'))
    renderPage()

    expect(await screen.findByText(/quote gateway timeout/)).not.toBeNull()
    expect(screen.getByRole('button', { name: '重试报价' })).not.toBeNull()
    expect(screen.queryByRole('img', { name: /把握度/ })).toBeNull()
  })
})
