/** 由标的代码推断所属市场（用于 mock 兜底种子，后端真实数据自带 market）。 */
export function inferMarket(sym: string): string {
  const s = (sym || '').trim().toUpperCase()
  if (/^\d{6}$/.test(s)) return 'a_shares'
  if (s.includes('-') || s.includes('/')) return 'crypto'
  return 'us_stocks'
}
