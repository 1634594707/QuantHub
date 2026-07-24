import { useEffect, useState } from 'react'
import type { CSSProperties } from 'react'
import type { RunResp, SignalResp, StrategyInfo } from '../api/types'
import { dirBucket, directionColor } from '../lib/signal-utils'

export type MarketKey = 'a_shares' | 'crypto' | 'us_stocks' | 'other'

export function marketKey(m: string): MarketKey {
  if (m === 'a_shares' || m === 'crypto' || m === 'us_stocks') return m
  return 'other'
}

export function marketBadge(m: StrategyInfo['market']) {
  if (m === 'a_shares') return 'A股'
  if (m === 'crypto') return '加密货币'
  if (m === 'us_stocks') return '美股'
  return m
}

export function defaultParams(name: string): Record<string, unknown> {
  const map: Record<string, Record<string, unknown>> = {
    sentiment: { symbols: ['300750'], news_limit: 10 },
    selector: { universe: 'hs300', top_n: 5 },
    supertrend: { symbols: ['600519'], timeframe: 'daily' },
    realtime_analyzer: { symbols: ['600519'], with_kline: true, with_indices: true },
    morning_brief: { symbols: ['600519', '000001'] },
    perks_monitor: {},
    news_scanner: {},
    pa_agent: { symbol: '600519', timeframe: '1h' },
    okx_grid: { symbol: 'BTC-USDT-SWAP', live: false },
    alphagpt: { symbol: 'BTC-USDT-SWAP' },
    alphamaster: {},
  }
  return map[name] ?? {}
}

export type FieldType = 'symbols' | 'text' | 'number' | 'select' | 'toggle'

export interface ParamField {
  key: string
  label: string
  type: FieldType
  options?: { label: string; value: string }[]
  min?: number
  max?: number
  placeholder?: string
}

export function paramFields(name: string): ParamField[] {
  switch (name) {
    case 'sentiment':
      return [
        { key: 'symbols', label: '股票代码（逗号分隔）', type: 'symbols', placeholder: '如 600519, 000001' },
        { key: 'news_limit', label: '新闻条数', type: 'number', min: 1, max: 100 },
      ]
    case 'okx_grid':
      return [
        { key: 'symbol', label: '交易对', type: 'text', placeholder: 'BTC-USDT-SWAP' },
        { key: 'live', label: '启用实盘', type: 'toggle' },
      ]
    case 'alphagpt':
      return [{ key: 'symbol', label: '交易对', type: 'text', placeholder: 'BTC-USDT-SWAP' }]
    case 'selector':
      return [
        {
          key: 'universe',
          label: '选股池',
          type: 'select',
          options: [
            { label: '沪深300', value: 'hs300' },
            { label: '中证500', value: 'csi500' },
            { label: '全市场', value: 'all' },
          ],
        },
        { key: 'top_n', label: '选出数量', type: 'number', min: 1, max: 50 },
      ]
    case 'pa_agent':
      return [
        { key: 'symbol', label: '标的代码', type: 'text', placeholder: '600519' },
        {
          key: 'timeframe',
          label: '周期',
          type: 'select',
          options: [
            { label: '1小时', value: '1h' },
            { label: '4小时', value: '4h' },
            { label: '日线', value: '1d' },
          ],
        },
      ]
    case 'supertrend':
      return [
        { key: 'symbols', label: '股票代码（逗号分隔）', type: 'symbols' },
        {
          key: 'timeframe',
          label: '周期',
          type: 'select',
          options: [
            { label: '日线', value: 'daily' },
            { label: '1小时', value: '1h' },
            { label: '4小时', value: '4h' },
          ],
        },
      ]
    case 'realtime_analyzer':
      return [
        { key: 'symbols', label: '股票代码（逗号分隔）', type: 'symbols' },
        { key: 'with_kline', label: '含 K 线', type: 'toggle' },
        { key: 'with_indices', label: '含指数', type: 'toggle' },
      ]
    case 'morning_brief':
      return [{ key: 'symbols', label: '股票代码（逗号分隔）', type: 'symbols' }]
    default:
      return []
  }
}

export { directionColor } from '../lib/signal-utils'

