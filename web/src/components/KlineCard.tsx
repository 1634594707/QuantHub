import { useEffect, useMemo, useRef, useState } from 'react'
import { genCandles, type Candle } from '../data/mock'
import { api } from '../api/client'
import { useApi } from '../api/useApi'

// UI 周期 → 后端 interval（A股在线源支持 5m/15m/1h/daily/weekly）
const PERIODS = ['5m', '15m', '1H', '1D', '1W'] as const
type Period = (typeof PERIODS)[number]
const INTERVAL_MAP: Record<Period, string> = {
  '5m': '5m',
  '15m': '15m',
  '1H': '1h',
  '1D': '1d',
  '1W': '1w',
}
const SEEDS: Record<string, number> = { '5m': 11, '15m': 23, '1H': 31, '1D': 42, '1W': 77 }
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
  source: 'live' | 'offline' | 'mock',
  candles: Candle[],
): { stale: boolean; text: string } {
  // 仅离线/模拟源需要提示滞后；实时源（腾讯/akshare）本身即最新行情
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
}

export default function KlineCard({
  symbol = '600519',
  market = 'a_shares',
  onSymbolChange,
  onMarketChange,
}: Props) {
  const [period, setPeriod] = useState<Period>('1D')
  const [zoom, setZoom] = useState(2) // 0..4, 越大可见 K 线越少
  const [size, setSize] = useState({ w: 780 })
  const [inputSym, setInputSym] = useState(symbol)
  const wrapRef = useRef<HTMLDivElement>(null)

  const [showMA, setShowMA] = useState({ 5: true, 10: true, 20: false })
  const [hoverIdx, setHoverIdx] = useState<number | null>(null)
  const [mousePos, setMousePos] = useState<{ x: number; y: number } | null>(null)

  // 外部 symbol 变化时同步输入框
  useEffect(() => setInputSym(symbol), [symbol])

  // ── 真实数据接入：经统一 API 客户端取 K 线，失败/无数据自动降级到模拟 ──
  const { data, loading, error } = useApi(
    () => api.kline(symbol, market, INTERVAL_MAP[period], 240),
    [period, symbol, market],
  )

  const isReal = !!data?.ok && data.candles.length > 0 && data.source !== 'empty'
  // 如实分类数据来源：腾讯/akshare 才算实时；local_parquet 等离线源标为离线，避免伪装成实时
  const isLive = data?.source === 'tencent' || data?.source === 'akshare'
  const source: 'live' | 'offline' | 'mock' = isLive ? 'live' : isReal ? 'offline' : 'mock'
  const hasData = data !== null

  const allCandles = useMemo<Candle[]>(() => {
    if (isReal) return data!.candles
    // 仅在后端失败/返回空时才降级到模拟数据；首次加载中显示骨架屏，避免一闪而过的假价格
    if (!loading || hasData) return genCandles(240, SEEDS[period] ?? 42)
    return []
  }, [isReal, data, period, loading, hasData])

  // 容器宽度（响应式铺满）
  useEffect(() => {
    if (!wrapRef.current) return
    const el = wrapRef.current
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const cr = entry.contentRect
        setSize({ w: Math.max(320, Math.floor(cr.width)) })
      }
    })
    ro.observe(el)
    setSize({ w: Math.max(320, Math.floor(el.clientWidth)) })
    return () => ro.disconnect()
  }, [])

  const emptyState = allCandles.length === 0
  const visibleCount = ZOOM_STEPS[zoom]
  const candles = useMemo(() => {
    if (allCandles.length <= visibleCount) return allCandles
    return allCandles.slice(allCandles.length - visibleCount)
  }, [allCandles, visibleCount])

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
      const offset = allCandles.length - n
      const maSeries: Record<number, (number | null)[]> = {}
      const maLines = MA_PERIODS.map(({ key, color }) => {
        maSeries[key] = computeMA(allCandles, key).slice(offset)
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
    }, [candles, allCandles, size.w, showMA])

  const lastUp = last.c >= last.o
  const lastColor = lastUp ? 'var(--up)' : 'var(--down)'
  const yLast = yOf(last.c)
  const freshness = useMemo(() => dataFreshness(source, allCandles), [source, allCandles])

  const onWheel = (e: React.WheelEvent) => {
    e.preventDefault()
    if (e.deltaY < 0) setZoom((z) => Math.min(ZOOM_STEPS.length - 1, z + 1))
    else setZoom((z) => Math.max(0, z - 1))
  }

  const handleMouseMove = (e: React.MouseEvent<SVGSVGElement>) => {
    if (!wrapRef.current || candles.length === 0) return
    const rect = e.currentTarget.getBoundingClientRect()
    const x = e.clientX - rect.left
    const y = e.clientY - rect.top
    const n = candles.length
    const i = Math.min(n - 1, Math.max(0, Math.floor((x - plotL + cw / 2) / cw)))
    setHoverIdx(i)
    setMousePos({ x, y })
  }

  const handleMouseLeave = () => {
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
          <span className={lastUp ? 'up' : 'down'} style={{ fontWeight: 600, fontSize: 12 }}>
            {emptyState
              ? '—'
              : `${lastUp ? '▲' : '▼'} ${fmt(Math.abs(change))} (${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%)`}
          </span>
          <span
            className={`src-pill ${source === 'live' ? 'live' : source === 'offline' ? 'warn' : 'mock'}`}
          >
            {source === 'live' ? '实时' : source === 'offline' ? '离线' : '模拟'}
          </span>
          {freshness.stale && <span className="src-pill warn">{freshness.text}</span>}
          {loading && <span className="src-pill loading">加载中…</span>}
        </div>
        <div className="kline-controls">
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
            <option value="crypto">加密</option>
            <option value="us_stocks">美股</option>
          </select>
          <div className="zoom-btns" title="滚轮也可缩放">
            <button className="zoom-btn" onClick={() => setZoom((z) => Math.max(0, z - 1))} aria-label="缩小">
              −
            </button>
            <button className="zoom-btn" onClick={() => setZoom((z) => Math.min(ZOOM_STEPS.length - 1, z + 1))} aria-label="放大">
              +
            </button>
          </div>
          <div className="period-tabs" role="tablist">
            {PERIODS.map((p) => (
              <button
                key={p}
                role="tab"
                aria-selected={p === period}
                className={`period-tab ${p === period ? 'active' : ''}`}
                onClick={() => setPeriod(p)}
              >
                {p}
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
              <span className="kline-ma-dot" style={{ background: color }} />
              {label}
            </button>
          ))}
        </div>
        <span className="kline-hint">滚轮缩放 · 悬停查看 OHLC 与均线</span>
      </div>

      <div className="kline-svg-wrap" ref={wrapRef} onWheel={onWheel}>
        {loading && (
          <div className="kline-overlay">
            <div className="kline-skeleton" />
          </div>
        )}
        {error && !loading && (
          <div className="kline-overlay kline-overlay-err">
            <div>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>后端连接失败</div>
              <div className="muted" style={{ fontSize: 'var(--fs-12)' }}>
                已降级为模拟数据展示
              </div>
            </div>
          </div>
        )}
        {!loading && allCandles.length === 0 && (
          <div className="kline-overlay">
            <div className="muted" style={{ fontSize: 'var(--fs-13)' }}>
              暂无 K 线数据
            </div>
          </div>
        )}
        <svg
          className="kline-svg"
          viewBox={`0 0 ${W} ${H}`}
          preserveAspectRatio="xMidYMid meet"
          role="img"
          aria-label="K线图，可滚轮缩放"
          style={{ opacity: loading ? 0.3 : 1, transition: 'opacity 200ms ease' }}
          onMouseMove={handleMouseMove}
          onMouseLeave={handleMouseLeave}
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
                  <span style={{ color }}>{label}</span>
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
          <span className="k">可见K线</span>
          <span className="v mono">
            {visibleCount}/{allCandles.length}
          </span>
        </div>
        {error && (
          <div className="item" style={{ minWidth: '100%' }}>
            <span className="k" style={{ color: 'var(--down-ink)' }}>
              后端连接失败，已降级为模拟数据
            </span>
          </div>
        )}
      </div>
    </div>
  )
}
