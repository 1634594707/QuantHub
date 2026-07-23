import type { PortfolioHolding } from '../api/types'
import type { Holding } from '../data/mock'
import { HOLDINGS } from '../data/mock'

const fmt = (n: number) => n.toLocaleString('en-US', { maximumFractionDigits: 2 })

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
        <table className="tbl">
          <thead>
            <tr>
              <th>标的</th>
              <th>最新价</th>
              <th>涨跌幅</th>
              <th>持仓</th>
              <th>浮动盈亏</th>
              <th>胜率</th>
            </tr>
          </thead>
          <tbody>
            {data.map((r) => {
              const up = r.chgPct >= 0
              const pnlUp = r.pnl >= 0
              return (
                <tr key={r.code}>
                  <td>
                    <div className="sym">
                      <div className="sym-badge">{r.name.slice(0, 1)}</div>
                      <div>
                        <div className="sym-name">{r.name}</div>
                        <div className="sym-code mono">{r.code}</div>
                      </div>
                    </div>
                  </td>
                  <td className="mono">{fmt(r.price)}</td>
                  <td className={`mono ${up ? 'up' : 'down'}`} style={{ fontWeight: 600 }}>
                    {up ? '+' : ''}
                    {r.chgPct.toFixed(2)}%
                  </td>
                  <td className="mono">{r.shares.toLocaleString('en-US')}</td>
                  <td className={`mono ${pnlUp ? 'up' : 'down'}`} style={{ fontWeight: 600 }}>
                    {pnlUp ? '+' : '-'}
                    {fmt(Math.abs(r.pnl))}
                  </td>
                  <td className="mono">
                    {r.winRate}%
                    <span className="winbar">
                      <i style={{ width: `${Math.min(100, Math.max(0, r.winRate))}%` }} />
                    </span>
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
