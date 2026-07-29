import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'

const RESOLVE_DELAY_MS = 450

type ResolvedHandler = (id: string, symbol: string, name: string) => void

/** 对代码输入做短延迟解析，避免逐字符请求行情接口。 */
export function useSecurityNameResolver(onResolved: ResolvedHandler) {
  const timers = useRef(new Map<string, ReturnType<typeof setTimeout>>())
  const versions = useRef(new Map<string, number>())
  const [resolvingIds, setResolvingIds] = useState<ReadonlySet<string>>(new Set())

  const setResolving = useCallback((id: string, resolving: boolean) => {
    setResolvingIds((current) => {
      const next = new Set(current)
      if (resolving) next.add(id)
      else next.delete(id)
      return next
    })
  }, [])

  const resolveName = useCallback(
    (id: string, rawSymbol: string, market: string) => {
      const symbol = rawSymbol.trim().toUpperCase()
      const previousTimer = timers.current.get(id)
      if (previousTimer) clearTimeout(previousTimer)

      const version = (versions.current.get(id) ?? 0) + 1
      versions.current.set(id, version)
      setResolving(id, false)
      if (!symbol) return
      if (market === 'crypto') return
      if (market === 'a_shares' && !/^\d{6}$/.test(symbol)) return

      const timer = setTimeout(async () => {
        timers.current.delete(id)
        setResolving(id, true)
        try {
          const quote = await api.quote(symbol, market)
          if (versions.current.get(id) !== version) return
          const name = quote.name?.trim()
          if (name && name.toUpperCase() !== symbol) {
            onResolved(id, symbol, name)
          }
        } catch {
          // 名称识别失败不阻断编辑；保存时后端会再次尝试解析。
        } finally {
          if (versions.current.get(id) === version) setResolving(id, false)
        }
      }, RESOLVE_DELAY_MS)
      timers.current.set(id, timer)
    },
    [onResolved, setResolving],
  )

  useEffect(
    () => () => {
      timers.current.forEach(clearTimeout)
      timers.current.clear()
    },
    [],
  )

  return { resolveName, resolvingIds }
}
