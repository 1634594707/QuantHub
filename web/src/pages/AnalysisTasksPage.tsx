import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import type { AnalysisTask, AnalysisTaskKind, AnalysisTaskStatus } from '../api/types'
import { useApi } from '../api/useApi'
import { AsyncStateBoundary } from '../components/ui/AsyncStateBoundary/AsyncStateBoundary'
import { ConfirmActionButton } from '../components/ui/ConfirmActionButton/ConfirmActionButton'
import { RefreshControl } from '../components/ui/RefreshControl/RefreshControl'
import { ResponsiveDetails } from '../components/ui/ResponsiveDetails/ResponsiveDetails'
import { WorkspaceHeader } from '../components/WorkspaceHeader/WorkspaceHeader'
import '../styles/tasks.css'

const KIND_META: Record<AnalysisTaskKind, string> = {
  pa: 'PA 分析',
  news: '新闻分析',
  ensemble: '协同预测',
  evaluation: '股票评估',
}

const STATUS_META: Record<AnalysisTaskStatus, string> = {
  queued: '排队中',
  running: '运行中',
  succeeded: '已完成',
  failed: '失败',
  cancelled: '已取消',
  timeout: '已超时',
}

function formatTime(value: number | null): string {
  if (!value) return '—'
  return new Date(value * 1000).toLocaleString('zh-CN', { hour12: false })
}

