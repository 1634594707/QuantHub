import { api } from '../api/client'
import { useApi } from '../api/useApi'
import type { StrategyInfo } from '../api/types'

function marketBadge(m: StrategyInfo['market']) {
  if (m === 'a_shares') return 'A股'
  if (m === 'crypto') return '加密货币'
  if (m === 'us_stocks') return '美股'
  return m
}

export default function StrategiesPage() {
  const strategies = useApi(() => api.strategies(), [])

  const list = strategies.data?.strategies ?? []
  const isReal = strategies.data != null

  return (
    <div className="card">
      <div className="card-head">
        <div className="card-title">
          策略模块
          <span className="sub">{isReal ? '实时' : '模拟'} · 共 {list.length} 个</span>
        </div>
        <button
          className="link-btn"
          onClick={() => strategies.refetch()}
          disabled={strategies.loading}
        >
          {strategies.loading ? '刷新中…' : '刷新'}
        </button>
      </div>
      <div style={{ padding: 'var(--sp-3)' }}>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
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
              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)' }}>
                <span style={{ fontWeight: 700, fontSize: 'var(--fs-15)' }}>{st.name}</span>
                <span
                  style={{
                    fontSize: 'var(--fs-12)',
                    padding: '2px 8px',
                    borderRadius: 'var(--r-pill)',
                    background: 'var(--accent-weak)',
                    color: 'var(--accent-strong)',
                  }}
                >
                  {marketBadge(st.market)}
                </span>
                {st.live_capable && (
                  <span
                    style={{
                      fontSize: 'var(--fs-12)',
                      padding: '2px 8px',
                      borderRadius: 'var(--r-pill)',
                      background: 'rgba(22,199,132,0.14)',
                      color: 'var(--up-ink)',
                    }}
                  >
                    可实盘
                  </span>
                )}
              </div>
              <p style={{ margin: 0, color: 'var(--text-2)', fontSize: 'var(--fs-13)', lineHeight: 1.5 }}>
                {st.description || '暂无描述'}
              </p>
            </div>
          ))}
        </div>
        {list.length === 0 && (
          <div className="muted" style={{ textAlign: 'center', padding: 'var(--sp-5)' }}>
            {strategies.loading ? '加载中…' : '暂无策略'}
          </div>
        )}
      </div>
    </div>
  )
}
