import { beforeEach, describe, expect, it } from 'vitest'
import {
  recordUsabilityEvent,
  sanitizeUsabilityEvent,
  USABILITY_METRICS_STORAGE_KEY,
} from './usabilityMetrics'

describe('usability metrics privacy boundary', () => {
  beforeEach(() => localStorage.clear())

  it('keeps only the anonymous allowlist and drops sensitive payloads', () => {
    localStorage.setItem(USABILITY_METRICS_STORAGE_KEY, JSON.stringify([{
      name: 'research_started', step: 'setup', api_key: 'old-secret', symbol: 'AAPL',
    }]))
    recordUsabilityEvent({
      name: 'research_completed',
      page: 'factor_research',
      step: 'result_reading',
      at: 123,
      duration_ms: 4321,
      api_key: 'secret',
      positions: [{ symbol: '600519', quantity: 100 }],
      model_config: { endpoint: 'private' },
      symbol: '600519',
    })

    const stored = localStorage.getItem(USABILITY_METRICS_STORAGE_KEY) || ''
    expect(stored).toContain('research_completed')
    expect(stored).not.toContain('secret')
    expect(stored).not.toContain('AAPL')
    expect(stored).not.toContain('600519')
    expect(stored).not.toContain('positions')
    expect(stored).not.toContain('model_config')
  })

  it('rejects events outside the fixed event and step vocabulary', () => {
    expect(sanitizeUsabilityEvent({ name: 'api_key_captured', step: 'setup' })).toBeNull()
    expect(sanitizeUsabilityEvent({ name: 'research_started', step: 'portfolio' })).toBeNull()
  })
})
