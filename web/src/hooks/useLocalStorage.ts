import { useEffect, useState } from 'react'

/** localStorage 持久化的 state；读写失败（隐私模式等）静默降级。 */
export function useLocalStorage<T>(key: string, initial: T) {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key)
      return raw ? (JSON.parse(raw) as T) : initial
    } catch {
      return initial
    }
  })

  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(value))
    } catch {
      /* 忽略写入失败 */
    }
  }, [key, value])

  return [value, setValue] as const
}
