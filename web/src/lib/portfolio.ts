import type { PortfolioSummary } from '../api/types'
import type { HoldingInput, HoldingRow } from '../hooks/useEditableHoldings'
import type { WatchInput, WatchRow } from '../hooks/useEditableWatchlist'
import type { QuoteResp } from '../api/types'

type Quote = Pick<QuoteResp, 'price' | 'chgPct' | 'available'>

const clamp = (n: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, n))

/** 由持仓输入 + 实时报价派生展示行（价格/市值/盈亏/涨跌派生分）。
 * 行情不可用时保持所有估值字段为空，避免用成本价伪造 NAV/PnL。
 * chgBasedScore 是由涨跌幅派生的情绪分（非真实胜率），真实胜率见
 * DecisionPanel 的 estimated_win_rate。 */
export function deriveHolding(h: HoldingInput, q?: Quote): HoldingRow {
  const price = q?.available === true && q.price != null ? q.price : null
  if (price == null) {
    return {
      ...h,
      price: null,
      chgPct: null,
      available: false,
      pnl: null,
      marketValue: null,
      chgBasedScore: null,
    }
  }
  const chgPct = q?.chgPct ?? null
  const marketValue = price * h.shares
  const pnl = (price - h.cost) * h.shares
  const ret = h.cost ? (price - h.cost) / h.cost : 0
  const chgBasedScore = clamp(50 + ret * 100 * 1.5, 1, 99)
  return { ...h, price, chgPct, available: true, pnl, marketValue, chgBasedScore }
}

/** 由关注输入 + 实时报价派生展示行；无源（如加密货币）诚实标 unavailable。 */
export function deriveWatch(w: WatchInput, q?: Quote): WatchRow {
  if (!q || q.available === false || q.price == null) {
    return { ...w, price: null, chgPct: null, available: false }
  }
  return { ...w, price: q.price, chgPct: q.chgPct ?? 0, available: true }
}

/** 由持仓派生账户汇总，供 KPI 联动（编辑持仓后 KPI 同步变化）。
 * cash 透传后端 /portfolio.summary.cash，避免与 configs/portfolio.yaml 漂移。 */
export function computeSummary(rows: HoldingRow[], cash: number = 0): PortfolioSummary {
  const totalCost = rows.reduce((s, r) => s + r.cost * r.shares, 0)
  const pricedRows = rows.filter((row) => row.available && row.marketValue != null && row.pnl != null)
  const valuationComplete = pricedRows.length === rows.length
  const totalValue = pricedRows.reduce((s, r) => s + (r.marketValue ?? 0), 0)
  const pnl = totalValue - totalCost
  const pnlPct = totalCost ? (pnl / totalCost) * 100 : 0
  const nav = totalValue + cash
  const chgBasedScore = rows.length && valuationComplete
    ? pricedRows.reduce((s, r) => s + (r.chgBasedScore ?? 0), 0) / rows.length
    : null
  return {
    nav: valuationComplete ? Math.round(nav * 100) / 100 : null,
    dailyPnl: valuationComplete ? Math.round(pnl * 100) / 100 : null,
    dailyPnlPct: valuationComplete ? Math.round(pnlPct * 100) / 100 : null,
    cash,
    chgBasedScore: chgBasedScore == null ? null : Math.round(chgBasedScore * 10) / 10,
    totalPositions: rows.length,
    pricedPositions: pricedRows.length,
    unpricedPositions: rows.length - pricedRows.length,
    costBasis: Math.round(totalCost * 100) / 100,
    valuationStatus: rows.length === 0
      ? 'available'
      : valuationComplete
        ? 'available'
        : pricedRows.length > 0
          ? 'partial'
          : 'unavailable',
  }
}
