import type { LedgerSummary, PortfolioSummary, SimulationAccount } from '../api/types'
import { KpiCard } from './ui/KpiCard/KpiCard'
import { useLanguage } from '../i18n'

export type AccountScope = 'research' | 'simulation' | 'ledger'

interface Props {
  scope: AccountScope
  research: PortfolioSummary
  simulation: SimulationAccount | null
  ledger: LedgerSummary | null
}

function money(value: number | null | undefined, locale: string): string {
  return value == null ? '—' : value.toLocaleString(locale, { maximumFractionDigits: 0 })
}

export default function KpiRow({ scope, research, simulation, ledger }: Props) {
  const { locale, t } = useLanguage()
  const items = scope === 'simulation' ? [
    { label: t('模拟账户权益'), value: money(simulation?.equity ?? 0, locale) },
    { label: t('模拟浮动盈亏'), value: money(simulation?.unrealized_pnl ?? 0, locale) },
    { label: t('模拟已实现盈亏'), value: money(simulation?.realized_pnl ?? 0, locale) },
    { label: t('模拟可用现金'), value: money(simulation?.cash ?? 0, locale) },
  ] : scope === 'ledger' ? [
    { label: t('账本净值'), value: money(ledger?.nav ?? 0, locale) },
    { label: t('账本浮动盈亏'), value: money(ledger?.unrealized_pnl ?? 0, locale) },
    { label: t('账本已实现盈亏'), value: money(ledger?.realized_pnl ?? 0, locale) },
    { label: t('账本现金'), value: money(ledger?.cash ?? 0, locale) },
  ] : [
    { label: t('研究组合总值'), value: money(research.nav, locale) },
    { label: t('研究组合累计盈亏'), value: money(research.dailyPnl, locale) },
    { label: t('持仓涨跌评分'), value: research.chgBasedScore == null ? '—' : research.chgBasedScore.toFixed(1), unit: undefined },
    { label: t('研究可用资金'), value: money(research.cash, locale) },
  ]

  return (
    <div className="kpi-row">
      {items.map((item) => (
        <KpiCard key={item.label} label={item.label} value={item.value} unit={item.unit ?? (item.label === t('持仓涨跌评分') ? undefined : '¥')} />
      ))}
    </div>
  )
}
