import KpiRow from '../components/KpiRow'
import KlineCard from '../components/KlineCard'
import DecisionPanel from '../components/DecisionPanel'
import MarketBreadth from '../components/MarketBreadth'
import Watchlist from '../components/Watchlist'
import HoldingsTable from '../components/HoldingsTable'
import { api } from '../api/client'
import { useApi } from '../api/useApi'
import { useState } from 'react'

export default function OverviewPage() {
  const portfolio = useApi(() => api.portfolio(), [])
  const breadth = useApi(() => api.marketBreadth(), [])
  const watchlist = useApi(() => api.watchlist(), [])
  const [symbol, setSymbol] = useState('600519')
  const [market, setMarket] = useState<'a_shares' | 'crypto' | 'us_stocks'>('a_shares')

  return (
    <>
      <KpiRow summary={portfolio.data?.summary} />
      <div className="grid-2">
        <div className="col-left">
          <KlineCard
            symbol={symbol}
            market={market}
            onSymbolChange={setSymbol}
            onMarketChange={setMarket}
          />
          <HoldingsTable rows={portfolio.data?.holdings} />
          <Watchlist items={watchlist.data?.items} />
          <MarketBreadth data={breadth.data} />
        </div>
        <div className="col-right">
          <DecisionPanel symbol={symbol} />
        </div>
      </div>
    </>
  )
}
