import { useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import type { Candle } from '../data/types'
import { api } from '../api/client'
import { useApi } from '../api/useApi'
import s from './KlineCard.module.css'

// UI 周期 → 后端 interval（A股在线源支持 5m/15m/1h/daily/weekly）
const ALL_PERIODS = ['5m', '15m', '1H', '4H', '1D', '1W'] as const
type Period = (typeof ALL_PERIODS)[number]
const PERIODS_BY_MARKET: Record<string, readonly Period[]> = {
  a_shares: ['1D', '1W'],
  us_stocks: ['5m', '15m', '1H', '1D'],
  crypto: ALL_PERIODS,
}
const A_SHARE_PERIOD_LABELS: Partial<Record<Period, string>> = {
  '1D': '日线',
  '1W': '周线',
}
const INTERVAL_MAP: Record<Period, string> = {
  '5m': '5m',
  '15m': '15m',
  '1H': '1h',
  '4H': '4h',
  '1D': '1d',
  '1W': '1w',
}
const ZOOM_STEPS = [60, 45, 30, 20, 12]

const H = 300
const padL = 8
const padR = 56
const padT = 10
const priceH = 210
const volTop = 228
const volH = 62

const MA_PERIODS = [
  { key: 5, color: 'var(--ma-5)', label: 'MA5' },
  { key: 10, color: 'var(--ma-10)', label: 'MA10' },
  { key: 20, color: 'var(--ma-20)', label: 'MA20' },
] as const

function fmt(n: number) {
  return n.toLocaleString('en-US', { maximumFractionDigits: 2 })
}

function fmtTs(t: string) {
  const d = Date.parse(t)
  if (Number.isNaN(d)) return t
  return new Date(d).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function computeMA(candles: Candle[], period: number): (number | null)[] {
  const out: (number | null)[] = []
  let sum = 0
  for (let i = 0; i < candles.length; i++) {
    sum += candles[i].c
    if (i >= period) sum -= candles[i - period].c
    if (i >= period - 1) out.push(sum / period)
    else out.push(null)
  }
  return out
}

function dataFreshness(
  source: 'live' | 'offline' | 'empty' | 'invalid',
  candles: Candle[],
): { stale: boolean; text: string } {
  // 仅离线源需要提示滞后；实时源（腾讯/akshare）本身即最新行情
  if (source === 'live' || !candles.length) return { stale: false, text: '' }
  const last = candles[candles.length - 1]
  const dt = Date.parse(last.t)
  // ordinal 时间编码无法解析（如本地 parquet 回测数据）→ 直接提示非实时
  if (Number.isNaN(dt)) return { stale: true, text: '离线数据，非实时' }
  const diffMs = Date.now() - dt
  const hours = Math.round(diffMs / 3600000)
  if (hours < 24) return { stale: false, text: `更新于 ${hours} 小时前` }
  return { stale: true, text: `数据已延迟 ${Math.floor(hours / 24)} 天` }
}

interface Props {
  symbol?: string
  market?: string
  onSymbolChange?: (s: string) => void
  onMarketChange?: (m: 'a_shares' | 'crypto' | 'us_stocks') => void
  defaultPeriod?: Period
  showInstrumentControls?: boolean
}

export default function KlineCard({
  symbol = '600519',
  market = 'a_shares',
  onSymbolChange,
  onMarketChange,
  defaultPeriod = '1D',
  showInstrumentControls = true,
}: Props) {
  const [period, setPeriod] = useState<Period>(defaultPeriod)
  const [zoom, setZoom] = useState(2) // 0..4, 越大可见 K 线越少
  const [windowOffset, setWindowOffset] = useState(0)
  const [isDragging, setIsDragging] = useState(false)
  const [size, setSize] = useState({ w: 780 })
  const [inputSym, setInputSym] = useState(symbol)
  const wrapRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef<{ pointerId: number; startX: number; startOffset: number } | null>(null)

  const [showMA, setShowMA] = useState({ 5: true, 10: true, 20: false })
  const [hoverIdx, setHoverIdx] = useState<number | null>(null)
  const [mousePos, setMousePos] = useState<{ x: number; y: number } | null>(null)

  // 外部 symbol 变化时同步输入框
  useEffect(() => setInputSym(symbol), [symbol])

  const availablePeriods = PERIODS_BY_MARKET[market] ?? ALL_PERIODS
  const effectivePeriod = availablePeriods.includes(period) ? period : '1D'

  useEffect(() => {
    if (period !== effectivePeriod) setPeriod(effectivePeriod)
    setWindowOffset(0)
  }, [effectivePeriod, market, period, symbol])

  // ── 真实数据接入：经统一 API 客户端取 K 线；失败/无数据一律走空态，不降级到模拟 ──
  const { data, loading, error } = useApi(
    () => api.kline(symbol, market, INTERVAL_MAP[effectivePeriod], 240),
    [effectivePeriod, symbol, market],
  )

  const isReal = !!data?.ok && data.candles.length > 0 && data.source !== 'empty'
  const blockedByQuality = data?.quality?.status === 'invalid' && !data.quality.usable
  // 如实分类数据来源：腾讯、AkShare、OKX 公共接口算实时；本地快照标为离线。
  const isLive = data?.source === 'tencent' || data?.source === 'akshare' || data?.source === 'okx'
  const source: 'live' | 'offline' | 'empty' | 'invalid' = blockedByQuality
    ? 'invalid'
    : isLive
      ? 'live'
      : isReal
        ? 'offline'
        : 'empty'

  const allCandles = useMemo<Candle[]>(() => {
    // M3 无假数据：只渲染后端真实返回的 K 线；质量拦截/失败/空返回一律走空态，
    // 不再生成任何模拟蜡烛图，避免用户把占位图形误认为行情。
    if (isReal) return data!.candles
    return []
  }, [isReal, data])

  // 容器宽度（响应式铺满）
  useEffect(() => {
    if (!wrapRef.current) return
    const el = wrapRef.current
    const updateSize = () => setSize({ w: Math.max(320, Math.floor(el.clientWidth || 780)) })
    if (typeof ResizeObserver === 'undefined') {
      updateSize()
      window.addEventListener('resize', updateSize)
      return () => window.removeEventListener('resize', updateSize)
    }
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const cr = entry.contentRect
        setSize({ w: Math.max(320, Math.floor(cr.width)) })
      }
    })
    ro.observe(el)
    updateSize()
    return () => ro.disconnect()
  }, [])

  const emptyState = allCandles.length === 0
  const visibleCount = ZOOM_STEPS[zoom]
  const maxWindowOffset = Math.max(0, allCandles.length - visibleCount)
  const boundedWindowOffset = Math.min(windowOffset, maxWindowOffset)
  const windowEnd = allCandles.length - boundedWindowOffset
  const windowStart = Math.max(0, windowEnd - visibleCount)

  useEffect(() => {
    if (windowOffset !== boundedWindowOffset) setWindowOffset(boundedWindowOffset)
  }, [boundedWindowOffset, windowOffset])

  const candles = useMemo(() => {
    if (allCandles.length <= visibleCount) return allCandles
    return allCandles.slice(windowStart, windowEnd)
  }, [allCandles, visibleCount, windowEnd, windowStart])

  const { wicks, bodies, vols, gridY, gridLabels, last, change, pct, yOf, periodHigh, periodLow, W, cw, plotL, maLines, maSeries } =
    useMemo(() => {
      const W = size.w
      const n = candles.length
      // 空态保护：加载中 / 无数据时返回占位对象，避免 Math.min(...[]) 与 candles[-1] 崩溃
      if (n === 0) {
        const zero: Candle = { t: '', o: 0, h: 0, l: 0, c: 0, v: 0 }
        return {
          wicks: [],
          bodies: [],
          vols: [],
          gridY: [],
          gridLabels: [],
          last: zero,
          change: 0,
          pct: 0,
          yOf: () => 0,
          periodHigh: 0,
          periodLow: 0,
          W,
          cw: 0,
          plotL: padL,
          maLines: [],
          maSeries: {} as Record<number, (number | null)[]>,
        }
      }
      const plotL = padL
      const plotR = W - padR
      const plotW = Math.max(1, plotR - plotL)
      const cw = plotW / n
      const bodyW = Math.max(2, cw * 0.7)

      const minL = Math.min(...candles.map((c) => c.l))
      const maxH = Math.max(...candles.map((c) => c.h))
      const pad = (maxH - minL) * 0.04
      const lo = minL - pad
      const hi = maxH + pad
      const yOf = (p: number) => padT + ((hi - p) / (hi - lo)) * priceH

      const maxV = Math.max(...candles.map((c) => c.v))

      const wicks: JSX.Element[] = []
      const bodies: JSX.Element[] = []
      const vols: JSX.Element[] = []

      candles.forEach((c, i) => {
        const x = plotL + cw * (i + 0.5)
        const up = c.c >= c.o
        const color = up ? 'var(--up)' : 'var(--down)'
        const yH = yOf(c.h)
        const yL = yOf(c.l)
        const yO = yOf(c.o)
        const yC = yOf(c.c)
        const top = Math.min(yO, yC)
        const bh = Math.max(1, Math.abs(yC - yO))

        wicks.push(<line key={`w${i}`} x1={x} y1={yH} x2={x} y2={yL} stroke={color} strokeWidth={1} />)
        bodies.push(
          <rect
            key={`b${i}`}
            x={x - bodyW / 2}
            y={top}
            width={bodyW}
            height={bh}
            fill={color}
            rx={0.6}
          />,
        )
        const vh = (c.v / maxV) * volH
        vols.push(
          <rect
            key={`v${i}`}
            x={x - bodyW / 2}
            y={volTop + (volH - vh)}
            width={bodyW}
            height={vh}
            fill={color}
            opacity={0.32}
          />,
        )
      })

      const gridY: number[] = []
      const gridLabels: string[] = []
      for (let g = 0; g <= 4; g++) {
        const p = hi - ((hi - lo) / 4) * g
        gridY.push(yOf(p))
        gridLabels.push(fmt(p))
      }

      const last = candles[n - 1]
      const first = candles[0]
      const change = last.c - first.c
      const pct = (change / first.c) * 100
      const periodHigh = Math.max(...candles.map((c) => c.h))
      const periodLow = Math.min(...candles.map((c) => c.l))

      // 在完整数据上计算 MA，再对齐到可见窗口，保证线条连续
      const maSeries: Record<number, (number | null)[]> = {}
      const maLines = MA_PERIODS.map(({ key, color }) => {
        maSeries[key] = computeMA(allCandles, key).slice(windowStart, windowEnd)
        if (!showMA[key]) return null
        const points = maSeries[key]
          .map((v, i) => (v == null ? null : (`${plotL + cw * (i + 0.5)},${yOf(v)}` as const)))
          .filter((s): s is `${number},${number}` => s !== null)
        if (points.length < 2) return null
        return (
          <polyline
            key={key}
            points={points.join(' ')}
            fill="none"
            stroke={color}
            strokeWidth={1.5}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        )
      })

      return { wicks, bodies, vols, gridY, gridLabels, last, change, pct, yOf, periodHigh, periodLow, W, cw, plotL, maLines, maSeries }
    }, [candles, allCandles, size.w, showMA, windowEnd, windowStart])

  const lastUp = last.c >= last.o
  const lastColor = lastUp ? 'var(--up)' : 'var(--down)'
  const yLast = yOf(last.c)
  const freshness = useMemo(() => dataFreshness(source, allCandles), [source, allCandles])

  // 非被动 wheel 监听：React 17+ onWheel 是 passive，preventDefault 无效会导致页面同步滚动。
  // 改用 ref + addEventListener({ passive: false }) 注册原生监听，确保缩放时锁定页面滚动。
  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const handler = (e: WheelEvent) => {
      e.preventDefault()
      if (e.deltaY < 0) setZoom((z) => Math.min(ZOOM_STEPS.length - 1, z + 1))
      else setZoom((z) => Math.max(0, z - 1))
    }
    el.addEventListener('wheel', handler, { passive: false })
    return () => el.removeEventListener('wheel', handler)
  }, [])

  const handlePointerDown = (e: React.PointerEvent<SVGSVGElement>) => {
    if (maxWindowOffset === 0 || (e.pointerType === 'mouse' && e.button !== 0)) return
    e.currentTarget.setPointerCapture(e.pointerId)
    dragRef.current = { pointerId: e.pointerId, startX: e.clientX, startOffset: boundedWindowOffset }
    setIsDragging(true)
    setHoverIdx(null)
    setMousePos(null)
  }

  const handlePointerMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const drag = dragRef.current
    if (drag?.pointerId === e.pointerId) {
      const deltaCandles = Math.round((e.clientX - drag.startX) / Math.max(cw, 1))
      setWindowOffset(Math.min(maxWindowOffset, Math.max(0, drag.startOffset + deltaCandles)))
      return
    }
    if (!wrapRef.current || candles.length === 0) return
    const rect = e.currentTarget.getBoundingClientRect()
    const x = e.clientX - rect.left
    const y = e.clientY - rect.top
    const n = candles.length
    const i = Math.min(n - 1, Math.max(0, Math.floor((x - plotL + cw / 2) / cw)))
    setHoverIdx(i)
    setMousePos({ x, y })
  }

  const endDrag = (e: React.PointerEvent<SVGSVGElement>) => {
    if (dragRef.current?.pointerId !== e.pointerId) return
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId)
    dragRef.current = null
    setIsDragging(false)
  }

  const handlePointerLeave = () => {
    if (dragRef.current) return
    setHoverIdx(null)
    setMousePos(null)
  }

  const hovered = hoverIdx != null ? candles[hoverIdx] : null
  const hoverX = hoverIdx != null ? plotL + cw * (hoverIdx + 0.5) : 0
  const hoverY = hovered ? yOf(hovered.c) : 0

  return (
    <div className="card">
      <div className="card-head kline-head">
        <div className="kline-title">
          <span className="sym">{symbol}</span>
          <span className="price mono">{emptyState ? '--' : fmt(last.c)}</span>
          <span className={`${lastUp ? 'up' : 'down'} ${s.changeText}`}>
            {emptyState
              ? '—'
              : `${lastUp ? '▲' : '▼'} ${fmt(Math.abs(change))} (${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%)`}
          </span>
          <span
            className={`src-pill ${source === 'live' ? 'live' : source === 'offline' || source === 'invalid' ? 'warn' : 'empty'}`}
            title={data?.quality
              ? `质量 ${data.quality.status} · 缺失 ${(data.quality.missing_rate * 100).toFixed(2)}% · 非法 ${data.quality.invalid_rows} 行 · 延迟 ${data.quality.latency_ms ?? '—'}ms`
              : undefined}
          >
            {source === 'live' ? '实时' : source === 'offline' ? '离线' : source === 'invalid' ? '质量拦截' : '无数据'}
          </span>
          {freshness.stale && <span className="src-pill warn">{freshness.text}</span>}
          {loading && <span className="src-pill loading">加载中…</span>}
        </div>
        <div className="kline-controls">
          {showInstrumentControls && <>
            <input
              className="kline-symbol-input"
              value={inputSym}
              onChange={(e) => setInputSym(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') onSymbolChange?.(inputSym.trim())
              }}
              placeholder="输入代码，回车切换"
              aria-label="股票代码"
            />
            <select
              className="kline-market-select"
              value={market}
              onChange={(e) => onMarketChange?.(e.target.value as 'a_shares' | 'crypto' | 'us_stocks')}
              aria-label="市场"
            >
              <option value="a_shares">A股</option>
              <option value="crypto">OKX 合约</option>
              <option value="us_stocks">美股</option>
            </select>
          </>}
          <div className="zoom-btns" title="滚轮也可缩放">
            <button className="zoom-btn" onClick={() => setZoom((z) => Math.max(0, z - 1))} aria-label="缩小" title="缩小">
              −
            </button>
            <button className="zoom-btn" onClick={() => setZoom((z) => Math.min(ZOOM_STEPS.length - 1, z + 1))} aria-label="放大" title="放大">
              +
            </button>
          </div>
          <div className="period-tabs" role="tablist">
            {availablePeriods.map((p) => (
              <button
                key={p}
                role="tab"
                aria-selected={p === effectivePeriod}
                className={`period-tab ${p === effectivePeriod ? 'active' : ''}`}
                onClick={() => setPeriod(p)}
              >
                {market === 'a_shares' ? A_SHARE_PERIOD_LABELS[p] ?? p : p}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="kline-toolbar">
        <div className="kline-legend">
          {MA_PERIODS.map(({ key, color, label }) => (
            <button
              key={key}
              type="button"
              className={`kline-ma-toggle ${showMA[key] ? 'on' : ''}`}
              onClick={() => setShowMA((s) => ({ ...s, [key]: !s[key] }))}
              aria-pressed={showMA[key]}
            >
              <span
                className={`kline-ma-dot ${s.maDot}`}
                style={{ '--c': color } as CSSProperties}
              />
              {label}
            </button>
          ))}
        </div>
        <span className="kline-hint">左右拖动查看历史 · 滚轮缩放</span>
      </div>

      <div className="kline-svg-wrap" ref={wrapRef}>
        {loading && (
          <div className="kline-overlay">
            <div className="kline-skeleton" />
          </div>
        )}
        {error && !loading && (
          <div className="kline-overlay kline-overlay-err">
            <div>
              <div className={s.errTitle}>后端连接失败</div>
              <div className={`muted ${s.errHint}`}>
                未取到行情数据，本卡片不展示任何替代数值
              </div>
            </div>
          </div>
        )}
        {!loading && !error && allCandles.length === 0 && (
          <div className="kline-overlay">
            <div className={`muted ${s.emptyHint}`}>
              {blockedByQuality ? '数据质量校验未通过，已拦截展示' : '暂无 K 线数据'}
            </div>
          </div>
        )}
        <svg
          className={`kline-svg ${isDragging ? 'dragging' : ''} ${s.svg}`}
          data-loading={loading ? 'true' : 'false'}
          viewBox={`0 0 ${W} ${H}`}
          preserveAspectRatio="xMidYMid meet"
          role="img"
          aria-label="K线图，可左右拖动查看历史并使用滚轮缩放"
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
          onPointerLeave={handlePointerLeave}
        >
          {gridY.map((y, i) => (
            <g key={i}>
              <line x1={padL} y1={y} x2={W - padR} y2={y} stroke="var(--grid-line)" strokeWidth={1} />
              <text
                x={W - padR + 7}
                y={y + 4}
                fill="var(--text-3)"
                fontSize={10}
                fontFamily="var(--font-mono)"
              >
                {gridLabels[i]}
              </text>
            </g>
          ))}

          {maLines}
          {vols}
          {wicks}
          {bodies}

          {/* 十字光标 */}
          {hovered && (
            <g className="kline-crosshair">
              <line
                x1={hoverX}
                y1={padT}
                x2={hoverX}
                y2={volTop + volH}
                stroke="var(--text-3)"
                strokeWidth={1}
                strokeDasharray="3 3"
                opacity={0.55}
              />
              <line
                x1={padL}
                y1={hoverY}
                x2={W - padR}
                y2={hoverY}
                stroke="var(--text-3)"
                strokeWidth={1}
                strokeDasharray="3 3"
                opacity={0.55}
              />
              <circle
                cx={hoverX}
                cy={hoverY}
                r={3.5}
                fill={hovered.c >= hovered.o ? 'var(--up)' : 'var(--down)'}
                stroke="#fff"
                strokeWidth={1}
              />
            </g>
          )}

          {/* 最新价标签 */}
          <line
            x1={padL}
            y1={yLast}
            x2={W - padR}
            y2={yLast}
            stroke={lastColor}
            strokeWidth={1}
            strokeDasharray="4 4"
            opacity={0.8}
          />
          <rect x={W - padR} y={yLast - 10} width={padR} height={20} fill={lastColor} rx={3} />
          <text
            x={W - padR / 2}
            y={yLast + 4}
            fill="#fff"
            fontSize={10}
            fontWeight={600}
            textAnchor="middle"
            fontFamily="var(--font-mono)"
          >
            {fmt(last.c)}
          </text>
        </svg>

        {/* 悬停提示框 */}
        {hovered && mousePos && (
          <div
            className="kline-tooltip"
            style={{
              left: Math.max(8, Math.min(mousePos.x + 14, size.w - 150)),
              top: Math.max(8, mousePos.y + 14),
            }}
          >
            <div className="kline-tooltip-head">{fmtTs(hovered.t)}</div>
            <div className="kline-tooltip-row">
              <span>开</span>
              <span className="mono">{fmt(hovered.o)}</span>
            </div>
            <div className="kline-tooltip-row">
              <span>高</span>
              <span className="mono">{fmt(hovered.h)}</span>
            </div>
            <div className="kline-tooltip-row">
              <span>低</span>
              <span className="mono">{fmt(hovered.l)}</span>
            </div>
            <div className="kline-tooltip-row">
              <span>收</span>
              <span className={`mono ${hovered.c >= hovered.o ? 'up' : 'down'}`}>{fmt(hovered.c)}</span>
            </div>
            <div className="kline-tooltip-row">
              <span>量</span>
              <span className="mono">{fmt(hovered.v)}</span>
            </div>
            {MA_PERIODS.map(({ key, color, label }) => {
              const series = maSeries[key]
              const v = hoverIdx != null ? series?.[hoverIdx] : null
              if (v == null) return null
              return (
                <div key={key} className="kline-tooltip-row">
                  <span
                    className={s.tooltipMaLabel}
                    style={{ '--c': color } as CSSProperties}
                  >
                    {label}
                  </span>
                  <span className="mono">{fmt(v)}</span>
                </div>
              )
            })}
          </div>
        )}
      </div>

      <div className="kline-meta">
        <div className="item">
          <span className="k">开</span>
          <span className="v mono">{emptyState ? '--' : fmt(candles[0].o)}</span>
        </div>
        <div className="item">
          <span className="k">高</span>
          <span className="v mono up">{emptyState ? '--' : fmt(periodHigh)}</span>
        </div>
        <div className="item">
          <span className="k">低</span>
          <span className="v mono down">{emptyState ? '--' : fmt(periodLow)}</span>
        </div>
        <div className="item">
          <span className="k">收</span>
          <span className="v mono">{emptyState ? '--' : fmt(last.c)}</span>
        </div>
        <div className="item">
          <span className="k">量</span>
          <span className="v mono">{emptyState ? '--' : fmt(last.v)}</span>
        </div>
        <div className="item">
          <span className="k">显示范围</span>
          <span className="v mono">
            {allCandles.length ? `${windowStart + 1}-${windowEnd}/${allCandles.length}` : '0/0'}
          </span>
        </div>
        {error && (
          <div className={`item ${s.itemFull}`}>
            <span className={`k ${s.itemKeyErr}`}>
              后端连接失败，已降级为模拟数据
            </span>
          </div>
        )}
      </div>
    </div>
  )
}
