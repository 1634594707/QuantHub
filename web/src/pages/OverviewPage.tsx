import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import KpiRow, { type AccountScope } from '../components/KpiRow'
import KlineCard from '../components/KlineCard'
import DecisionPanel from '../components/DecisionPanel'
import MarketBreadth from '../components/MarketBreadth'
import Watchlist from '../components/Watchlist'
import HoldingsTable from '../components/HoldingsTable'
import { api } from '../api/client'
import { useApi } from '../api/useApi'
import { useEditableHoldings } from '../hooks/useEditableHoldings'
import { useEditableWatchlist } from '../hooks/useEditableWatchlist'
import { useMarketQuotes, quoteKey } from '../hooks/useMarketQuotes'
import { useLocalStorage } from '../hooks/useLocalStorage'
import { useInterfaceMode } from '../hooks/useInterfaceMode'
import { computeSummary, deriveHolding, deriveWatch } from '../lib/portfolio'
import type { PaAnalyzeResp } from '../api/types'
import { AsyncStateBoundary } from '../components/ui/AsyncStateBoundary/AsyncStateBoundary'
import { WorkspaceHeader } from '../components/WorkspaceHeader/WorkspaceHeader'
import { ActionQueue } from '../components/ActionQueue/ActionQueue'
import { Button } from '../components/ui/Button/Button'
import { IconChart, IconCog, IconGrid } from '../components/icons'
import { SegmentedControl } from '../components/ui/SegmentedControl/SegmentedControl'
import { Toggle } from '../components/ui/Toggle/Toggle'
import { alertEventHref } from '../lib/alerts'
import s from './OverviewPage.module.css'

const DASHBOARD_MODULES = [
  { id: 'evaluation', label: '标的评估' },
  { id: 'market', label: '关注与市场' },
  { id: 'actions', label: '待处理事项' },
  { id: 'account', label: '账户指标' },
  { id: 'analysis', label: '行情与分析' },
] as const

type DashboardModuleId = typeof DASHBOARD_MODULES[number]['id']

interface DashboardLayout {
  order: DashboardModuleId[]
  hidden: DashboardModuleId[]
}

const DEFAULT_ADVANCED_LAYOUT: DashboardLayout = {
  order: ['evaluation', 'actions', 'market', 'account', 'analysis'],
  hidden: [],
}

const DEFAULT_BEGINNER_LAYOUT: DashboardLayout = {
  order: ['evaluation', 'actions', 'market', 'account', 'analysis'],
  hidden: ['account', 'analysis'],
}

