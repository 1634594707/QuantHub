import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type {
  AutomationAuditLog,
  AutomationJob,
  AutomationRun,
} from '../api/types'
import { useApi } from '../api/useApi'
import { AsyncStateBoundary } from '../components/ui/AsyncStateBoundary/AsyncStateBoundary'
import { Button } from '../components/ui/Button/Button'
import { RefreshControl } from '../components/ui/RefreshControl/RefreshControl'
import { Table, type Column } from '../components/ui/Table/Table'
import { WorkspaceHeader } from '../components/WorkspaceHeader/WorkspaceHeader'
import { linkedResultHref, researchRunHref } from '../lib/researchResults'
import s from './OperationsPages.module.css'

type ConsoleTab = 'runs' | 'alerts' | 'audit'

const ACTOR = 'local-user'

function formatTime(value: number | string | null) {
  if (value === null) return '—'
  const date = typeof value === 'number' ? new Date(value * 1000) : new Date(value)
  return Number.isNaN(date.getTime())
    ? String(value)
    : date.toLocaleString('zh-CN', { hour12: false })
}

function runStatusLabel(status: AutomationRun['status']) {
  return {
    queued: '排队中',
    running: '运行中',
    succeeded: '已完成',
    failed: '失败',
  }[status]
}

export default function AutomationPage() {
  const navigate = useNavigate()
  const status = useApi(() => api.automationStatus(), [], { retry: false })
  const jobs = useApi(() => api.automationJobs(), [], { retry: false })
  const runs = useApi(() => api.automationRuns(), [], { retry: false })
  const alerts = useApi(() => api.automationAlerts(), [], { retry: false })
  const audit = useApi(() => api.automationAudit(), [], { retry: false })
  const [cronDrafts, setCronDrafts] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [actionNotice, setActionNotice] = useState<string | null>(null)
  const [tab, setTab] = useState<ConsoleTab>('runs')
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [loadingMoreRuns, setLoadingMoreRuns] = useState(false)
  const [loadingMoreAudit, setLoadingMoreAudit] = useState(false)

  const rows = useMemo(() => jobs.data?.jobs ?? [], [jobs.data])
  const runRows = useMemo(() => runs.data?.runs ?? [], [runs.data])
  const alertRows = useMemo(() => alerts.data?.alerts ?? [], [alerts.data])
  const auditRows = useMemo(() => audit.data?.audit ?? [], [audit.data])

  useEffect(() => {
    setCronDrafts((current) => {
      const next = { ...current }
      rows.forEach((job) => {
        if (!(job.name in next)) next[job.name] = job.cron
      })
      return next
    })
  }, [rows])

  useEffect(() => {
    if (!runRows.some((run) => run.status === 'queued' || run.status === 'running')) return
    const timer = window.setTimeout(() => {
      void runs.refetch()
      void status.refetch()
      void alerts.refetch()
      void audit.refetch()
    }, 1500)
    return () => window.clearTimeout(timer)
  }, [runRows, runs, status, alerts, audit])

  const selectedRun = useMemo(
    () => [...runRows, ...alertRows].find((run) => run.id === selectedRunId) ?? null,
    [runRows, alertRows, selectedRunId],
  )

  function refresh() {
    void status.refetch()
    void jobs.refetch()
    void runs.refetch()
    void alerts.refetch()
    void audit.refetch()
  }

  async function act(key: string, notice: string, action: () => Promise<unknown>) {
    setBusy(key)
    setActionError(null)
    setActionNotice(null)
    try {
      await action()
      setActionNotice(notice)
      refresh()
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(null)
    }
  }

  async function loadMoreRuns() {
    const cursor = runs.data?.next_cursor
    if (!cursor || loadingMoreRuns) return
    setLoadingMoreRuns(true)
    setActionError(null)
    try {
      const page = await api.automationRuns(undefined, undefined, 100, cursor)
      runs.setData((current) => {
        const ids = new Set(current.runs.map((run) => run.id))
        const additions = page.runs.filter((run) => !ids.has(run.id))
        return { ...current, runs: [...current.runs, ...additions], count: current.runs.length + additions.length, total: page.total, next_cursor: page.next_cursor }
      })
    } catch (error) {
      setActionError(error instanceof Error ? error.message : '继续加载运行历史失败')
    } finally {
      setLoadingMoreRuns(false)
    }
  }

  async function loadMoreAudit() {
    const cursor = audit.data?.next_cursor
    if (!cursor || loadingMoreAudit) return
    setLoadingMoreAudit(true)
    setActionError(null)
    try {
      const page = await api.automationAudit(100, cursor)
      audit.setData((current) => {
        const ids = new Set(current.audit.map((item) => item.id))
        const additions = page.audit.filter((item) => !ids.has(item.id))
        return { ...current, audit: [...current.audit, ...additions], count: current.audit.length + additions.length, total: page.total, next_cursor: page.next_cursor }
      })
    } catch (error) {
      setActionError(error instanceof Error ? error.message : '继续加载审计记录失败')
    } finally {
      setLoadingMoreAudit(false)
    }
  }

  async function openRunResult(run: AutomationRun) {
    if (!run.result_type || !run.result_id) return
    setActionError(null)
    try {
      if (run.result_type === 'research_run') {
        const response = await api.researchRun(run.result_id)
        navigate(researchRunHref(response.run))
        return
      }
      const href = linkedResultHref(run.result_type, run.result_id)
      if (!href) throw new Error(`暂不支持打开产出类型：${run.result_type}`)
      navigate(href)
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : '产出定位失败')
    }
  }

  const jobColumns: Column<AutomationJob>[] = [
    {
      key: 'enabled', header: '启用', width: 64, render: (row) => (
        <label className={s.switch}>
          <input
            type="checkbox"
            aria-label={`启用 ${row.name}`}
            checked={row.enabled}
            disabled={busy !== null}
            onChange={(event) => {
              const enabled = event.target.checked
              void act(
                `toggle:${row.name}`,
                `${row.name} 已${enabled ? '启用' : '停用'}`,
                () => api.updateAutomationJob(row.name, { enabled, actor: ACTOR }),
              )
            }}
          />
          <span aria-hidden="true" />
        </label>
      ),
    },
    {
      key: 'name', header: '任务', render: (row) => (
        <div className={s.taskIdentity}>
          <strong className={s.code}>{row.name}</strong>
          <span>{row.market} · {row.custom ? '自定义入口' : '通用策略入口'}</span>
        </div>
      ),
    },
    {
      key: 'cron', header: '执行计划', width: 260, render: (row) => {
        const value = cronDrafts[row.name] ?? row.cron
        const changed = value !== row.cron
        return (
          <div className={s.cronEditor}>
            <input
              aria-label={`Cron ${row.name}`}
              className={s.cronInput}
              value={value}
              disabled={busy !== null}
              onChange={(event) => setCronDrafts((current) => ({
                ...current,
                [row.name]: event.target.value,
              }))}
            />
            <Button
              size="sm"
              variant={changed ? 'primary' : 'ghost'}
              disabled={!changed || busy !== null}
              loading={busy === `cron:${row.name}`}
              onClick={() => void act(
                `cron:${row.name}`,
                `${row.name} 的 Cron 已保存`,
                () => api.updateAutomationJob(row.name, { cron: value, actor: ACTOR }),
              )}
            >保存</Button>
          </div>
        )
      },
    },
    {
      key: 'next_run', header: '下次执行', width: 180, render: (row) => (
        <span className={row.enabled ? s.code : s.meta}>
          {row.enabled ? formatTime(row.next_run) : '已停用'}
        </span>
      ),
    },
    {
      key: 'action', header: '操作', width: 96, render: (row) => (
        <Button
          size="sm"
          variant="secondary"
          disabled={!row.enabled || busy !== null}
          loading={busy === `run:${row.name}`}
          onClick={() => void act(
            `run:${row.name}`,
            `${row.name} 已进入运行队列`,
            async () => {
              const response = await api.runAutomationJob(row.name, ACTOR)
              setSelectedRunId(response.run.id)
              setTab('runs')
            },
          )}
        >立即运行</Button>
      ),
    },
  ]

  const runColumns: Column<AutomationRun>[] = [
    { key: 'job_name', header: '任务', render: (row) => <span className={s.code}>{row.job_name}</span> },
    {
      key: 'status', header: '状态', width: 92, render: (row) => (
        <span className={`${s.runState} ${s[`runState_${row.status}`]}`}>{runStatusLabel(row.status)}</span>
      ),
    },
    { key: 'trigger_type', header: '触发', width: 72, render: (row) => row.trigger_type === 'retry' ? '重试' : '手动' },
    { key: 'attempt', header: '次数', width: 64, render: (row) => <span className={s.code}>{row.attempt}</span> },
    { key: 'created_at', header: '创建时间', width: 170, render: (row) => formatTime(row.created_at) },
    { key: 'duration_ms', header: '耗时', width: 90, render: (row) => row.duration_ms === null ? '—' : `${row.duration_ms} ms` },
    {
      key: 'actions', header: '操作', width: 230, render: (row) => (
        <div className={s.rowActions}>
          <Button size="sm" variant="link" onClick={() => setSelectedRunId(row.id)}>查看日志</Button>
          {row.status === 'succeeded' && row.result_type && row.result_id && (
            <Button size="sm" variant="link" onClick={() => void openRunResult(row)}>查看本次产出</Button>
          )}
          {row.status === 'failed' && (
            <Button
              size="sm"
              variant="link"
              disabled={busy !== null}
              loading={busy === `retry:${row.id}`}
              onClick={() => void act(
                `retry:${row.id}`,
                `${row.job_name} 已重新进入队列`,
                () => api.retryAutomationRun(row.id, ACTOR),
              )}
            >重试</Button>
          )}
          {row.status === 'failed' && row.acknowledged_at === null && (
            <Button
              size="sm"
              variant="link"
              disabled={busy !== null}
              loading={busy === `ack:${row.id}`}
              onClick={() => void act(
                `ack:${row.id}`,
                `${row.job_name} 的告警已确认`,
                () => api.acknowledgeAutomationRun(row.id, ACTOR),
              )}
            >确认告警</Button>
          )}
        </div>
      ),
    },
  ]

  const auditColumns: Column<AutomationAuditLog>[] = [
    { key: 'created_at', header: '时间', width: 170, render: (row) => formatTime(row.created_at) },
    { key: 'action', header: '动作', width: 150, render: (row) => <span className={s.code}>{row.action}</span> },
    { key: 'entity_id', header: '对象', render: (row) => <span className={s.code}>{row.entity_id}</span> },
    { key: 'actor', header: '操作者', width: 120, render: (row) => row.actor },
    {
      key: 'result', header: '结果', width: 90, render: (row) => (
        <span className={row.result === 'failed' ? s.negative : row.result === 'succeeded' ? s.positive : s.meta}>
          {row.result}
        </span>
      ),
    },
    { key: 'error', header: '错误', render: (row) => row.error || '—' },
  ]

  const consoleState = tab === 'runs' ? runs : tab === 'alerts' ? alerts : audit
  const consoleCount = tab === 'runs' ? runRows.length : tab === 'alerts' ? alertRows.length : auditRows.length
  const refreshing = status.loading || jobs.loading || runs.loading || alerts.loading || audit.loading

  return (
    <div className={s.page}>
      <WorkspaceHeader
        context="运营 / 作业调度"
        title="任务运行控制台"
        metrics={[
          { label: '启用任务', value: `${status.data?.enabled_count ?? 0} / ${status.data?.total ?? rows.length}` },
          { label: '活动运行', value: status.data?.running_count ?? 0 },
          { label: '失败记录', value: status.data?.failed_count ?? 0 },
          { label: '未确认告警', value: status.data?.unacknowledged_alert_count ?? alertRows.length },
        ]}
      />

      <AsyncStateBoundary
        loading={status.loading}
        error={status.error}
        reconnecting={status.reconnecting}
        hasData={status.data !== null}
        isEmpty={false}
        onRetry={status.refetch}
        loadingTitle="正在读取自动化状态…"
        emptyTitle="暂无自动化状态"
      >
        <div className={s.controlNotice}>
          <div>
            <strong>本地持久化控制面</strong>
            <span>{status.data?.note || '任务覆盖、运行记录和审计信息保存在业务数据库。'}</span>
          </div>
          <RefreshControl onRefresh={refresh} refreshing={refreshing} updatedAt={status.updatedAt} label="刷新全部" variant="secondary" />
        </div>
      </AsyncStateBoundary>
      {actionError && <div className={s.error} role="alert">{actionError}</div>}
      {actionNotice && <div className={s.success} role="status">{actionNotice}</div>}

      <section className={s.section}>
        <div className={s.sectionHead}>
          <div><h2>任务配置</h2><span>开关和 Cron 覆盖保存后立即成为控制台真值</span></div>
          <span className={s.meta}>{jobs.loading ? '读取中' : `${rows.length} 个任务`}</span>
        </div>
        <AsyncStateBoundary
          loading={jobs.loading}
          error={jobs.error}
          reconnecting={jobs.reconnecting}
          hasData={jobs.data !== null}
          isEmpty={rows.length === 0}
          onRetry={jobs.refetch}
          loadingTitle="正在读取任务配置…"
          emptyTitle="没有自动化任务"
        >
          <Table columns={jobColumns} rows={rows} rowKey={(row) => row.name} density="compact" />
        </AsyncStateBoundary>
      </section>

      <section className={s.section}>
        <div className={s.tabs} role="tablist" aria-label="自动化记录视图">
          <button className={tab === 'runs' ? s.tabActive : s.tab} onClick={() => setTab('runs')} role="tab" aria-selected={tab === 'runs'}>
            运行历史 <span>{runs.data?.total ?? runRows.length}</span>
          </button>
          <button className={tab === 'alerts' ? s.tabActive : s.tab} onClick={() => setTab('alerts')} role="tab" aria-selected={tab === 'alerts'}>
            未确认告警 <span>{alertRows.length}</span>
          </button>
          <button className={tab === 'audit' ? s.tabActive : s.tab} onClick={() => setTab('audit')} role="tab" aria-selected={tab === 'audit'}>
            审计记录 <span>{audit.data?.total ?? auditRows.length}</span>
          </button>
        </div>

        <div className={s.consoleBody}>
          <AsyncStateBoundary
            loading={consoleState.loading}
            error={consoleState.error}
            reconnecting={consoleState.reconnecting}
            hasData={consoleState.data !== null}
            isEmpty={consoleCount === 0}
            onRetry={consoleState.refetch}
            loadingTitle="正在读取自动化记录…"
            emptyTitle={tab === 'alerts' ? '没有未确认告警' : tab === 'audit' ? '没有审计记录' : '没有运行记录'}
          >
            {tab === 'runs' && <Table columns={runColumns} rows={runRows} rowKey={(row) => row.id} density="compact" />}
            {tab === 'alerts' && <Table columns={runColumns} rows={alertRows} rowKey={(row) => row.id} density="compact" />}
            {tab === 'audit' && <Table columns={auditColumns} rows={auditRows} rowKey={(row) => row.id} density="compact" />}
          </AsyncStateBoundary>
          {tab === 'runs' && runs.data?.next_cursor && <div className={s.formActions}><Button variant="secondary" loading={loadingMoreRuns} onClick={() => void loadMoreRuns()}>继续加载 · 已显示 {runRows.length} / {runs.data.total}</Button></div>}
          {tab === 'audit' && audit.data?.next_cursor && <div className={s.formActions}><Button variant="secondary" loading={loadingMoreAudit} onClick={() => void loadMoreAudit()}>继续加载 · 已显示 {auditRows.length} / {audit.data.total}</Button></div>}
        </div>

        {selectedRun && tab !== 'audit' && (
          <div className={s.logInspector}>
            <div className={s.logHead}>
              <div>
                <strong>{selectedRun.job_name}</strong>
                <span className={s.code}>{selectedRun.id}</span>
              </div>
              <Button size="sm" variant="ghost" onClick={() => setSelectedRunId(null)}>关闭</Button>
            </div>
            {selectedRun.error && <div className={s.logError}>{selectedRun.error}</div>}
            {selectedRun.result_type && selectedRun.result_id && (
              <div className={s.formActions}>
                <Button size="sm" variant="secondary" onClick={() => void openRunResult(selectedRun)}>
                  查看本次产出 · {selectedRun.result_type}
                </Button>
              </div>
            )}
            <pre>{selectedRun.log || '运行尚未生成日志。'}</pre>
          </div>
        )}
      </section>
    </div>
  )
}
