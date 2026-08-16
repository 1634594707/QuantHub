import { useMemo, useState } from 'react'
import { Bot, Check, CircleAlert, FileCheck2, List, ShieldCheck, TrendingUp, WalletCards } from 'lucide-react'
import type { FactorFactoryRunResponse } from '../api/types'
import { Badge, Button, Field, Input } from '../components/ui'
import s from './FactorFactoryWorkflow.module.css'

function pct(value: unknown, digits = 2) {
  return typeof value === 'number' && Number.isFinite(value) ? `${(value * 100).toFixed(digits)}%` : '—'
}

function num(value: unknown, digits = 2) {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '—'
}

const GATE_LABELS: Record<string, string> = {
  minimum_observation_days: '观察自然日',
  minimum_rebalances: '有效再平衡',
  positive_after_cost_return: '成本后收益',
  risk_adjusted_excess: '风险调整超额',
  random_distribution: '随机策略分位',
  not_leverage_driven: '非高敞口驱动',
  drawdown_within_limit: '回撤上限',
  freshness: '数据新鲜度',
  reconciliation: '账实对账',
  kill_switch: 'Kill Switch',
  fill_and_capacity: '成交与容量',
  risk_limits: '风险上限',
  replay_reconciled: '账本回放',
  regime_stability: '状态稳定性',
}

type EquityPoint = { t?: string; equity?: number }

function normalizedEquityPath(points: EquityPoint[]) {
  const values = points.map((point) => Number(point.equity)).filter(Number.isFinite)
  if (values.length < 2 || values[0] === 0) return ''
  const normalized = values.map((value) => value / values[0])
  const min = Math.min(...normalized)
  const max = Math.max(...normalized)
  const range = Math.max(max - min, 1e-9)
  return normalized.map((value, index) => {
    const x = index / (normalized.length - 1) * 100
    const y = 42 - (value - min) / range * 36
    return `${index === 0 ? 'M' : 'L'}${x.toFixed(2)},${y.toFixed(2)}`
  }).join(' ')
}

type Props = {
  run: FactorFactoryRunResponse
  busy: string
  onReview: () => Promise<void>
  onRequest: () => Promise<void>
  onApprove: (payload: {
    actor: string
    maximum_capital: number
    maximum_exposure: number
    maximum_loss: number
    valid_until: string
  }) => Promise<void>
}

