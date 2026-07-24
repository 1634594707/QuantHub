import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { useLocalStorage } from './useLocalStorage'
import { uid } from '../lib/uid'
import type { RunRecord, RunResp } from '../api/types'

const KEY = 'qh.strategy.runs.v1'

/** 策略运行历史：后端持久化为真源（跨设备），localStorage 仅作离线兜底（G2）。 */
export function useStrategyRuns() {
  const [local, setLocal] = useLocalStorage<RunRecord[]>(KEY, [])
  const [runs, setRuns] = useState<RunRecord[]>(local)
  const didInit = useRef(false)

  useEffect(() => {
    if (didInit.current) return
    didInit.current = true
    api
      .strategyRuns()
      .then((r) => setRuns(r.runs))
      .catch(() => setRuns(local))
  }, [local])

  useEffect(() => {
    setLocal(runs)
  }, [runs, setLocal])

  const addRun = useCallback(
    async (name: string, params: Record<string, unknown>, result: RunResp) => {
      const rec: RunRecord = {
        id: uid(),
        name,
        params,
        result,
        ts: Date.now() / 1000,
      }
      setRuns((prev) => [rec, ...prev].slice(0, 200))
      try {
        await api.saveRun(name, params, result)
      } catch {
        /* 后端不可用：保留本地 */
      }
    },
    [],
  )

  const runsFor = useCallback(
    (name: string, limit = 10) => runs.filter((r) => r.name === name).slice(0, limit),
    [runs],
  )

  const lastRun = useCallback((name: string) => runs.find((r) => r.name === name), [runs])

  const clear = useCallback(() => setRuns([]), [])

  return { runs, addRun, runsFor, lastRun, clear }
}
