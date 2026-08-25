import type { LedgerSummary, PortfolioSummary, SimulationAccount } from '../api/types'
import { KpiCard } from './ui/KpiCard/KpiCard'

export type AccountScope = 'research' | 'simulation' | 'ledger'

interface Props {
  scope: AccountScope
  research: PortfolioSummary
  simulation: SimulationAccount | null
  ledger: LedgerSummary | null
}

function money(value: number | null | undefined): string {
  return value == null ? '—' : value.toLocaleString('zh-CN', { maximumFractionDigits: 0 })
}

export default function KpiRow({ scope, research, simulation, ledger }: Props) {
  const items = scope === 'simulation' ? [
    { label: '模拟账户权益', value: money(simulation?.equity ?? 0) },
    { label: '模拟浮动盈亏', value: money(simulation?.unrealized_pnl ?? 0) },
    { label: '模拟已实现盈亏', value: money(simulation?.realized_pnl ?? 0) },
    { label: '模拟可用现金', value: money(simulation?.cash ?? 0) },
  ] : scope === 'ledger' ? [
    { label: '账本净值', value: money(ledger?.nav ?? 0) },
    { label: '账本浮动盈亏', value: money(ledger?.unrealized_pnl ?? 0) },
    { label: '账本已实现盈亏', value: money(ledger?.realized_pnl ?? 0) },
    { label: '账本现金', value: money(ledger?.cash ?? 0) },
  ] : [
    { label: '研究组合总值', value: money(research.nav) },
    { label: '研究组合累计盈亏', value: money(research.dailyPnl) },
    { label: '持仓涨跌评分', value: research.chgBasedScore == null ? '—' : research.chgBasedScore.toFixed(1), unit: undefined },
    { label: '研究可用资金', value: money(research.cash) },
  ]

  return (
    <div className="kpi-row">
      {items.map((item) => (
        <KpiCard key={item.label} label={item.label} value={item.value} unit={item.unit ?? (item.label === '持仓涨跌评分' ? undefined : '¥')} />
      ))}
    </div>
  )
}