export function FactorCohortPanel({ run, busy, onReview, onRequest, onApprove }: Props) {
  const cohort = run.cohort
  const [ledgerKey, setLedgerKey] = useState('')
  const [workspaceView, setWorkspaceView] = useState<'ranking' | 'detail'>('ranking')
  const [actor, setActor] = useState('risk-owner')
  const [maximumCapital, setMaximumCapital] = useState(1000)
  const [maximumExposure, setMaximumExposure] = useState(0.05)
  const [maximumLoss, setMaximumLoss] = useState(25)
  const [validUntil, setValidUntil] = useState('2026-09-12T00:00:00+08:00')
  const ranking = cohort?.latest_report.ranking ?? []
  const comparison = cohort?.latest_report.comparison ?? {}
  const candidateKey = typeof comparison.candidate_key === 'string' ? comparison.candidate_key : ranking[0]?.member_key ?? ''
  const selectedKey = ledgerKey || candidateKey || ranking[0]?.member_key || ''
  const selectedLedger = cohort?.latest_report.ledgers[selectedKey]
  const selectedMetrics = ranking.find((item) => item.member_key === selectedKey)?.metrics
  const selectedCurve = Array.isArray(selectedLedger?.equity_curve) ? selectedLedger.equity_curve as EquityPoint[] : []
  const candidateCurve = Array.isArray(cohort?.latest_report.ledgers[candidateKey]?.equity_curve)
    ? cohort?.latest_report.ledgers[candidateKey]?.equity_curve as EquityPoint[] : []
  const buyHoldCurve = Array.isArray(cohort?.latest_report.ledgers.buy_hold?.equity_curve)
    ? cohort?.latest_report.ledgers.buy_hold?.equity_curve as EquityPoint[] : []
  const selectedGrid = cohort?.latest_report.grid_risk?.[selectedKey]
  const aiReview = (cohort?.ai_review ?? {}) as Record<string, unknown>
  const effectiveRecommendation = typeof aiReview.effective_recommendation === 'string'
    ? aiReview.effective_recommendation
    : null
  const review = (aiReview.review ?? {}) as Record<string, unknown>
  const remainingRisks = Array.isArray(review.remaining_risks) ? review.remaining_risks.map(String) : []
  const criticalRows = useMemo(() => {
    const keys = new Set([candidateKey, 'cash', 'buy_hold', 'dca', 'fixed_exposure'])
    const topRule = ranking.find((item) => !item.member_key.startsWith('random_') && !keys.has(item.member_key))
    if (topRule) keys.add(topRule.member_key)
    return ranking.filter((item) => item.member_key && keys.has(item.member_key)).slice(0, 7)
  }, [candidateKey, ranking])

  if (!cohort) return <p className={s.cohortEmpty}>因子尚未通过研究门禁，暂未建立同期评估 cohort。</p>

  return <section className={s.cohortPanel} aria-label="同期评估">
    <header className={s.cohortHeader}>
      <div><span>COHORT · {String(cohort.definition.cohort_id ?? '')}</span><h4>同期策略基准与独立账本</h4><p>相同行情和执行模型，成员现金、持仓、订单、费用与风险状态完全隔离。</p></div>
      <Badge variant={cohort.program_gate.passed ? 'up' : 'warn'} dot>{cohort.status}</Badge>
    </header>
    {run.market_data_status && <div className={s.freshnessBar}>
      <span><small>行情事件</small><strong>{new Date(run.market_data_status.event_time).toLocaleString('zh-CN', { hour12: false })}</strong></span>
      <span><small>接收延迟</small><strong>{num(run.market_data_status.age_ms, 0)} ms</strong></span>
      <span><small>K 线状态</small><strong>{run.market_data_status.is_closed ? '已收盘' : '形成中'}</strong></span>
      <span><small>来源</small><strong>{run.market_data_status.source}</strong></span>
      <span><small>质量</small><strong className={run.market_data_status.quality_status === 'stale' ? s.down : s.up}>{run.market_data_status.quality_status}</strong></span>
    </div>}
    <div className={s.cohortSummary}>
      <span><small>候选排名</small><strong>{String(comparison.candidate_rank ?? '—')} / {ranking.length}</strong></span>
      <span><small>随机分位</small><strong>{pct(comparison.random_percentile)}</strong></span>
      <span><small>相对买入持有</small><strong className={Number(comparison.excess_vs_buy_hold ?? 0) >= 0 ? s.up : s.down}>{pct(comparison.excess_vs_buy_hold)}</strong></span>
      <span><small>相对网格中位数</small><strong className={Number(comparison.excess_vs_grid_median ?? 0) >= 0 ? s.up : s.down}>{pct(comparison.excess_vs_grid_median)}</strong></span>
      <span><small>市场状态</small><strong>{comparison.market_tailwind ? '市场顺风' : '无普遍顺风'}</strong></span>
    </div>
    <div className={s.cohortWorkspace}>
      <div className={s.cohortWorkspaceTabs} role="tablist" aria-label="同期评估视图">
        <button type="button" role="tab" aria-selected={workspaceView === 'ranking'} onClick={() => setWorkspaceView('ranking')}><List size={15} />关键基准</button>
        <button type="button" role="tab" aria-selected={workspaceView === 'detail'} onClick={() => setWorkspaceView('detail')}><WalletCards size={15} />账本详情</button>
      </div>
      {workspaceView === 'ranking' ? <section className={s.benchmarkRanking}>
        <header><strong>关键基准</strong><span>默认隐藏随机种子明细；选择成员后进入详情</span></header>
        <div className={s.benchmarkHead}><span>成员</span><span>收益</span><span>Sharpe</span><span>回撤</span></div>
        {criticalRows.map((item) => <button type="button" key={item.member_key} aria-pressed={item.member_key === selectedKey} onClick={() => { setLedgerKey(item.member_key); setWorkspaceView('detail') }}>
          <span><strong>{item.member_key === candidateKey ? '候选因子' : item.member_key}</strong><small>{item.member_key}</small></span>
          <span className={Number(item.metrics.after_cost_return) >= 0 ? s.up : s.down}>{pct(item.metrics.after_cost_return)}</span>
          <span>{num(item.metrics.sharpe)}</span>
          <span>{pct(item.metrics.max_drawdown)}</span>
        </button>)}
      </section> : <section className={s.ledgerDetail}>
        <header><WalletCards size={16} /><strong>{selectedKey || '独立账本'}</strong></header>
        <div className={s.equityOverlay} aria-label="归一化权益曲线叠加">
          <div><TrendingUp size={15} /><strong>归一化权益</strong><span><i />候选</span><span><i />买入持有</span>{selectedKey !== candidateKey && selectedKey !== 'buy_hold' ? <span><i />当前账本</span> : null}</div>
          <svg viewBox="0 0 100 48" role="img" aria-label="候选、买入持有与当前账本权益曲线">
            <path className={s.equityCandidate} d={normalizedEquityPath(candidateCurve)} />
            <path className={s.equityBenchmark} d={normalizedEquityPath(buyHoldCurve)} />
            {selectedKey !== candidateKey && selectedKey !== 'buy_hold' ? <path className={s.equitySelected} d={normalizedEquityPath(selectedCurve)} /> : null}
          </svg>
        </div>
        <dl>
          <div><dt>期末权益</dt><dd>{num(selectedMetrics?.final_equity, 0)}</dd></div>
          <div><dt>成本后收益</dt><dd>{pct(selectedMetrics?.after_cost_return)}</dd></div>
          <div><dt>资金占用</dt><dd>{pct(selectedMetrics?.capital_utilization)}</dd></div>
          <div><dt>换手</dt><dd>{num(selectedMetrics?.turnover)}</dd></div>
          <div><dt>成交次数</dt><dd>{num(selectedMetrics?.trade_count, 0)}</dd></div>
          <div><dt>手续费</dt><dd>{num(selectedMetrics?.fees)}</dd></div>
          <div><dt>滑点成本</dt><dd>{num(selectedMetrics?.slippage_cost)}</dd></div>
          <div><dt>资金费率</dt><dd>{num(selectedMetrics?.funding_pnl)}</dd></div>
        </dl>
        {selectedGrid ? <div className={s.gridRiskDetail}>
          <header><strong>网格预注册风险</strong><Badge variant={selectedGrid.outside_range ? 'warn' : 'neutral'}>{selectedGrid.outside_range ? '区间外' : '区间内'}</Badge></header>
          <dl>
            <div><dt>区间</dt><dd>{num(selectedGrid.range.lower)} – {num(selectedGrid.range.upper)}</dd></div>
            <div><dt>层数</dt><dd>{selectedGrid.levels}</dd></div>
            <div><dt>库存</dt><dd>{num(selectedGrid.inventory_quantity, 4)}</dd></div>
            <div><dt>库存风险</dt><dd>{pct(selectedGrid.inventory_risk)}</dd></div>
            <div><dt>资金占用</dt><dd>{pct(selectedGrid.capital_utilization)}</dd></div>
            <div><dt>区间外损失</dt><dd>{num(selectedGrid.outside_range_loss)}</dd></div>
          </dl>
        </div> : null}
        <p>订单 {Array.isArray(selectedLedger?.orders) ? selectedLedger.orders.length : 0} · 成交 {Array.isArray(selectedLedger?.executions) ? selectedLedger.executions.length : 0} · 风险事件 {Array.isArray(selectedLedger?.risk_events) ? selectedLedger.risk_events.length : 0}</p>
      </section>}
    </div>
    <section className={s.admissionPanel}>
      <header><ShieldCheck size={16} /><strong>小额实盘准入</strong><Badge variant={cohort.program_gate.passed ? 'up' : 'warn'}>{cohort.program_gate.passed ? '程序门禁通过' : '继续观察'}</Badge></header>
      <div className={s.gateMatrix}>{Object.entries(cohort.program_gate.checks).map(([key, passed]) => <span className={passed ? s.alphaCheckPass : s.alphaCheckFail} key={key}>{passed ? <Check size={13} /> : <CircleAlert size={13} />}<b>{GATE_LABELS[key] ?? key}</b></span>)}</div>
      <div className={s.admissionEvidence}>
        <span><small>随机分位</small><strong>{pct(comparison.random_percentile)}</strong></span>
        <span><small>失败门禁</small><strong>{cohort.program_gate.violations.length ? cohort.program_gate.violations.map((key) => GATE_LABELS[key] ?? key).join('、') : '无'}</strong></span>
        <span><small>AI 剩余风险</small><strong>{remainingRisks.length ? remainingRisks.join('、') : '尚未评审'}</strong></span>
        <span><small>审批绑定</small><strong>{cohort.manual_approval_validity ? (cohort.manual_approval_validity.valid ? '有效' : `已失效：${cohort.manual_approval_validity.reasons.join('、')}`) : '未审批'}</strong></span>
      </div>
      <div className={s.cohortActions}>
        <Button variant="secondary" size="sm" loading={busy === 'cohort-review'} onClick={() => void onReview()} icon={<Bot size={15} />}>AI 证据评审</Button>
        <Button variant="secondary" size="sm" loading={busy === 'live-request'} disabled={!cohort.program_gate.passed || effectiveRecommendation !== 'request_small_live'} onClick={() => void onRequest()} icon={<FileCheck2 size={15} />}>提交人工审批</Button>
        <span>AI 建议：{effectiveRecommendation ?? '尚未评审'} · 实盘开关保持关闭</span>
      </div>
      {cohort.status === 'live_requested' && <div className={s.approvalForm}>
        <Field label="审批人"><Input value={actor} onChange={(event) => setActor(event.target.value)} /></Field>
        <Field label="最大资金"><Input type="number" min={1} value={maximumCapital} onChange={(event) => setMaximumCapital(Number(event.target.value))} /></Field>
        <Field label="最大敞口"><Input type="number" min={0.01} max={1} step={0.01} value={maximumExposure} onChange={(event) => setMaximumExposure(Number(event.target.value))} /></Field>
        <Field label="最大损失"><Input type="number" min={1} value={maximumLoss} onChange={(event) => setMaximumLoss(Number(event.target.value))} /></Field>
        <Field label="有效期"><Input value={validUntil} onChange={(event) => setValidUntil(event.target.value)} /></Field>
        <Button variant="primary" size="sm" loading={busy === 'manual-approval'} onClick={() => void onApprove({ actor, maximum_capital: maximumCapital, maximum_exposure: maximumExposure, maximum_loss: maximumLoss, valid_until: validUntil })} icon={<ShieldCheck size={15} />}>锁定审批配置</Button>
      </div>}
    </section>
  </section>
}
