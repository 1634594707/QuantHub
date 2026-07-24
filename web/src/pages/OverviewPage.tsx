import { useMemo, useState } from 'react'
import KpiRow from '../components/KpiRow'
import KlineCard from '../components/KlineCard'
import DecisionPanel from '../components/DecisionPanel'
import MarketBreadth from '../components/MarketBreadth'
import Watchlist from '../components/Watchlist'
import HoldingsTable from '../components/HoldingsTable'
import { api } from '../api/client'
import { useApi } from '../api/useApi'
import { useEditableHoldings } from '../hooks/useEditableHoldings'
import { useEditableWatchlist } from '../hooks/useEditableWatchlist'
import { useMarketQuotes, quoteKey } from '../hooks/useMarketQuotes'
import { computeSummary, deriveHolding, deriveWatch } from '../lib/portfolio'

export default function OverviewPage() {
  const breadth = useApi(() => api.marketBreadth(), [])
  const holdings = useEditableHoldings()
  const watchlist = useEditableWatchlist()
  const [editH, setEditH] = useState(false)
  const [editW, setEditW] = useState(false)
  const [symbol, setSymbol] = useState('600519')
  const [market, setMarket] = useState<'a_shares' | 'crypto' | 'us_stocks'>('a_shares')

  // 仅在查看态拉取实时报价，编辑态不触发（避免逐字符输入引发请求风暴）
  const holdingQuotes = useMarketQuotes(
    !editH ? holdings.list.map((h) => ({ market: h.market, symbol: h.code })) : [],
  )
  const watchQuotes = useMarketQuotes(
    !editW ? watchlist.list.map((w) => ({ market: w.market, symbol: w.sym })) : [],
  )

  const holdingRows = useMemo(
    () => holdings.list.map((h) => deriveHolding(h, holdingQuotes[quoteKey(h.market, h.code)])),
    [holdings.list, holdingQuotes],
  )
  const watchRows = useMemo(
    () => watchlist.list.map((w) => deriveWatch(w, watchQuotes[quoteKey(w.market, w.sym)])),
    [watchlist.list, watchQuotes],
  )
  const summary = useMemo(() => computeSummary(holdingRows), [holdingRows])

  return (
    <>
      <KpiRow summary={summary} />
      <div className="grid-2">
        <div className="col-left">
          <KlineCard
            symbol={symbol}
            market={market}
            onSymbolChange={setSymbol}
            onMarketChange={setMarket}
          />
          <HoldingsTable
            rows={holdingRows}
            editing={editH}
            onAdd={() => holdings.add('a_shares')}
            onUpdate={holdings.update}
            onRemove={holdings.remove}
            onToggleEdit={() => setEditH((v) => !v)}
          />
          <Watchlist
            rows={watchRows}
            editing={editW}
            onAdd={() => watchlist.add('a_shares')}
            onUpdate={watchlist.update}
            onRemove={watchlist.remove}
            onToggleEdit={() => setEditW((v) => !v)}
          />
          <MarketBreadth data={breadth.data} />
        </div>
        <div className="col-right">
          <DecisionPanel symbol={symbol} />
        </div>
      </div>
    </>
  )
}
