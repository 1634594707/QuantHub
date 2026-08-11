import { useState } from 'react'
import { RefreshCw, Search } from 'lucide-react'
import { api } from '../api/client'
import type { ContractEnvelope, RiskMode, TradingDashboard, TradingHealth } from '../api/types'
import { useApi } from '../api/useApi'
import { ContractStatusBar } from '../components/contract/ContractStatusBar'
import { WorkspaceHeader } from '../components/WorkspaceHeader/WorkspaceHeader'
import { Badge } from '../components/ui/Badge/Badge'
import { Button } from '../components/ui/Button/Button'
import { ConfirmActionButton } from '../components/ui/ConfirmActionButton/ConfirmActionButton'
import { EmptyState } from '../components/ui/EmptyState/EmptyState'
import { Field } from '../components/ui/Field/Field'
import { Input } from '../components/ui/Input/Input'
import { Panel } from '../components/ui/Panel/Panel'
import { Select } from '../components/ui/Select/Select'
import s from './TradingWorkspacePage.module.css'

/**
 * 账户与风控工作区（M2-06）。
 *
 * 边界（路线图 3.E）：
 *   - 余额、持仓、盈亏、风险模式、对账差异一律来自服务端真实状态，无任何本地兜底数字。
 *   - 停机、只撤单、恢复、对账均为高危操作，必须二次确认并带 demo/live 环境标识。
 */

const RISK_MODES: Array<{ value: RiskMode; label: string; description: string }> = [
  { value: 'normal', label: 'normal（正常交易）', description: '允许新开仓与撤单。存在未解决对账差异时不应恢复。' },
  { value: 'cancel_only', label: 'cancel_only（只撤单）', description: '停止新开仓，仅允许撤销已有订单。' },
  { value: 'halted', label: 'halted（全面停机）', description: '停止一切下单动作，仅保留只读查询。' },
]

const ENVIRONMENT_LABELS: Record<string, string> = {
  shadow: '影子（只读，不下单）',
  demo: 'OKX 模拟盘 demo',
  live: 'OKX 实盘 live',
}

