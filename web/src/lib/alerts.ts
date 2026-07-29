import type { AlertEvent } from '../api/types'

export function alertEventHref(event: AlertEvent): string {
  if (event.related_type === 'signal' && event.related_id) {
    return `/signals?signal_id=${encodeURIComponent(event.related_id)}`
  }
  const query = new URLSearchParams({ market: event.market, view: 'overview' })
  if (event.related_type === 'research_run' && event.related_id) {
    query.set('view', 'history')
    query.set('run_id', event.related_id)
  }
  return `/research/${encodeURIComponent(event.symbol)}?${query.toString()}`
}
