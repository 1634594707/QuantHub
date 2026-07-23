import { useMemo } from 'react'
import type { Decision, Direction } from '../data/mock'
import { DECISION } from '../data/mock'
import { api } from '../api/client'
import { useApi } from '../api/useApi'
import type { DecisionView, FutureTrendView, PaAnalyzeResp } from '../api/types'

const DIR_LABEL: Record<Direction, string> = { long: '看多 · 做多', short: '看空 · 做空', hold: '观望' }

function parseDirection(raw: string | null | undefined): Direction {
  const s = (raw || '').trim().toLowerCase()
  if (s === '做多' || s === 'long' || s === 'buy' || s === 'bullish') return 'long'
  if (s === '做空' || s === 'short' || s === 'sell' || s === 'bearish') return 'short'
  return 'hold'
}

function parsePct(value: unknown): number {
  if (value == null) return 0
  if (typeof value === 'number') return value
  const s = String(value).replace(/%/g, '').trim()
  const n = parseFloat(s)
  return Number.isFinite(n) ? n : 0
}

function parseRatioText(txt: string | null | undefined): number {
  if (!txt) return 0
  const m = txt.match(/[\d.]+/)
  return m ? parseFloat(m[0]) : 0
}

function mapNextBar(bar: FutureTrendView['next_bar']): Decision['nextBar'] {
  if (!bar) {
    return { predictable: false, top3: [], remainder: 1 }
  }
  const probs = bar.probabilities || { bullish: 0, bearish: 0, neutral: 0 }
  const total = probs.bullish + probs.bearish + probs.neutral
  const predictable = total > 0
  const entries = [
    { label: '上涨', prob: (probs.bullish || 0) / 100 },
    { label: '下跌', prob: (probs.bearish || 0) / 100 },
    { label: '横盘', prob: (probs.neutral || 0) / 100 },
  ].sort((a, b) => b.prob - a.prob)
  const top3 = entries.filter((e) => e.prob > 0)
  const sum = top3.reduce((acc, e) => acc + e.prob, 0)
  return { predictable, top3, remainder: Math.max(0, 1 - sum) }
}

function mapNextCycle(cyc: FutureTrendView['next_cycle']): Decision['nextCycle'] {
  if (!cyc) {
    return { predictable: false, top3: [], remainder: 1 }
  }
  const top3 = (cyc.top3 || []).map((t) => ({ label: t.label, prob: t.pct / 100 }))
  const restSum = (cyc.rest || []).reduce((acc, r) => acc + r.pct / 100, 0)
  return { predictable: !cyc.unpredictable, top3, remainder: restSum }
}

function mapGateTrace(path: PaAnalyzeResp['tree']['path']): Decision['gateTrace'] {
  if (!path || path.length === 0) {
    return DECISION.gateTrace
  }
  return path.slice(0, 6).map((p) => ({
    gate: p.question || p.node || '—',
    result: p.answer || '—',
  }))
}

function mapPaToDecision(resp: PaAnalyzeResp | null): Decision {
  if (!resp || !resp.ok || !resp.decision) {
    return DECISION
  }
  const v: DecisionView = resp.decision
  const direction = parseDirection(v.direction)
  return {
    direction,
    trend: v.trend || DECISION.trend,
    cycle: v.cycle || DECISION.cycle,
    phase: v.phase || DECISION.phase,
    confidence: v.trade_confidence?.score ?? DECISION.confidence,
    dualConfidence: {
      stage1: v.diagnosis_confidence?.score ?? DECISION.dualConfidence.stage1,
      stage2: v.trade_confidence?.score ?? DECISION.dualConfidence.stage2,
    },
    nextBar: mapNextBar(resp.future?.next_bar),
    nextCycle: mapNextCycle(resp.future?.next_cycle),
    stop: v.sl ?? DECISION.stop,
    target: v.tp1 ?? DECISION.target,
    riskReward: v.risk_reward ? parseRatioText(v.risk_reward.ratio_text) : DECISION.riskReward,
    winRate: parsePct(v.estimated_win_rate) || DECISION.winRate,
    reason: v.reasoning || DECISION.reason,
    gateTrace: mapGateTrace(resp.tree?.path),
  }
}

