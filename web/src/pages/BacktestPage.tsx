import { useState } from 'react'
import { api } from '../api/client'
import { useApi } from '../api/useApi'
import type { RunResp, SignalResp } from '../api/types'

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

export default function BacktestPage() {
  const strategies = useApi(() => api.strategies(), [])
  const [running, setRunning] = useState<string | null>(null)
  const [result, setResult] = useState<RunResp | null>(null)
  const [error, setError] = useState<string | null>(null)

  const list = strategies.data?.strategies ?? []

  async function run(name: string) {
    setRunning(name)
    setError(null)
    setResult(null)
    try {
      const r = await api.runStrategy(name)
      setResult(r)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setRunning(null)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-4)' }}>
      <div className="card">
        <div className="card-head">
          <div className="card-title">
            回测工作台
            <span className="sub">选择策略并运行回测</span>
          </div>
        </div>
        <div style={{ padding: 'var(--sp-3)' }}>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
              gap: 'var(--sp-3)',
            }}
          >
            {list.map((st) => (
              <div
                key={st.name}
                style={{
                  padding: 'var(--sp-3)',
                  borderRadius: 'var(--r-md)',
                  border: '1px solid var(--border)',
                  background: 'var(--bg-subtle)',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 'var(--sp-2)',
                }}
              >
                <div style={{ fontWeight: 700 }}>{st.name}</div>
                <p style={{ margin: 0, color: 'var(--text-2)', fontSize: 'var(--fs-13)' }}>
                  {st.description || '暂无描述'}
                </p>
                <button
                  className="period-tab"
                  style={{ alignSelf: 'flex-start', marginTop: 'auto' }}
                  onClick={() => run(st.name)}
                  disabled={running === st.name}
                >
                  {running === st.name ? '运行中…' : '运行回测'}
                </button>
              </div>
            ))}
          </div>
          {list.length === 0 && (
            <div className="muted" style={{ textAlign: 'center', padding: 'var(--sp-5)' }}>
              {strategies.loading ? '加载策略中…' : '暂无策略'}
            </div>
          )}
        </div>
      </div>

      {error && (
        <div
          className="card"
          style={{
            padding: 'var(--sp-3)',
            color: 'var(--down-ink)',
            borderColor: 'var(--down-ink)',
            background: 'rgba(234,57,67,0.06)',
          }}
        >
          {error}
        </div>
      )}

      {result && (
        <div className="card">
          <div className="card-head">
            <div className="card-title">
              回测结果
              <span className="sub">
                {result.name} · 信号数 {result.count}
              </span>
            </div>
            {!result.ok && <span className="delta down">失败</span>}
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
                </tr>
              </thead>
              <tbody>
                {result.signals.map((s, i) => (
                  <tr key={`${s.symbol}-${i}`}>
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
                  </tr>
                ))}
                {result.signals.length === 0 && (
                  <tr>
                    <td colSpan={5} className="muted" style={{ textAlign: 'center' }}>
                      无信号
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
