import type { SignalResp } from '../api/types'
import { dirBucket } from '../lib/signal-utils'
import s from './SignalViz.module.css'

/**
 * 方向占比环图：用 CSS conic-gradient 绘制做多/做空/观望三段，
 * 中心显示信号总数，右侧为图例。零依赖、暗亮主题自适应。
 * 注意：方向色恒定语义（绿涨/红跌/灰观望），不因板块改变，保证可读性。
 */
export function DirectionDonut({ signals }: { signals: SignalResp[] }) {
  if (signals.length === 0) return null

  const buy = signals.filter((s) => dirBucket(s.direction) === 'buy').length
  const sell = signals.filter((s) => dirBucket(s.direction) === 'sell').length
  const hold = signals.length - buy - sell
  const total = signals.length

  const buyPct = (buy / total) * 100
  const sellPct = (sell / total) * 100
  const grad = `conic-gradient(var(--up) 0 ${buyPct}%, var(--down) ${buyPct}% ${
    buyPct + sellPct
  }%, var(--text-3) ${buyPct + sellPct}% 100%)`

  const legend = [
    { label: '做多', cnt: buy, color: 'var(--up)' },
    { label: '做空', cnt: sell, color: 'var(--down)' },
    { label: '观望', cnt: hold, color: 'var(--text-3)' },
  ]

  return (
    <div className={s.visualization}>
      <div className={s.donutWrap}>
        <div
          className={s.donut}
          style={{ background: grad }}
          role="img"
          aria-label={`方向分布：做多 ${buy}，做空 ${sell}，观望 ${hold}`}
        >
          <div className={s.donutCenter}>
            <b>{total}</b>
            <span>信号</span>
          </div>
        </div>
      </div>
      <div className={s.legend}>
        {legend.map((l) => (
          <div className={s.legendItem} key={l.label}>
            <span className={s.legendDot} style={{ background: l.color }} />
            <span>{l.label}</span>
            <span className={s.legendCount}>{l.cnt}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

/**
 * 分数分布柱状图：将 score(0~1) 切成 10 个桶，展示信号得分集中区间。
 */
export function ScoreHistogram({ signals }: { signals: SignalResp[] }) {
  if (signals.length === 0) return null

  const buckets = new Array(10).fill(0)
  signals.forEach((s) => {
    const idx = Math.min(9, Math.max(0, Math.floor(s.score * 10)))
    buckets[idx] += 1
  })
  const max = Math.max(1, ...buckets)

  return (
    <div>
      <div className={s.histogram}>
        {buckets.map((c, i) => (
          <div
            className={s.histogramBar}
            key={i}
            title={`${(i / 10).toFixed(1)}–${((i + 1) / 10).toFixed(1)}：${c} 条`}
          >
            <span className={s.histogramValue}>{c}</span>
            <div className={s.histogramFill} style={{ height: `${(c / max) * 100}%` }} />
          </div>
        ))}
      </div>
      <div className={s.histogramAxis}>
        <span>0</span>
        <span>0.5</span>
        <span>1.0</span>
      </div>
    </div>
  )
}

/**
 * 跨策略来源分布条形图 —— 信号中心专属维度。
 * 同一标的/信号可能来自多个策略，用水平条形对比各来源策略的贡献，
 * 让「全局监控视角」与单策略工作台的 donut/histo 形成明确区隔。
 */
export function SourceBars({ signals }: { signals: SignalResp[] }) {
  if (signals.length === 0) return null

  const map = new Map<string, number>()
  signals.forEach((s) => map.set(s.source, (map.get(s.source) ?? 0) + 1))
  const entries = [...map.entries()].sort((a, b) => b[1] - a[1])
  const max = Math.max(...entries.map((e) => e[1]))

  return (
    <div className={s.sourceBars}>
      <div className={s.sourceTitle}>按来源策略分布</div>
      <div className={s.sourceList}>
        {entries.map(([src, cnt]) => (
          <div className={s.sourceRow} key={src}>
            <span className={s.sourceName} title={src}>
              {src}
            </span>
            <span className={s.sourceTrack}>
              <span className={s.sourceFill} style={{ width: `${(cnt / max) * 100}%` }} />
            </span>
            <span className={s.sourceCount}>{cnt}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
