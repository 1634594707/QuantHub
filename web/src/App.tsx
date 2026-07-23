import { useState } from 'react'
import Sidebar from './components/Sidebar'
import Topbar from './components/Topbar'
import KpiRow from './components/KpiRow'
import KlineCard from './components/KlineCard'
import HoldingsTable from './components/HoldingsTable'
import DecisionPanel from './components/DecisionPanel'
import MarketBreadth from './components/MarketBreadth'
import Watchlist from './components/Watchlist'
import { api } from './api/client'
import { useApi } from './api/useApi'

export default function App() {
  const [collapsed, setCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)

  // ── 概览屏统一取数：健康/策略/信号/组合/市场（K线在 KlineCard 内自取）──
  const health = useApi(() => api.health(), [])
  const strategies = useApi(() => api.strategies(), [])
  const signals = useApi(() => api.signals(50), [])
  const portfolio = useApi(() => api.portfolio(), [])
  const breadth = useApi(() => api.marketBreadth(), [])
  const watchlist = useApi(() => api.watchlist(), [])

  const apiOnline = !health.error && !strategies.error
  const strategyCount = strategies.data?.count ?? 0
  const signalCount = signals.data?.count ?? 0

  return (
    <div className={`app-shell ${collapsed ? 'collapsed' : ''} ${mobileOpen ? 'mobile-open' : ''}`}>
      <div className="scrim" onClick={() => setMobileOpen(false)} />
      <Sidebar
        collapsed={collapsed}
        mobileOpen={mobileOpen}
        onToggleCollapse={() => setCollapsed((c) => !c)}
        onNavigate={() => setMobileOpen(false)}
        strategyCount={strategyCount}
      />
      <div className="main">
        <Topbar
          onMenu={() => setMobileOpen((o) => !o)}
          health={health.data}
          apiOnline={apiOnline}
          signalCount={signalCount}
        />
        <main className="content">
          <KpiRow summary={portfolio.data?.summary} />
          <div className="grid-2">
            <KlineCard symbol="600519" market="a_shares" />
            <div className="col-right">
              <DecisionPanel symbol="600519" />
              <MarketBreadth data={breadth.data} />
              <Watchlist items={watchlist.data?.items} />
            </div>
          </div>
          <HoldingsTable rows={portfolio.data?.holdings} />
        </main>
      </div>
    </div>
  )
}
