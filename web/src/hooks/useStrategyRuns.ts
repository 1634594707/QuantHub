import { useCallback } from 'react'
import { useLocalStorage } from './useLocalStorage'
import { uid } from '../lib/uid'
import type { RunResp } from '../api/types'

export interface RunRecord {
  id: string
  name: string
  params: Record<string, unknown>
  result: RunResp
  ts: string
}

const KEY = 'qh.strategy.runs.v1'

/** 本地持久化的策略运行历史（后端无此数据，仅用于前端回顾）。 */
export function useStrategyRuns() {
  const [runs, setRuns] = useLocalStorage<RunRecord[]>(KEY, [])

  const addRun = useCallback(
    (name: string, params: Record<string, unknown>, result: RunResp) => {
      setRuns((prev) =>
        [{ id: uid(), name, params, result, ts: new Date().toISOString() }, ...prev].slice(0, 200),
      )
    },
    [setRuns],
  )

  const runsFor = useCallback(
    (name: string, limit = 10) => runs.filter((r) => r.name === name).slice(0, limit),
    [runs],
  )

  const lastRun = useCallback(
    (name: string) => runs.find((r) => r.name === name),
    [runs],
  )

  const clear = useCallback(() => setRuns([]), [setRuns])

  return { runs, addRun, runsFor, lastRun, clear }
}
