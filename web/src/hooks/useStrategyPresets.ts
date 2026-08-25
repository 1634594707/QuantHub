import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { Preset } from '../api/types'

/** 策略参数预设仅由后端持久化；失败时不回退到浏览器业务缓存。 */
export function useStrategyPresets() {
  const [presets, setPresets] = useState<Record<string, Preset[]>>({})
  const [error, setError] = useState('')
  const didInit = useRef(false)

  useEffect(() => {
    if (didInit.current) return
    didInit.current = true
    api
      .strategyPresets()
      .then((response) => {
        setPresets(response.presets)
        setError('')
      })
      .catch((reason) => {
        setPresets({})
        setError(reason instanceof Error ? reason.message : '策略预设加载失败')
      })
  }, [])

  const forStrategy = useCallback((name: string) => presets[name] ?? [], [presets])

  const save = useCallback(async (name: string, presetName: string, params: Record<string, unknown>) => {
    try {
      const response = await api.savePreset(name, presetName, params)
      setPresets((previous) => ({
        ...previous,
        [name]: [response.preset, ...(previous[name] ?? [])].slice(0, 20),
      }))
      setError('')
      return response.preset
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : '策略预设保存失败'
      setError(message)
      throw reason instanceof Error ? reason : new Error(message)
    }
  }, [])

  const remove = useCallback(async (name: string, id: string) => {
    try {
      await api.deletePreset(name, id)
      setPresets((previous) => ({
        ...previous,
        [name]: (previous[name] ?? []).filter((preset) => preset.id !== id),
      }))
      setError('')
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : '策略预设删除失败'
      setError(message)
      throw reason instanceof Error ? reason : new Error(message)
    }
  }, [])

  return { presets, error, forStrategy, save, remove }
}
