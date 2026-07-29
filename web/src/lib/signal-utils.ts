// 信号方向单一来源（single source of truth）。
// 此前 dirBucket / dirLabel / directionColor 在 SignalViz、SignalsPage、
// StrategyDetailPage、StrategyShared 中各自重复实现，易漂移。
// 现统一收敛到这里，任何方向语义变更只需改一处。

export type DirBucket = 'buy' | 'sell' | 'hold'

/** 把任意方向字符串归一到 buy / sell / hold 之一。 */
export function dirBucket(d: string): DirBucket {
  const s = String(d).toLowerCase()
  if (s === 'buy' || s === 'bullish' || s === '做多') return 'buy'
  if (s === 'sell' || s === 'bearish' || s === '做空') return 'sell'
  return 'hold'
}

/** 方向中文标签（做多 / 做空 / 观望）。 */
export function dirLabel(d: string): string {
  const b = dirBucket(d)
  return b === 'buy' ? '做多' : b === 'sell' ? '做空' : '观望'
}

/** 方向语义色：恒定为绿涨 / 红跌 / 灰观望，绝不随板块签名改变，保证可读性。 */
export function directionColor(d: string): string {
  const b = dirBucket(d)
  if (b === 'buy') return 'var(--up-ink)'
  if (b === 'sell') return 'var(--down-ink)'
  return 'var(--text-2)'
}

/** 方向匹配：用于「全部 / 做多 / 做空 / 观望」筛选。 */
export function matchDir(direction: string, dir: 'all' | DirBucket): boolean {
  if (dir === 'all') return true
  return dirBucket(direction) === dir
}