function fieldControl(
  f: ParamField,
  params: Record<string, unknown>,
  onChange: (p: Record<string, unknown>) => void,
) {
  const value = params[f.key]
  const base: CSSProperties = {
    padding: 'var(--sp-2)',
    borderRadius: 'var(--r-sm)',
    border: '1px solid var(--border)',
    background: 'var(--bg-elevated)',
    color: 'var(--text-1)',
    fontSize: 'var(--fs-14)',
    width: '100%',
    boxSizing: 'border-box',
  }
  if (f.type === 'symbols') {
    const text = Array.isArray(value) ? (value as unknown[]).join(', ') : ''
    return (
      <input
        type="text"
        value={text}
        placeholder={f.placeholder}
        onChange={(e) => {
          const codes = e.target.value
            .split(/[,，]/)
            .map((s) => s.trim())
            .filter(Boolean)
          onChange({ ...params, [f.key]: codes })
        }}
        style={base}
      />
    )
  }
  if (f.type === 'text') {
    return (
      <input
        type="text"
        value={value == null ? '' : String(value)}
        placeholder={f.placeholder}
        onChange={(e) => onChange({ ...params, [f.key]: e.target.value })}
        style={base}
      />
    )
  }
  if (f.type === 'number') {
    return (
      <input
        type="number"
        min={f.min}
        max={f.max}
        value={value == null ? '' : Number(value)}
        onChange={(e) => {
          const n = parseInt(e.target.value || '0', 10)
          onChange({ ...params, [f.key]: Number.isNaN(n) ? 0 : n })
        }}
        style={base}
      />
    )
  }
  if (f.type === 'select') {
    return (
      <select
        value={value == null ? '' : String(value)}
        onChange={(e) => onChange({ ...params, [f.key]: e.target.value })}
        style={base}
      >
        {f.options?.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    )
  }
  if (f.type === 'toggle') {
    const on = value === true || value === 1 || value === 'true'
    return (
      <button
        type="button"
        onClick={() => onChange({ ...params, [f.key]: !on })}
        style={{
          alignSelf: 'flex-start',
          padding: '6px 16px',
          borderRadius: 999,
          border: `1px solid ${on ? 'var(--accent)' : 'var(--border)'}`,
          background: on ? 'var(--accent)' : 'var(--bg-elevated)',
          color: on ? '#fff' : 'var(--text-1)',
          fontSize: 'var(--fs-13)',
          cursor: 'pointer',
          fontWeight: 600,
        }}
      >
        {on ? '已开启' : '已关闭'}
      </button>
    )
  }
  return null
}

export function ParamsEditor({
  name,
  params,
  onChange,
}: {
  name: string
  params: Record<string, unknown>
  onChange: (p: Record<string, unknown>) => void
}) {
  const fields = paramFields(name)
  const [jsonText, setJsonText] = useState(() => JSON.stringify(params, null, 2))
  const [jsonError, setJsonError] = useState('')

  useEffect(() => {
    setJsonText(JSON.stringify(params, null, 2))
    setJsonError('')
  }, [name])

  const box: CSSProperties = {
    display: 'flex',
    flexDirection: 'column',
    gap: 'var(--sp-3)',
    padding: 'var(--sp-3)',
    borderRadius: 'var(--r-md)',
    border: '1px solid var(--border)',
    background: 'var(--bg-subtle)',
  }

  return (
    <div style={box}>
      <div style={{ fontSize: 'var(--fs-14)', fontWeight: 600 }}>运行参数</div>
      {fields.length > 0 ? (
        fields.map((f) => (
          <div key={f.key} style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-1)' }}>
            <label style={{ fontSize: 'var(--fs-12)', color: 'var(--text-2)' }}>{f.label}</label>
            {fieldControl(f, params, onChange)}
          </div>
        ))
      ) : (
        <>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ fontSize: 'var(--fs-13)', color: 'var(--text-2)' }}>
              该策略暂不支持可视化参数，请填写 JSON
            </span>
            {jsonError && <span style={{ fontSize: 'var(--fs-12)', color: 'var(--down-ink)' }}>{jsonError}</span>}
          </div>
          <textarea
            value={jsonText}
            onChange={(e) => {
              setJsonText(e.target.value)
              try {
                const parsed = JSON.parse(e.target.value)
                if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
                  onChange(parsed as Record<string, unknown>)
                  setJsonError('')
                } else {
                  setJsonError('参数必须是对象')
                }
              } catch {
                setJsonError('JSON 格式错误')
              }
            }}
            rows={6}
            style={{
              padding: 'var(--sp-2)',
              borderRadius: 'var(--r-sm)',
              border: '1px solid ' + (jsonError ? 'var(--down-ink)' : 'var(--border)'),
              background: 'var(--bg-elevated)',
              color: 'var(--text-1)',
              fontFamily: 'monospace',
              fontSize: 'var(--fs-13)',
              resize: 'vertical',
              boxSizing: 'border-box',
              width: '100%',
            }}
          />
        </>
      )}
    </div>
  )
}

