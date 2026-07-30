import { describe, expect, it } from 'vitest'
import { researchResultHref, researchRunHref } from './researchResults'

describe('research result navigation', () => {
  it('routes factor research to its saved result reader', () => {
    expect(researchResultHref({ runId: 'factor-1', modules: ['factor_research'] }))
      .toBe('/factor-research?run_id=factor-1')
  })

  it('routes integrated research to the matching symbol history', () => {
    expect(researchRunHref({
      id: 'run-1', modules: ['pa', 'news'], symbol: '600519', market: 'a_shares', timeframe: '1d',
    })).toBe('/research/600519?market=a_shares&tf=1d&view=history&run_id=run-1')
  })
})
