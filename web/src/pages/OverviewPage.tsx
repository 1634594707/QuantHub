import KpiRow from '../components/KpiRow'
import KlineCard from '../components/KlineCard'
import DecisionPanel from '../components/DecisionPanel'
import MarketBreadth from '../components/MarketBreadth'
import Watchlist from '../components/Watchlist'
import HoldingsTable from '../components/HoldingsTable'
import { api } from '../api/client'
import { useApi } from '../api/useApi'

export default function OverviewPage() {
  const portfolio = useApi(() => api.portfolio(), [])
  const breadth = useApi(() => api.marketBreadth(), [])
  const watchlist = useApi(() => api.watchlist(), [])

  return (
    <>
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
    </>
  )
}
