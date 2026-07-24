import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import { useLocalStorage } from './useLocalStorage'
import { uid } from '../lib/uid'
import { HOLDINGS } from '../data/mock'
import type { PortfolioHolding } from '../api/types'

export interface HoldingInput {
  id: string
  code: string
  name: string
  shares: number
  cost: number
  market: string
}

export interface HoldingRow extends HoldingInput {
  price: number
  chgPct: number
  available: boolean
  pnl: number
  marketValue: number
  winRate: number
}

const KEY = 'qh.holdings.v1'

function toInput(h: PortfolioHolding): HoldingInput {
  return {
    id: uid(),
    code: h.code,
    name: h.name,
    shares: h.shares,
    cost: h.cost ?? h.price,
    market: 'a_shares',
  }
}

/**
 * 可编辑持仓：以 localStorage 为唯一真值来源（首屏用后端 /portfolio 播种）。
 * 编辑（增/改/删）即时落盘，刷新后保留。
 */
export function useEditableHoldings() {
  const [list, setList] = useLocalStorage<HoldingInput[]>(KEY, [])
  const [seeded, setSeeded] = useState(false)

  useEffect(() => {
    if (seeded) return
    let active = true
    api
      .portfolio()
      .then((r) => {
        if (!active) return
        const seed = (r.holdings ?? []).map(toInput)
        setList(
          seed.length
            ? seed
            : HOLDINGS.map((h) => ({
                id: uid(),
                code: h.code,
                name: h.name,
                shares: h.shares,
                cost: h.price,
                market: 'a_shares',
              })),
        )
        setSeeded(true)
      })
      .catch(() => {
        if (!active) return
        setList(
          HOLDINGS.map((h) => ({
            id: uid(),
            code: h.code,
            name: h.name,
            shares: h.shares,
            cost: h.price,
            market: 'a_shares',
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
      setList((prev) => [...prev, { id: uid(), code: '', name: '', shares: 0, cost: 0, market }])
    },
    [setList],
  )
  const update = useCallback(
    (id: string, patch: Partial<HoldingInput>) => {
      setList((prev) => prev.map((h) => (h.id === id ? { ...h, ...patch } : h)))
    },
    [setList],
  )
  const remove = useCallback(
    (id: string) => {
      setList((prev) => prev.filter((h) => h.id !== id))
    },
    [setList],
  )
  const reset = useCallback(() => setList([]), [setList])

  return { list, add, update, remove, reset, seeded }
}
