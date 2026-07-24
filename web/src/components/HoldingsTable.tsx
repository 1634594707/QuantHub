import type { PortfolioHolding } from '../api/types'
import type { Holding } from '../data/mock'
import { HOLDINGS } from '../data/mock'

const fmt = (n: number) => n.toLocaleString('en-US', { maximumFractionDigits: 2 })
const fmtInt = (n: number) => n.toLocaleString('en-US', { maximumFractionDigits: 0 })

function WinRateBar({ value }: { value: number }) {
  const pct = Math.min(100, Math.max(0, value))
  return (
    <div className="winrate">
      <span className="winrate-value">{value}%</span>
      <div className="winrate-track">
        <div className="winrate-fill" style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

export default function HoldingsTable({ rows }: { rows?: PortfolioHolding[] | Holding[] }) {
  const data = rows && rows.length > 0 ? rows : HOLDINGS
  return (
    <div className="card">
      <div className="card-head">
        <div className="card-title">
          持仓明细 <span className="sub">{data.length} 只</span>
        </div>
        <button className="link-btn">全部持仓 →</button>
      </div>
      <div className="table-wrap">
        <table className="tbl holdings-tbl">
          <thead>
            <tr>
              <th className="col-name">标的</th>
              <th className="col-num">最新价</th>
              <th className="col-num">涨跌幅</th>
              <th className="col-num">持仓</th>
              <th className="col-num">市值</th>
              <th className="col-num">浮动盈亏</th>
              <th className="col-win">胜率</th>
            </tr>
          </thead>
          <tbody>
            {data.map((r) => {
              const up = r.chgPct >= 0
              const pnlUp = r.pnl >= 0
              const mkt = r.price * r.shares
              return (
                <tr key={r.code}>
                  <td className="col-name">
                    <div className="sym">
                      <div className="sym-badge">{r.name.slice(0, 1)}</div>
                      <div>
                        <div className="sym-name">{r.name}</div>
                        <div className="sym-code mono">{r.code}</div>
                      </div>
                    </div>
                  </td>
                  <td className="col-num mono">{fmt(r.price)}</td>
                  <td className={`col-num mono chg ${up ? 'up' : 'down'}`}>
                    {up ? '+' : ''}
                    {r.chgPct.toFixed(2)}%
                  </td>
                  <td className="col-num mono">{fmtInt(r.shares)}</td>
                  <td className="col-num mono">{fmtInt(mkt)}</td>
                  <td className={`col-num mono pnl ${pnlUp ? 'up' : 'down'}`}>
                    {pnlUp ? '+' : '-'}
                    {fmt(Math.abs(r.pnl))}
                  </td>
                  <td className="col-win">
                    <WinRateBar value={r.winRate} />
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
