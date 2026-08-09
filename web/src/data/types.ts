// QuantHub 前端展示层数据形状定义。
//
// 约束（M3 无假数据）：本文件**只允许**声明 type / interface，
// 不得导出任何常量数据、示例数据或随机数生成函数。
// 任何需要展示的数值必须来自后端契约响应；无数据时渲染空态。
//
// 约束（M2-02 无死类型）：只保留仍被生产组件引用的形状。
// 已随孤立组件一并移除：Kpi、Holding、Breadth、Watch、Sector。

export interface Candle {
  t: string
  o: number
  h: number
  l: number
  c: number
  v: number
}

export type Direction = 'long' | 'short' | 'hold'

export interface Decision {
  direction: Direction
  trend: string
  cycle: string
  phase: string
  confidence: number
  dualConfidence: { stage1: number; stage2: number }
  nextBar: { predictable: boolean; top3: { label: string; prob: number }[]; remainder?: number }
  nextCycle: { predictable: boolean; top3: { label: string; prob: number }[]; remainder?: number }
  stop: number
  target: number
  riskReward: number
  winRate: number
  reason: string
  gateTrace: { gate: string; result: string }[]
}
