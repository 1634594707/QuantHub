import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { useApi } from '../api/useApi'
import type { RunResp } from '../api/types'
import {
  defaultParams,
  marketBadge,
  ParamsEditor,
  SignalRow,
  summarize,
} from '../components/StrategyShared'

export default function StrategyDetailPage() {
  const { name } = useParams<{ name: string }>()
  const strategies = useApi(() => api.strategies(), [])
  const strategy = strategies.data?.strategies.find((s) => s.name === name)

  const [params, setParams] = useState<Record<string, unknown>>(() => defaultParams(name ?? ''))
  const [runResult, setRunResult] = useState<RunResp | null>(null)
  const [running, setRunning] = useState(false)
  const [runError, setRunError] = useState('')

  async function handleRun() {
    if (!name) return
    setRunning(true)
    setRunError('')
    setRunResult(null)
    try {
      const resp = await api.runStrategy(name, params)
      setRunResult(resp)
    } catch (err) {
      setRunError(err instanceof Error ? err.message : '运行失败')
    } finally {
      setRunning(false)
    }
  }

  if (strategies.loading) {
    return (
      <div className="card">
        <div className="card-head">
          <div className="card-title">加载中…</div>
        </div>
      </div>
    )
  }

  if (!strategy) {
    return (
      <div className="card">
        <div className="card-head">
          <div className="card-title">未找到策略</div>
        </div>
        <div style={{ padding: 'var(--sp-3)' }}>
          <div className="muted" style={{ marginBottom: 'var(--sp-3)' }}>
            策略 <code>{name}</code> 未注册或已被移除。
          </div>
          <Link to="/strategies" className="period-tab" style={{ textDecoration: 'none' }}>
            ← 返回策略模块列表
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className="card">
      <div className="card-head">
        <div className="card-title" style={{ alignItems: 'center', gap: 'var(--sp-2)' }}>
          <Link
            to="/strategies"
            className="muted"
            style={{ textDecoration: 'none', fontSize: 'var(--fs-18)', lineHeight: 1 }}
            title="返回策略模块列表"
          >
            ←
          </Link>
          <span>{strategy.name}</span>
          <span
            style={{
              fontSize: 'var(--fs-12)',
              padding: '2px 8px',
              borderRadius: 'var(--r-pill)',
              background: 'var(--accent-weak)',
              color: 'var(--accent-strong)',
            }}
          >
            {marketBadge(strategy.market)}
          </span>
          {strategy.live_capable && (
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
      </div>

      <div style={{ padding: 'var(--sp-3)', display: 'flex', flexDirection: 'column', gap: 'var(--sp-4)' }}>
        <p style={{ margin: 0, color: 'var(--text-2)', fontSize: 'var(--fs-14)', lineHeight: 1.6 }}>
          {strategy.description || '暂无描述'}
        </p>

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))',
            gap: 'var(--sp-4)',
            alignItems: 'start',
          }}
        >
          <ParamsEditor name={strategy.name} params={params} onChange={setParams} />

          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-3)' }}>
            <button
              className="period-tab"
              onClick={handleRun}
              disabled={running}
              style={{
                background: 'var(--accent)',
                color: '#fff',
                opacity: running ? 0.7 : 1,
                alignSelf: 'flex-start',
              }}
            >
              {running ? '运行中…' : '运行策略'}
            </button>

            {runError && <div style={{ color: 'var(--down-ink)', fontSize: 'var(--fs-13)' }}>{runError}</div>}

            {runResult && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-3)' }}>
                <div style={{ fontSize: 'var(--fs-14)', fontWeight: 600 }}>
                  运行结果
                  <span className="sub" style={{ marginLeft: 'var(--sp-2)' }}>
                    {runResult.ok ? `产出 ${runResult.count} 条信号` : '失败'}
                  </span>
                </div>
                {!runResult.ok && runResult.error && (
                  <div style={{ color: 'var(--down-ink)', fontSize: 'var(--fs-13)' }}>{runResult.error}</div>
                )}
                {runResult.ok && runResult.signals.length > 0 && (
                  <div style={{ fontSize: 'var(--fs-12)', color: 'var(--text-2)' }}>{summarize(runResult.signals)}</div>
                )}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-2)' }}>
                  {runResult.signals.map((sig, idx) => (
                    <SignalRow key={`${sig.symbol}-${idx}`} sig={sig} />
                  ))}
                  {runResult.signals.length === 0 && (
                    <div className="muted" style={{ fontSize: 'var(--fs-13)' }}>
                      未产出信号
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