function probBar(label: string, prob: number, i: number) {
  return (
    <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
      <span style={{ width: 68, color: 'var(--text-2)' }}>{label}</span>
      <div style={{ flex: 1, height: 6, borderRadius: 999, background: 'var(--bg-elevated)', overflow: 'hidden' }}>
        <div
          style={{
            width: `${(prob * 100).toFixed(0)}%`,
            height: '100%',
            borderRadius: 999,
            background: i === 0 ? 'var(--accent)' : 'var(--text-3)',
          }}
        />
      </div>
      <span className="mono" style={{ width: 34, textAlign: 'right', fontWeight: 600 }}>
        {(prob * 100).toFixed(0)}%
      </span>
    </div>
  )
}

function FutureBox({
  title,
  predictable,
  top3,
  remainder,
}: {
  title: string
  predictable: boolean
  top3: { label: string; prob: number }[]
  remainder?: number
}) {
  return (
    <div className="d-cell">
      <div className="k" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        {title}
        <span
          style={{
            fontSize: 11,
            padding: '2px 6px',
            borderRadius: 999,
            background: predictable ? 'rgba(22,199,132,0.12)' : 'var(--accent-weak)',
            color: predictable ? 'var(--up-ink)' : 'var(--accent-strong)',
          }}
        >
          {predictable ? '可预测' : '不可预测'}
        </span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 6 }}>
        {top3.map((t, i) => probBar(t.label, t.prob, i))}
        {remainder != null && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
            <span style={{ width: 68, color: 'var(--text-3)' }}>其他</span>
            <span style={{ flex: 1 }} />
            <span className="mono" style={{ width: 34, textAlign: 'right', color: 'var(--text-3)' }}>
              {(remainder * 100).toFixed(0)}%
            </span>
          </div>
        )}
      </div>
    </div>
  )
}

export default function DecisionPanel({ symbol = '600519' }: { symbol?: string }) {
  const { data, loading, error, refetch } = useApi(() => api.analyzePa(symbol, '1h'), [symbol])
  const d = useMemo(() => mapPaToDecision(data), [data])
  const isReal = !!data?.ok

  return (
    <div className="card">
      <div className="card-head">
        <div className="card-title">
          PA 决策面板 <span className="sub">AI · 二阶段推理</span>
        </div>
        <button
          className="run-btn"
          onClick={refetch}
          disabled={loading}
          title={`对 ${symbol} 运行 PA 分析`}
        >
          {loading ? '分析中…' : '运行 PA 分析'}
        </button>
      </div>
      <div className="decision">
        <span className={`dir-pill ${d.direction}`}>{DIR_LABEL[d.direction]}</span>

        <div className="d-grid">
          <div className="d-cell">
            <div className="k">趋势</div>
            <div className="v">{d.trend}</div>
          </div>
          <div className="d-cell">
            <div className="k">周期</div>
            <div className="v">{d.cycle}</div>
          </div>
          <div className="d-cell">
            <div className="k">阶段</div>
            <div className="v">{d.phase}</div>
          </div>
          <div className="d-cell">
            <div className="k">Stage1 / Stage2 置信度</div>
            <div className="v mono">
              {d.dualConfidence.stage1}% / {d.dualConfidence.stage2}%
            </div>
          </div>
          <div className="d-cell">
            <div className="k">止损 / 目标</div>
            <div className="v mono down">
              {d.stop} / <span className="up">{d.target}</span>
            </div>
          </div>
          <div className="d-cell">
            <div className="k">盈亏比 · 胜率</div>
            <div className="v mono">
              {d.riskReward} · {d.winRate}%
            </div>
          </div>
        </div>

        <div className="d-subsection">未来走势概率分布</div>
        <div className="d-future">
          <FutureBox title="下一根 K 线" {...d.nextBar} />
          <FutureBox title="下一周期" {...d.nextCycle} />
        </div>

        <div className="d-subsection">决策门路径</div>
        <div className="d-trace">
          {d.gateTrace.map((g, idx) => (
            <div className="d-trace-row" key={idx}>
              <span className="gate">{g.gate}</span>
              <span className={`res ${g.result === '通过' ? 'up' : g.result === '边缘' ? 'warn' : ''}`}>{g.result}</span>
            </div>
          ))}
        </div>

        <div className="d-reason">{d.reason}</div>

        {!isReal && !loading && (
          <div className={`run-status ${error ? 'err' : 'ok'}`} role="status">
            {error
              ? `⚠ 后端未返回真实决策：${error}（当前显示 mock 数据）`
              : 'ℹ 当前为模拟决策数据，点击「运行 PA 分析」请求真实分析（需配置 DEEPSEEK_API_KEY）'}
          </div>
        )}
      </div>
    </div>
  )
}
