import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { DataSourceOperation, IncidentAction, IncidentRecord, IncidentSource } from '../api/types'
import { useApi } from '../api/useApi'
import { AsyncStateBoundary } from '../components/ui/AsyncStateBoundary/AsyncStateBoundary'
import { Button } from '../components/ui/Button/Button'
import { Input } from '../components/ui/Input/Input'
import { RefreshControl } from '../components/ui/RefreshControl/RefreshControl'
import { Table, type Column } from '../components/ui/Table/Table'
import { WorkspaceHeader } from '../components/WorkspaceHeader/WorkspaceHeader'
import { useRecordNavigation } from '../hooks/useRecordNavigation'
import { researchRunHref } from '../lib/researchResults'
import s from './OperationsPages.module.css'

const SOURCE_LABELS: Record<IncidentSource, string> = {
  analysis_task: '分析任务',
  automation_run: '自动化',
  ledger_sync: '账本同步',
  data_source: '数据源',
  research_run: '统计验证',
  research_persistence: '研究持久化',
}

function isDataSourceOperation(value: unknown): value is DataSourceOperation {
  return value === 'get_kline' || value === 'get_news' || value === 'get_announcements'
}

export default function IncidentsPage() {
  const navigate = useNavigate()
  const incidents = useApi(() => api.incidents(), [], { retry: false })
  const [source, setSource] = useState<IncidentSource | 'all'>('all')
  const [busy, setBusy] = useState<string | null>(null)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [actionResults, setActionResults] = useState<Record<string, { status: 'succeeded' | 'failed'; message: string }>>({})
  const [selectedIncidentId, setSelectedIncidentId] = useState<string | null>(null)
  const [sourceCheckForm, setSourceCheckForm] = useState({ market: 'a_shares', symbol: '', interval: '1d' })
  const [recoveryResolution, setRecoveryResolution] = useState('')
  const [loadingMore, setLoadingMore] = useState(false)
  const rows = useMemo(
    () => (incidents.data?.incidents ?? []).filter((item) => source === 'all' || item.source === source),
    [incidents.data, source],
  )
  const counts = useMemo(() => {
    const result: Record<IncidentSource, number> = {
      analysis_task: 0,
      automation_run: 0,
      ledger_sync: 0,
      data_source: 0,
      research_run: 0,
      research_persistence: 0,
    }
    ;(incidents.data?.incidents ?? []).forEach((item) => { result[item.source] += 1 })
    return result
  }, [incidents.data])
  const handleIncidentKeyDown = useRecordNavigation({
    keys: rows.map((row) => row.id),
    activeKey: selectedIncidentId,
    onSelect: setSelectedIncidentId,
  })

  async function execute(incident: IncidentRecord, action: IncidentAction) {
    const key = `${incident.id}:${action.type}`
    setBusy(key)
    setMessage('')
    setError('')
    try {
      if (action.type === 'open_research_result' && action.research_run_id) {
        const response = await api.researchRun(action.research_run_id)
        navigate(researchRunHref(response.run))
        return
      } else if (action.type === 'retry_analysis_task' && action.task_id) {
        await api.retryAnalysisTask(action.task_id)
      } else if (action.type === 'retry_automation_run' && action.run_id) {
        await api.retryAutomationRun(action.run_id)
      } else if (action.type === 'acknowledge_automation_run' && action.run_id) {
        await api.acknowledgeAutomationRun(action.run_id)
      } else if (action.type === 'retry_ledger_sync' && action.order_id && action.execution_id) {
        await api.retrySimulationLedgerSync(action.order_id, action.execution_id)
      } else if (action.type === 'check_data_source' && action.incident_id) {
        const operation = incident.context.operation
        const sourceName = incident.context.source
        if (typeof sourceName !== 'string' || !isDataSourceOperation(operation)) {
          throw new Error('数据源故障记录缺少精确来源或操作')
        }
        if (!sourceCheckForm.market || !sourceCheckForm.symbol.trim() || !sourceCheckForm.interval.trim()) {
          throw new Error('检查数据源前需要填写市场、标的和周期')
        }
        const result = await api.checkIncidentDataSource({
          incident_id: action.incident_id, market: sourceCheckForm.market,
          source: sourceName, operation, symbol: sourceCheckForm.symbol.trim(),
          interval: sourceCheckForm.interval.trim(),
        })
        if (!result.ok) throw new Error(result.check.error || '数据源检查未恢复')
      } else if (action.type === 'acknowledge_data_source_recovery' && action.incident_id) {
        if (!recoveryResolution.trim()) throw new Error('确认恢复前需要填写处理结果')
        const result = await api.acknowledgeDataSourceRecovery(
          action.incident_id, recoveryResolution.trim(),
        )
        if (!result.ok) throw new Error('数据源恢复确认失败')
      } else if (action.type === 'open_data_source_status') {
        navigate('/config')
        return
      } else {
        throw new Error(`故障动作缺少所需标识符: ${action.type}`)
      }
      setMessage(`${SOURCE_LABELS[incident.source]}操作已提交：${action.label}`)
      setActionResults((current) => ({ ...current, [key]: { status: 'succeeded', message: `${action.label}已提交` } }))
      void incidents.refetch()
    } catch (actionError) {
      const actionMessage = actionError instanceof Error ? actionError.message : String(actionError)
      setError(actionMessage)
      setActionResults((current) => ({ ...current, [key]: { status: 'failed', message: actionMessage } }))
    } finally {
      setBusy(null)
    }
  }

  async function loadMore() {
    const cursor = incidents.data?.next_cursor
    if (!cursor || loadingMore) return
    setLoadingMore(true)
    setError('')
    try {
      const page = await api.incidents(100, cursor)
      incidents.setData((current) => {
        const ids = new Set(current.incidents.map((incident) => incident.id))
        const additions = page.incidents.filter((incident) => !ids.has(incident.id))
        return { ...current, incidents: [...current.incidents, ...additions], count: current.incidents.length + additions.length, total: page.total, next_cursor: page.next_cursor }
      })
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '继续加载故障记录失败')
    } finally {
      setLoadingMore(false)
    }
  }

  const columns: Column<IncidentRecord>[] = [
    {
      key: 'source', header: '来源', width: 100, render: (row) => (
        <span className={`${s.incidentSource} ${s[`incidentSource_${row.source}`]}`}>
          {SOURCE_LABELS[row.source]}
        </span>
      ),
    },
    { key: 'occurred_at', header: '发生时间', width: 170, render: (row) => new Date(row.occurred_at * 1000).toLocaleString('zh-CN', { hour12: false }) },
    { key: 'status', header: '状态', width: 90, render: (row) => <span className={s.negative}>{row.status}</span> },
    {
      key: 'entity_id', header: '对象', render: (row) => (
        <div className={s.incidentIdentity}>
          <span className={s.code}>{row.entity_id}</span>
          <small>{Object.entries(row.context).map(([key, value]) => `${key}=${String(value)}`).join(' · ')}</small>
        </div>
      ),
    },
    { key: 'error', header: '错误', render: (row) => <span className={s.incidentError}>{row.error}</span> },
    {
      key: 'actions', header: '操作', width: 220, render: (row) => (
        <div className={`${s.rowActions} ${s.incidentActions}`}>
          {row.actions.map((action) => (
            <span key={action.type}>
              <Button
                size="sm"
                variant="link"
                disabled={busy !== null}
                loading={busy === `${row.id}:${action.type}`}
                onClick={() => void execute(row, action)}
              >{actionResults[`${row.id}:${action.type}`]?.status === 'failed' ? `重试${action.label}` : action.label}</Button>
              {actionResults[`${row.id}:${action.type}`] && <small className={actionResults[`${row.id}:${action.type}`].status === 'succeeded' ? s.positive : s.negative}>{actionResults[`${row.id}:${action.type}`].message}</small>}
            </span>
          ))}
        </div>
      ),
    },
  ]

  return (
    <div className={s.page}>
      <WorkspaceHeader
        context="运营 / 运行故障"
        title="异常处理队列"
        metrics={[
          { label: '全部异常', value: incidents.data?.total ?? 0 },
          { label: '分析任务', value: counts.analysis_task },
          { label: '自动化', value: counts.automation_run },
          { label: '账本与数据源', value: counts.ledger_sync + counts.data_source },
        ]}
      />

      <div className={s.toolbar}>
        <label className={s.grow}>
          异常来源
          <select value={source} onChange={(event) => setSource(event.target.value as IncidentSource | 'all')}>
            <option value="all">全部来源</option>
            {Object.entries(SOURCE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <RefreshControl onRefresh={incidents.refetch} refreshing={incidents.loading || incidents.reconnecting} updatedAt={incidents.updatedAt} variant="secondary" />
      </div>
      {(source === 'all' || source === 'data_source') && (
        <div className={s.formBand}>
          <label>检查市场<select value={sourceCheckForm.market} onChange={(event) => setSourceCheckForm({ ...sourceCheckForm, market: event.target.value })}><option value="a_shares">a_shares</option><option value="crypto">crypto</option><option value="us_stocks">us_stocks</option><option value="mt5">mt5</option></select></label>
          <label>标的<Input value={sourceCheckForm.symbol} onChange={(event) => setSourceCheckForm({ ...sourceCheckForm, symbol: event.target.value })} /></label>
          <label>周期<Input value={sourceCheckForm.interval} onChange={(event) => setSourceCheckForm({ ...sourceCheckForm, interval: event.target.value })} /></label>
          <label className={s.grow}>恢复处理结果<Input value={recoveryResolution} onChange={(event) => setRecoveryResolution(event.target.value)} /></label>
        </div>
      )}
      {error && <div className={s.error} role="alert">{error}</div>}
      {message && <div className={s.success} role="status">{message}</div>}

      <section className={s.section}>
        <div className={s.sectionHead}>
          <div><h2>当前异常</h2><span>按发生时间倒序</span></div>
          <span className={s.meta}>{rows.length} 条</span>
        </div>
        <AsyncStateBoundary
          loading={incidents.loading}
          error={incidents.error}
          reconnecting={incidents.reconnecting}
          hasData={incidents.data !== null}
          isEmpty={rows.length === 0}
          onRetry={incidents.refetch}
          loadingTitle="正在聚合异常记录…"
          emptyTitle="当前来源没有异常"
        >
          <div className={s.keyboardList} tabIndex={0} onKeyDown={handleIncidentKeyDown} aria-label="可用方向键选择故障记录">
            <Table
              columns={columns}
              rows={rows}
              rowKey={(row) => row.id}
              density="compact"
              activeRowKey={selectedIncidentId}
              onRowClick={(row) => setSelectedIncidentId(row.id)}
            />
          </div>
        </AsyncStateBoundary>
        {incidents.data?.next_cursor && <div className={s.formActions}><Button variant="secondary" loading={loadingMore} onClick={() => void loadMore()}>继续加载 · 已显示 {incidents.data.incidents.length} / {incidents.data.total}</Button></div>}
      </section>
    </div>
  )
}
