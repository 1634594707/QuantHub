import { api } from '../api/client'
import { useApi } from '../api/useApi'
import type { SignalResp } from '../api/types'

function fmtTs(ts: string | null) {
  if (!ts) return '-'
  const d = new Date(ts)
  return Number.isNaN(d.getTime()) ? ts : d.toLocaleString('zh-CN')
}

function dirClass(d: string) {
  const s = d.toLowerCase()
  if (s === 'buy') return 'long'
  if (s === 'sell') return 'short'
  return 'hold'
}

function dirLabel(s: SignalResp['direction']) {
  const d = s.toLowerCase()
  if (d === 'buy') return '买入'
  if (d === 'sell') return '卖出'
  return '观望'
}

export default function SignalsPage() {
  const signals = useApi(() => api.signals(100), [])

  const rows = signals.data?.signals ?? []
  const isReal = signals.data != null

  return (
    <div className="card">
      <div className="card-head">
        <div className="card-title">
          信号列表
          <span className="sub">{isReal ? '实时' : '模拟'} · 共 {rows.length} 条</span>
        </div>
        <button
          className="link-btn"
          onClick={() => signals.refetch()}
          disabled={signals.loading}
        >
          {signals.loading ? '刷新中…' : '刷新'}
        </button>
      </div>
      <div className="table-wrap">
        <table className="tbl">
          <thead>
            <tr>
              <th>标的</th>
              <th>方向</th>
              <th>得分</th>
              <th>置信度</th>
              <th>周期</th>
              <th>来源</th>
              <th>标签</th>
              <th>时间</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((s, i) => (
              <tr key={`${s.symbol}-${s.ts ?? i}`}>
                <td>
                  <div className="sym">
                    <div className="sym-badge">{s.symbol.slice(0, 2)}</div>
                    <div>
                      <div className="sym-name">{s.symbol}</div>
                      <div className="sym-code">{s.market}</div>
                    </div>
                  </div>
                </td>
                <td>
                  <span className={`dir-pill ${dirClass(s.direction)}`}>
                    {dirLabel(s.direction)}
                  </span>
                </td>
                <td className="mono">{s.score.toFixed(2)}</td>
                <td className="mono">{(s.confidence * 100).toFixed(1)}%</td>
                <td>{s.timeframe}</td>
                <td>{s.source}</td>
                <td>
                  {s.tags.length > 0 ? (
                    s.tags.join(' · ')
                  ) : (
                    <span className="muted">-</span>
                  )}
                </td>
                <td className="muted">{fmtTs(s.ts)}</td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={8} className="muted" style={{ textAlign: 'center', padding: 'var(--sp-5)' }}>
                  {signals.loading ? '加载中…' : '暂无信号'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
