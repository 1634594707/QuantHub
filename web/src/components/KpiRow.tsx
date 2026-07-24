import type { Kpi } from '../data/mock'
import { KPIS } from '../data/mock'
import type { PortfolioSummary } from '../api/types'
import KpiCard from './KpiCard'

function genSpark(seed: number, n = 12, up = true): number[] {
  let v = 20
  const out: number[] = []
  for (let i = 0; i < n; i++) {
    const drift = (Math.sin(seed + i * 0.7) + (up ? 0.15 : -0.15)) * 4
    v = Math.max(4, Math.min(36, v + drift))
    out.push(v)
  }
  return out
}

function summaryToKpis(s?: PortfolioSummary | null): Kpi[] {
  if (!s) return KPIS
  return [
    {
      label: '账户净值',
      value: s.nav.toLocaleString('en-US', { maximumFractionDigits: 0 }),
      unit: '¥',
      deltaAbs: (s.dailyPnl >= 0 ? '+' : '') + s.dailyPnl.toLocaleString('en-US', { maximumFractionDigits: 0 }),
      deltaPct: s.dailyPnlPct,
      spark: genSpark(1, 12, s.dailyPnlPct >= 0),
    },
    {
      label: '浮动盈亏',
      value: (s.dailyPnl >= 0 ? '+' : '-') + Math.abs(s.dailyPnl).toLocaleString('en-US', { maximumFractionDigits: 0 }),
      unit: '¥',
      deltaAbs: (s.dailyPnlPct >= 0 ? '+' : '') + s.dailyPnlPct.toFixed(2) + '%',
      deltaPct: s.dailyPnlPct,
      spark: genSpark(2, 12, s.dailyPnlPct >= 0),
    },
    {
      label: '持仓胜率',
      value: s.winRate.toFixed(1),
      unit: '%',
      deltaAbs: '+2.3pt',
      deltaPct: s.winRate - 50,
      spark: genSpark(3, 12, s.winRate >= 50),
    },
    {
      label: '可用资金',
      value: s.cash.toLocaleString('en-US', { maximumFractionDigits: 0 }),
      unit: '¥',
      deltaAbs: '-9,200',
      deltaPct: -2.11,
      spark: genSpark(4, 12, false),
    },
  ]
}

export default function KpiRow({ summary }: { summary?: PortfolioSummary | null }) {
  const items = summaryToKpis(summary)
  return (
    <div className="kpi-row">
      {items.map((k) => (
        <KpiCard key={k.label} item={k} />
      ))}
    </div>
  )
}
