import type { ResearchRun } from '../api/types'

type ResearchResultContext = {
  runId: string
  modules?: string[]
  symbol?: string
  market?: string
  timeframe?: string
}

export function researchResultHref({
  runId,
  modules = [],
  symbol = '',
  market = 'a_shares',
  timeframe = '1d',
}: ResearchResultContext): string {
  if (modules.includes('factor_research')) {
    return `/factor-research?run_id=${encodeURIComponent(runId)}`
  }
  if (!symbol) return `/factor-research?run_id=${encodeURIComponent(runId)}`
  const query = new URLSearchParams({ market, tf: timeframe, view: 'history', run_id: runId })
  return `/research/${encodeURIComponent(symbol)}?${query.toString()}`
}

export function researchRunHref(run: Pick<ResearchRun, 'id' | 'modules' | 'symbol' | 'market' | 'timeframe'>): string {
  return researchResultHref({
    runId: run.id,
    modules: run.modules,
    symbol: run.symbol,
    market: run.market,
    timeframe: run.timeframe,
  })
}

export function linkedResultHref(
  resultType: string | null | undefined,
  resultId: string | null | undefined,
  context: Omit<ResearchResultContext, 'runId'> = {},
): string | null {
  if (!resultType || !resultId) return null
  if (resultType === 'signal') return `/signals?signal_id=${encodeURIComponent(resultId)}`
  if (resultType === 'simulation_order') return `/simulation?order_id=${encodeURIComponent(resultId)}`
  if (resultType === 'factor_research') return `/factor-research?run_id=${encodeURIComponent(resultId)}`
  if (resultType === 'research_run') return researchResultHref({ runId: resultId, ...context })
  return null
}
