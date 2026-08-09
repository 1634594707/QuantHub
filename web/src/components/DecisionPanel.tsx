import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import type { Decision, Direction } from '../data/types'
import { api } from '../api/client'
import { executeAnalysisTask } from '../api/taskRunner'
import type { DecisionTreeView, DecisionView, FutureTrendView, PaAnalyzeResp } from '../api/types'
import '../styles/strategy-module.css'

const PA_TIMEOUT_MS = 90_000

const EMPTY_DECISION: Decision = {
  direction: 'hold',
  trend: '—',
  cycle: '—',
  phase: '—',
  confidence: 0,
  dualConfidence: { stage1: 0, stage2: 0 },
  nextBar: { predictable: false, top3: [], remainder: 1 },
  nextCycle: { predictable: false, top3: [], remainder: 1 },
  stop: 0,
  target: 0,
  riskReward: 0,
  winRate: 0,
  reason: '运行 PA 分析后显示诊断依据与交易计划。',
  gateTrace: [],
}

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

function mapNextBar(bar: FutureTrendView['next_bar'] | undefined): Decision['nextBar'] {
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

function mapNextCycle(cyc: FutureTrendView['next_cycle'] | undefined): Decision['nextCycle'] {
  if (!cyc) {
    return { predictable: false, top3: [], remainder: 1 }
  }
  const top3 = (cyc.top3 || []).map((t) => ({ label: t.label, prob: t.pct / 100 }))
  const restSum = (cyc.rest || []).reduce((acc, r) => acc + r.pct / 100, 0)
  return { predictable: !cyc.unpredictable, top3, remainder: restSum }
}

function mapGateTrace(path: DecisionTreeView['path'] | undefined): Decision['gateTrace'] {
  if (!path || path.length === 0) {
    return []
  }
  return path.slice(0, 6).map((p) => ({
    gate: p.question || p.node || '—',
    result: p.answer || '—',
  }))
}

function mapPaToDecision(resp: PaAnalyzeResp | null): Decision {
  if (!resp || !resp.ok || !resp.decision) {
    return EMPTY_DECISION
  }
  const v: DecisionView = resp.decision
  const direction = parseDirection(v.direction)
  return {
    direction,
    trend: v.trend || EMPTY_DECISION.trend,
    cycle: v.cycle || EMPTY_DECISION.cycle,
    phase: v.phase || EMPTY_DECISION.phase,
    confidence: v.trade_confidence?.score ?? EMPTY_DECISION.confidence,
    dualConfidence: {
      stage1: v.diagnosis_confidence?.score ?? EMPTY_DECISION.dualConfidence.stage1,
      stage2: v.trade_confidence?.score ?? EMPTY_DECISION.dualConfidence.stage2,
    },
    nextBar: mapNextBar(resp.future?.next_bar),
    nextCycle: mapNextCycle(resp.future?.next_cycle),
    stop: v.sl ?? EMPTY_DECISION.stop,
    target: v.tp1 ?? EMPTY_DECISION.target,
    riskReward: v.risk_reward ? parseRatioText(v.risk_reward.ratio_text) : EMPTY_DECISION.riskReward,
    winRate: parsePct(v.estimated_win_rate) || EMPTY_DECISION.winRate,
    reason: v.reasoning || EMPTY_DECISION.reason,
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
        <div
          className="d-prob-fill"
          style={{
            '--w': `${(prob * 100).toFixed(0)}%`,
            '--c': color,
          } as CSSProperties}
        />
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
  market,
  requestKey = 0,
  researchRunId,
  onResearchRunId,
  initialData,
}: {
  symbol?: string
  timeframe?: string
  market?: string
  requestKey?: number
  researchRunId?: string | null
  onResearchRunId?: (runId: string) => void
  initialData?: PaAnalyzeResp | null
}) {
  const [data, setData] = useState<PaAnalyzeResp | null>(initialData ?? null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [publishing, setPublishing] = useState(false)
  const [publishMessage, setPublishMessage] = useState('')
  const controllerRef = useRef<AbortController | null>(null)
  const lastRequestKey = useRef(0)
  const timedOutRef = useRef(false)
  const taskIdRef = useRef<string | null>(null)

  const runAnalysis = useCallback(async () => {
    const normalized = symbol.trim()
    if (!normalized || loading) return

    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller
    timedOutRef.current = false
    setLoading(true)
    setError(null)
    const timer = window.setTimeout(() => {
      timedOutRef.current = true
      controller.abort()
    }, PA_TIMEOUT_MS)

    try {
      const response = await executeAnalysisTask<PaAnalyzeResp>({
        kind: 'pa',
        symbol: normalized,
        timeframe,
        market: market || 'a_shares',
        payload: { research_run_id: researchRunId ?? undefined },
        timeoutSeconds: 90,
      }, {
        signal: controller.signal,
        onTask: (task) => { taskIdRef.current = task.id },
      })
      if (!response.ok) throw new Error(response.error || 'PA 分析未返回完整结果')
      setData(response)
      if (response.research_run_id) onResearchRunId?.(response.research_run_id)
    } catch (err) {
      if (controller.signal.aborted) {
        setError(timedOutRef.current ? '分析超过 90 秒，已自动结束' : '本次分析已取消')
      } else {
        setError(err instanceof Error ? err.message : String(err))
      }
    } finally {
      window.clearTimeout(timer)
      if (controllerRef.current === controller) controllerRef.current = null
      taskIdRef.current = null
      setLoading(false)
    }
  }, [loading, market, onResearchRunId, researchRunId, symbol, timeframe])

  const cancelAnalysis = useCallback(() => {
    timedOutRef.current = false
    if (taskIdRef.current) void api.cancelAnalysisTask(taskIdRef.current)
    controllerRef.current?.abort()
  }, [])

  useEffect(() => {
    if (requestKey <= 0 || requestKey === lastRequestKey.current) return
    lastRequestKey.current = requestKey
    void runAnalysis()
  }, [requestKey, runAnalysis])

  useEffect(() => () => controllerRef.current?.abort(), [])

  useEffect(() => {
    setData(initialData ?? null)
    setError(null)
  }, [initialData, symbol, timeframe])

  const d = useMemo(() => mapPaToDecision(data), [data])
  const isReal = Boolean(data?.ok && data.decision)
  const dir = DIR_LABEL[d.direction]
  const [tab, setTab] = useState<'overview' | 'deep'>('overview')
  const details = data?.decision
  const validationReports = Object.values(data?.meta?.validation ?? {})
  const validationPassed = validationReports.every((report) => report.valid)
  const validationWarnings = validationReports
    .flatMap((report) => report.issues)
    .filter((issue) => issue.severity === 'warning')
  const validationRetries = data?.meta?.validation_retries ?? 0
  const priceText = (value: number | null | undefined) => value && value > 0 ? value : '—'

  const publishSignal = useCallback(async () => {
    if (!data?.ok || !data.decision || !validationPassed) return
    setPublishing(true)
    setPublishMessage('')
    try {
      const direction = parseDirection(data.decision.direction)
      const signalDirection = direction === 'long' ? 'buy' : direction === 'short' ? 'sell' : 'hold'
      const probabilities = data.future?.next_bar?.probabilities
      const score = signalDirection === 'buy'
        ? (probabilities?.bullish ?? 50) / 100
        : signalDirection === 'sell'
          ? (probabilities?.bearish ?? 50) / 100
          : (probabilities?.neutral ?? 50) / 100
      const tradeConfidence = data.decision.trade_confidence?.score
      const diagnosisConfidence = data.decision.diagnosis_confidence?.score
      const confidence = typeof tradeConfidence === 'number'
        ? tradeConfidence / 100
        : typeof diagnosisConfidence === 'number'
          ? diagnosisConfidence / 100
          : 0.3
      const runId = data.research_run_id ?? researchRunId ?? null
      const response = await api.publishSignal({
        symbol: data.symbol,
        market: data.market,
        timeframe: data.timeframe,
        direction: signalDirection,
        score: Math.max(0, Math.min(1, score)),
        confidence: Math.max(0, Math.min(1, confidence)),
        source: 'pa_agent',
        tags: ['pa_agent', 'two_stage', 'research'],
        meta: {
          research_run_id: runId,
          order_type: data.decision.order_type,
          entry: data.decision.entry,
          sl: data.decision.sl,
          tp1: data.decision.tp1,
          tp2: data.decision.tp2,
          risk_reward: data.decision.risk_reward,
          reasoning: data.decision.reasoning,
          validation: data.meta?.validation,
        },
      })
      if (runId) {
        await api.addResearchEvidence(runId, {
          kind: 'signal',
          source: 'signals',
          title: `${data.symbol} PA 待审核信号`,
          payload: { signal: response.signal },
        })
      }
      setPublishMessage(response.ok ? '信号已进入信号中心' : '信号发布失败')
    } catch (reason) {
      setPublishMessage(reason instanceof Error ? reason.message : '信号发布失败')
    } finally {
      setPublishing(false)
    }
  }, [data, researchRunId, validationPassed])

  return (
    <div className="card">
      <div className="card-head">
        <div className="card-title">PA 决策面板</div>
        <div className="pa-panel-actions">
          {isReal && (
            <button className="run-btn" onClick={() => void publishSignal()} disabled={publishing || loading || !validationPassed} title={validationPassed ? '生成一条待人工审核的信号' : '输出质量闸门未通过，不能生成信号'}>
              {publishing ? '发布中…' : '生成待审核信号'}
            </button>
          )}
          {loading && <button className="run-btn danger" onClick={cancelAnalysis}>取消</button>}
          <button className="run-btn" onClick={() => void runAnalysis()} disabled={loading} title={`对 ${symbol} 运行 PA 分析`}>
            {loading ? '分析中…' : '运行 PA 分析'}
          </button>
        </div>
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
              <span className="v mono">{d.winRate > 0 ? `${d.winRate}%` : '—'}</span>
            </div>
            <div className="d-verdict-stat">
              <span className="k">盈亏比</span>
              <span className="v mono">{d.riskReward > 0 ? `${d.riskReward}:1` : '—'}</span>
            </div>
          </div>
        </div>

        {/* 标签页 */}
        <div className="d-tabs">
          <button
            type="button"
            className={`d-tab ${tab === 'overview' ? 'active' : ''}`}
            onClick={() => setTab('overview')}
          >
            概览
          </button>
          <button
            type="button"
            className={`d-tab ${tab === 'deep' ? 'active' : ''}`}
            onClick={() => setTab('deep')}
          >
            深度
          </button>
        </div>

        {tab === 'overview' ? (
          <>
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
                  <span className="k">入场</span>
                  <span className="v mono">{priceText(details?.entry)}</span>
                </div>
                <div className="d-plan-arrow">→</div>
                <div className="d-plan-item">
                  <span className="k">止损</span>
                  <span className="v mono down">{priceText(d.stop)}</span>
                </div>
                <div className="d-plan-arrow">→</div>
                <div className="d-plan-item">
                  <span className="k">目标</span>
                  <span className="v mono up">{priceText(d.target)}</span>
                </div>
              </div>
            </div>

            {/* 原因 */}
            <div className="d-reason">{d.reason}</div>
          </>
        ) : (
          <>
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

            <div className="d-section">
              <div className="d-section-title">关键因素与风险</div>
              <div className="d-insight-grid">
                <div>
                  <span className="d-insight-label">关键因素</span>
                  <ul className="d-insight-list">
                    {(details?.key_factors?.length ? details.key_factors : ['暂无关键因素']).map((item) => <li key={item}>{item}</li>)}
                  </ul>
                </div>
                <div>
                  <span className="d-insight-label">观察点</span>
                  <ul className="d-insight-list">
                    {(details?.watch_points?.length ? details.watch_points : ['暂无观察点']).map((item) => <li key={item}>{item}</li>)}
                  </ul>
                </div>
              </div>
              {details?.risk_assessment && <div className="d-reason">{details.risk_assessment}</div>}
            </div>

            {!!validationReports.length && (
              <div className="d-section">
                <div className="d-section-title">输出质量闸门</div>
                <div className="d-quality-grid">
                  {validationReports.map((report) => (
                    <div className="d-quality-row" key={report.stage}>
                      <span>{report.stage === 'stage1' ? '市场诊断' : '交易决策'}</span>
                      <b className={report.valid ? 'passed' : 'failed'}>{report.valid ? '通过' : '阻断'}</b>
                      <small>{report.attempts === 0 ? '程序短路生成' : `${report.attempts} 次模型输出`}</small>
                    </div>
                  ))}
                </div>
                {validationWarnings.length > 0 && (
                  <ul className="d-quality-warnings">
                    {validationWarnings.slice(0, 4).map((issue) => <li key={`${issue.field}:${issue.code}`}>{issue.field} · {issue.message}</li>)}
                  </ul>
                )}
              </div>
            )}
          </>
        )}

        {loading && <div className="run-status work" role="status">正在执行市场诊断与决策评估，最长等待 90 秒…</div>}
        {!loading && error && <div className="run-status err" role="alert">PA 分析失败：{error}</div>}
        {!loading && isReal && (
          <div className={`run-status ${validationPassed ? 'success' : 'err'}`} role="status">
            {validationPassed ? '质量闸门通过' : '质量闸门阻断'} · K线 {data?.meta?.kline_count ?? '—'} 根 · {validationRetries ? `自动修正 ${validationRetries} 次` : '无需自动修正'}
          </div>
        )}
        {publishMessage && (
          <div className="run-status ok" role="status">
            {publishMessage} · <a href="/signals">打开信号中心</a>
          </div>
        )}
        {!loading && !isReal && !error && (
          <div className="run-status ok" role="status">等待运行 · 不会自动请求大模型</div>
        )}
      </div>
    </div>
  )
}
