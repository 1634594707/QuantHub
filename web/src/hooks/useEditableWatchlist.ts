import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import { useLocalStorage } from './useLocalStorage'
import { uid } from '../lib/uid'
import { inferMarket } from '../lib/market'
import { WATCH } from '../data/mock'
import type { WatchlistItem } from '../api/types'

export interface WatchInput {
  id: string
  sym: string
  name: string
  market: string
}

export interface WatchRow extends WatchInput {
  price: number | null
  chgPct: number | null
  available: boolean
}

const KEY = 'qh.watchlist.v1'

function toInput(i: WatchlistItem): WatchInput {
  return { id: uid(), sym: i.sym, name: i.name, market: i.market ?? 'a_shares' }
}

/**
 * 可编辑关注列表：以 localStorage 为唯一真值来源（首屏用后端 /market/watchlist 播种）。
 * 编辑（增/改/删）即时落盘，刷新后保留。
 */
export function useEditableWatchlist() {
  const [list, setList] = useLocalStorage<WatchInput[]>(KEY, [])
  const [seeded, setSeeded] = useState(false)

  useEffect(() => {
    if (seeded) return
    let active = true
    api
      .watchlist()
      .then((r) => {
        if (!active) return
        const seed = (r.items ?? []).map(toInput)
        setList(
          seed.length
            ? seed
            : WATCH.map((w) => ({
                id: uid(),
                sym: w.sym,
                name: w.name,
                market: inferMarket(w.sym),
              })),
        )
        setSeeded(true)
      })
      .catch(() => {
        if (!active) return
        setList(
          WATCH.map((w) => ({
            id: uid(),
            sym: w.sym,
            name: w.name,
            market: inferMarket(w.sym),
          })),
        )
        setSeeded(true)
      })
    return () => {
      active = false
    }
  }, [seeded, setList])

  const add = useCallback(
    (market = 'a_shares') => {
      setList((prev) => [...prev, { id: uid(), sym: '', name: '', market }])
    },
    [setList],
  )
  const update = useCallback(
    (id: string, patch: Partial<WatchInput>) => {
      setList((prev) => prev.map((w) => (w.id === id ? { ...w, ...patch } : w)))
    },
    [setList],
  )
  const remove = useCallback(
    (id: string) => {
      setList((prev) => prev.filter((w) => w.id !== id))
    },
    [setList],
  )
  const reset = useCallback(() => setList([]), [setList])

  return { list, add, update, remove, reset, seeded }
}
