import { useEffect, useMemo, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { useApi } from '../api/useApi'
import type { BacktestResp, RunResp, SignalResp } from '../api/types'
import {
  defaultParams,
  INTERVAL_OPTIONS,
  MARKET_OPTIONS,
  marketBadge,
  StructuredParamsEditor,
  SignalResults,
} from '../components/StrategyShared'
import { DirectionDonut, ScoreHistogram } from '../components/SignalViz'
import EquityCurve from '../components/EquityCurve'
import { Table } from '../components/ui/Table'
import { useStrategyRuns } from '../hooks/useStrategyRuns'
import { useStrategyPresets } from '../hooks/useStrategyPresets'
import { useSignals } from '../hooks/useSignals'
import { formatRelativeTime } from '../lib/time'
import { Button } from '../components/ui/Button/Button'
import { AsyncStateBoundary } from '../components/ui/AsyncStateBoundary/AsyncStateBoundary'
import { ConfirmActionButton } from '../components/ui/ConfirmActionButton/ConfirmActionButton'
import { Input } from '../components/ui/Input/Input'
import { Select } from '../components/ui/Select/Select'
import { SegmentedControl } from '../components/ui/SegmentedControl/SegmentedControl'
import { Tag } from '../components/ui/Tag/Tag'
import { WorkspaceHeader } from '../components/WorkspaceHeader/WorkspaceHeader'
import s from './StrategyDetailPage.module.css'

type Tab = 'overview' | 'run' | 'backtest' | 'history' | 'signals'

/** Tab 列表：原 7 Tab 精简为 5 Tab。「参数」已合并进「运行」（运行 Tab 含 ParamsEditor）；
 *  「实盘」已合并进「概览」（实盘状态作为 stat-tile + 模拟 Tick 小节）。 */
const TAB_LIST: { key: Tab; label: string }[] = [
  { key: 'overview', label: '概览' },
  { key: 'run', label: '运行' },
  { key: 'backtest', label: '回测' },
  { key: 'history', label: '历史' },
  { key: 'signals', label: '信号' },
]

function paramsPreview(params: Record<string, unknown>) {
  return Object.entries(params)
    .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : String(v)}`)
    .join(' · ')
}

export default function StrategyDetailPage() {
  const { name } = useParams<{ name: string }>()
  const [searchParams] = useSearchParams()
  const strategies = useApi(() => api.strategies(), [])
  const strategy = strategies.data?.strategies.find((item) => item.name === name)

  const { addRun, runsFor } = useStrategyRuns()
  const { forStrategy, save, remove } = useStrategyPresets()
  const presets = name ? forStrategy(name) : []
  const history = name ? runsFor(name, 8) : []
  // 信号总线（与信号中心同源）：运行策略后总线自动填充，彻底消除双源割裂。
  const { signals: busSignals, refetch: refetchBus } = useSignals(name)

  const [params, setParams] = useState<Record<string, unknown>>(() => defaultParams(name ?? ''))
  const [runResult, setRunResult] = useState<RunResp | null>(null)
  const [running, setRunning] = useState(false)
  const [runError, setRunError] = useState('')
  const [presetName, setPresetName] = useState('')
  const [loadedPreset, setLoadedPreset] = useState('')
  const [presetMessage, setPresetMessage] = useState('')
  const [presetError, setPresetError] = useState('')

  // ?tab= 直达（列表卡片「回测」按钮跳 /strategies/:name?tab=backtest）
  // 兼容旧 Tab 值：'params' → 'run'（已合并），'live' → 'overview'（已合并）
  const rawTab = searchParams.get('tab') as Tab | 'params' | 'live' | null
  const initialTab: Tab =
    rawTab === 'backtest' || rawTab === 'run' || rawTab === 'history' || rawTab === 'signals'
      ? rawTab
      : 'overview'
  const [tab, setTab] = useState<Tab>(initialTab)

  // ---- G6 回测 ----
  const [btSymbol, setBtSymbol] = useState('600519')
  const [btMarket, setBtMarket] = useState('a_shares')
  const [btInterval, setBtInterval] = useState('1d')
  const [btLimit, setBtLimit] = useState(300)
  const [btCapital, setBtCapital] = useState(100000)
  const [btResult, setBtResult] = useState<BacktestResp | null>(null)
  const [btRunning, setBtRunning] = useState(false)
  const [btError, setBtError] = useState('')

  useEffect(() => {
    if (!strategy) return
    setBtMarket(strategy.market)
    if (strategy.market === 'mt5') {
      setBtSymbol('XAUUSD')
      setBtInterval('1h')
    }
  }, [strategy?.name, strategy?.market])

  async function handleBacktest() {
    if (!name) return
    setBtRunning(true)
    setBtError('')
    setBtResult(null)
    try {
      const resp = await api.backtest(name, {
        symbol: btSymbol,
        market: btMarket,
        interval: btInterval,
        limit: btLimit,
        initial_capital: btCapital,
      })
      setBtResult(resp)
    } catch (err) {
      setBtError(err instanceof Error ? err.message : '回测失败')
    } finally {
      setBtRunning(false)
    }
  }

  // ---- G5 实盘（paper）----
  const liveInfo = useApi(
    () => (name ? api.liveStatus(name) : Promise.resolve(null)),
    [name],
    { resetKey: name },
  )
  const [liveState, setLiveState] = useState<unknown>(null)
  const [liveRunning, setLiveRunning] = useState(false)
  const [liveError, setLiveError] = useState('')

  async function handleLiveTick() {
    if (!name) return
    setLiveRunning(true)
    setLiveError('')
    try {
      const resp = await api.liveTick(name)
      setLiveState(resp.state ?? null)
    } catch (err) {
      setLiveError(err instanceof Error ? err.message : '实盘 tick 失败')
    } finally {
      setLiveRunning(false)
    }
  }

  const lastOkRun = useMemo(
    () => history.find((h) => h.result.ok && h.result.signals.length > 0),
    [history],
  )
  const vizSignals: SignalResp[] =
    busSignals.length > 0
      ? busSignals
      : runResult && runResult.signals.length > 0
        ? runResult.signals
        : lastOkRun?.result.signals ?? []

  async function handleRun() {
    if (!name) return
    setRunning(true)
    setRunError('')
    setRunResult(null)
    try {
      const resp = await api.runStrategy(name, params)
      setRunResult(resp)
      try {
        await addRun(name, params, resp)
      } catch (reason) {
        setRunError(`策略已运行，但历史保存失败：${reason instanceof Error ? reason.message : '未知错误'}`)
      }
      // 运行后总线已写入该策略信号，刷新以与信号中心保持同源
      void refetchBus()
    } catch (err) {
      setRunError(err instanceof Error ? err.message : '运行失败')
    } finally {
      setRunning(false)
    }
  }

  async function savePreset() {
    if (!name || !presetName.trim()) return
    setPresetError('')
    setPresetMessage('')
    try {
      await save(name, presetName.trim(), params)
      setPresetMessage(`预设 ${presetName.trim()} 已保存`)
      setPresetName('')
    } catch (reason) {
      setPresetError(reason instanceof Error ? reason.message : '预设保存失败')
    }
  }

  async function removePreset(presetId: string, presetLabel: string) {
    if (!name) return
    setPresetError('')
    setPresetMessage('')
    try {
      await remove(name, presetId)
      if (loadedPreset === presetLabel) setLoadedPreset('')
      setPresetMessage(`预设 ${presetLabel} 已删除`)
    } catch (reason) {
      setPresetError(reason instanceof Error ? reason.message : '预设删除失败')
    }
  }

  if (!strategies.data) {
    return (
      <div className="card">
        <AsyncStateBoundary
          loading={strategies.loading}
          error={strategies.error}
          reconnecting={strategies.reconnecting}
          hasData={false}
          isEmpty={false}
          onRetry={strategies.refetch}
          loadingTitle="正在读取策略详情…"
          emptyTitle="暂无策略详情"
        >
          <div />
        </AsyncStateBoundary>
      </div>
    )
  }

  if (!strategy) {
    return (
      <div className="card">
        <div className="card-head">
          <div className="card-title">未找到策略</div>
        </div>
        <div className={s.notFoundBody}>
          <div className={`muted ${s.notFoundHint}`}>
            策略 <code>{name}</code> 未注册或已被移除。
          </div>
          <Link to="/strategies" className={`link-btn ${s.backLink}`}>
            ← 返回策略模块列表
          </Link>
        </div>
      </div>
    )
  }

  return (
    <>
      <WorkspaceHeader
        context="策略 / 策略运行"
        title={`${strategy?.name ?? '策略'} 运行工作台`}
        description={strategy?.description}
        metrics={[
          { label: '市场', value: marketBadge(strategy?.market ?? '') },
          { label: '实盘', value: strategy?.live_capable ? '可' : '否' },
        ]}
      />
    <div className="card" data-board="workbench">
      <div className="card-head">
        <div className={`card-title ${s.titleRow}`}>
          <Link
            to="/strategies"
            className={`muted ${s.backArrow}`}
            title="返回策略模块列表"
          >
            ←
          </Link>
          <span>{strategy.name}</span>
          <Tag variant="accent">{marketBadge(strategy.market)}</Tag>
          {/* M2-04：如实标注为策略自声明，避免被误读为「已核准可实盘」 */}
          {strategy.live_capable && <Tag variant="accent">声明支持实盘</Tag>}
        </div>
      </div>

      <div className={s.operationBar}>
        <span><small>状态</small><b className={running ? s.runningState : s.stoppedState}>{running ? '运行中' : '已停止'}</b></span>
        <span><small>参数</small><b>{paramsPreview(params) || '无参数'}</b></span>
        <span><small>最近结果</small><b>{runResult ? `${runResult.count} 条信号` : lastOkRun ? `${lastOkRun.result.count} 条信号` : '—'}</b></span>
        <div>
          <Button variant="primary" size="sm" onClick={() => { setTab('run'); void handleRun() }} loading={running}>运行</Button>
          <Button size="sm" onClick={() => setTab('backtest')}>回测</Button>
        </div>
      </div>

      <div className="detail-tabs">
        <SegmentedControl
          value={tab}
          onChange={(v) => setTab(v as Tab)}
          options={TAB_LIST.map((t) => ({ value: t.key, label: t.label }))}
          size="sm"
          className={s.tabsWrap}
        />
      </div>

      <div className="detail-body">
        {/* 概览 */}
        {tab === 'overview' && (
          <>
            <div className="detail-section">
              <div className="detail-section-title">策略说明</div>
              <p className="detail-desc">{strategy.description || '暂无描述'}</p>
            </div>
            <div className="overview-stats">
              <div className="stat-tile">
                <span className="k">市场</span>
                <span className="v">{marketBadge(strategy.market)}</span>
              </div>
              <div className="stat-tile">
                <span className="k">实盘能力（自声明）</span>
                <span className="v" title="来自策略元数据 live_capable，非实盘核准结果；能否真实下单由交易通道审批决定">
                  {strategy.live_capable ? '声明支持实盘' : '仅回测 / 分析'}
                </span>
              </div>
              <div className="stat-tile">
                <span className="k">当前模式</span>
                <span className="v mono">{liveInfo.data?.is_live ? 'LIVE' : 'PAPER'}</span>
              </div>
              <div className="stat-tile">
                <span className="k">参数预设</span>
                <span className="v mono">{presets.length}</span>
              </div>
              <div className="stat-tile">
                <span className="k">运行次数</span>
                <span className="v mono">{history.length}</span>
              </div>
              <div className="stat-tile">
                <span className="k">最近运行</span>
                <span className={`v ${s.statValueSmall}`}>
                  {history[0] ? formatRelativeTime(history[0].ts) : '—'}
                </span>
              </div>
              <div className="stat-tile">
                <span className="k">上次信号数</span>
                <span className="v mono">
                  {lastOkRun ? lastOkRun.result.count : '—'}
                </span>
              </div>
            </div>
            <div className="detail-section">
              <div className="detail-section-title">信号分布</div>
              {vizSignals.length > 0 ? (
                <>
                  <DirectionDonut signals={vizSignals} />
                  <div className={s.histogramWrap}>
                    <ScoreHistogram signals={vizSignals} />
                  </div>
                </>
              ) : (
                <div className="empty-hint">暂无运行记录</div>
              )}
            </div>
            {/* 实盘状态：原独立 Tab 已合并到概览（信息密度低，作为概览末尾小节） */}
            <div className="detail-section">
              <div className="detail-section-title">实盘状态</div>
              <AsyncStateBoundary
                loading={liveInfo.loading}
                error={liveInfo.error}
                reconnecting={liveInfo.reconnecting}
                hasData={liveInfo.data !== null}
                isEmpty={false}
                onRetry={liveInfo.refetch}
                loadingTitle="正在读取实盘状态…"
                emptyTitle="暂无实盘状态"
              >
                <>
                  <div className="bus-hint warn">
                    {liveInfo.data?.note ||
                      '实盘需要交易所/券商 API 配置；未配置时 live_tick 为 no-op（模拟态），不产生真实成交。'}
                  </div>
                  <div className="detail-actions">
                    <Button
                      variant="primary"
                      size="sm"
                      onClick={handleLiveTick}
                      loading={liveRunning}
                    >
                      {liveRunning ? 'Tick 中…' : '模拟一次 Tick'}
                    </Button>
                  </div>
                  {liveError && <div className="run-error">{liveError}</div>}
                  {liveState != null && (
                    <pre className="live-state">{JSON.stringify(liveState, null, 2)}</pre>
                  )}
                </>
              </AsyncStateBoundary>
            </div>
            <div className="detail-actions">
              <Button
                variant="primary"
                size="sm"
                onClick={() => {
                  setTab('run')
                  void handleRun()
                }}
              >
                快速运行
              </Button>
              <Button variant="link" size="sm" onClick={() => setTab('run')}>
                配置参数
              </Button>
            </div>
          </>
        )}

        {/* 运行（含参数编辑 + 运行 + 参数预设，原「参数」Tab 已合并） */}
        {tab === 'run' && (
          <>
            <div className="detail-section">
              <div className="detail-section-title">运行参数</div>
              <StructuredParamsEditor name={strategy.name} params={params} onChange={setParams} />
              <div className="detail-actions">
                <Button
                  variant="primary"
                  size="sm"
                  onClick={handleRun}
                  loading={running}
                >
                  {running ? '运行中…' : '运行策略'}
                </Button>
                <Button
                  variant="link"
                  size="sm"
                  onClick={() => setParams({ ...defaultParams(strategy.name) })}
                >
                  重置默认参数
                </Button>
              </div>
              {runError && <div className="run-error">{runError}</div>}
            </div>

            {runResult && (
              <div className="detail-section">
                <div className="detail-section-title">运行结果</div>
                <div className={`signal-result-summary ${s.resultSummary}`}>
                  {runResult.ok
                    ? runResult.signals.length > 0
                      ? `产出 ${runResult.count} 条信号`
                      : '运行成功，但未产出信号'
                    : `运行失败${runResult.error ? ' · ' + runResult.error : ''}`}
                </div>
                {runResult.ok && runResult.signals.length > 0 && (
                  <Button variant="primary" size="sm" onClick={() => setTab('signals')}>
                    查看完整信号分析 →
                  </Button>
                )}
              </div>
            )}

            {/* 参数预设（原「参数」Tab 迁移至此） */}
            <div className="detail-section">
              <div className="detail-section-title">
                参数预设
                <span className="local-hint">后端保存 · 跨设备同步</span>
              </div>
              <div className="preset-add">
                <Input
                  placeholder="预设名称，如 激进 / 稳健"
                  value={presetName}
                  onChange={(e) => setPresetName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') void savePreset()
                  }}
                />
                <Button
                  variant="primary"
                  size="sm"
                  disabled={!presetName.trim() || !name}
                  onClick={() => void savePreset()}
                >
                  保存当前为预设
                </Button>
              </div>

              {presets.length > 0 ? (
                <div className="preset-list">
                  {presets.map((p) => (
                    <div className="preset-row" key={p.id}>
                      <span className="preset-name" title={p.name}>
                        {p.name}
                      </span>
                      <div className="preset-actions">
                        <Button
                          variant="link"
                          size="sm"
                          onClick={() => {
                            setParams({ ...p.params })
                            setLoadedPreset(p.name)
                          }}
                        >
                          加载
                        </Button>
                        <ConfirmActionButton
                          label="删除"
                          title="确认删除参数预设"
                          description={`删除预设 ${p.name} 后无法从后端预设列表恢复。策略运行历史不会被删除。`}
                          confirmLabel="确认删除"
                          variant="link"
                          onConfirm={() => removePreset(p.id, p.name)}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className={`muted ${s.mutedSmall}`}>
                  暂无参数预设
                </div>
              )}

              {loadedPreset && (
                <div className="local-hint ok">已加载预设：{loadedPreset}</div>
              )}
              {presetMessage && <div className="local-hint ok" role="status">{presetMessage}</div>}
              {presetError && <div className="run-error" role="alert">{presetError}</div>}
            </div>
          </>
        )}

        {/* 回测（G6：接真实 backtest()，替代原重复的「假回测」页） */}
        {tab === 'backtest' && (
          <>
            <div className="detail-section">
              <div className="detail-section-title">回测设置</div>
              <div className="bt-form">
                <label className="bt-field">
                  <span>标的</span>
                  <Input value={btSymbol} onChange={(e) => setBtSymbol(e.target.value)} />
                </label>
                <label className="bt-field">
                  <span>市场</span>
                  <Select
                    options={MARKET_OPTIONS}
                    value={btMarket}
                    onChange={(e) => setBtMarket(e.target.value)}
                  />
                </label>
                <label className="bt-field">
                  <span>周期</span>
                  <Select
                    options={INTERVAL_OPTIONS}
                    value={btInterval}
                    onChange={(e) => setBtInterval(e.target.value)}
                  />
                </label>
                <label className="bt-field">
                  <span>K线数</span>
                  <Input
                    type="number"
                    value={btLimit}
                    onChange={(e) => setBtLimit(Number(e.target.value) || 300)}
                  />
                </label>
                <label className="bt-field">
                  <span>初始资金</span>
                  <Input
                    type="number"
                    value={btCapital}
                    onChange={(e) => setBtCapital(Number(e.target.value) || 100000)}
                  />
                </label>
              </div>
              <div className="detail-actions">
                <Button
                  variant="primary"
                  size="sm"
                  onClick={handleBacktest}
                  loading={btRunning}
                  disabled={btRunning || !btSymbol.trim()}
                >
                  {btRunning ? '回测中…' : '运行回测'}
                </Button>
              </div>
              {btError && <div className="run-error">{btError}</div>}
            </div>

            {btResult && (
              <div className="detail-section">
                <div className="detail-section-title">回测结果</div>
                {!btResult.ok ? (
                  <div className="run-error">{btResult.error || '回测失败'}</div>
                ) : (
                  <>
                    <div className="overview-stats">
                      <div className="stat-tile">
                        <span className="k">引擎</span>
                        <span className="v mono">{btResult.summary?.engine ?? '—'}</span>
                      </div>
                      <div className="stat-tile">
                        <span className="k">收益率</span>
                        <span
                          className={`v mono ${
                            (btResult.summary?.total_return ?? 0) >= 0 ? s.returnPositive : s.returnNegative
                          }`}
                        >
                          {((btResult.summary?.total_return ?? 0) * 100).toFixed(2)}%
                        </span>
                      </div>
                      <div className="stat-tile">
                        <span className="k">最大回撤</span>
                        <span className={`v mono ${s.maxDrawdown}`}>
                          {((btResult.summary?.max_drawdown ?? 0) * 100).toFixed(2)}%
                        </span>
                      </div>
                      <div className="stat-tile">
                        <span className="k">成交数</span>
                        <span className="v mono">{btResult.summary?.n_trades ?? 0}</span>
                      </div>
                      <div className="stat-tile">
                        <span className="k">夏普</span>
                        <span className="v mono">
                          {btResult.summary?.metrics?.sharpe?.toFixed(2) ?? '—'}
                        </span>
                      </div>
                      <div className="stat-tile">
                        <span className="k">胜率</span>
                        <span className="v mono">
                          {btResult.summary?.metrics?.win_rate != null
                            ? `${(btResult.summary.metrics.win_rate * 100).toFixed(1)}%`
                            : '—'}
                        </span>
                      </div>
                    </div>

                    {btResult.equity.length > 1 && (
                      <div className="bt-equity">
                        <div className="detail-section-title">权益曲线</div>
                        <EquityCurve points={btResult.equity} initial={btCapital} />
                      </div>
                    )}

                    <div className={`detail-section-title ${s.tradesTitle}`}>
                      成交明细
                    </div>
                    {btResult.trades.length > 0 ? (
                      <Table
                        rows={btResult.trades.slice(0, 50)}
                        rowKey={(_, i) => String(i)}
                        columns={[
                          { key: 'idx', header: '#', render: (_, i) => <span className="mono">{(i ?? 0) + 1}</span> },
                          { key: 'entry', header: '开仓', render: (t) => <span className="mono">{String(t.entry_time ?? t.entry ?? '—')}</span> },
                          { key: 'exit', header: '平仓', render: (t) => <span className="mono">{String(t.exit_time ?? t.exit ?? '—')}</span> },
                          {
                            key: 'pnl',
                            header: '盈亏',
                            align: 'right',
                            render: (t) => {
                              const pnl = Number(t.pnl ?? 0)
                              return <span className={s.pnlCell} data-positive={pnl >= 0}><span className="mono">{pnl.toFixed(2)}</span></span>
                            },
                          },
                          {
                            key: 'ret',
                            header: '收益%',
                            align: 'right',
                            render: (t) => {
                              const ret = Number(t.return_pct ?? t.ret_pct ?? 0)
                              return <span className={s.pnlCell} data-positive={ret >= 0}><span className="mono">{ret.toFixed(2)}%</span></span>
                            },
                          },
                        ]}
                      />
                    ) : (
                      <div className={`muted ${s.mutedSmall}`}>
                        该回测未返回逐笔成交（策略 backtest() 未产出 trades）。
                      </div>
                    )}
                  </>
                )}
              </div>
            )}
          </>
        )}

        {/* 历史 */}
        {tab === 'history' && (
          <div className="detail-section">
            <div className="detail-section-title">运行历史</div>
            {history.length > 0 ? (
              <div className="run-history">
                {history.map((h) => (
                  <div className="run-record" key={h.id}>
                    <div className="run-record-head">
                      <span className="run-record-time">{formatRelativeTime(h.ts)}</span>
                      <span className={`run-record-status ${h.result.ok ? 'ok' : 'err'}`}>
                        {h.result.ok ? `成功 · ${h.result.count} 条` : '失败'}
                      </span>
                    </div>
                    <div className="run-record-params">{paramsPreview(h.params)}</div>
                    <Button
                      variant="link"
                      size="sm"
                      className={s.restoreBtn}
                      onClick={() => {
                        setParams({ ...h.params })
                        setRunResult(h.result)
                        setRunError('')
                        setTab('signals')
                      }}
                    >
                      恢复结果与参数
                    </Button>
                  </div>
                ))}
              </div>
            ) : (
              <div className={`muted ${s.mutedSmall}`}>
                暂无运行记录。
              </div>
            )}
          </div>
        )}

        {/* 信号 */}
        {tab === 'signals' && (
          <div className="detail-section">
            <div className="detail-section-title">信号结果</div>
            <div className="bus-hint">
              信号读取自全局总线（与「信号中心」同源）；运行策略后会自动写入并显示。
            </div>
            {busSignals.length > 0 ? (
              <SignalResults signals={busSignals} />
            ) : runResult && runResult.ok && runResult.signals.length > 0 ? (
              <SignalResults signals={runResult.signals} />
            ) : lastOkRun && lastOkRun.result.ok ? (
              <>
                <div className={`signal-result-summary ${s.resultSummary}`}>
                  显示最近一次运行（{formatRelativeTime(lastOkRun.ts)}）的 {lastOkRun.result.count} 条信号。
                </div>
                <SignalResults signals={lastOkRun.result.signals} />
              </>
            ) : (
              <div className="empty-hint">请先在「运行」页运行策略以生成信号。</div>
            )}
          </div>
        )}
      </div>
    </div>
    </>
  )
}
