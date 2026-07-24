import { useMemo } from 'react'
import type { Decision, Direction } from '../data/mock'
import { DECISION } from '../data/mock'
import { api } from '../api/client'
import { useApi } from '../api/useApi'
import type { DecisionView, FutureTrendView, PaAnalyzeResp } from '../api/types'

const DIR_LABEL: Record<Direction, { title: string; sub: string }> = {
  long: { title: '看多 · 建议做多', sub: '趋势向上，风险可控' },
  short: { title: '看空 · 建议做空', sub: '趋势承压，谨慎参与' },
  hold: { title: '观望', sub: '信号不明确，等待确认' },
}

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

function probColor(label: string): string {
  const bullish = ['上涨', '继续上涨', '主升', '突破', '走强', '反弹']
  const bearish = ['下跌', '回调', '见顶', '走弱', '回落', '下跌']
  if (bullish.some((k) => label.includes(k))) return 'var(--up)'
  if (bearish.some((k) => label.includes(k))) return 'var(--down)'
  return 'var(--text-3)'
}

function probBar(label: string, prob: number, i: number) {
  const color = i === 0 ? probColor(label) : 'var(--text-3)'
  return (
    <div key={label} className="d-prob-row">
      <span className="d-prob-label">{label}</span>
      <div className="d-prob-track">
        <div className="d-prob-fill" style={{ width: `${(prob * 100).toFixed(0)}%`, background: color }} />
      </div>
      <span className="d-prob-value mono">{(prob * 100).toFixed(0)}%</span>
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
    <div className="d-prob-card">
      <div className="d-prob-head">
        <span className="d-prob-title">{title}</span>
        <span className={`d-prob-badge ${predictable ? 'on' : 'off'}`}>
          {predictable ? '可预测' : '不可预测'}
        </span>
      </div>
      <div className="d-prob-list">
        {top3.map((t, i) => probBar(t.label, t.prob, i))}
        {remainder != null && remainder > 0.001 && (
          <div className="d-prob-row">
            <span className="d-prob-label muted">其他</span>
            <div className="d-prob-track" />
            <span className="d-prob-value mono muted">{(remainder * 100).toFixed(0)}%</span>
          </div>
        )}
      </div>
    </div>
  )
}

export default function DecisionPanel({
  symbol = '600519',
  timeframe = '1h',
}: {
  symbol?: string
  timeframe?: string
}) {
  const { data, loading, error, refetch } = useApi(() => api.analyzePa(symbol, timeframe), [symbol, timeframe])
  const d = useMemo(() => mapPaToDecision(data), [data])
  const isReal = !!data?.ok
  const dir = DIR_LABEL[d.direction]

  return (
    <div className="card">
      <div className="card-head">
        <div className="card-title">PA 决策面板</div>
        <button className="run-btn" onClick={refetch} disabled={loading} title={`对 ${symbol} 运行 PA 分析`}>
          {loading ? '分析中…' : '运行 PA 分析'}
        </button>
      </div>
      <div className="decision">
        {/* 大方向牌 */}
        <div className={`d-verdict ${d.direction}`}>
          <div className="d-verdict-main">
            <span className={`dir-pill ${d.direction}`}>{dir.title}</span>
            <div className="d-verdict-sub">{dir.sub}</div>
          </div>
          <div className="d-verdict-stats">
            <div className="d-verdict-stat">
              <span className="k">胜率</span>
              <span className="v mono">{d.winRate}%</span>
            </div>
            <div className="d-verdict-stat">
              <span className="k">盈亏比</span>
              <span className="v mono">{d.riskReward}:1</span>
            </div>
          </div>
        </div>

        {/* 趋势诊断 */}
        <div className="d-section">
          <div className="d-section-title">趋势诊断</div>
          <div className="d-metrics">
            <div className="d-metric">
              <span className="k">趋势</span>
              <span className="v">{d.trend}</span>
            </div>
            <div className="d-metric">
              <span className="k">周期</span>
              <span className="v">{d.cycle}</span>
            </div>
            <div className="d-metric">
              <span className="k">阶段</span>
              <span className="v">{d.phase}</span>
            </div>
            <div className="d-metric">
              <span className="k">双阶段置信</span>
              <span className="v mono">{d.dualConfidence.stage1}% / {d.dualConfidence.stage2}%</span>
            </div>
          </div>
        </div>

        {/* 交易计划 */}
        <div className="d-section">
          <div className="d-section-title">交易计划</div>
          <div className="d-plan">
            <div className="d-plan-item">
              <span className="k">止损</span>
              <span className="v mono down">{d.stop}</span>
            </div>
            <div className="d-plan-arrow">→</div>
            <div className="d-plan-item">
              <span className="k">目标</span>
              <span className="v mono up">{d.target}</span>
            </div>
          </div>
        </div>

        {/* 未来概率 */}
        <div className="d-section">
          <div className="d-section-title">未来走势概率</div>
          <div className="d-probs">
            <FutureBox title="下一根 K 线" {...d.nextBar} />
            <FutureBox title="下一周期" {...d.nextCycle} />
          </div>
        </div>

        {/* 决策门路径 */}
        <div className="d-section">
          <div className="d-section-title">决策门路径</div>
          <div className="d-trace">
            {d.gateTrace.map((g, idx) => (
              <div className="d-trace-step" key={idx}>
                <div className="d-trace-dot" />
                {idx < d.gateTrace.length - 1 && <div className="d-trace-line" />}
                <div className="d-trace-body">
                  <span className="gate">{g.gate}</span>
                  <span
                    className={`res ${
                      g.result === '通过' ? 'up' : g.result === '边缘' ? 'warn' : g.result === '不通过' ? 'down' : ''
                    }`}
                  >
                    {g.result}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* 原因 */}
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
