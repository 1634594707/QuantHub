import { useCallback, useEffect, useState } from 'react'
import { api, HttpError } from '../api/client'
import { useLocalStorage } from './useLocalStorage'
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
  price: number
  chgPct: number
  available: boolean
  pnl: number
  marketValue: number
  chgBasedScore: number
}

const KEY = 'qh.holdings.v1'
const CASH_KEY = 'qh.portfolio.cash.v1'

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
 * 可编辑持仓：后端 SQLite 为真值源，localStorage 为离线缓存。
 *
 * 同步策略：
 *   - 首屏从 ``/portfolio`` 加载，覆盖 localStorage
 *   - 编辑模式中 add/update/remove 即时改 list（保持流畅输入）
 *   - remove 先做本地乐观更新，并立即提交 DELETE；失败时恢复原行
 *   - 退出编辑模式时调用 ``commit()`` 全量同步：
 *     tmp- 前缀行（code 非空）→ ``POST``；真实行 → ``PATCH``
 *   - 后端不可达时只保留 localStorage 中的用户缓存
 */
export function useEditableHoldings() {
  const [list, setList] = useLocalStorage<HoldingInput[]>(KEY, [])
  const [seedCash, setSeedCash] = useLocalStorage<number>(CASH_KEY, 0)
  const [seeded, setSeeded] = useState(false)
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
    if (seeded) return
    let active = true
    api
      .portfolio()
      .then((r) => {
        if (!active) return
        const seed = (r.holdings ?? []).map(toInput)
        setList(seed)
        if (typeof r.summary?.cash === 'number') {
          setSeedCash(r.summary.cash)
        }
        setSeeded(true)
      })
      .catch(() => {
        if (!active) return
        // 后端不可达时只保留用户缓存，绝不注入不可删除的演示持仓。
        setSeeded(true)
      })
    return () => {
      active = false
    }
  }, [seeded, setList, setSeedCash])

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
    list, add, update, remove, commit, seeded, seedCash,
    resolveName, resolvingIds, mutationError,
  }
}
