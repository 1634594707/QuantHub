import type { HoldingInput, HoldingRow } from '../hooks/useEditableHoldings'

const fmt = (n: number) => n.toLocaleString('en-US', { maximumFractionDigits: 2 })
const fmtInt = (n: number) => n.toLocaleString('en-US', { maximumFractionDigits: 0 })

const MARKETS = [
  { value: 'a_shares', label: 'A股' },
  { value: 'us_stocks', label: '美股' },
  { value: 'crypto', label: '加密货币' },
]

function ReturnBar({ ret }: { ret: number }) {
  const pct = Math.min(98, Math.max(2, 50 + ret * 1.5))
  const up = ret >= 0
  return (
    <div className="winrate">
      <span className={`winrate-value ${up ? 'up' : 'down'}`}>
        {up ? '+' : ''}
        {ret.toFixed(1)}%
      </span>
      <div className="winrate-track">
        <div
          className="winrate-fill"
          style={{ width: `${pct}%`, background: up ? 'var(--up)' : 'var(--down)' }}
        />
      </div>
    </div>
  )
}

interface Props {
  rows: HoldingRow[]
  editing: boolean
  onAdd: () => void
  onUpdate: (id: string, patch: Partial<HoldingInput>) => void
  onRemove: (id: string) => void
  onToggleEdit: () => void
}

export default function HoldingsTable({ rows, editing, onAdd, onUpdate, onRemove, onToggleEdit }: Props) {
  return (
    <div className="card">
      <div className="card-head">
        <div className="card-title">
          持仓明细 <span className="sub">{rows.length} 只</span>
        </div>
        {editing ? (
          <div style={{ display: 'flex', gap: 'var(--sp-2)' }}>
            <button className="link-btn" onClick={onAdd}>
              + 添加
            </button>
            <button
              className="period-tab"
              style={{ background: 'var(--accent)', color: '#fff' }}
              onClick={onToggleEdit}
            >
              完成
            </button>
          </div>
        ) : (
          <button className="link-btn" onClick={onToggleEdit}>
            编辑
          </button>
        )}
      </div>

      {editing ? (
        <div className="edit-list">
          {rows.map((r) => (
            <div className="edit-row" key={r.id}>
              <input
                className="edit-input"
                placeholder="代码"
                value={r.code}
                onChange={(e) => onUpdate(r.id, { code: e.target.value })}
              />
              <input
                className="edit-input"
                placeholder="名称"
                value={r.name}
                onChange={(e) => onUpdate(r.id, { name: e.target.value })}
              />
              <select
                className="edit-input"
                value={r.market}
                onChange={(e) => onUpdate(r.id, { market: e.target.value })}
              >
                {MARKETS.map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label}
                  </option>
                ))}
              </select>
              <input
                className="edit-input num"
                type="number"
                placeholder="股数"
                value={r.shares}
                onChange={(e) => onUpdate(r.id, { shares: Number(e.target.value) || 0 })}
              />
              <input
                className="edit-input num"
                type="number"
                placeholder="成本"
                value={r.cost}
                onChange={(e) => onUpdate(r.id, { cost: Number(e.target.value) || 0 })}
              />
              <button className="icon-btn" title="删除持仓" onClick={() => onRemove(r.id)}>
                ✕
              </button>
            </div>
          ))}
          {rows.length === 0 && (
            <div className="muted" style={{ padding: 'var(--sp-3)' }}>
              暂无持仓，点击「+ 添加」新增
            </div>
          )}
        </div>
      ) : (
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
                <th className="col-win">收益率</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const up = r.chgPct >= 0
                const pnlUp = r.pnl >= 0
                return (
                  <tr key={r.id}>
                    <td className="col-name">
                      <div className="sym">
                        <div className="sym-badge">{r.name.slice(0, 1)}</div>
                        <div>
                          <div className="sym-name">{r.name}</div>
                          <div className="sym-code mono">{r.code}</div>
                        </div>
                      </div>
                    </td>
                    <td className="col-num mono">
                      {r.available ? fmt(r.price) : <span className="watch-unavail">无行情</span>}
                    </td>
                    <td className={`col-num mono chg ${up ? 'up' : 'down'}`}>
                      {up ? '+' : ''}
                      {r.chgPct.toFixed(2)}%
                    </td>
                    <td className="col-num mono">{fmtInt(r.shares)}</td>
                    <td className="col-num mono">{fmtInt(r.marketValue)}</td>
                    <td className={`col-num mono pnl ${pnlUp ? 'up' : 'down'}`}>
                      {pnlUp ? '+' : '-'}
                      {fmt(Math.abs(r.pnl))}
                    </td>
                    <td className="col-win">
                      <ReturnBar ret={(r.price - r.cost) / r.cost * 100} />
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
