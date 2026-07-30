import type { AlertEvent } from '../api/types'
import { researchResultHref } from './researchResults'

export function alertEventHref(event: AlertEvent): string {
  if (event.related_type === 'signal' && event.related_id) {
    return `/signals?signal_id=${encodeURIComponent(event.related_id)}`
  }
  const query = new URLSearchParams({ market: event.market, view: 'overview' })
  if (event.related_type === 'research_run' && event.related_id) {
    return researchResultHref({
      runId: event.related_id,
      modules: event.related_modules,
      symbol: event.symbol,
      market: event.market,
      timeframe: '1d',
    })
  }
  return `/research/${encodeURIComponent(event.symbol)}?${query.toString()}`
}
