import { useEffect, useMemo, useState } from 'react'
import { ArrowRight, BrainCircuit, CheckCircle2, CircleDashed, Code2, Database, GitBranch, ShieldAlert, TimerReset } from 'lucide-react'
import type { FactorAiReviewResp, FactorEvaluation, FactorResearchResp } from '../api/types'
import { api } from '../api/client'
import s from './FactorEvidenceWorkbench.module.css'

type Props = {
  result: FactorResearchResp
  aiReview: FactorAiReviewResp | null
}

function statusLabel(status: string): string {
  return ({ usable: '统计可用', watch: '需复核', reject: '已拒绝' } as Record<string, string>)[status] ?? status
}

function stateForFactor(factor: FactorEvaluation, aiReview: FactorAiReviewResp | null): string {
  const review = aiReview?.review?.factor_reviews.find((item) => item.factor_key === factor.key)
  if (review?.statistical_status) return `${statusLabel(factor.status)} · AI ${review.statistical_status}`
  return statusLabel(factor.status)
}

export function FactorEvidenceWorkbench({ result, aiReview }: Props) {
  const candidates = useMemo(() => [...result.factors].sort((left, right) => right.score - left.score), [result.factors])
  const [selectedKey, setSelectedKey] = useState(candidates[0]?.key ?? '')
  const [lineage, setLineage] = useState<Awaited<ReturnType<typeof api.factorLineage>> | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const selected = candidates.find((factor) => factor.key === selectedKey) ?? candidates[0]

  useEffect(() => {
    if (!selected) return
    setSelectedKey(selected.key)
    let active = true
    setLoading(true)
    setError('')
    void api.factorLineage(selected.key, selected.formula_version, result.market).then((response) => {
      if (active) setLineage(response)
    }).catch((reason) => {
      if (active) setError(reason instanceof Error ? reason.message : '证据链读取失败')
    }).finally(() => {
      if (active) setLoading(false)
    })
    return () => { active = false }
  }, [result.market, selected?.key, selected?.formula_version])

  if (!selected) return null
  const trace = lineage?.trace
  const evidence = [
    { label: 'AI 假设', icon: BrainCircuit, count: trace?.ai_hypothesis.length ?? 0, tone: 'ai' },
    { label: 'DSL 定义', icon: Code2, count: trace ? 1 : 0, tone: 'dsl' },
    { label: '数据验证', icon: Database, count: trace?.data_validation.length ?? 0, tone: 'data' },
    { label: '统计实验', icon: GitBranch, count: trace?.experiments.length ?? 0, tone: 'stats' },
    { label: '组合决策', icon: ArrowRight, count: trace?.portfolio_decisions.length ?? 0, tone: 'portfolio' },
    { label: '模拟运行', icon: TimerReset, count: trace?.simulation.length ?? 0, tone: 'simulation' },
  ]

  return (
    <section className={s.panel} aria-label="因子证据工作台">
      <header className={s.header}>
        <div><span>05 / EVIDENCE ROUTE</span><h2>因子证据工作台</h2></div>
        <div className={s.headerState} data-ready={lineage?.evidence_complete === true}>
          {lineage?.evidence_complete ? <CheckCircle2 size={16} /> : <CircleDashed size={16} />}
          <span>{lineage?.evidence_complete ? '证据链完整' : '证据链仍在补齐'}</span>
        </div>
      </header>

      <div className={s.body}>
        <aside className={s.factorRail} aria-label="候选因子列表">
          {candidates.map((factor) => (
            <button key={factor.key} type="button" className={s.factorItem} data-active={factor.key === selected.key} onClick={() => setSelectedKey(factor.key)}>
              <span><strong>{factor.label}</strong><small>{factor.key}</small></span>
              <em data-status={factor.status}>{stateForFactor(factor, aiReview)}</em>
            </button>
          ))}
        </aside>

        <main className={s.detail} aria-busy={loading}>
          <div className={s.detailHead}>
            <div><span>SELECTED FACTOR</span><h3>{selected.label}</h3><code>{selected.key}@{selected.formula_version}</code></div>
            <dl>
              <div><dt>探索分数</dt><dd>{selected.score.toFixed(3)}</dd></div>
              <div><dt>研究状态</dt><dd data-status={selected.status}>{statusLabel(selected.status)}</dd></div>
              <div><dt>交易状态</dt><dd>{lineage?.current_state ?? '读取中'}</dd></div>
            </dl>
          </div>

          <div className={s.route} aria-label="证据链路">
            {evidence.map(({ label, icon: Icon, count, tone }) => (
              <div key={label} className={s.routeNode} data-tone={tone}>
                <Icon size={16} /><strong>{label}</strong><b>{count}</b>
              </div>
            ))}
          </div>

          <div className={s.auditGrid}>
            <article><span>经济假设</span><p>{selected.description}</p><small>公式方向：{selected.direction === 'positive' ? '正向' : '反向'} · 假设族：{selected.hypothesis_family ?? '未声明'}</small></article>
            <article><span>DSL / 数据</span><code>{lineage ? JSON.stringify(lineage.definition.ast) : '读取中…'}</code><small>{lineage?.definition.input_fields?.join(' · ') || '未读取输入字段'}</small></article>
            <article><span>窗口稳定性</span><p>{selected.window_pass_rate == null ? '未提供窗口证据' : `通过率 ${(selected.window_pass_rate * 100).toFixed(1)}% · ${selected.window_count ?? 0} 个窗口`}</p><small>最差窗口 IC：{selected.worst_window_ic?.toFixed(3) ?? '—'} · 方向翻转：{selected.direction_flips ?? 0}</small></article>
            <article><span>AI 审阅</span><p>{aiReview?.review?.factor_reviews.find((item) => item.factor_key === selected.key)?.assessment ?? '尚未生成 AI 审阅'}</p><small>{aiReview?.meta?.statistical_conclusions_locked ? '统计结论已锁定，AI 只能提供风险与下一实验' : 'AI 审阅不改变统计状态'}</small></article>
          </div>

          {error && <div className={s.error} role="alert"><ShieldAlert size={16} />{error}</div>}
          {!loading && trace?.simulation.length === 0 && <div className={s.simulationNotice}><TimerReset size={16} /><span>该因子尚未进入模拟交易，统计结果不等于交易验证。</span></div>}
        </main>
      </div>
    </section>
  )
}
