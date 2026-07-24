import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { useLocalStorage } from './useLocalStorage'
import { uid } from '../lib/uid'
import type { Preset } from '../api/types'

const KEY = 'qh.strategy.presets.v1'

/** 策略参数预设：后端持久化为真源，localStorage 仅作离线兜底（G2 收敛边界）。 */
export function useStrategyPresets() {
  const [local, setLocal] = useLocalStorage<Record<string, Preset[]>>(KEY, {})
  const [presets, setPresets] = useState<Record<string, Preset[]>>(local)
  const didInit = useRef(false)

  useEffect(() => {
    if (didInit.current) return
    didInit.current = true
    api
      .strategyPresets()
      .then((r) => setPresets(r.presets))
      .catch(() => setPresets(local)) // 后端不可用时回落本地
  }, [local])

  // 双向同步到 localStorage（离线兜底）
  useEffect(() => {
    setLocal(presets)
  }, [presets, setLocal])

  const forStrategy = useCallback((name: string) => presets[name] ?? [], [presets])

  const save = useCallback(
    async (name: string, presetName: string, params: Record<string, unknown>) => {
      const optimistic: Preset = { id: uid(), name: presetName, params }
      setPresets((p) => ({
        ...p,
        [name]: [optimistic, ...(p[name] ?? [])].slice(0, 20),
      }))
      try {
        const r = await api.savePreset(name, presetName, params)
        // 用后端真实 id 替换乐观项
        setPresets((p) => ({
          ...p,
          [name]: [r.preset, ...(p[name] ?? []).filter((x) => x.id !== optimistic.id)].slice(0, 20),
        }))
      } catch {
        /* 后端不可用：保留本地乐观项 */
      }
    },
    [],
  )

  const remove = useCallback(
    async (name: string, id: string) => {
      setPresets((p) => ({
        ...p,
        [name]: (p[name] ?? []).filter((x) => x.id !== id),
      }))
      try {
        await api.deletePreset(name, id)
      } catch {
        /* 保留本地 */
      }
    },
    [],
  )

  return { presets, forStrategy, save, remove }
}
