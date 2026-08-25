import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from './client'
import { executeAnalysisTask } from './taskRunner'
import type { AnalysisTask } from './types'

const queuedTask: AnalysisTask = {
  id: 'task-1',
  kind: 'evaluation',
  status: 'queued',
  symbol: '600519',
  market: 'a_shares',
  timeframe: '1d',
  fingerprint: 'f',
  request: {},
  result: null,
  error: null,
  attempt: 1,
  parent_task_id: null,
  created_at: 1,
  updated_at: 1,
  started_at: null,
  finished_at: null,
  duration_ms: null,
}

afterEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
})

describe('analysis task progress contract', () => {
  it('surfaces SSE failure instead of switching to legacy polling', async () => {
    vi.spyOn(api, 'createAnalysisTask').mockResolvedValue({ ok: true, duplicate: false, task: queuedTask })
    const poll = vi.spyOn(api, 'analysisTask').mockRejectedValue(new Error('polling must not run'))
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(null, { status: 502 }))

    await expect(executeAnalysisTask({
      kind: 'evaluation',
      symbol: '600519',
      market: 'a_shares',
      timeframe: '1d',
    })).rejects.toThrow('SSE stream unavailable')
    expect(poll).not.toHaveBeenCalled()
  })
})
