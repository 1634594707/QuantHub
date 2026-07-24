// 信号总线读取 hook —— 策略工作台「信号」Tab 与信号中心共用的唯一数据源。
// 信号总线是后端进程内单例（strategies produce() 运行时会写入），
// 所以「工作台运行策略」与「信号中心」天然共享同一批信号，彻底消除双源割裂。

import { useApi } from '../api/useApi'
import { api } from '../api/client'
import type { SignalResp, SignalsResp } from '../api/types'

/**
 * @param source 可选：按策略名（即信号的 source 字段）过滤，
 *               用于工作台只展示该策略产生的信号。
 */
export function useSignals(source?: string) {
  const state = useApi<SignalsResp>(() => api.signals(200, source), [source])
  const signals: SignalResp[] = state.data?.signals ?? []
  return {
    signals,
    loading: state.loading,
    error: state.error,
    refetch: state.refetch,
    /** 已成功取数但为空（区别于加载中）。 */
    isEmpty: !state.loading && signals.length === 0,
  }
}
