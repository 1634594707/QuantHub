import { useEffect, useMemo, useRef, useState } from 'react'
import { genCandles, type Candle } from '../data/mock'
import { api } from '../api/client'
import { useApi } from '../api/useApi'

// UI 周期 → 后端 interval（A股本地 parquet 仅含 5m/15m/1h；1D/1W 暂无本地数据，回退 1h）
const PERIODS = ['5m', '15m', '1H', '1D', '1W'] as const
type Period = (typeof PERIODS)[number]
const INTERVAL_MAP: Record<Period, string> = {
  '5m': '5m',
  '15m': '15m',
  '1H': '1h',
  '1D': '1h',
  '1W': '1h',
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

function fmt(n: number) {
  return n.toLocaleString('en-US', { maximumFractionDigits: 2 })
}

interface Props {
  symbol?: string
  market?: string
}

export default function KlineCard({ symbol = '600519', market = 'a_shares' }: Props) {
  const [period, setPeriod] = useState<Period>('1H')
  const [zoom, setZoom] = useState(2) // 0..4, 越大可见 K 线越少
  const [size, setSize] = useState({ w: 780 })
  const wrapRef = useRef<HTMLDivElement>(null)

  // ── 真实数据接入：经统一 API 客户端取 K 线，失败/无数据自动降级到模拟 ──
  const { data, loading, error } = useApi(
    () => api.kline(symbol, market, INTERVAL_MAP[period], 240),
    [period, symbol, market],
  )

  const isReal = !!data?.ok && data.candles.length > 0
  const source: 'local' | 'mock' = isReal ? 'local' : 'mock'

  const allCandles = useMemo<Candle[]>(() => {
    if (isReal) return data!.candles
    return genCandles(240, SEEDS[period] ?? 42)
  }, [isReal, data, period])

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

  const visibleCount = ZOOM_STEPS[zoom]
  const candles = useMemo(() => {
    if (allCandles.length <= visibleCount) return allCandles
    return allCandles.slice(allCandles.length - visibleCount)
  }, [allCandles, visibleCount])

  const { wicks, bodies, vols, gridY, gridLabels, last, change, pct, yOf, periodHigh, periodLow, W } =
    useMemo(() => {
      const W = size.w
      const n = candles.length
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
      return { wicks, bodies, vols, gridY, gridLabels, last, change, pct, yOf, periodHigh, periodLow, W }
    }, [candles, size.w])

  const lastUp = last.c >= last.o
  const lastColor = lastUp ? 'var(--up)' : 'var(--down)'
  const yLast = yOf(last.c)

  const onWheel = (e: React.WheelEvent) => {
    e.preventDefault()
    if (e.deltaY < 0) setZoom((z) => Math.min(ZOOM_STEPS.length - 1, z + 1))
    else setZoom((z) => Math.max(0, z - 1))
  }

  return (
    <div className="card">
      <div className="card-head">
        <div className="card-title">
          {symbol}
          <span className="sub mono">{fmt(last.c)}</span>
          <span className={lastUp ? 'up' : 'down'} style={{ fontWeight: 600, fontSize: 12 }}>
            {lastUp ? '▲' : '▼'} {fmt(Math.abs(change))} ({pct >= 0 ? '+' : ''}
            {pct.toFixed(2)}%)
          </span>
          <span className={`src-pill ${source === 'local' ? 'live' : 'mock'}`}>
            {source === 'local' ? '实时' : '模拟'}
          </span>
          {loading && <span className="src-pill loading">加载中…</span>}
        </div>
        <div className="kline-toolbar">
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

      <div className="kline-svg-wrap" ref={wrapRef} onWheel={onWheel}>
        <svg
          className="kline-svg"
          viewBox={`0 0 ${W} ${H}`}
          preserveAspectRatio="xMidYMid meet"
          role="img"
          aria-label="K线图，可滚轮缩放"
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

          {vols}
          {wicks}
          {bodies}

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
      </div>

      <div className="kline-meta">
        <div className="item">
          <span className="k">开</span>
          <span className="v mono">{fmt(candles[0].o)}</span>
        </div>
        <div className="item">
          <span className="k">高</span>
          <span className="v mono up">{fmt(periodHigh)}</span>
        </div>
        <div className="item">
          <span className="k">低</span>
          <span className="v mono down">{fmt(periodLow)}</span>
        </div>
        <div className="item">
          <span className="k">收</span>
          <span className="v mono">{fmt(last.c)}</span>
        </div>
        <div className="item">
          <span className="k">量</span>
          <span className="v mono">{fmt(last.v)}</span>
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
