import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import { useEditableHoldings } from './useEditableHoldings'
import { useEditableWatchlist } from './useEditableWatchlist'
import { useStrategyPresets } from './useStrategyPresets'
import { useStrategyRuns } from './useStrategyRuns'

afterEach(() => {
  cleanup()
  localStorage.clear()
  vi.restoreAllMocks()
})

beforeEach(() => {
  localStorage.setItem('qh.strategy.runs.v1', JSON.stringify([
    { id: 'legacy-run', name: 'legacy', params: {}, result: { ok: true, count: 0, signals: [] }, ts: 1 },
  ]))
  localStorage.setItem('qh.strategy.presets.v1', JSON.stringify({
    legacy: [{ id: 'legacy-preset', name: '旧预设', params: {} }],
  }))
  localStorage.setItem('qh.holdings.v1', JSON.stringify([
    { id: 'legacy-holding', code: '000001', name: '旧持仓', shares: 1, cost: 1, market: 'a_shares' },
  ]))
  localStorage.setItem('qh.portfolio.cash.v1', JSON.stringify(999))
  localStorage.setItem('qh.watchlist.v1', JSON.stringify([
    { id: 'legacy-watch', sym: '000001', name: '旧自选', market: 'a_shares' },
  ]))
})

describe('business source-of-truth hooks', () => {
  it('does not display legacy strategy cache when the API read fails', async () => {
    vi.spyOn(api, 'strategyRuns').mockRejectedValue(new Error('runs unavailable'))
    vi.spyOn(api, 'strategyPresets').mockRejectedValue(new Error('presets unavailable'))

    const runs = renderHook(() => useStrategyRuns())
    const presets = renderHook(() => useStrategyPresets())

    await waitFor(() => expect(runs.result.current.error).toBe('runs unavailable'))
    await waitFor(() => expect(presets.result.current.error).toBe('presets unavailable'))

    expect(runs.result.current.runs).toEqual([])
    expect(presets.result.current.presets).toEqual({})
    expect(localStorage.getItem('qh.strategy.runs.v1')).not.toBeNull()
    expect(localStorage.getItem('qh.strategy.presets.v1')).not.toBeNull()
  })

  it('uses only successful strategy API data and rejects failed mutations without local state changes', async () => {
    vi.spyOn(api, 'strategyRuns').mockResolvedValue({
      runs: [{ id: 'api-run', name: 'api', params: {}, result: { ok: true, count: 0, signals: [] }, ts: 2 }],
    } as never)
    vi.spyOn(api, 'strategyPresets').mockResolvedValue({
      presets: { api: [{ id: 'api-preset', name: '服务端预设', params: { limit: 20 } }] },
    } as never)
    vi.spyOn(api, 'saveRun').mockRejectedValue(new Error('save run failed'))
    vi.spyOn(api, 'savePreset').mockRejectedValue(new Error('save preset failed'))
    vi.spyOn(api, 'deletePreset').mockRejectedValue(new Error('delete preset failed'))

    const runs = renderHook(() => useStrategyRuns())
    const presets = renderHook(() => useStrategyPresets())

    await waitFor(() => expect(runs.result.current.runs.map((item) => item.id)).toEqual(['api-run']))
    await waitFor(() => expect(presets.result.current.forStrategy('api').map((item) => item.id)).toEqual(['api-preset']))

    await act(async () => {
      await expect(runs.result.current.addRun('api', {}, { ok: true, count: 0, signals: [] } as never)).rejects.toThrow('save run failed')
    })
    expect(runs.result.current.runs.map((item) => item.id)).toEqual(['api-run'])

    await act(async () => {
      await expect(presets.result.current.save('api', '不应保存', {})).rejects.toThrow('save preset failed')
    })
    expect(presets.result.current.forStrategy('api').map((item) => item.id)).toEqual(['api-preset'])

    await act(async () => {
      await expect(presets.result.current.remove('api', 'api-preset')).rejects.toThrow('delete preset failed')
    })
    expect(presets.result.current.forStrategy('api').map((item) => item.id)).toEqual(['api-preset'])
  })

  it('does not display legacy holdings or cash when the portfolio API fails', async () => {
    vi.spyOn(api, 'portfolio').mockRejectedValue(new Error('portfolio unavailable'))

    const holdings = renderHook(() => useEditableHoldings())

    await waitFor(() => expect(holdings.result.current.seeded).toBe(true))
    expect(holdings.result.current.loadError).toBe('portfolio unavailable')
    expect(holdings.result.current.list).toEqual([])
    expect(holdings.result.current.seedCash).toBe(0)
    expect(localStorage.getItem('qh.holdings.v1')).not.toBeNull()
    expect(localStorage.getItem('qh.portfolio.cash.v1')).not.toBeNull()
  })

  it('uses holdings returned by the portfolio API only', async () => {
    vi.spyOn(api, 'portfolio').mockResolvedValue({
      holdings: [{ id: 'api-holding', code: '600519', name: '贵州茅台', shares: 2, cost: 1000, price: 1100, market: 'a_shares' }],
      summary: { cash: 321 },
    } as never)

    const holdings = renderHook(() => useEditableHoldings())

    await waitFor(() => expect(holdings.result.current.seeded).toBe(true))
    expect(holdings.result.current.list).toEqual([
      { id: 'api-holding', code: '600519', name: '贵州茅台', shares: 2, cost: 1000, market: 'a_shares' },
    ])
    expect(holdings.result.current.seedCash).toBe(321)
  })

  it('does not display legacy watchlist data when the API fails and uses API data on success', async () => {
    const watchlist = vi.spyOn(api, 'watchlist').mockRejectedValueOnce(new Error('watchlist unavailable'))
    const failed = renderHook(() => useEditableWatchlist())

    await waitFor(() => expect(failed.result.current.seeded).toBe(true))
    expect(failed.result.current.loadError).toBe('watchlist unavailable')
    expect(failed.result.current.list).toEqual([])
    failed.unmount()

    watchlist.mockResolvedValueOnce({
      items: [{ id: 'api-watch', sym: 'AAPL', name: 'Apple', market: 'us_stocks' }],
    } as never)
    const succeeded = renderHook(() => useEditableWatchlist())

    await waitFor(() => expect(succeeded.result.current.seeded).toBe(true))
    expect(succeeded.result.current.list).toEqual([
      { id: 'api-watch', sym: 'AAPL', name: 'Apple', market: 'us_stocks' },
    ])
    expect(localStorage.getItem('qh.watchlist.v1')).not.toBeNull()
  })
})
