import { useEffect, useMemo, useState } from 'react'
import {
  CheckCircle2,
  Database,
  Fingerprint,
  FlaskConical,
  LockKeyhole,
  RefreshCw,
  ShieldAlert,
} from 'lucide-react'
import { api } from '../api/client'
import type {
  FactorConfirmationSetOpening,
  FactorExperimentRecord,
  FactorResearchPlanRecord,
} from '../api/types'
import { Button } from '../components/ui/Button/Button'
import { EmptyState } from '../components/ui/EmptyState/EmptyState'
import { Input } from '../components/ui/Input/Input'
import { Select } from '../components/ui/Select/Select'
import s from './FactorConfirmationPanel.module.css'

function formatTime(value: number): string {
  return new Date(value * 1000).toLocaleString('zh-CN', { hour12: false })
}

function shortHash(value: string): string {
  return `${value.slice(0, 10)}…${value.slice(-8)}`
}

export function FactorConfirmationPanel() {
  const [plans, setPlans] = useState<FactorResearchPlanRecord[]>([])
  const [selectedPlanId, setSelectedPlanId] = useState('')
  const [experiments, setExperiments] = useState<FactorExperimentRecord[]>([])
  const [selectedExperimentId, setSelectedExperimentId] = useState('')
  const [opening, setOpening] = useState<FactorConfirmationSetOpening | null>(null)
  const [openedBy, setOpenedBy] = useState('local-researcher')
  const [acknowledged, setAcknowledged] = useState(false)
  const [confirmationPhrase, setConfirmationPhrase] = useState('')
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [openingNow, setOpeningNow] = useState(false)
  const [error, setError] = useState('')

  const selectedPlan = plans.find((plan) => plan.id === selectedPlanId) ?? null
  const dataSplit = selectedPlan?.budget.data_split ?? null
  const eligibleExperiments = useMemo(() => experiments.filter((experiment) => (
    experiment.status === 'succeeded'
    && experiment.pre_registration.confirmation_set_openings === 1
  )), [experiments])

  async function loadPlans() {
    setLoading(true)
    setError('')
    try {
      const response = await api.factorResearchPlans()
      setPlans(response.plans)
      setSelectedPlanId((current) => {
        if (response.plans.some((plan) => plan.id === current)) return current
        return response.plans.find((plan) => plan.budget.data_split)?.id ?? response.plans[0]?.id ?? ''
      })
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '研究计划读取失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadPlans()
  }, [])

  useEffect(() => {
    if (!selectedPlanId) {
      setExperiments([])
      setOpening(null)
      return
    }
    let active = true
    setDetailLoading(true)
    setError('')
    Promise.all([
      api.factorExperiments(selectedPlanId),
      api.factorConfirmationSet(selectedPlanId),
    ]).then(([experimentResponse, openingResponse]) => {
      if (!active) return
      setExperiments(experimentResponse.experiments)
      setOpening(openingResponse.opening)
      const eligible = experimentResponse.experiments.filter((experiment) => (
        experiment.status === 'succeeded'
        && experiment.pre_registration.confirmation_set_openings === 1
      ))
      setSelectedExperimentId((current) => (
        eligible.some((experiment) => experiment.id === current) ? current : eligible[0]?.id ?? ''
      ))
      setAcknowledged(false)
      setConfirmationPhrase('')
    }).catch((reason) => {
      if (active) setError(reason instanceof Error ? reason.message : '确认集审计状态读取失败')
    }).finally(() => {
      if (active) setDetailLoading(false)
    })
    return () => {
      active = false
    }
  }, [selectedPlanId])

  async function openConfirmationSet() {
    if (!selectedPlan || !dataSplit || !selectedExperimentId) return
    setOpeningNow(true)
    setError('')
    try {
      const response = await api.openFactorConfirmationSet(selectedPlan.id, {
        experiment_id: selectedExperimentId,
        confirmation_data_fingerprint: dataSplit.locked_confirmation.data_fingerprint,
        opened_by: openedBy.trim(),
        irreversible_ack: true,
      })
      setOpening(response.opening)
      setPlans((current) => current.map((plan) => plan.id === selectedPlan.id
        ? {
          ...plan,
          usage: plan.usage ? { ...plan.usage, confirmation_set_openings: 1 } : plan.usage,
        }
        : plan))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '锁定确认集开启失败')
    } finally {
      setOpeningNow(false)
    }
  }

  const ready = Boolean(
    selectedPlan
    && dataSplit
    && selectedExperimentId
    && openedBy.trim()
    && acknowledged
    && confirmationPhrase === selectedPlan.id,
  )

  return (
    <section className={s.panel} aria-label="锁定确认集治理">
      <header className={s.header}>
        <div className={s.seal}><LockKeyhole size={22} /></div>
        <div>
          <span>LOCKED EVIDENCE / IRREVERSIBLE EVENT</span>
          <h2>锁定确认集</h2>
          <p>只有预注册实验完成后才能开启一次；开启记录写入不可变审计账本。</p>
        </div>
        <Button type="button" variant="ghost" size="sm" loading={loading} icon={<RefreshCw size={15} />} onClick={() => void loadPlans()}>
          刷新计划
        </Button>
      </header>

      {error && <div className={s.error} role="alert"><ShieldAlert size={17} /><span>{error}</span></div>}

      {!loading && plans.length === 0 ? (
        <EmptyState title="还没有预注册研究计划" desc="先通过研究计划 API 保存三段数据范围、指纹和确认集开启预算。" icon={<Database size={30} />} />
      ) : (
        <div className={s.workspace}>
          <aside className={s.planRail}>
            <label><span>研究计划</span><Select value={selectedPlanId} options={plans.map((plan) => ({ value: plan.id, label: plan.title }))} onChange={(event) => setSelectedPlanId(event.target.value)} /></label>
            {selectedPlan && <div className={s.planMeta}>
              <small>{selectedPlan.target_market}</small>
              <strong>{selectedPlan.id}</strong>
              <dl>
                <div><dt>累计实验</dt><dd>{selectedPlan.usage?.experiments ?? 0}</dd></div>
                <div><dt>开启预算</dt><dd>{selectedPlan.budget.maximum_confirmation_set_openings}</dd></div>
                <div><dt>已开启</dt><dd>{selectedPlan.usage?.confirmation_set_openings ?? 0}</dd></div>
              </dl>
            </div>}
            <div className={s.ruleCard}>
              <ShieldAlert size={16} />
              <p>确认集开启后，本计划将永久禁止创建新实验。任何继续调参必须建立新计划并重新预注册。</p>
            </div>
          </aside>

          <main className={s.evidenceDesk} aria-busy={detailLoading}>
            {!selectedPlan ? null : !dataSplit ? (
              <EmptyState title="该计划没有锁定分区" desc="旧计划仍可查阅，但不能开启确认集；请新建带三段数据指纹的研究计划。" icon={<Fingerprint size={30} />} />
            ) : (
              <>
                <div className={s.partitionTimeline} aria-label="预注册数据分区">
                  {([
                    ['01', '发现集', dataSplit.discovery],
                    ['02', '滚动验证集', dataSplit.rolling_validation],
                    ['03', '锁定确认集', dataSplit.locked_confirmation],
                  ] as const).map(([number, label, partition]) => (
                    <article key={label} data-locked={number === '03'}>
                      <b>{number}</b>
                      <div><strong>{label}</strong><span>{partition.start} → {partition.end}</span><code title={partition.data_fingerprint}>{shortHash(partition.data_fingerprint)}</code></div>
                    </article>
                  ))}
                  <footer>隔离：purge {dataSplit.purge_periods} 期 · embargo {dataSplit.embargo_periods} 期</footer>
                </div>

                {opening ? (
                  <article className={s.openedLedger}>
                    <CheckCircle2 size={24} />
                    <div><span>CONFIRMATION SET OPENED</span><h3>确认集已开启，计划已冻结</h3><p>开启人 {opening.opened_by} · {formatTime(opening.created_at)}</p></div>
                    <dl>
                      <div><dt>审计记录</dt><dd>{opening.id}</dd></div>
                      <div><dt>成功实验</dt><dd>{opening.experiment_id}</dd></div>
                      <div><dt>数据指纹</dt><dd>{opening.confirmation_data_fingerprint}</dd></div>
                    </dl>
                  </article>
                ) : (
                  <div className={s.openingContract}>
                    <div className={s.contractLead}>
                      <FlaskConical size={20} />
                      <div><span>FINAL GATE</span><h3>签署一次性开启合同</h3><p>系统只列出成功且预注册了 1 次开启权限的实验。</p></div>
                    </div>
                    {eligibleExperiments.length === 0 ? (
                      <div className={s.noExperiment}>没有满足条件的成功实验。先完成预注册实验，再返回此处。</div>
                    ) : (
                      <div className={s.contractFields}>
                        <label><span>成功实验</span><Select value={selectedExperimentId} options={eligibleExperiments.map((experiment) => ({ value: experiment.id, label: `#${experiment.attempt_number} ${experiment.factor_key} · ${experiment.hypothesis}` }))} onChange={(event) => setSelectedExperimentId(event.target.value)} /></label>
                        <label><span>开启人</span><Input value={openedBy} maxLength={120} onChange={(event) => setOpenedBy(event.target.value)} /></label>
                        <label className={s.acknowledgement}><input type="checkbox" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} /><span>我确认这是不可逆研究事件，并理解开启后不能在本计划继续调参。</span></label>
                        <label><span>输入计划 ID 进行最终确认</span><Input variant="mono" value={confirmationPhrase} placeholder={selectedPlan.id} onChange={(event) => setConfirmationPhrase(event.target.value)} /></label>
                        <Button type="button" variant="danger" loading={openingNow} disabled={!ready} icon={<LockKeyhole size={16} />} onClick={() => void openConfirmationSet()}>
                          不可逆地开启确认集
                        </Button>
                      </div>
                    )}
                  </div>
                )}
              </>
            )}
          </main>
        </div>
      )}
    </section>
  )
}
