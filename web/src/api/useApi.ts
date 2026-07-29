// 通用异步数据 Hook：每个取数点都具备 loading / error / data 三态。
// 组件据此渲染骨架屏、错误提示或真实数据，后端不可达时优雅降级，不白屏。
//
// 韧性策略（2026-07-25 修订）：
//   1. 失败时保留上一次成功加载的 data（prev.data），仅置 error + loading:false，
//      UI 据此显示「重连中」角标而非清空已渲染内容，避免数据闪烁。
//   2. 区分错误类型——NetworkError（网关不可达）与 5xx 可重试；4xx 为确定性业务错误
//      （策略不存在/参数非法），不重试，避免 10 分钟空转。
//   3. refetch() 重置重试计数，用户可手动触发立即重试。

import { useEffect, useRef, useState } from 'react'
import { HttpError, NetworkError } from './client'

export interface AsyncState<T> {
  data: T | null
  loading: boolean
  error: string | null
  errorKind: 'network' | 'http' | 'unknown' | null
  errorStatus: number | null
  /** 是否处于「断线重连中」——有旧 data 但本次请求失败待重试。 */
  reconnecting: boolean
  /** 最近一次成功完成请求的浏览器时间戳（毫秒）。 */
  updatedAt: number | null
  refetch: () => void
  /** 手动更新缓存数据（乐观更新用）；接受新值或 updater 函数 */
  setData: (updater: T | ((prev: T) => T)) => void
}

export interface UseApiOptions<T> {
  /** 是否执行请求；用于必须由用户显式触发的分析任务。 */
  enabled?: boolean
  /** 失败后是否自动重试（默认 true，用于后端未启动时优雅等待） */
  retry?: boolean
  /** 重试间隔（毫秒，默认 5000） */
  retryInterval?: number
  /** 最大重试次数（默认 120 ≈ 10 分钟，到顶后停止并保留降级态） */
  maxRetries?: number
  /** 成功后的刷新周期；未设置时只在依赖变化或手动刷新时请求。 */
  pollInterval?: number
  /** 返回 false 时停止成功轮询，适合任务到达终态后停止请求。 */
  pollWhile?: (data: T) => boolean
  /** 页面不可见时暂停成功轮询，重新可见后立即刷新。 */
  pauseWhenHidden?: boolean
  /** 业务上下文标识；标识变化时清空旧数据，避免跨标的或跨记录显示上一上下文。 */
  resetKey?: unknown
}

/** 判断错误是否值得重试：网络错误与 5xx 可重试，4xx 不可重试。 */
function isRetryable(e: unknown): boolean {
  if (e instanceof NetworkError) return true
  if (e instanceof HttpError) return e.status >= 500
  // 未知错误默认可重试（保守策略，宁可多试）
  return true
}

function errorMetadata(e: unknown): Pick<AsyncState<unknown>, 'errorKind' | 'errorStatus'> {
  if (e instanceof NetworkError) return { errorKind: 'network', errorStatus: null }
  if (e instanceof HttpError) return { errorKind: 'http', errorStatus: e.status }
  return { errorKind: 'unknown', errorStatus: null }
}

export function useApi<T>(
  fn: () => Promise<T>,
  deps: unknown[] = [],
  opts: UseApiOptions<T> = {},
): AsyncState<T> {
  const {
    enabled = true,
    retry = true,
    retryInterval = 5000,
    maxRetries = 120,
    pollInterval,
    pollWhile,
    pauseWhenHidden = true,
    resetKey,
  } = opts
  const [state, setState] = useState<Omit<AsyncState<T>, 'refetch' | 'setData'>>({
    data: null,
    loading: true,
    error: null,
    errorKind: null,
    errorStatus: null,
    reconnecting: false,
    updatedAt: null,
  })
  const [tick, setTick] = useState(0)
  const retryCount = useRef(0)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const previousResetKey = useRef(resetKey)

  useEffect(() => {
    if (!pollInterval || !pauseWhenHidden || typeof document === 'undefined') return
    function onVisibilityChange() {
      if (document.visibilityState === 'visible') setTick((value) => value + 1)
    }
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => document.removeEventListener('visibilitychange', onVisibilityChange)
  }, [pauseWhenHidden, pollInterval])

  useEffect(() => {
    let alive = true
    const contextChanged = !Object.is(previousResetKey.current, resetKey)
    previousResetKey.current = resetKey
    if (!enabled) {
      setState((s) => ({
        ...s,
        data: contextChanged ? null : s.data,
        loading: false,
        error: null,
        errorKind: null,
        errorStatus: null,
        reconnecting: false,
      }))
      return () => {
        alive = false
      }
    }
    // 同一上下文重新请求时保留旧数据；业务上下文变化时先清空，避免显示错位记录。
    setState((s) => ({
      data: contextChanged ? null : s.data,
      loading: contextChanged || s.data === null,
      error: null,
      errorKind: null,
      errorStatus: null,
      reconnecting: !contextChanged && s.data !== null,
      updatedAt: contextChanged ? null : s.updatedAt,
    }))
    fn()
      .then((d) => {
        if (!alive) return
        retryCount.current = 0
        setState({ data: d, loading: false, error: null, errorKind: null, errorStatus: null, reconnecting: false, updatedAt: Date.now() })
        const pageVisible = typeof document === 'undefined' || document.visibilityState === 'visible'
        if (pollInterval && (pollWhile?.(d) ?? true) && (!pauseWhenHidden || pageVisible)) {
          timer.current = setTimeout(() => setTick((value) => value + 1), pollInterval)
        }
      })
      .catch((e) => {
        if (!alive) return
        const msg = e instanceof Error ? e.message : String(e)
        const metadata = errorMetadata(e)
        // 关键：保留 prev.data，UI 不清空
        setState((s) => ({
          data: s.data,
          loading: false,
          error: msg,
          ...metadata,
          reconnecting: retry && isRetryable(e) && retryCount.current < maxRetries,
          updatedAt: s.updatedAt,
        }))
        // 仅对可重试错误调度重试
        if (retry && isRetryable(e) && retryCount.current < maxRetries) {
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
  }, [...deps, enabled, tick, resetKey, pollInterval, pauseWhenHidden, pollWhile])

  return {
    ...state,
    refetch: () => {
      retryCount.current = 0
      setTick((t) => t + 1)
    },
    setData: (updater) => {
      setState((s) => {
        if (s.data === null) return s
        const next = typeof updater === 'function' ? (updater as (p: T) => T)(s.data) : updater
        return { ...s, data: next }
      })
    },
  }
}
