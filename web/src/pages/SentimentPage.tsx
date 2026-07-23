import { useMemo, useState } from 'react'
import { api } from '../api/client'
import { useApi } from '../api/useApi'
import type { RunResp, SignalResp } from '../api/types'

function parseSymbols(raw: string): string[] {
  return raw
    .split(/[,，\s]+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0)
}

function directionLabel(d: string) {
  if (d === 'buy') return '看多'
  if (d === 'sell') return '看空'
  return '观望'
}

function directionClassName(d: string) {
  if (d === 'buy') return 'up'
  if (d === 'sell') return 'down'
  return ''
}

function directionColor(d: string) {
  if (d === 'buy') return 'var(--up-ink)'
  if (d === 'sell') return 'var(--down-ink)'
  return 'var(--text-3)'
}

function scoreColor(direction: string) {
  if (direction === 'buy') return 'var(--up)'
  if (direction === 'sell') return 'var(--down)'
  return 'var(--accent)'
}

export default function SentimentPage() {
  const [symbols, setSymbols] = useState('600519, 000001, 300750')
  const [req, setReq] = useState<{ symbols: string; tick: number }>({ symbols: '', tick: 0 })

  const result = useApi<RunResp>(async () => {
    const codes = parseSymbols(req.symbols)
    if (codes.length === 0) {
      return { ok: true, name: 'sentiment', count: 0, signals: [] }
    }
    return api.runStrategy('sentiment', { symbols: codes, news_limit: 20 })
  }, [req.tick])

  const list = result.data?.signals ?? []
  const isReal = result.data?.ok ?? false
  const hasError = Boolean(result.error || result.data?.error)

  const run = () => setReq({ symbols, tick: req.tick + 1 })

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-4)' }}>
      <div className="card">
        <div className="card-head">
          <div className="card-title">
            情感分析
            <span className="sub">FinBERT2 中文新闻情绪</span>
          </div>
          <span
            className={`src-pill ${result.loading ? 'loading' : isReal ? 'live' : 'mock'}`}
          >
            {result.loading ? '分析中' : isReal ? '实时' : '模拟'}
          </span>
        </div>
        <div style={{ padding: 'var(--sp-3)', display: 'flex', flexDirection: 'column', gap: 'var(--sp-3)' }}>
          <label style={{ fontSize: 'var(--fs-13)', color: 'var(--text-2)' }}>
            股票代码（多个用逗号或空格分隔）
          </label>
          <input
            type="text"
            value={symbols}
            onChange={(e) => setSymbols(e.target.value)}
            placeholder="例如：600519, 000001, 300750"
            style={{
              width: '100%',
              padding: '10px var(--sp-3)',
              borderRadius: 'var(--r-md)',
              border: '1px solid var(--border)',
              background: 'var(--bg-elevated)',
              color: 'var(--text-1)',
              fontSize: 'var(--fs-14)',
              fontFamily: 'inherit',
              outline: 'none',
            }}
          />
          <div style={{ display: 'flex', gap: 'var(--sp-3)', alignItems: 'center' }}>
            <button className="run-btn" onClick={run} disabled={result.loading}>
              {result.loading ? '分析中…' : '运行情感分析'}
            </button>
            {hasError && (
              <span style={{ color: 'var(--down-ink)', fontSize: 'var(--fs-13)' }}>
                {result.error || result.data?.error || '分析失败'}
              </span>
            )}
          </div>
        </div>
      </div>

      {result.data && !result.loading && list.length === 0 && req.symbols && (
        <div className="card">
          <div className="card-head">
            <div className="card-title">
              分析结果
              <span className="sub">无信号</span>
            </div>
          </div>
          <div style={{ padding: 'var(--sp-3)', color: 'var(--text-2)', fontSize: 'var(--fs-13)' }}>
            未从这些标的抓取到有效新闻或未触发情绪阈值。尝试更换代码或增加新闻条数。
          </div>
        </div>
      )}

      {list.length > 0 && (
        <div className="card">
          <div className="card-head">
            <div className="card-title">
              分析结果
              <span className="sub">共 {list.length} 条信号</span>
            </div>
          </div>
          <div style={{ padding: '0 var(--sp-3) var(--sp-3)', display: 'flex', flexDirection: 'column', gap: 'var(--sp-3)' }}>
            {list.map((sig: SignalResp, idx: number) => (
              <SentimentResultCard key={`${sig.symbol}-${idx}`} signal={sig} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function SentimentResultCard({ signal }: { signal: SignalResp }) {
  const meta = signal.meta || {}
  const label = (meta.label as string) || directionLabel(signal.direction)
  const newsCount = (meta.news_count as number) ?? 0
  const engine = (meta.engine as string) || 'unknown'
  const posProb = (meta.pos_prob as number) ?? signal.score

  return (
    <div
      style={{
        padding: 'var(--sp-3)',
        borderRadius: 'var(--r-md)',
        border: '1px solid var(--border)',
        background: 'var(--bg-subtle)',
        display: 'grid',
        gridTemplateColumns: '120px 1fr auto',
        gap: 'var(--sp-4)',
        alignItems: 'center',
      }}
    >
      <div>
        <div style={{ fontWeight: 700, fontSize: 'var(--fs-15)' }}>{signal.symbol}</div>
        <div style={{ fontSize: 'var(--fs-12)', color: 'var(--text-3)', marginTop: 2 }}>
          {signal.market}
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-2)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)', flexWrap: 'wrap' }}>
              <span
                className={`delta ${directionClassName(signal.direction)}`}
                style={{ color: directionColor(signal.direction) }}
              >
                {directionLabel(signal.direction)}
              </span>
          <span style={{ fontSize: 'var(--fs-13)', color: 'var(--text-2)' }}>{label}</span>
          <span style={{ fontSize: 'var(--fs-12)', color: 'var(--text-3)' }}>
            新闻 {newsCount} 条 · 引擎 {engine}
          </span>
        </div>
        <ScoreBar label="正向概率" value={posProb} direction={signal.direction} />
        <ScoreBar label="置信度" value={signal.confidence} direction={signal.direction} />
      </div>

      <div
        style={{
          fontSize: 'var(--fs-22)',
          fontWeight: 700,
          color: directionColor(signal.direction),
          textAlign: 'right',
        }}
      >
        {(posProb * 100).toFixed(1)}%
      </div>
    </div>
  )
}

function ScoreBar({ label, value, direction = '' }: { label: string; value: number; direction?: string }) {
  const pct = Math.max(0, Math.min(1, value)) * 100
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)' }}>
      <span style={{ fontSize: 'var(--fs-12)', color: 'var(--text-3)', width: 60 }}>{label}</span>
      <div
        style={{
          flex: 1,
          height: 6,
          borderRadius: 'var(--r-pill)',
          background: 'var(--bg-elevated)',
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            width: `${pct}%`,
            height: '100%',
            borderRadius: 'var(--r-pill)',
            background: scoreColor(direction),
            transition: 'width 300ms ease',
          }}
        />
      </div>
      <span style={{ fontSize: 'var(--fs-12)', color: 'var(--text-2)', width: 42, textAlign: 'right' }}>
        {pct.toFixed(0)}%
      </span>
    </div>
  )
}
