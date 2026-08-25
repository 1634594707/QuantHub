import { useCallback, useEffect, useState } from 'react'
import { api, HttpError } from '../api/client'
import { uid } from '../lib/uid'
import { useSecurityNameResolver } from './useSecurityNameResolver'
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
  price: number | null
  chgPct: number | null
  available: boolean
  pnl: number | null
  marketValue: number | null
  chgBasedScore: number | null
}

function toInput(h: PortfolioHolding): HoldingInput {
  return {
    id: h.id ?? uid(),
    code: h.code,
    name: h.name,
    shares: h.shares,
    cost: h.cost ?? h.price,
    market: h.market ?? 'a_shares',
  }
}

/**
 * 可编辑持仓：后端 SQLite 是唯一业务真源。
 *
 * 首屏只从 ``/portfolio`` 读取；读取失败时保持空列表并暴露错误，绝不读取旧浏览器缓存。
 * 编辑草稿仅存在于当前页面内存；DELETE 的同一请求失败可回滚该次乐观删除。
 */
export function useEditableHoldings(enabled = true) {
  const [list, setList] = useState<HoldingInput[]>([])
  const [seedCash, setSeedCash] = useState(0)
  const [seeded, setSeeded] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [mutationError, setMutationError] = useState('')

  const applyResolvedName = useCallback(
    (id: string, symbol: string, name: string) => {
      setList((prev) => prev.map((holding) => (
        holding.id === id && holding.code.trim().toUpperCase() === symbol && !holding.name.trim()
          ? { ...holding, name }
          : holding
      )))
    },
    [setList],
  )
  const { resolveName, resolvingIds } = useSecurityNameResolver(applyResolvedName)

  useEffect(() => {
    if (!enabled || seeded) return
    let active = true
    api
      .portfolio()
      .then((response) => {
        if (!active) return
        setList((response.holdings ?? []).map(toInput))
        setSeedCash(typeof response.summary?.cash === 'number' ? response.summary.cash : 0)
        setLoadError('')
        setSeeded(true)
      })
      .catch((reason) => {
        if (!active) return
        setList([])
        setSeedCash(0)
        setLoadError(reason instanceof Error ? reason.message : '持仓加载失败')
        setSeeded(true)
      })
    return () => {
      active = false
    }
  }, [enabled, seeded])

  const add = useCallback(
    (market = 'a_shares') => {
      // tmp- 前缀标识未持久化的行，commit 时才调 POST
      setList((prev) => [...prev, { id: `tmp-${uid()}`, code: '', name: '', shares: 0, cost: 0, market }])
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
      const index = list.findIndex((holding) => holding.id === id)
      const removed = list[index]
      if (!removed) return
      setMutationError('')
      setList((prev) => prev.filter((h) => h.id !== id))
      if (id.startsWith('tmp-')) return

      void api.deleteHolding(id).catch((error) => {
        if (error instanceof HttpError && error.status === 404) return
        setList((prev) => {
          if (prev.some((holding) => holding.id === id)) return prev
          const next = [...prev]
          next.splice(Math.min(index, next.length), 0, removed)
          return next
        })
        setMutationError(error instanceof Error ? error.message : '持仓删除失败')
      })
    },
    [list, setList],
  )

  const commit = useCallback(async () => {
    // 全量同步：tmp 行 POST 创建（用返回 id 替换），真实行 PATCH 更新
    const snapshot = list
    const failed: string[] = []
    setMutationError('')
    for (const h of snapshot) {
      if (h.id.startsWith('tmp-')) {
        if (!h.code) continue // 空行跳过
        try {
          const r = await api.addHolding({
            code: h.code, name: h.name, shares: h.shares, cost: h.cost, market: h.market,
          })
          setList((prev) => prev.map((x) => (x.id === h.id ? { ...r.holding } : x)))
        } catch {
          failed.push(h.code)
        }
      } else {
        try {
          const r = await api.updateHolding(h.id, {
            code: h.code, name: h.name, shares: h.shares, cost: h.cost, market: h.market,
          })
          setList((prev) => prev.map((x) => (x.id === h.id ? { ...r.holding } : x)))
        } catch {
          failed.push(h.code)
        }
      }
    }
    if (failed.length) {
      throw new Error(`以下持仓保存失败：${failed.join('、')}`)
    }
  }, [list, setList])

  return {
    list, add, update, remove, commit, seeded, seedCash, loadError,
    resolveName, resolvingIds, mutationError,
  }
}
