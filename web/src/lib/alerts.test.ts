import { describe, expect, it } from 'vitest'
import type { AlertEvent } from '../api/types'
import { alertEventHref } from './alerts'

const BASE_EVENT: AlertEvent = {
  id: 'EVENT-1',
  rule_id: 'ALERT-1',
  status: 'pending',
  message: '提醒',
  observed_value: 1600,
  related_type: 'instrument',
  related_id: '600519',
  delivery: {},
  triggered_at: 1,
  acknowledged_at: null,
  rule_name: '价格提醒',
  symbol: '600519',
  market: 'a_shares',
}

describe('alertEventHref', () => {
  it('opens a signal by its exact signal_id', () => {
    expect(alertEventHref({ ...BASE_EVENT, related_type: 'signal', related_id: 'SIG-1' }))
      .toBe('/signals?signal_id=SIG-1')
  })

  it('opens the associated research run in history', () => {
    expect(alertEventHref({ ...BASE_EVENT, related_type: 'research_run', related_id: 'RUN-1' }))
      .toBe('/research/600519?market=a_shares&view=history&run_id=RUN-1')
  })

  it('opens the instrument research overview for a price event', () => {
    expect(alertEventHref(BASE_EVENT))
      .toBe('/research/600519?market=a_shares&view=overview')
  })
})