export function summarize(signals: SignalResp[]) {
  const buy = signals.filter((s) => dirBucket(s.direction) === 'buy').length
  const sell = signals.filter((s) => dirBucket(s.direction) === 'sell').length
  const hold = signals.length - buy - sell
  const parts: string[] = []
  if (buy) parts.push('做多 ' + buy)
  if (sell) parts.push('做空 ' + sell)
  if (hold) parts.push('观望 ' + hold)
  return parts.join(' · ')
}

export function SignalRow({ sig }: { sig: SignalResp }) {
  const meta = sig.meta || {}
  const reason =
    (typeof meta.reason === 'string' && meta.reason) ||
    (typeof meta.summary === 'string' && meta.summary) ||
    (typeof meta.note === 'string' && meta.note) ||
    null
  const extra = Object.entries(meta)
    .filter(
      ([k, v]) =>
        !['reason', 'summary', 'note', 'symbol', 'direction', 'timeframe'].includes(k) &&
        (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean'),
    )
    .slice(0, 4)

  return (
    <div
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
        <span style={{ fontWeight: 700, fontSize: 'var(--fs-15)' }}>{sig.symbol}</span>
        <span
          style={{
            fontSize: 'var(--fs-12)',
            padding: '2px 10px',
            borderRadius: 'var(--r-pill)',
            fontWeight: 700,
            color: '#fff',
            background: directionColor(sig.direction),
          }}
        >
          {sig.direction.toUpperCase()}
        </span>
        <span className="muted" style={{ fontSize: 'var(--fs-12)', marginLeft: 'auto' }}>
          score {sig.score.toFixed(2)}
        </span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)' }}>
        <span style={{ fontSize: 'var(--fs-12)', color: 'var(--text-2)', width: 56 }}>置信度</span>
        <div style={{ flex: 1, height: 6, borderRadius: 999, background: 'var(--bg-elevated)', overflow: 'hidden' }}>
          <div
            style={{
              width: `${(sig.confidence * 100).toFixed(0)}%`,
              height: '100%',
              borderRadius: 999,
              background: directionColor(sig.direction),
            }}
          />
        </div>
        <span
          className="mono"
          style={{ width: 40, textAlign: 'right', fontSize: 'var(--fs-12)', fontWeight: 600 }}
        >
          {(sig.confidence * 100).toFixed(0)}%
        </span>
      </div>
      <div style={{ fontSize: 'var(--fs-12)', color: 'var(--text-2)' }}>
        {sig.market} · {sig.timeframe} · 来源 {sig.source}
      </div>
      {reason && (
        <div
          style={{
            fontSize: 'var(--fs-13)',
            lineHeight: 1.6,
            color: 'var(--text-1)',
            padding: 'var(--sp-2) var(--sp-3)',
            borderRadius: 'var(--r-sm)',
            background: 'var(--accent-weak)',
          }}
        >
          {reason}
        </div>
      )}
      {extra.length > 0 && (
        <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', marginTop: '2px' }}>
          {extra.map(([k, v]) => (
            <span
              key={k}
              style={{
                fontSize: 'var(--fs-11)',
                padding: '2px 6px',
                borderRadius: 'var(--r-pill)',
                background: 'var(--bg-elevated)',
                color: 'var(--text-2)',
              }}
            >
              {k}: {String(v)}
            </span>
          ))}
        </div>
      )}
      {sig.tags.length > 0 && (
        <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap', marginTop: '2px' }}>
          {sig.tags.map((t) => (
            <span
              key={t}
              style={{
                fontSize: 'var(--fs-11)',
                padding: '2px 6px',
                borderRadius: 'var(--r-pill)',
                background: 'var(--accent-weak)',
                color: 'var(--accent-strong)',
              }}
            >
              {t}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
