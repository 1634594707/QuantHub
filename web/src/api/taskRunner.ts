import { api } from './client'
import type { AnalysisTask, AnalysisTaskKind } from './types'

interface AnalysisTaskSpec {
  kind: AnalysisTaskKind
  symbol: string
  market: string
  timeframe: string
  payload?: Record<string, unknown>
  timeoutSeconds?: number
}

function wait(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(resolve, ms)
    signal?.addEventListener('abort', () => {
      window.clearTimeout(timer)
      reject(new DOMException('任务轮询已中止', 'AbortError'))
    }, { once: true })
  })
}

function storageKey(task: Pick<AnalysisTaskSpec, 'kind' | 'symbol' | 'market' | 'timeframe'>): string {
  return `qh.analysis-task.${task.kind}.${task.market}.${task.symbol}.${task.timeframe}`
}

export async function executeAnalysisTask<T>(
  spec: AnalysisTaskSpec,
  options: { signal?: AbortSignal; onTask?: (task: AnalysisTask) => void } = {},
): Promise<T> {
  const normalized = { ...spec, symbol: spec.symbol.trim().toUpperCase() }
  const created = await api.createAnalysisTask({
    kind: normalized.kind,
    symbol: normalized.symbol,
    market: normalized.market,
    timeframe: normalized.timeframe,
    payload: normalized.payload,
    timeout_seconds: normalized.timeoutSeconds ?? 90,
  })
  let task = created.task
  options.onTask?.(task)
  try {
    localStorage.setItem(storageKey(normalized), task.id)
  } catch {
    // Storage may be unavailable in private or embedded browser contexts.
  }

  while (task.status === 'queued' || task.status === 'running') {
    if (options.signal?.aborted) throw new DOMException('任务轮询已中止', 'AbortError')
    await wait(750, options.signal)
    task = (await api.analysisTask(task.id)).task
    options.onTask?.(task)
  }

  try {
    localStorage.removeItem(storageKey(normalized))
  } catch {
    // Ignore unavailable storage.
  }
  if (task.status === 'succeeded' && task.result) return task.result as T
  throw new Error(task.error || `分析任务结束：${task.status}`)
}
