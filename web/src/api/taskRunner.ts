import { api, getApiToken, getBase } from './client'
import type { AnalysisTask, AnalysisTaskKind } from './types'

interface AnalysisTaskSpec {
  kind: AnalysisTaskKind
  symbol: string
  market: string
  timeframe: string
  payload?: Record<string, unknown>
  timeoutSeconds?: number
}

async function streamTask(
  taskId: string,
  options: { signal?: AbortSignal; onTask?: (task: AnalysisTask) => void },
): Promise<AnalysisTask> {
  const headers = new Headers({ Accept: 'text/event-stream' })
  const token = getApiToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const response = await fetch(`${getBase()}/analysis/tasks/${encodeURIComponent(taskId)}/stream`, {
    headers,
    signal: options.signal,
  })
  if (!response.ok || !response.body) throw new Error(`SSE stream unavailable (${response.status})`)
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let latest: AnalysisTask | null = null
  try {
    while (true) {
      const chunk = await reader.read()
      if (chunk.done) break
      buffer += decoder.decode(chunk.value, { stream: true })
      const frames = buffer.split(/\r?\n\r?\n/)
      buffer = frames.pop() ?? ''
      for (const frame of frames) {
        const data = frame.split(/\r?\n/).find((line) => line.startsWith('data:'))?.slice(5).trim()
        if (!data || data === '{}') continue
        const task = JSON.parse(data) as AnalysisTask
        latest = task
        options.onTask?.(task)
      }
    }
  } finally {
    reader.releaseLock()
  }
  if (!latest) throw new Error('SSE stream ended without a task')
  return latest
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

  if (task.status === 'queued' || task.status === 'running') {
    // The stream is the single task-progress contract.  A stream failure is
    // surfaced to the caller instead of silently switching to the legacy
    // polling endpoint, which could observe a different task state.
    task = await streamTask(task.id, options)
  }

  if (task.status === 'succeeded' && task.result) return task.result as T
  throw new Error(task.error || `分析任务结束：${task.status}`)
}
