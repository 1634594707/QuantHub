import { useMemo, useState } from 'react'
import type { CSSProperties } from 'react'
import type { SignalResp, StrategyInfo } from '../api/types'
import { dirBucket, directionColor, matchDir } from '../lib/signal-utils'
import { DirectionDonut, ScoreHistogram } from './SignalViz'
import { Input } from './ui/Input/Input'
import { Select } from './ui/Select/Select'
import { Textarea } from './ui/Textarea/Textarea'
import { Toggle } from './ui/Toggle/Toggle'
import { Tag } from './ui/Tag/Tag'
import { Button } from './ui/Button/Button'
import s from './StrategyShared.module.css'
import '../styles/strategy-module.css'

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
    alphamaster: {
      formulas: [[2], [9], [23]],
      min_trade_exposure: 0.05,
      cost_rate: 0.0001,
      slippage_rate: 0.0001,
    },
  }
  return map[name] ?? {}
}

export type FieldType = 'symbols' | 'formulas' | 'text' | 'number' | 'select' | 'toggle'

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
    case 'alphamaster':
      return [
        { key: 'formulas', label: '因子公式 token', type: 'formulas', placeholder: '2; 9; 23' },
        { key: 'min_trade_exposure', label: '最小交易敞口', type: 'number', min: 0, max: 1 },
        { key: 'cost_rate', label: '单边手续费率', type: 'number', min: 0, max: 0.1 },
        { key: 'slippage_rate', label: '单边滑点率', type: 'number', min: 0, max: 0.1 },
      ]
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
  if (f.type === 'symbols') {
    const text = Array.isArray(value) ? (value as unknown[]).join(', ') : ''
    return (
      <Input
        type="text"
        value={text}
        placeholder={f.placeholder}
        onChange={(e) => {
          const codes = e.target.value
            .split(/[,，]/)
            .map((str) => str.trim())
            .filter(Boolean)
          onChange({ ...params, [f.key]: codes })
        }}
      />
    )
  }
  if (f.type === 'text') {
    return (
      <Input
        type="text"
        value={value == null ? '' : String(value)}
        placeholder={f.placeholder}
        onChange={(e) => onChange({ ...params, [f.key]: e.target.value })}
      />
    )
  }
  if (f.type === 'formulas') {
    const text = Array.isArray(value)
      ? (value as unknown[])
        .map((formula) => Array.isArray(formula) ? formula.join(', ') : '')
        .filter(Boolean)
        .join('; ')
      : ''
    return (
      <Textarea
        variant="mono"
        rows={3}
        value={text}
        placeholder={f.placeholder}
        onChange={(event) => {
          const groups = event.target.value.split(';').map((group) => group.trim()).filter(Boolean)
          const formulas = groups.map((group) => group.split(',').map((token) => Number(token.trim())))
          if (formulas.some((formula) => formula.length === 0 || formula.some((token) => !Number.isInteger(token)))) return
          onChange({ ...params, [f.key]: formulas })
        }}
      />
    )
  }
  if (f.type === 'number') {
    return (
      <Input
        type="number"
        min={f.min}
        max={f.max}
        value={value == null ? '' : Number(value)}
        onChange={(e) => {
          const n = Number(e.target.value || '0')
          onChange({ ...params, [f.key]: Number.isNaN(n) ? 0 : n })
        }}
      />
    )
  }
  if (f.type === 'select') {
    return (
      <Select
        value={value == null ? '' : String(value)}
        onChange={(e) => onChange({ ...params, [f.key]: e.target.value })}
        options={f.options ?? []}
      />
    )
  }
  if (f.type === 'toggle') {
    const on = value === true || value === 1 || value === 'true'
    return (
      <Toggle
        checked={on}
        onChange={(next) => onChange({ ...params, [f.key]: next })}
        label={on ? '已开启' : '已关闭'}
      />
    )
  }
  return null
}

function structuredValueControl(
  key: string,
  value: unknown,
  onChange: (value: unknown) => void,
) {
  if (typeof value === 'boolean') {
    return <Toggle checked={value} onChange={onChange} label={value ? '已开启' : '已关闭'} />
  }
  if (typeof value === 'number') {
    return <Input type="number" step="any" value={value} onChange={(event) => onChange(Number(event.target.value))} />
  }
  if (typeof value === 'string' || value == null) {
    return <Input value={value == null ? '' : value} onChange={(event) => onChange(event.target.value)} />
  }
  if (Array.isArray(value)) {
    return (
      <div className={s.structuredList}>
        {value.map((item, index) => (
          <div key={`${key}:${index}`}>
            <span>{index + 1}</span>
            {structuredValueControl(`${key}.${index}`, item, (next) => onChange(value.map((current, itemIndex) => itemIndex === index ? next : current)))}
            <Button type="button" variant="link" size="sm" onClick={() => onChange(value.filter((_, itemIndex) => itemIndex !== index))}>移除</Button>
          </div>
        ))}
        <Button type="button" variant="link" size="sm" onClick={() => onChange([...value, typeof value[0] === 'number' ? 0 : ''])}>增加一项</Button>
      </div>
    )
  }
  const entries = Object.entries(value as Record<string, unknown>)
  return entries.length ? (
    <div className={s.structuredObject}>
      {entries.map(([childKey, childValue]) => (
        <label key={childKey}>
          <span>{childKey}</span>
          {structuredValueControl(`${key}.${childKey}`, childValue, (next) => onChange({ ...(value as Record<string, unknown>), [childKey]: next }))}
        </label>
      ))}
    </div>
  ) : <span className={s.emptyParams}>空对象</span>
}

