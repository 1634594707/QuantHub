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
  try {
    localStorage.setItem(storageKey(normalized), task.id)
  } catch {
    // Storage may be unavailable in private or embedded browser contexts.
  }

  if (task.status === 'queued' || task.status === 'running') {
    try {
      task = await streamTask(task.id, options)
    } catch (streamError) {
      if (options.signal?.aborted) throw streamError
      // SSE 可能被旧版反向代理拦截，继续使用兼容轮询。
      while (task.status === 'queued' || task.status === 'running') {
        if (options.signal?.aborted) throw new DOMException('任务轮询已中止', 'AbortError')
        await wait(750, options.signal)
        task = (await api.analysisTask(task.id)).task
        options.onTask?.(task)
      }
    }
  }

  try {
    localStorage.removeItem(storageKey(normalized))
  } catch {
    // Ignore unavailable storage.
  }
  if (task.status === 'succeeded' && task.result) return task.result as T
  throw new Error(task.error || `分析任务结束：${task.status}`)
}
