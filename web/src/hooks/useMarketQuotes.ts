import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { QuoteResp } from '../api/types'

export type QuoteMap = Record<string, QuoteResp>

/** 实时报价 map 的键：market:symbol。 */
export function quoteKey(market: string, symbol: string) {
  return `${market}:${symbol}`
}

/**
 * 批量拉取一组标的的实时报价（A股/美股走腾讯真实源，加密货 available=false）。
 * items 为空时不发请求。依赖 JSON 化的 items 变化触发刷新。
 */
export function useMarketQuotes(items: { market: string; symbol: string }[]) {
  const [map, setMap] = useState<QuoteMap>({})
  const key = JSON.stringify(items)

  useEffect(() => {
    if (items.length === 0) {
      setMap({})
      return
    }
    let cancelled = false
    Promise.all(
      items.map((i) =>
        api
          .quote(i.symbol, i.market)
          .then((q) => [quoteKey(i.market, i.symbol), q] as const)
          .catch(() => null),
      ),
    ).then((results) => {
      if (cancelled) return
      const m: QuoteMap = {}
      results.forEach((r) => {
        if (r) m[r[0]] = r[1]
      })
      setMap(m)
    })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  return map
}
