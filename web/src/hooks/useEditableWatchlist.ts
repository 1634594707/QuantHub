import { useCallback, useEffect, useState } from 'react'
import { api, HttpError } from '../api/client'
import { useLocalStorage } from './useLocalStorage'
import { uid } from '../lib/uid'
import type { WatchlistItem } from '../api/types'
import { useSecurityNameResolver } from './useSecurityNameResolver'

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
  return { id: i.id ?? uid(), sym: i.sym, name: i.name, market: i.market ?? 'a_shares' }
}

/**
 * 可编辑关注列表：后端 SQLite 为真值源，localStorage 为离线缓存。
 *
 * 同步策略同 useEditableHoldings：编辑模式即时改 list，退出时 commit 全量同步。
 */
export function useEditableWatchlist() {
  const [list, setList] = useLocalStorage<WatchInput[]>(KEY, [])
  const [seeded, setSeeded] = useState(false)
  const [mutationError, setMutationError] = useState('')

  const applyResolvedName = useCallback(
    (id: string, symbol: string, name: string) => {
      setList((prev) => prev.map((watch) => (
        watch.id === id && watch.sym.trim().toUpperCase() === symbol && !watch.name.trim()
          ? { ...watch, name }
          : watch
      )))
    },
    [setList],
  )
  const { resolveName, resolvingIds } = useSecurityNameResolver(applyResolvedName)

  useEffect(() => {
    if (seeded) return
    let active = true
    api
      .watchlist()
      .then((r) => {
        if (!active) return
        const seed = (r.items ?? []).map(toInput)
        setList(seed)
        setSeeded(true)
      })
      .catch(() => {
        if (!active) return
        // 后端不可达时只保留用户缓存，绝不注入不可删除的演示关注项。
        setSeeded(true)
      })
    return () => {
      active = false
    }
  }, [seeded, setList])

  const add = useCallback(
    (market = 'a_shares') => {
      setList((prev) => [...prev, { id: `tmp-${uid()}`, sym: '', name: '', market }])
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
      const index = list.findIndex((watch) => watch.id === id)
      const removed = list[index]
      if (!removed) return
      setMutationError('')
      setList((prev) => prev.filter((w) => w.id !== id))
      if (id.startsWith('tmp-')) return

      void api.deleteWatch(id).catch((error) => {
        if (error instanceof HttpError && error.status === 404) return
        setList((prev) => {
          if (prev.some((watch) => watch.id === id)) return prev
          const next = [...prev]
          next.splice(Math.min(index, next.length), 0, removed)
          return next
        })
        setMutationError(error instanceof Error ? error.message : '关注标的删除失败')
      })
    },
    [list, setList],
  )

  const commit = useCallback(async () => {
    const snapshot = list
    const failed: string[] = []
    setMutationError('')
    for (const w of snapshot) {
      if (w.id.startsWith('tmp-')) {
        if (!w.sym) continue
        try {
          const r = await api.addWatch({ sym: w.sym, name: w.name, market: w.market })
          setList((prev) => prev.map((x) => (x.id === w.id ? { ...r.watch } : x)))
        } catch {
          failed.push(w.sym)
        }
      } else {
        try {
          const r = await api.updateWatch(w.id, { sym: w.sym, name: w.name, market: w.market })
          setList((prev) => prev.map((x) => (x.id === w.id ? { ...r.watch } : x)))
        } catch {
          failed.push(w.sym)
        }
      }
    }
    if (failed.length) {
      throw new Error(`以下关注标的保存失败：${failed.join('、')}`)
    }
  }, [list, setList])

  const reset = useCallback(() => {
    setMutationError('')
    setList([])
  }, [setList])

  return {
    list, add, update, remove, reset, commit, seeded,
    resolveName, resolvingIds, mutationError,
  }
}