export default function AccountRiskPage() {
  const health = useApi(() => api.tradingHealth(), [], { retry: false, pollInterval: 20000 })
  const dashboard = useApi(() => api.tradingDashboard(), [], { retry: false, pollInterval: 15000 })
  const healthData: TradingHealth | null = health.data?.data ?? null
  const environment = healthData?.environment ?? null
  const configured = Boolean(healthData?.configured)
  const reachable = Boolean(healthData?.reachable)
  const dashboardData: TradingDashboard | null = dashboard.data?.data ?? null
  const openDiffs = dashboardData?.reconciliation_diffs.filter((item) => item.status === 'open') ?? []

  const [accountId, setAccountId] = useState('')
  const [account, setAccount] = useState<ContractEnvelope<Record<string, unknown>> | null>(null)
  const [accountError, setAccountError] = useState('')
  const [accountLoading, setAccountLoading] = useState(false)

  const [reconciliation, setReconciliation] = useState<ContractEnvelope<Record<string, unknown>> | null>(null)
  const [reconciliationError, setReconciliationError] = useState('')

  const [mode, setMode] = useState<RiskMode>('cancel_only')
  const [scope, setScope] = useState('global')
  const [operator, setOperator] = useState('')
  const [reason, setReason] = useState('')
  const [riskResult, setRiskResult] = useState<ContractEnvelope<Record<string, unknown>> | null>(null)
  const [riskError, setRiskError] = useState('')

  const [recovery, setRecovery] = useState<ContractEnvelope<Record<string, unknown>> | null>(null)
  const [recoveryError, setRecoveryError] = useState('')
  const [diffOwner, setDiffOwner] = useState('local-operator')
  const [diffResolution, setDiffResolution] = useState('')
  const [diffDetail, setDiffDetail] = useState<ContractEnvelope<Record<string, unknown>> | null>(null)
  const [diffError, setDiffError] = useState('')

  const channelBlocked = !configured
    ? '未配置 Runner 地址（QH_RUNNER_BASE_URL），账户与风控数据不可读。'
    : !reachable
      ? '交易服务不可达，以下数据无法刷新；页面不会显示任何缓存伪造值。'
      : ''

  const riskFormError = operator.trim().length < 2
    ? '请填写操作者（至少 2 个字符）'
    : reason.trim().length < 3
      ? '请填写变更原因（至少 3 个字符）'
      : ''

  async function loadAccount() {
    if (!accountId.trim()) {
      setAccountError('请填写账户 ID')
      return
    }
    setAccountLoading(true)
    setAccountError('')
    try {
      setAccount(await api.tradingAccount(accountId.trim()))
    } catch (reasonValue) {
      setAccount(null)
      setAccountError(reasonValue instanceof Error ? reasonValue.message : String(reasonValue))
    } finally {
      setAccountLoading(false)
    }
  }

  async function runReconciliation() {
    setReconciliationError('')
    try {
      setReconciliation(await api.tradingReconcile(accountId.trim()))
    } catch (reasonValue) {
      setReconciliation(null)
      setReconciliationError(reasonValue instanceof Error ? reasonValue.message : String(reasonValue))
      throw reasonValue
    }
  }

  async function applyRiskMode() {
    setRiskError('')
    try {
      setRiskResult(await api.tradingSetRiskMode({
        scope: scope.trim() || 'global',
        mode,
        reason: reason.trim(),
        operator: operator.trim(),
      }))
    } catch (reasonValue) {
      setRiskResult(null)
      setRiskError(reasonValue instanceof Error ? reasonValue.message : String(reasonValue))
      throw reasonValue
    }
  }

  async function runRecovery() {
    setRecoveryError('')
    try {
      setRecovery(await api.tradingRecoverOrders())
    } catch (reasonValue) {
      setRecovery(null)
      setRecoveryError(reasonValue instanceof Error ? reasonValue.message : String(reasonValue))
      throw reasonValue
    }
  }

  async function loadDiff(diffId: string) {
    setDiffError('')
    try {
      setDiffDetail(await api.tradingReconciliationDiff(diffId))
    } catch (reasonValue) {
      setDiffError(reasonValue instanceof Error ? reasonValue.message : String(reasonValue))
    }
  }

  async function resolveDiff(diffId: string) {
    setDiffError('')
    try {
      await api.tradingResolveDiff(diffId, {
        owner: diffOwner.trim(),
        resolution: diffResolution.trim(),
      })
      setDiffDetail(null)
      dashboard.refetch()
    } catch (reasonValue) {
      setDiffError(reasonValue instanceof Error ? reasonValue.message : String(reasonValue))
      throw reasonValue
    }
  }

  return (
    <div className={s.page}>
      <WorkspaceHeader
        context="账户风控"
        title="账户与风控"
        description="余额、持仓、风险与对账"
        metrics={[
          {
            label: '环境',
            value: environment
              ? <Badge variant={environment === 'live' ? 'down' : environment === 'demo' ? 'warn' : 'neutral'} dot>
                  {ENVIRONMENT_LABELS[environment] ?? environment}
                </Badge>
              : <Badge variant="neutral" dot>未知</Badge>,
          },
          { label: '通道', value: reachable ? '已连接' : configured ? '不可达' : '未配置' },
        ]}
      />

      <ContractStatusBar envelope={health.data ?? null} transportError={health.error} label="交易服务健康" />

      {channelBlocked ? (
        <div className={s.blocked} role="alert">
          <strong>数据不可用</strong>
          <span>{channelBlocked}</span>
        </div>
      ) : null}

      <Panel
        title="账户快照"
        subtitle="余额、可用资金、持仓与保证金；无数据时显示空状态，不显示占位数字。"
        actions={<Button variant="ghost" size="sm" loading={accountLoading} onClick={loadAccount} disabled={!configured}>读取</Button>}
      >
        <div className={s.lookupRow}>
          <Input
            value={accountId}
            placeholder="账户 ID（与 OKX 子账户映射）"
            onChange={(event) => setAccountId(event.target.value)}
          />
          <ConfirmActionButton
            label="发起对账"
            variant="secondary"
            title={`确认在【${ENVIRONMENT_LABELS[environment ?? ''] ?? '未知环境'}】发起对账`}
            description={`环境：${environment ?? '未知'}\n账户：${accountId || '(未填)'}\n对账会向 OKX 拉取真实持仓与订单进行比对。`}
            confirmLabel="开始对账"
            disabled={!configured || !accountId.trim()}
            onConfirm={runReconciliation}
          />
        </div>
        {accountError ? <p className={s.formError} role="alert">{accountError}</p> : null}
        {account ? (
          <div className={s.receipt}>
            <ContractStatusBar envelope={account} label="账户快照" />
            {account.data ? <pre className={s.json}>{JSON.stringify(account.data, null, 2)}</pre> : null}
          </div>
        ) : (
          <EmptyState variant="no-data" title="尚未读取账户" desc="填写账户 ID 后点击「读取」。" />
        )}

        {reconciliationError ? <p className={s.formError} role="alert">{reconciliationError}</p> : null}
        {reconciliation ? (
          <div className={s.receipt}>
            <ContractStatusBar envelope={reconciliation} label="对账结果" />
            {reconciliation.data ? <pre className={s.json}>{JSON.stringify(reconciliation.data, null, 2)}</pre> : null}
          </div>
        ) : null}
      </Panel>

      <Panel
        title={`对账差异（${openDiffs.length}）`}
        subtitle="只关闭已人工确认来源与影响的差异；关闭动作保留操作者、结论和时间。"
        actions={<Button variant="ghost" size="sm" icon={<RefreshCw size={15} />} onClick={dashboard.refetch} loading={dashboard.loading}>刷新</Button>}
      >
        <div className={s.formGrid}>
          <Field label="处理人" required>
            <Input value={diffOwner} onChange={(event) => setDiffOwner(event.target.value)} />
          </Field>
          <Field label="处理结论" required hint="例如：确认是本人在 OKX Demo 手工创建的现货订单">
            <Input value={diffResolution} onChange={(event) => setDiffResolution(event.target.value)} />
          </Field>
        </div>
        {openDiffs.length ? (
          <div className={s.diffList}>
            {openDiffs.map((diff) => (
              <div key={diff.diff_id} className={s.diffRow}>
                <div>
                  <Badge variant="warn" dot>{diff.kind}</Badge>
                  <strong>{diff.key || '无 client_order_id 的外部订单'}</strong>
                  <small>{diff.account_id} · {new Date(diff.created_at).toLocaleString('zh-CN', { hour12: false })}</small>
                </div>
                <div className={s.diffActions}>
                  <Button variant="ghost" size="sm" icon={<Search size={15} />} onClick={() => loadDiff(diff.diff_id)}>详情</Button>
                  <ConfirmActionButton
                    label="关闭差异"
                    title="确认关闭对账差异"
                    description={`差异：${diff.kind} / ${diff.key || '无 client_order_id'}\n处理人：${diffOwner}\n结论：${diffResolution || '(未填)'}`}
                    confirmLabel="确认关闭"
                    disabled={diffOwner.trim().length < 2 || diffResolution.trim().length < 3}
                    onConfirm={() => resolveDiff(diff.diff_id)}
                  />
                </div>
              </div>
            ))}
          </div>
        ) : <EmptyState variant="no-data" title="没有开放差异" desc="可在确认风险状态后恢复 normal，并继续 Demo 策略测试。" />}
        {diffError ? <p className={s.formError} role="alert">{diffError}</p> : null}
        {diffDetail?.data ? <pre className={s.json}>{JSON.stringify(diffDetail.data, null, 2)}</pre> : null}
      </Panel>

      <Panel
        title="风险模式"
        subtitle="全局或账户级 normal / cancel_only / halted。变更会记录操作者与原因。"
      >
        <div className={s.formGrid}>
          <Field label="作用域" hint="global 表示全局；也可填入账户 ID">
            <Input value={scope} onChange={(event) => setScope(event.target.value)} />
          </Field>
          <Field label="目标模式" required>
            <Select
              value={mode}
              options={RISK_MODES.map((item) => ({ value: item.value, label: item.label }))}
              onChange={(event) => setMode(event.target.value as RiskMode)}
            />
          </Field>
          <Field label="操作者" required>
            <Input value={operator} onChange={(event) => setOperator(event.target.value)} />
          </Field>
          <Field label="变更原因" required>
            <Input value={reason} onChange={(event) => setReason(event.target.value)} />
          </Field>
        </div>
        <p className={s.notional}>{RISK_MODES.find((item) => item.value === mode)?.description}</p>
        {riskFormError ? <p className={s.formError} role="alert">{riskFormError}</p> : null}

        <div className={s.actions}>
          <ConfirmActionButton
            label="应用风险模式"
            title={`确认在【${ENVIRONMENT_LABELS[environment ?? ''] ?? '未知环境'}】变更风险模式`}
            description={[
              `环境：${environment ?? '未知'}`,
              `作用域：${scope || 'global'}`,
              `目标模式：${mode}`,
              `操作者：${operator || '(未填)'}`,
              `原因：${reason || '(未填)'}`,
              mode === 'normal' ? '注意：存在未解决对账差异时不得恢复正常交易。' : '',
            ].filter(Boolean).join('\n')}
            confirmLabel="确认变更"
            disabled={!configured || Boolean(riskFormError)}
            onConfirm={applyRiskMode}
          />
          <ConfirmActionButton
            label="恢复未决订单"
            variant="secondary"
            title={`确认在【${ENVIRONMENT_LABELS[environment ?? ''] ?? '未知环境'}】执行订单恢复`}
            description={`环境：${environment ?? '未知'}\n恢复会重新向 OKX 查询本地处于未决状态的订单并同步真实状态。`}
            confirmLabel="开始恢复"
            disabled={!configured}
            onConfirm={runRecovery}
          />
        </div>

        {riskError ? <p className={s.formError} role="alert">{riskError}</p> : null}
        {riskResult ? (
          <div className={s.receipt}>
            <ContractStatusBar envelope={riskResult} label="风险模式回执" />
            {riskResult.data ? <pre className={s.json}>{JSON.stringify(riskResult.data, null, 2)}</pre> : null}
          </div>
        ) : null}

        {recoveryError ? <p className={s.formError} role="alert">{recoveryError}</p> : null}
        {recovery ? (
          <div className={s.receipt}>
            <ContractStatusBar envelope={recovery} label="订单恢复结果" />
            {recovery.data ? <pre className={s.json}>{JSON.stringify(recovery.data, null, 2)}</pre> : null}
          </div>
        ) : null}
      </Panel>
    </div>
  )
}
