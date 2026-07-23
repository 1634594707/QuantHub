// 通用异步数据 Hook：每个取数点都具备 loading / error / data 三态。
// 这是前端接入真实后端的标准模式——组件据此渲染骨架屏、错误提示或真实数据，
// 后端不可达时也能优雅降级，不会白屏。
//
// 韧性增强（2026-07-24）：后端未启动 / 临时不可达时，本 Hook 会按固定间隔
// 自动重试，直到取数成功，从而让面板从「模拟降级」无缝切回「实时数据」，
// 不必手动刷新页面。重试次数有上限，避免无限空转。

import { useEffect, useRef, useState } from 'react'

export interface AsyncState<T> {
  data: T | null
  loading: boolean
  error: string | null
  refetch: () => void
}

export interface UseApiOptions {
  /** 失败后是否自动重试直到成功（默认 true，用于后端未启动时优雅等待） */
  retry?: boolean
  /** 重试间隔（毫秒，默认 5000） */
  retryInterval?: number
  /** 最大重试次数（默认 120 ≈ 10 分钟，到顶后停止并保留降级态） */
  maxRetries?: number
}

export function useApi<T>(
  fn: () => Promise<T>,
  deps: unknown[] = [],
  opts: UseApiOptions = {},
): AsyncState<T> {
  const { retry = true, retryInterval = 5000, maxRetries = 120 } = opts
  const [state, setState] = useState<Omit<AsyncState<T>, 'refetch'>>({
    data: null,
    loading: true,
    error: null,
  })
  const [tick, setTick] = useState(0)
  const retryCount = useRef(0)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    let alive = true
    setState((s) => ({ ...s, loading: true, error: null }))
    fn()
      .then((d) => {
        if (!alive) return
        retryCount.current = 0
        setState({ data: d, loading: false, error: null })
      })
      .catch((e) => {
        if (!alive) return
        const msg = e instanceof Error ? e.message : String(e)
        setState({ data: null, loading: false, error: msg })
        // 后端未就绪：按间隔自动重试，直至成功或触达上限
        if (retry && retryCount.current < maxRetries) {
          retryCount.current += 1
          timer.current = setTimeout(() => setTick((t) => t + 1), retryInterval)
        }
      })
    return () => {
      alive = false
      if (timer.current) {
        clearTimeout(timer.current)
        timer.current = null
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick])

  return { ...state, refetch: () => setTick((t) => t + 1) }
}
