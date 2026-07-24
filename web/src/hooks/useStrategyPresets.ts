import { useCallback } from 'react'
import { useLocalStorage } from './useLocalStorage'
import { uid } from '../lib/uid'

export interface Preset {
  id: string
  name: string
  params: Record<string, unknown>
}

const KEY = 'qh.strategy.presets.v1'

/** 本地持久化的策略参数预设（每个策略最多 20 组）。 */
export function useStrategyPresets() {
  const [presets, setPresets] = useLocalStorage<Record<string, Preset[]>>(KEY, {})

  const forStrategy = useCallback((name: string) => presets[name] ?? [], [presets])

  const save = useCallback(
    (name: string, presetName: string, params: Record<string, unknown>) => {
      setPresets((prev) => ({
        ...prev,
        [name]: [{ id: uid(), name: presetName, params }, ...(prev[name] ?? [])].slice(0, 20),
      }))
    },
    [setPresets],
  )

  const remove = useCallback(
    (name: string, id: string) => {
      setPresets((prev) => ({
        ...prev,
        [name]: (prev[name] ?? []).filter((p) => p.id !== id),
      }))
    },
    [setPresets],
  )

  return { presets, forStrategy, save, remove }
}
