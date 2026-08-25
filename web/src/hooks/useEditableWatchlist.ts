import { useCallback, useEffect, useState } from 'react'
import { api, HttpError } from '../api/client'
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

function toInput(i: WatchlistItem): WatchInput {
  return { id: i.id ?? uid(), sym: i.sym, name: i.name, market: i.market ?? 'a_shares' }
}

/**
 * 可编辑关注列表：后端 SQLite 是唯一业务真源。
 *
 * GET 失败时保持空列表并暴露错误；编辑草稿只保留在当前页面内存中。
 */
export function useEditableWatchlist(enabled = true) {
  const [list, setList] = useState<WatchInput[]>([])
  const [seeded, setSeeded] = useState(false)
  const [loadError, setLoadError] = useState('')
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
    if (!enabled || seeded) return
    let active = true
    api
      .watchlist()
      .then((response) => {
        if (!active) return
        setList((response.items ?? []).map(toInput))
        setLoadError('')
        setSeeded(true)
      })
      .catch((reason) => {
        if (!active) return
        setList([])
        setLoadError(reason instanceof Error ? reason.message : '关注列表加载失败')
        setSeeded(true)
      })
    return () => {
      active = false
    }
  }, [enabled, seeded])

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

  return {
    list, add, update, remove, commit, seeded, loadError,
    resolveName, resolvingIds, mutationError,
  }
}