export function StructuredParamsEditor({
  name,
  params,
  onChange,
}: {
  name: string
  params: Record<string, unknown>
  onChange: (params: Record<string, unknown>) => void
}) {
  const fields = paramFields(name)
  if (fields.length) {
    return (
      <div className={s.box}>
        {fields.map((field) => (
          <div key={field.key} className={s.fieldRow}>
            <label className={s.fieldLabel}>{field.label}</label>
            {fieldControl(field, params, onChange)}
          </div>
        ))}
      </div>
    )
  }

  const entries = Object.entries(params)
  return (
    <div className={s.box}>
      {entries.length ? entries.map(([key, value]) => (
        <div key={key} className={s.fieldRow}>
          <label className={s.fieldLabel}>{key}</label>
          {structuredValueControl(key, value, (next) => onChange({ ...params, [key]: next }))}
        </div>
      )) : <span className={s.emptyParams}>当前策略没有参数</span>}
    </div>
  )
}

export function summarize(signals: SignalResp[]) {
  const buy = signals.filter((sig) => dirBucket(sig.direction) === 'buy').length
  const sell = signals.filter((sig) => dirBucket(sig.direction) === 'sell').length
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

  // 方向色作为 CSS 变量注入，避免在子元素上重复内联 style
  const dirStyle = { '--dir-color': directionColor(sig.direction) } as CSSProperties

  return (
    <div className={s.signalRow} style={dirStyle}>
      <div className={s.rowHead}>
        <span className={s.symbol}>{sig.symbol}</span>
        <span className={s.dirBadge}>{sig.direction.toUpperCase()}</span>
        <span className={['muted', s.score].join(' ')}>
          score {sig.score.toFixed(2)}
        </span>
      </div>
      <div className={s.confRow}>
        <span className={s.confLabel}>置信度</span>
        <div className={s.confBar}>
          <div
            className={s.confFill}
            style={{ '--w': `${(sig.confidence * 100).toFixed(0)}%` } as CSSProperties}
          />
        </div>
        <span className={['mono', s.confValue].join(' ')}>
          {(sig.confidence * 100).toFixed(0)}%
        </span>
      </div>
      <div className={s.meta}>
        {sig.market} · {sig.timeframe} · 来源 {sig.source}
      </div>
      {reason && <div className={s.reason}>{reason}</div>}
      {extra.length > 0 && (
        <div className={s.extraList}>
          {extra.map(([k, v]) => (
            <Tag key={k} variant="neutral">{k}: {String(v)}</Tag>
          ))}
        </div>
      )}
      {sig.tags.length > 0 && (
        <div className={s.tagList}>
          {sig.tags.map((t) => (
            <Tag key={t} variant="accent">{t}</Tag>
          ))}
        </div>
      )}
    </div>
  )
}

/* ---------------- 共享常量（回测表单 / 信号筛选） ---------------- */
/** 回测市场选项：与 marketKey/marketBadge 同源，详情页回测表单复用 */
export const MARKET_OPTIONS = [
  { value: 'a_shares', label: 'A股' },
  { value: 'us_stocks', label: '美股' },
  { value: 'crypto', label: '加密' },
  { value: 'mt5', label: 'MT5' },
]

/** 回测周期选项 */
export const INTERVAL_OPTIONS = [
  { value: '1d', label: '日线' },
  { value: '1h', label: '1小时' },
  { value: '4h', label: '4小时' },
  { value: '15m', label: '15分钟' },
]

/** 信号方向筛选选项：详情页 SignalResults 与 SignalsPage 复用，单一来源 */
export const DIR_FILTERS: ReadonlyArray<['all' | 'buy' | 'sell' | 'hold', string]> = [
  ['all', '全部'],
  ['buy', '做多'],
  ['sell', '做空'],
  ['hold', '观望'],
]

/** 信号排序选项 */
export const SIGNAL_SORT_OPTIONS = [
  { value: 'score', label: '按分数' },
  { value: 'confidence', label: '按置信度' },
  { value: 'time', label: '按时间' },
]

/**
 * 运行结果区块：方向环图 + 分数分布 + 方向筛选 + 排序 + 信号卡片列表。
 * 详情页「信号」「运行」Tab 复用；未来 SignalsPage 也可复用。
 */
export function SignalResults({ signals }: { signals: SignalResp[] }) {
  const [dirFilter, setDirFilter] = useState<'all' | 'buy' | 'sell' | 'hold'>('all')
  const [sortBy, setSortBy] = useState<'time' | 'score' | 'confidence'>('score')

  const filtered = useMemo(() => {
    const list = signals.filter((sig) => matchDir(sig.direction, dirFilter))
    return [...list].sort((a, b) => {
      if (sortBy === 'score') return b.score - a.score
      if (sortBy === 'confidence') return b.confidence - a.confidence
      return 0
    })
  }, [signals, dirFilter, sortBy])

  return (
    <>
      <DirectionDonut signals={signals} />
      <div className={s.histogramWrap}>
        <ScoreHistogram signals={signals} />
      </div>
      <div className={`signal-result-head ${s.resultHead}`}>
        <div className="signal-result-summary">{summarize(signals)}</div>
      </div>
      <div className="signal-filter-bar">
        <div className="signal-filters">
          {DIR_FILTERS.map(([k, l]) => (
            <Button
              key={k}
              size="sm"
              variant={dirFilter === k ? 'primary' : 'secondary'}
              onClick={() => setDirFilter(k)}
            >
              {l}
            </Button>
          ))}
        </div>
        <Select
          className={s.sortSelect}
          options={SIGNAL_SORT_OPTIONS}
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value as typeof sortBy)}
        />
      </div>
      <div className="signal-list">
        {filtered.map((sig, idx) => (
          <SignalRow key={`${sig.symbol}-${idx}`} sig={sig} />
        ))}
        {filtered.length === 0 && <div className="muted">当前筛选下无信号</div>}
      </div>
    </>
  )
}