export default function AnalysisTasksPage() {
  const [kind, setKind] = useState<AnalysisTaskKind>('pa')
  const [symbol, setSymbol] = useState('600519')
  const [market, setMarket] = useState('a_shares')
  const [timeframe, setTimeframe] = useState('1d')
  const [statusFilter, setStatusFilter] = useState<AnalysisTaskStatus | ''>('')
  const [kindFilter, setKindFilter] = useState<AnalysisTaskKind | ''>('')
  const [tick, setTick] = useState(0)
  const [submitting, setSubmitting] = useState(false)
  const [actionError, setActionError] = useState('')
  const [actionMessage, setActionMessage] = useState('')
  const [loadedTasks, setLoadedTasks] = useState<AnalysisTask[]>([])
  const [loadingMore, setLoadingMore] = useState(false)
  const tasks = useApi(
    () => api.analysisTasks(statusFilter || undefined, kindFilter || undefined, 50),
    [statusFilter, kindFilter, tick],
    { retry: false, resetKey: `${statusFilter}|${kindFilter}` },
  )

  useEffect(() => setLoadedTasks([]), [statusFilter, kindFilter])

  useEffect(() => {
    const page = tasks.data
    if (!page) return
    setLoadedTasks((current) => {
      const freshIds = new Set(page.tasks.map((task) => task.id))
      return [...page.tasks, ...current.filter((task) => !freshIds.has(task.id))]
    })
  }, [tasks.data])

  const hasActive = useMemo(
    () => loadedTasks.some((task) => task.status === 'queued' || task.status === 'running'),
    [loadedTasks],
  )

  useEffect(() => {
    if (!hasActive) return
    const timer = window.setInterval(() => setTick((value) => value + 1), 1500)
    return () => window.clearInterval(timer)
  }, [hasActive])

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    const normalized = symbol.trim().toUpperCase()
    if (!normalized) return
    setSubmitting(true)
    setActionError('')
    try {
      const payload = kind === 'news'
        ? { limit: 20, use_api: true }
        : kind === 'ensemble'
          ? { limit: 200 }
          : {}
      await api.createAnalysisTask({
        kind,
        symbol: normalized,
        market,
        timeframe,
        payload,
        timeout_seconds: 90,
      })
      setTick((value) => value + 1)
    } catch (error) {
      setActionError(error instanceof Error ? error.message : '任务提交失败')
    } finally {
      setSubmitting(false)
    }
  }

  async function act(action: 'cancel' | 'retry', taskId: string) {
    setActionError('')
    setActionMessage('')
    try {
      if (action === 'cancel') await api.cancelAnalysisTask(taskId)
      else await api.retryAnalysisTask(taskId)
      setTick((value) => value + 1)
      setActionMessage(action === 'cancel' ? `任务 ${taskId} 已取消` : `任务 ${taskId} 已重新提交`)
    } catch (error) {
      setActionError(error instanceof Error ? error.message : '任务操作失败')
      throw error
    }
  }

  async function loadMore() {
    const cursor = tasks.data?.next_cursor
    if (!cursor || loadingMore) return
    setLoadingMore(true)
    setActionError('')
    try {
      const page = await api.analysisTasks(
        statusFilter || undefined, kindFilter || undefined, 50, cursor,
      )
      setLoadedTasks((current) => {
        const ids = new Set(current.map((task) => task.id))
        return [...current, ...page.tasks.filter((task) => !ids.has(task.id))]
      })
      tasks.setData((current) => current ? { ...current, next_cursor: page.next_cursor, total: page.total } : page)
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : '继续加载任务失败')
    } finally {
      setLoadingMore(false)
    }
  }

  return (
    <div className="tasks-page">
      <WorkspaceHeader
        context="研究 / 分析任务"
        title="分析任务"
        metrics={[
          { label: '任务总数', value: tasks.data?.total ?? 0 },
          { label: '活动任务', value: loadedTasks.filter((task) => ['queued', 'running'].includes(task.status)).length },
        ]}
      />

      <form className="tasks-submit" onSubmit={submit}>
        <label>模块<select value={kind} onChange={(event) => setKind(event.target.value as AnalysisTaskKind)}><option value="pa">PA</option><option value="news">新闻</option><option value="ensemble">共识</option></select></label>
        <label>标的<input value={symbol} onChange={(event) => setSymbol(event.target.value)} /></label>
        <label>市场<select value={market} onChange={(event) => setMarket(event.target.value)}><option value="a_shares">A股</option><option value="crypto">加密</option></select></label>
        <label>周期<select value={timeframe} onChange={(event) => setTimeframe(event.target.value)}><option value="1h">1h</option><option value="1d">1d</option><option value="1w">1w</option></select></label>
        <button type="submit" disabled={submitting || !symbol.trim()}>{submitting ? '提交中' : '提交任务'}</button>
      </form>

      <div className="tasks-toolbar">
        <select value={kindFilter} onChange={(event) => setKindFilter(event.target.value as AnalysisTaskKind | '')} aria-label="筛选任务模块"><option value="">全部模块</option><option value="pa">PA</option><option value="news">新闻</option><option value="ensemble">共识</option></select>
        <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as AnalysisTaskStatus | '')} aria-label="筛选任务状态"><option value="">全部状态</option>{Object.entries(STATUS_META).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select>
        <RefreshControl onRefresh={tasks.refetch} refreshing={tasks.loading || tasks.reconnecting} updatedAt={tasks.updatedAt} />
        {actionError && <span>{actionError}</span>}
        {actionMessage && <span className="ok" role="status">{actionMessage}</span>}
      </div>

      <div className="tasks-table">
        <div className="tasks-row head"><span>状态</span><span>任务</span><span>标的</span><span>创建 / 耗时</span><span>结果</span><span>操作</span></div>
        <AsyncStateBoundary
          loading={tasks.loading}
          error={tasks.error}
          reconnecting={tasks.reconnecting}
          hasData={tasks.data !== null}
          isEmpty={loadedTasks.length === 0}
          onRetry={tasks.refetch}
          loadingTitle="正在读取任务…"
          emptyTitle="当前筛选条件下没有任务"
        >
          {loadedTasks.map((task) => (
            <div className="tasks-row" key={task.id}>
              <span><b className={`task-status ${task.status}`}>{STATUS_META[task.status]}</b><small>第 {task.attempt} 次</small></span>
              <span><b>{KIND_META[task.kind]}</b><small className="mono-num">{task.id.slice(0, 12)}</small></span>
              <span><b className="mono-num">{task.symbol}</b><small>{task.market} · {task.timeframe}</small></span>
              <ResponsiveDetails className="task-row-details" compactAt={760} summary="查看任务详情">
                <span><b>{formatTime(task.created_at)}</b><small>{task.duration_ms == null ? '—' : `${(task.duration_ms / 1000).toFixed(1)} 秒`}</small></span>
                <span title={task.error || undefined}><b>{task.error || (task.result ? '结果已保存' : '等待执行')}</b><small>{task.result && typeof task.result.research_run_id === 'string' ? `研究 ${task.result.research_run_id.slice(0, 10)}` : '—'}</small></span>
                <span className="task-actions">
                  {['queued', 'running'].includes(task.status) && (
                    <ConfirmActionButton
                      label="取消"
                      title="确认取消分析任务"
                      description={`取消任务 ${task.id} 后，本次运行不会继续生成研究结果。`}
                      confirmLabel="确认取消"
                      onConfirm={() => act('cancel', task.id)}
                    />
                  )}
                  {['failed', 'cancelled', 'timeout'].includes(task.status) && <button type="button" onClick={() => { void act('retry', task.id).catch(() => {}) }}>重试</button>}
                </span>
              </ResponsiveDetails>
            </div>
          ))}
        </AsyncStateBoundary>
        {tasks.data?.next_cursor && (
          <button type="button" className="tasks-load-more" disabled={loadingMore} onClick={() => void loadMore()}>
            {loadingMore ? '加载中…' : `继续加载 · 已显示 ${loadedTasks.length} / ${tasks.data.total}`}
          </button>
        )}
      </div>
    </div>
  )
}