export default function OverviewPage() {
  const navigate = useNavigate()
  const [interfaceMode] = useInterfaceMode()
  const isAdvanced = interfaceMode === 'advanced'
  const [layoutSettingsOpen, setLayoutSettingsOpen] = useState(false)
  const [accountScope, setAccountScope] = useLocalStorage<AccountScope>('quanthub.overview.account-scope', 'research')
  const [beginnerLayout, setBeginnerLayout] = useLocalStorage<DashboardLayout>(
    'quanthub.overview.modules.beginner.v1',
    DEFAULT_BEGINNER_LAYOUT,
  )
  const [advancedLayout, setAdvancedLayout] = useLocalStorage<DashboardLayout>(
    'quanthub.overview.modules.advanced.v1',
    DEFAULT_ADVANCED_LAYOUT,
  )
  const dashboardLayout = isAdvanced ? advancedLayout : beginnerLayout
  const setDashboardLayout = isAdvanced ? setAdvancedLayout : setBeginnerLayout
  const moduleVisible = (id: DashboardModuleId) => !dashboardLayout.hidden.includes(id)
  const marketVisible = moduleVisible('market')
  const actionsVisible = moduleVisible('actions')
  const accountVisible = moduleVisible('account')
  const analysisVisible = moduleVisible('analysis')

  const breadth = useApi(() => api.marketBreadth(), [], { enabled: marketVisible })
  const simulationAccount = useApi(
    () => api.simulationAccount(),
    [],
    { enabled: accountVisible && accountScope === 'simulation', retry: false, pollInterval: 15000 },
  )
  const ledgerSummary = useApi(
    () => api.ledgerSummary(),
    [],
    { enabled: accountVisible && accountScope === 'ledger', retry: false, pollInterval: 15000 },
  )
  const holdings = useEditableHoldings(accountVisible || analysisVisible)
  const watchlist = useEditableWatchlist(marketVisible)
  const [editH, setEditH] = useState(false)
  const [editW, setEditW] = useState(false)
  const [savingH, setSavingH] = useState(false)
  const [savingW, setSavingW] = useState(false)
  const [holdingSaveError, setHoldingSaveError] = useState('')
  const [watchSaveError, setWatchSaveError] = useState('')
  const [symbol, setSymbol] = useState('600519')
  const [market, setMarket] = useState<'a_shares' | 'crypto' | 'us_stocks'>('a_shares')
  const paHistory = useApi(
    () => api.researchRuns(symbol, 'succeeded', 20),
    [symbol],
    { enabled: analysisVisible, retryInterval: 15000, resetKey: symbol },
  )
  const advancedActionsEnabled = isAdvanced && actionsVisible
  const pendingSignals = useApi(() => api.signals(50, undefined, 'new'), [], { enabled: advancedActionsEnabled, retry: false })
  const pendingIncidents = useApi(() => api.incidents(50), [], { enabled: advancedActionsEnabled, retry: false })
  const factorAttention = useApi(
    () => api.factorResearchAttention(),
    [],
    { enabled: advancedActionsEnabled, retry: false, pollInterval: 60000 },
  )
  const automationAlerts = useApi(() => api.automationAlerts(50), [], { enabled: advancedActionsEnabled, retry: false })
  const userAlerts = useApi(
    () => api.alertEvents(true, 50),
    [],
    { enabled: actionsVisible, retry: false, pollInterval: 60000 },
  )
  const firstPendingAlert = userAlerts.data?.events[0]
  const failedTasks = useApi(
    () => api.analysisTasks('failed', undefined, 50),
    [],
    { enabled: actionsVisible, retry: false },
  )
  const simulationOrders = useApi(
    () => api.simulationOrders(undefined, undefined, 100),
    [],
    { enabled: actionsVisible, retry: false },
  )
  const simulationAttentionCount = (simulationOrders.data?.orders ?? []).filter((order) => (
    order.status === 'pending'
    || order.status === 'partially_filled'
    || order.executions.some((execution) => execution.ledger_sync_status === 'failed')
  )).length
  const recentPaRun = paHistory.data?.runs.find((run) => run.modules.includes('pa'))
  const paSummary = recentPaRun?.summary.pa as Record<string, unknown> | undefined
  const recentPa = paSummary?.decision
    ? {
        ok: true,
        symbol,
        market: recentPaRun?.market ?? market,
        timeframe: recentPaRun?.timeframe ?? '1h',
        research_run_id: recentPaRun?.id,
        decision: paSummary.decision,
        future: paSummary.future,
        tree: paSummary.tree,
        meta: paSummary.meta,
      } as PaAnalyzeResp
    : null

  // 仅在查看态拉取实时报价，编辑态不触发（避免逐字符输入引发请求风暴）
  const holdingQuotes = useMarketQuotes(
    analysisVisible && !editH ? holdings.list.map((h) => ({ market: h.market, symbol: h.code })) : [],
  )
  const watchQuotes = useMarketQuotes(
    marketVisible && !editW ? watchlist.list.map((w) => ({ market: w.market, symbol: w.sym })) : [],
  )

  const holdingRows = useMemo(
    () => holdings.list.map((h) => deriveHolding(h, holdingQuotes[quoteKey(h.market, h.code)])),
    [holdings.list, holdingQuotes],
  )
  const watchRows = useMemo(
    () => watchlist.list.map((w) => deriveWatch(w, watchQuotes[quoteKey(w.market, w.sym)])),
    [watchlist.list, watchQuotes],
  )
  const summary = useMemo(() => computeSummary(holdingRows, holdings.seedCash), [holdingRows, holdings.seedCash])
  const accountMetrics = accountScope === 'simulation'
    ? {
        totalLabel: '模拟账户权益',
        total: simulationAccount.data?.equity ?? 0,
        positionLabel: '模拟持仓',
        positions: simulationAccount.data?.positions.length ?? 0,
      }
    : accountScope === 'ledger'
      ? {
          totalLabel: '账本净值',
          total: ledgerSummary.data?.summary.nav ?? 0,
          positionLabel: '账本持仓',
          positions: ledgerSummary.data?.summary.n_positions ?? 0,
        }
      : {
          totalLabel: '研究组合总值',
          total: summary.nav,
          positionLabel: '研究持仓',
          positions: summary.totalPositions,
        }
  const accountScopeDescription = accountScope === 'simulation'
    ? '模拟账户：由模拟订单和成交驱动，不代表真实资产。'
    : accountScope === 'ledger'
      ? '账本账户：由账本成交、现金和持仓记录计算。'
      : '研究组合：由手工维护的研究持仓计算，不代表模拟账户或账本账户。'
  const moduleOrder = [
    ...dashboardLayout.order.filter((id) => DASHBOARD_MODULES.some((item) => item.id === id)),
    ...DASHBOARD_MODULES.map((item) => item.id).filter((id) => !dashboardLayout.order.includes(id)),
  ]

  function moveDashboardModule(id: DashboardModuleId, direction: -1 | 1) {
    setDashboardLayout((current) => {
      const order = [
        ...current.order.filter((item) => DASHBOARD_MODULES.some((module) => module.id === item)),
        ...DASHBOARD_MODULES.map((module) => module.id).filter((item) => !current.order.includes(item)),
      ]
      const index = order.indexOf(id)
      const target = index + direction
      if (index < 0 || target < 0 || target >= order.length) return current
      const next = [...order]
      ;[next[index], next[target]] = [next[target], next[index]]
      return { ...current, order: next }
    })
  }

  function setDashboardModuleVisible(id: DashboardModuleId, visible: boolean) {
    setDashboardLayout((current) => ({
      ...current,
      hidden: visible
        ? current.hidden.filter((item) => item !== id)
        : [...current.hidden.filter((item) => item !== id), id],
    }))
  }

  const breadthData = breadth.data
  const headerMetrics = [
    ...(accountVisible
      ? [{ label: accountMetrics.totalLabel, value: accountMetrics.total == null ? '—' : `¥${(accountMetrics.total ?? 0).toLocaleString('zh-CN')}` },
        { label: accountMetrics.positionLabel, value: accountMetrics.positions }]
      : []),
    ...(marketVisible && watchlist.seeded ? [{ label: '自选', value: watchlist.list.length }] : []),
    ...(marketVisible && breadthData ? [{ label: '涨/跌', value: `${breadthData.up}/${breadthData.down}` }] : []),
  ]
  const actionLoading = userAlerts.loading || failedTasks.loading || simulationOrders.loading
    || (isAdvanced && (pendingSignals.loading || pendingIncidents.loading || factorAttention.loading || automationAlerts.loading))
  const actionError = userAlerts.error || failedTasks.error || simulationOrders.error
    || (isAdvanced ? pendingSignals.error || pendingIncidents.error || factorAttention.error || automationAlerts.error : null)
  const actionReconnecting = userAlerts.reconnecting || failedTasks.reconnecting || simulationOrders.reconnecting
    || (isAdvanced && (pendingSignals.reconnecting || pendingIncidents.reconnecting || factorAttention.reconnecting || automationAlerts.reconnecting))
  const actionHasData = userAlerts.data !== null && failedTasks.data !== null && simulationOrders.data !== null
    && (!isAdvanced || (
      pendingSignals.data !== null
      && pendingIncidents.data !== null
      && factorAttention.data !== null
      && automationAlerts.data !== null
    ))

  async function toggleHoldingsEdit() {
    if (!editH) {
      setHoldingSaveError('')
      setEditH(true)
      return
    }
    setSavingH(true)
    setHoldingSaveError('')
    try {
      await holdings.commit()
      setEditH(false)
    } catch (error) {
      setHoldingSaveError(error instanceof Error ? error.message : '持仓保存失败')
    } finally {
      setSavingH(false)
    }
  }

  async function toggleWatchlistEdit() {
    if (!editW) {
      setWatchSaveError('')
      setEditW(true)
      return
    }
    setSavingW(true)
    setWatchSaveError('')
    try {
      await watchlist.commit()
      setEditW(false)
    } catch (error) {
      setWatchSaveError(error instanceof Error ? error.message : '关注列表保存失败')
    } finally {
      setSavingW(false)
    }
  }

  return (
    <>
      <WorkspaceHeader
        context="驾驶舱"
        title="总览"
        description="账户、行情与执行状态"
        metrics={headerMetrics}
      />
      {accountVisible ? <section className={s.accountScope} aria-label="驾驶舱账户口径">
        <div>
          <span>数据口径</span>
          <strong>{accountScopeDescription}</strong>
        </div>
        <SegmentedControl
          value={accountScope}
          onChange={(value) => setAccountScope(value as AccountScope)}
          options={[
            { value: 'research', label: '研究组合' },
            { value: 'simulation', label: '模拟账户' },
            { value: 'ledger', label: '账本账户' },
          ]}
        />
      </section> : null}
      <div className={s.layoutSettings}>
        <Button
          size="sm"
          variant="ghost"
          icon={<IconGrid size={16} />}
          aria-expanded={layoutSettingsOpen}
          aria-controls="overview-layout-settings"
          onClick={() => setLayoutSettingsOpen((open) => !open)}
        >
          布局设置
        </Button>
      </div>
      {layoutSettingsOpen ? (
        <section id="overview-layout-settings" className={s.layoutPanel} aria-label="总览布局设置">
          <header>
            <div>
              <strong>总览布局</strong>
              <span>调整当前界面的模块顺序与可见性</span>
            </div>
            <Button size="sm" variant="ghost" onClick={() => setLayoutSettingsOpen(false)}>完成</Button>
          </header>
          <div className={s.layoutRows}>
          {moduleOrder.map((id, index) => {
            const module = DASHBOARD_MODULES.find((item) => item.id === id)
            if (!module) return null
            const visible = moduleVisible(id)
            return <div key={id}>
              <strong>{module.label}</strong>
              <div>
                <Button size="sm" variant="link" disabled={index === 0} onClick={() => moveDashboardModule(id, -1)}>上移</Button>
                <Button size="sm" variant="link" disabled={index === moduleOrder.length - 1} onClick={() => moveDashboardModule(id, 1)}>下移</Button>
                <Toggle size="sm" checked={visible} onChange={(checked) => setDashboardModuleVisible(id, checked)} label={visible ? '显示' : '隐藏'} />
              </div>
            </div>
          })}
          </div>
        </section>
      ) : null}
      <div className={s.moduleStack}>
      {moduleVisible('evaluation') ? <div style={{ order: moduleOrder.indexOf('evaluation') }}>
      <section className={s.evaluationEntry} aria-labelledby="evaluation-entry-title">
        <div className={s.entryCopy}>
          <h2 id="evaluation-entry-title">标的评估</h2>
          <p>输入一个标的，自动汇总行情快照、新闻事件与价格结构到同一份研究记录。</p>
        </div>
        <div className={s.entryActions}>
          <Button variant="primary" size="lg" icon={<IconChart size={18} />} onClick={() => navigate('/evaluate')}>
            开始评估
          </Button>
          <Button size="lg" onClick={() => navigate('/tasks')}>
            历史记录
          </Button>
          <Button variant="ghost" size="lg" icon={<IconCog size={18} />} onClick={() => navigate('/config')}>
            数据设置
          </Button>
        </div>
      </section>
      </div> : null}
      {marketVisible ? <div style={{ order: moduleOrder.indexOf('market') }}>
      <section id="watchlist" className={s.marketDesk} aria-label="关注标的与市场广度">
        <Watchlist
          rows={watchRows}
          editing={editW}
          onAdd={() => watchlist.add('a_shares')}
          onUpdate={watchlist.update}
          onResolveName={watchlist.resolveName}
          onRemove={watchlist.remove}
          onToggleEdit={() => void toggleWatchlistEdit()}
          saving={savingW}
          saveError={watchSaveError || watchlist.mutationError}
          resolvingIds={watchlist.resolvingIds}
        />
        <AsyncStateBoundary
          loading={breadth.loading}
          error={breadth.error}
          reconnecting={breadth.reconnecting}
          hasData={breadth.data !== null}
          isEmpty={false}
          onRetry={breadth.refetch}
          loadingTitle="正在读取市场广度…"
          loadingSkeleton
          skeletonRows={2}
          emptyTitle="暂无市场广度"
        >
          <MarketBreadth data={breadth.data} />
        </AsyncStateBoundary>
      </section>
      </div> : null}
      {actionsVisible ? <div style={{ order: moduleOrder.indexOf('actions') }}>
      <AsyncStateBoundary
        loading={actionLoading}
        error={actionError}
        reconnecting={actionReconnecting}
        hasData={actionHasData}
        isEmpty={false}
        onRetry={() => {
          void userAlerts.refetch()
          void failedTasks.refetch()
          void simulationOrders.refetch()
          if (isAdvanced) {
            void pendingSignals.refetch()
            void pendingIncidents.refetch()
            void factorAttention.refetch()
            void automationAlerts.refetch()
          }
        }}
        loadingTitle="正在读取待处理事项…"
        loadingSkeleton
        skeletonRows={4}
        emptyTitle="暂无待处理事项"
      >
        <ActionQueue items={[
          { id: 'alerts', label: '待确认提醒', count: userAlerts.data?.count ?? 0, detail: firstPendingAlert ? `${firstPendingAlert.symbol} · ${firstPendingAlert.rule_name}` : '查看触发条件', to: firstPendingAlert ? alertEventHref(firstPendingAlert) : '/alerts', tone: 'warning' },
          { id: 'tasks', label: '失败分析任务', count: failedTasks.data?.total ?? 0, detail: '查看错误并重试', to: '/tasks?status=failed', tone: 'danger' },
          { id: 'orders', label: '需处理订单', count: simulationAttentionCount, detail: '待成交或同步失败', to: '/simulation', tone: 'warning' },
          ...(isAdvanced ? [
          { id: 'signals', label: '待审核信号', count: pendingSignals.data?.total ?? 0, detail: '进入审核队列', to: '/signals?status=new' },
          { id: 'factor-revalidation', label: '需复验研究', count: factorAttention.data?.counts.needs_revalidation ?? 0, detail: factorAttention.data?.items.find((item) => item.states.includes('needs_revalidation')) ? `${factorAttention.data.items.find((item) => item.states.includes('needs_revalidation'))?.symbol} · 查看窗口证据` : '查看多窗口一致性', to: factorAttention.data?.items.find((item) => item.states.includes('needs_revalidation')) ? `/factor-research?run_id=${encodeURIComponent(factorAttention.data.items.find((item) => item.states.includes('needs_revalidation'))!.run_id)}` : '/factor-research', tone: 'warning' },
          { id: 'factor-invalidated', label: '已失效研究', count: factorAttention.data?.counts.invalidated ?? 0, detail: factorAttention.data?.items.find((item) => item.states.includes('invalidated')) ? `${factorAttention.data.items.find((item) => item.states.includes('invalidated'))?.symbol} · 查看淘汰因子` : '查看已标记淘汰的因子', to: factorAttention.data?.items.find((item) => item.states.includes('invalidated')) ? `/factor-research?run_id=${encodeURIComponent(factorAttention.data.items.find((item) => item.states.includes('invalidated'))!.run_id)}` : '/factor-research', tone: 'danger' },
          { id: 'factor-stale', label: '数据过期研究', count: factorAttention.data?.counts.data_stale ?? 0, detail: factorAttention.data?.items.find((item) => item.states.includes('data_stale')) ? `${factorAttention.data.items.find((item) => item.states.includes('data_stale'))?.symbol} · 已超过 ${factorAttention.data.stale_hours} 小时` : '查看超过时效阈值的研究', to: factorAttention.data?.items.find((item) => item.states.includes('data_stale')) ? `/factor-research?run_id=${encodeURIComponent(factorAttention.data.items.find((item) => item.states.includes('data_stale'))!.run_id)}` : '/factor-research', tone: 'warning' },
          { id: 'automation', label: '自动化告警', count: automationAlerts.data?.count ?? 0, detail: '确认或重试失败运行', to: '/automation', tone: 'warning' },
          { id: 'incidents', label: '全部故障', count: pendingIncidents.data?.total ?? 0, detail: '跨域故障统一处置', to: '/incidents', tone: 'danger' },
          ] as const : []),
        ]} />
      </AsyncStateBoundary>
      </div> : null}
      {accountVisible && ((accountScope === 'simulation' && simulationAccount.error) || (accountScope === 'ledger' && ledgerSummary.error)) ? (
        <div className={s.accountError} role="alert">
          {accountScope === 'simulation' ? simulationAccount.error : ledgerSummary.error}
        </div>
      ) : null}
      {accountVisible ? <div style={{ order: moduleOrder.indexOf('account') }}>
      <KpiRow
        scope={accountScope}
        research={summary}
        simulation={simulationAccount.data}
        ledger={ledgerSummary.data?.summary ?? null}
      />
      </div> : null}
      {analysisVisible ? <div style={{ order: moduleOrder.indexOf('analysis') }}>
      <div className="grid-2">
        <div className="col-left">
          <KlineCard
            symbol={symbol}
            market={market}
            onSymbolChange={setSymbol}
            onMarketChange={(nextMarket) => {
              setMarket(nextMarket)
              setSymbol(nextMarket === 'us_stocks' ? 'NVDA' : nextMarket === 'crypto' ? 'BTC-USDT' : '600519')
            }}
          />
          <HoldingsTable
            rows={holdingRows}
            editing={editH}
            onAdd={() => holdings.add('a_shares')}
            onUpdate={holdings.update}
            onResolveName={holdings.resolveName}
            onRemove={holdings.remove}
            onToggleEdit={() => void toggleHoldingsEdit()}
            saving={savingH}
            saveError={holdingSaveError || holdings.mutationError}
            resolvingIds={holdings.resolvingIds}
          />
        </div>
        <div className="col-right">
          <DecisionPanel
            symbol={symbol}
            market={market}
            timeframe={recentPaRun?.timeframe ?? '1h'}
            researchRunId={recentPaRun?.id}
            initialData={recentPa}
          />
        </div>
      </div>
      </div> : null}
      </div>
    </>
  )
}
