// 通用异步数据 Hook：每个取数点都具备 loading / error / data 三态。
// 这是前端接入真实后端的标准模式——组件据此渲染骨架屏、错误提示或真实数据，
// 后端不可达时也能优雅降级，不会白屏。

import { useEffect, useState } from 'react'

export interface AsyncState<T> {
  data: T | null
  loading: boolean
  error: string | null
  refetch: () => void
}

export function useApi<T>(fn: () => Promise<T>, deps: unknown[] = []): AsyncState<T> {
  const [state, setState] = useState<Omit<AsyncState<T>, 'refetch'>>({
    data: null,
    loading: true,
    error: null,
  })
  const [tick, setTick] = useState(0)

  useEffect(() => {
    let alive = true
    setState((s) => ({ ...s, loading: true, error: null }))
    fn()
      .then((d) => {
        if (alive) setState({ data: d, loading: false, error: null })
      })
      .catch((e) => {
        if (alive)
          setState({
            data: null,
            loading: false,
            error: e instanceof Error ? e.message : String(e),
          })
      })
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick])

  return { ...state, refetch: () => setTick((t) => t + 1) }
}
