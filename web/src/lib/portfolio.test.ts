import { describe, expect, it } from 'vitest'
import { computeSummary, deriveHolding } from './portfolio'
import type { HoldingInput } from '../hooks/useEditableHoldings'

const holding: HoldingInput = {
  id: 'h-1',
  code: '600519',
  name: '贵州茅台',
  shares: 2,
  cost: 100,
  market: 'a_shares',
}

describe('research portfolio valuation truth', () => {
  it('keeps valuation fields unavailable when the primary quote fails', () => {
    const row = deriveHolding(holding, {
      price: null,
      chgPct: null,
      available: false,
    })

    expect(row.available).toBe(false)
    expect(row.price).toBeNull()
    expect(row.marketValue).toBeNull()
    expect(row.pnl).toBeNull()
    expect(row.chgBasedScore).toBeNull()
  })

  it('does not include cost-derived values in NAV when any holding is unpriced', () => {
    const priced = deriveHolding(holding, { price: 110, chgPct: 1, available: true })
    const unavailable = deriveHolding({ ...holding, id: 'h-2', code: 'BTC-USDT' }, undefined)

    const summary = computeSummary([priced, unavailable], 50)

    expect(summary.nav).toBeNull()
    expect(summary.dailyPnl).toBeNull()
    expect(summary.chgBasedScore).toBeNull()
    expect(summary.pricedPositions).toBe(1)
    expect(summary.unpricedPositions).toBe(1)
    expect(summary.valuationStatus).toBe('partial')
  })

  it('computes valuation only when every holding has a primary quote', () => {
    const row = deriveHolding(holding, { price: 110, chgPct: 1, available: true })
    const summary = computeSummary([row], 50)

    expect(summary.nav).toBe(270)
    expect(summary.dailyPnl).toBe(20)
    expect(summary.valuationStatus).toBe('available')
  })
})
