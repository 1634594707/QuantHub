import { useState } from 'react'
import DecisionPanel from '../components/DecisionPanel'

const TIMEFRAMES = ['5m', '15m', '1h', '1d']

export default function PaAnalysisPage() {
  const [symbol, setSymbol] = useState('600519')
  const [timeframe, setTimeframe] = useState('1h')
  const [active, setActive] = useState({ symbol: '600519', timeframe: '1h' })

  function run() {
    setActive({ symbol: symbol.trim(), timeframe })
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-4)' }}>
      <div className="card">
        <div className="card-head">
          <div className="card-title">
            PA 分析工作台
            <span className="sub">价格行为两阶段分析</span>
          </div>
        </div>
        <div
          style={{
            padding: 'var(--sp-3)',
            display: 'flex',
            gap: 'var(--sp-3)',
            flexWrap: 'wrap',
            alignItems: 'center',
          }}
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            <label style={{ fontSize: 'var(--fs-12)', color: 'var(--text-3)' }}>标的代码</label>
            <input
              type="text"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && run()}
              style={{
                width: 140,
                padding: '8px 12px',
                borderRadius: 'var(--r-md)',
                border: '1px solid var(--border)',
                background: 'var(--bg-elevated)',
                color: 'var(--text-1)',
                fontSize: 'var(--fs-14)',
              }}
              placeholder="如 600519"
            />
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            <label style={{ fontSize: 'var(--fs-12)', color: 'var(--text-3)' }}>周期</label>
            <div className="period-tabs">
              {TIMEFRAMES.map((tf) => (
                <button
                  key={tf}
                  className={`period-tab ${timeframe === tf ? 'active' : ''}`}
                  onClick={() => setTimeframe(tf)}
                >
                  {tf}
                </button>
              ))}
            </div>
          </div>

          <button
            className="period-tab"
            style={{ marginTop: 'auto', background: 'var(--accent)', color: '#fff' }}
            onClick={run}
          >
            运行分析
          </button>
        </div>
      </div>

      <DecisionPanel symbol={active.symbol} timeframe={active.timeframe} />
    </div>
  )
}
