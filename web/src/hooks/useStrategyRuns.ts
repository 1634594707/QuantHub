import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { RunRecord, RunResp } from '../api/types'

/** 策略运行历史仅由后端持久化；请求失败时不读取或展示任何本地旧数据。 */
export function useStrategyRuns() {
  const [runs, setRuns] = useState<RunRecord[]>([])
  const [error, setError] = useState('')
  const didInit = useRef(false)

  useEffect(() => {
    if (didInit.current) return
    didInit.current = true
    api
      .strategyRuns()
      .then((response) => {
        setRuns(response.runs)
        setError('')
      })
      .catch((reason) => {
        setRuns([])
        setError(reason instanceof Error ? reason.message : '策略运行历史加载失败')
      })
  }, [])

  const addRun = useCallback(async (name: string, params: Record<string, unknown>, result: RunResp) => {
    try {
      const response = await api.saveRun(name, params, result)
      setRuns((previous) => [response.run, ...previous].slice(0, 200))
      setError('')
      return response.run
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : '策略运行记录保存失败'
      setError(message)
      throw reason instanceof Error ? reason : new Error(message)
    }
  }, [])

  const runsFor = useCallback(
    (name: string, limit = 10) => runs.filter((run) => run.name === name).slice(0, limit),
    [runs],
  )

  const lastRun = useCallback((name: string) => runs.find((run) => run.name === name), [runs])

  return { runs, error, addRun, runsFor, lastRun }
}
