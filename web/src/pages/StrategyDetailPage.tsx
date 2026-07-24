import { useMemo, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { useApi } from '../api/useApi'
import type { BacktestResp, LiveResp, RunResp, SignalResp } from '../api/types'
import {
  defaultParams,
  marketBadge,
  ParamsEditor,
  SignalRow,
  summarize,
} from '../components/StrategyShared'
import { DirectionDonut, ScoreHistogram } from '../components/SignalViz'
import { useStrategyRuns } from '../hooks/useStrategyRuns'
import { useStrategyPresets } from '../hooks/useStrategyPresets'
import { useSignals } from '../hooks/useSignals'
import { matchDir } from '../lib/signal-utils'
import { formatRelativeTime } from '../lib/time'

type Tab = 'overview' | 'params' | 'run' | 'history' | 'signals' | 'backtest' | 'live'

function paramsPreview(params: Record<string, unknown>) {
  return Object.entries(params)
    .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : String(v)}`)
    .join(' · ')
}

/** 运行结果区块：方向环图 + 分数分布 + 方向筛选 + 排序 + 信号卡片列表。供「运行」「信号」两个 Tab 复用。 */
function SignalResults({ signals }: { signals: SignalResp[] }) {
  const [dirFilter, setDirFilter] = useState<'all' | 'buy' | 'sell' | 'hold'>('all')
  const [sortBy, setSortBy] = useState<'time' | 'score' | 'confidence'>('score')

  const filtered = useMemo(() => {
    let list = signals.filter((s) => matchDir(s.direction, dirFilter))
    return [...list].sort((a, b) => {
      if (sortBy === 'score') return b.score - a.score
      if (sortBy === 'confidence') return b.confidence - a.confidence
      return 0
    })
  }, [signals, dirFilter, sortBy])

  return (
    <>
      <DirectionDonut signals={signals} />
      <div style={{ marginTop: 'var(--sp-3)' }}>
        <ScoreHistogram signals={signals} />
      </div>
      <div className="signal-result-head" style={{ marginTop: 'var(--sp-3)' }}>
        <div className="signal-result-summary">{summarize(signals)}</div>
      </div>
      <div className="signal-filter-bar">
        <div className="signal-filters">
          {(
            [
              ['all', '全部'],
              ['buy', '做多'],
              ['sell', '做空'],
              ['hold', '观望'],
            ] as const
          ).map(([k, l]) => (
            <button
              key={k}
              className="period-tab"
              onClick={() => setDirFilter(k)}
              style={{
                background: dirFilter === k ? 'var(--accent)' : 'var(--bg-subtle)',
                color: dirFilter === k ? '#fff' : 'var(--text-1)',
                border: dirFilter === k ? '1px solid var(--accent)' : '1px solid var(--border)',
              }}
            >
              {l}
            </button>
          ))}
        </div>
        <select
          className="edit-input"
          style={{ width: 110, flex: '0 0 auto' }}
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value as typeof sortBy)}
        >
          <option value="score">按分数</option>
          <option value="confidence">按置信度</option>
          <option value="time">按时间</option>
        </select>
      </div>
      <div className="signal-list">
        {filtered.map((sig, idx) => (
          <SignalRow key={`${sig.symbol}-${idx}`} sig={sig} />
        ))}
        {filtered.length === 0 && <div className="muted">当前筛选下无信号</div>}
      </div>
    </>
  )
}

/** 权益曲线（纯 SVG，零依赖）。points 为 {t, equity} 序列。 */
function EquityCurve({ points, initial }: { points: Array<{ t: string | null; equity: number }>; initial: number }) {
  const W = 720
  const H = 200
  const pad = 24
  if (points.length < 2) return null
  const eqs = points.map((p) => p.equity)
  const min = Math.min(initial, ...eqs)
  const max = Math.max(initial, ...eqs)
  const span = max - min || 1
  const stepX = (W - pad * 2) / (points.length - 1)
  const y = (v: number) => H - pad - ((v - min) / span) * (H - pad * 2)
  const x = (i: number) => pad + i * stepX
  const d = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(p.equity).toFixed(1)}`).join(' ')
  const baseY = y(initial)
  const lastUp = points[points.length - 1].equity >= initial
  const stroke = lastUp ? 'var(--up-ink)' : 'var(--down-ink)'
  return (
    <svg className="bt-equity-svg" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label="权益曲线">
      <line x1={pad} y1={baseY} x2={W - pad} y2={baseY} stroke="var(--border)" strokeDasharray="3 3" />
      <path d={d} fill="none" stroke={stroke} strokeWidth={2} />
    </svg>
  )
}

export default function StrategyDetailPage() {
  const { name } = useParams<{ name: string }>()
  const [searchParams] = useSearchParams()
  const strategies = useApi(() => api.strategies(), [])
  const strategy = strategies.data?.strategies.find((s) => s.name === name)

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

  // ?tab= 直达（侧栏「回测工作台」可跳 /strategies/supertrend?tab=backtest）
  const initialTab = (searchParams.get('tab') as Tab | null) || 'overview'
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
  const liveInfo = useApi(() => (name ? api.liveStatus(name) : Promise.resolve(null)), [name])
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
      addRun(name, params, resp)
      // 运行后总线已写入该策略信号，刷新以与信号中心保持同源
      void refetchBus()
    } catch (err) {
      setRunError(err instanceof Error ? err.message : '运行失败')
    } finally {
      setRunning(false)
    }
  }

  if (strategies.loading) {
    return (
      <div className="card">
        <div className="card-head">
          <div className="card-title">加载中…</div>
        </div>
      </div>
    )
  }

  if (!strategy) {
    return (
      <div className="card">
        <div className="card-head">
          <div className="card-title">未找到策略</div>
        </div>
        <div style={{ padding: 'var(--sp-3)' }}>
          <div className="muted" style={{ marginBottom: 'var(--sp-3)' }}>
            策略 <code>{name}</code> 未注册或已被移除。
          </div>
          <Link to="/strategies" className="period-tab" style={{ textDecoration: 'none' }}>
            ← 返回策略模块列表
          </Link>
        </div>
      </div>
    )
  }

  const tabs: { key: Tab; label: string }[] = [
    { key: 'overview', label: '概览' },
    { key: 'params', label: '参数' },
    { key: 'run', label: '运行' },
    { key: 'backtest', label: '回测' },
    { key: 'history', label: '历史' },
    { key: 'signals', label: '信号' },
    { key: 'live', label: '实盘' },
  ]

  return (
    <div className="card" data-board="workbench">
      <div className="card-head">
        <div className="card-title" style={{ alignItems: 'center', gap: 'var(--sp-2)' }}>
          <Link
            to="/strategies"
            className="muted"
            style={{ textDecoration: 'none', fontSize: 'var(--fs-18)', lineHeight: 1 }}
            title="返回策略模块列表"
          >
            ←
          </Link>
          <span>{strategy.name}</span>
          <span className="strategy-card-badge market">{marketBadge(strategy.market)}</span>
          {strategy.live_capable && <span className="strategy-card-badge live">可实盘</span>}
        </div>
      </div>

      <div className="detail-tabs">
        <div className="period-tabs" role="tablist" aria-label="策略工作台">
          {tabs.map((t) => (
            <button
              key={t.key}
              role="tab"
              aria-selected={tab === t.key}
              className={`period-tab ${tab === t.key ? 'active' : ''}`}
              onClick={() => setTab(t.key)}
            >
              {t.label}
            </button>
          ))}
        </div>
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
                <span className="k">实盘能力</span>
                <span className="v">{strategy.live_capable ? '可实盘' : '回测/分析'}</span>
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
                <span className="v" style={{ fontSize: 'var(--fs-13)' }}>
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
                  <div style={{ marginTop: 'var(--sp-3)' }}>
                    <ScoreHistogram signals={vizSignals} />
                  </div>
                </>
              ) : (
                <div className="empty-hint">
                  暂无运行记录。前往「运行」页运行策略后，这里会展示方向占比与分数分布。
                </div>
              )}
            </div>
            <div className="detail-actions">
              <button
                className="period-tab"
                onClick={() => {
                  setTab('run')
                  void handleRun()
                }}
                style={{ background: 'var(--accent)', color: '#fff' }}
              >
                快速运行
              </button>
              <button className="link-btn" onClick={() => setTab('params')}>
                配置参数
              </button>
            </div>
          </>
        )}

        {/* 参数 */}
        {tab === 'params' && (
          <div className="detail-section">
            <div className="detail-section-title">运行参数</div>
            <ParamsEditor name={strategy.name} params={params} onChange={setParams} />

            <div className="preset-block">
              <div className="detail-section-title">
                参数预设
                <span className="local-hint">本机保存 · 不跨设备</span>
              </div>
              <div className="preset-add">
                <input
                  className="edit-input"
                  placeholder="预设名称，如 激进 / 稳健"
                  value={presetName}
                  onChange={(e) => setPresetName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && presetName.trim() && name) {
                      save(name, presetName.trim(), params)
                      setPresetName('')
                    }
                  }}
                />
                <button
                  className="period-tab"
                  disabled={!presetName.trim() || !name}
                  onClick={() => {
                    if (!presetName.trim() || !name) return
                    save(name, presetName.trim(), params)
                    setPresetName('')
                  }}
                  style={{ background: 'var(--accent)', color: '#fff' }}
                >
                  保存当前为预设
                </button>
              </div>

              {presets.length > 0 ? (
                <div className="preset-list">
                  {presets.map((p) => (
                    <div className="preset-row" key={p.id}>
                      <span className="preset-name" title={p.name}>
                        {p.name}
                      </span>
                      <div className="preset-actions">
                        <button
                          className="link-btn"
                          onClick={() => {
                            setParams({ ...p.params })
                            setLoadedPreset(p.name)
                          }}
                        >
                          加载
                        </button>
                        <button
                          className="link-btn"
                          onClick={() => {
                            if (name) remove(name, p.id)
                            if (loadedPreset === p.name) setLoadedPreset('')
                          }}
                        >
                          删除
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="muted" style={{ fontSize: 'var(--fs-13)' }}>
                  暂无预设。调整参数后点击「保存当前为预设」即可复用。
                </div>
              )}

              {loadedPreset && (
                <div className="local-hint ok">已加载预设：{loadedPreset}</div>
              )}
            </div>

            <div className="detail-actions">
              <button
                className="link-btn"
                onClick={() => setParams({ ...defaultParams(strategy.name) })}
              >
                重置默认参数
              </button>
            </div>
          </div>
        )}

        {/* 运行 */}
        {tab === 'run' && (
          <>
            <div className="detail-section">
              <div className="detail-section-title">运行参数</div>
              <ParamsEditor name={strategy.name} params={params} onChange={setParams} />
              <div className="detail-actions">
                <button
                  className="period-tab"
                  onClick={handleRun}
                  disabled={running}
                  style={{
                    background: 'var(--accent)',
                    color: '#fff',
                    opacity: running ? 0.7 : 1,
                  }}
                >
                  {running ? '运行中…' : '运行策略'}
                </button>
                <button
                  className="link-btn"
                  onClick={() => setParams({ ...defaultParams(strategy.name) })}
                >
                  重置默认参数
                </button>
              </div>
              {runError && <div className="run-error">{runError}</div>}
            </div>

            {runResult && (
              <div className="detail-section">
                <div className="detail-section-title">运行结果</div>
                <div className="signal-result-summary" style={{ marginBottom: 'var(--sp-3)' }}>
                  {runResult.ok
                    ? runResult.signals.length > 0
                      ? `产出 ${runResult.count} 条信号`
                      : '运行成功，但未产出信号'
                    : `运行失败${runResult.error ? ' · ' + runResult.error : ''}`}
                </div>
                {runResult.ok && runResult.signals.length > 0 && (
                  <button
                    className="period-tab"
                    onClick={() => setTab('signals')}
                    style={{ background: 'var(--accent)', color: '#fff' }}
                  >
                    查看完整信号分析 →
                  </button>
                )}
              </div>
            )}
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
                  <input
                    className="edit-input"
                    value={btSymbol}
                    onChange={(e) => setBtSymbol(e.target.value)}
                  />
                </label>
                <label className="bt-field">
                  <span>市场</span>
                  <select
                    className="edit-input"
                    value={btMarket}
                    onChange={(e) => setBtMarket(e.target.value)}
                  >
                    <option value="a_shares">A股</option>
                    <option value="us_stocks">美股</option>
                    <option value="crypto">加密</option>
                  </select>
                </label>
                <label className="bt-field">
                  <span>周期</span>
                  <select
                    className="edit-input"
                    value={btInterval}
                    onChange={(e) => setBtInterval(e.target.value)}
                  >
                    <option value="1d">日线</option>
                    <option value="1h">1小时</option>
                    <option value="4h">4小时</option>
                  </select>
                </label>
                <label className="bt-field">
                  <span>K线数</span>
                  <input
                    className="edit-input"
                    type="number"
                    value={btLimit}
                    onChange={(e) => setBtLimit(Number(e.target.value) || 300)}
                  />
                </label>
                <label className="bt-field">
                  <span>初始资金</span>
                  <input
                    className="edit-input"
                    type="number"
                    value={btCapital}
                    onChange={(e) => setBtCapital(Number(e.target.value) || 100000)}
                  />
                </label>
              </div>
              <div className="detail-actions">
                <button
                  className="period-tab"
                  onClick={handleBacktest}
                  disabled={btRunning || !btSymbol.trim()}
                  style={{ background: 'var(--accent)', color: '#fff' }}
                >
                  {btRunning ? '回测中…' : '运行回测'}
                </button>
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
                          className="v mono"
                          style={{
                            color:
                              (btResult.summary?.total_return ?? 0) >= 0
                                ? 'var(--up-ink)'
                                : 'var(--down-ink)',
                          }}
                        >
                          {((btResult.summary?.total_return ?? 0) * 100).toFixed(2)}%
                        </span>
                      </div>
                      <div className="stat-tile">
                        <span className="k">最大回撤</span>
                        <span className="v mono" style={{ color: 'var(--down-ink)' }}>
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

                    <div className="detail-section-title" style={{ marginTop: 'var(--sp-3)' }}>
                      成交明细
                    </div>
                    {btResult.trades.length > 0 ? (
                      <div className="table-wrap">
                        <table className="tbl">
                          <thead>
                            <tr>
                              <th>#</th>
                              <th>开仓</th>
                              <th>平仓</th>
                              <th>盈亏</th>
                              <th>收益%</th>
                            </tr>
                          </thead>
                          <tbody>
                            {btResult.trades.slice(0, 50).map((t, i) => {
                              const pnl = Number(t.pnl ?? 0)
                              const ret = Number(t.return_pct ?? t.ret_pct ?? 0)
                              return (
                                <tr key={i}>
                                  <td className="mono">{i + 1}</td>
                                  <td className="mono">{String(t.entry_time ?? t.entry ?? '—')}</td>
                                  <td className="mono">{String(t.exit_time ?? t.exit ?? '—')}</td>
                                  <td
                                    className="mono"
                                    style={{ color: pnl >= 0 ? 'var(--up-ink)' : 'var(--down-ink)' }}
                                  >
                                    {pnl.toFixed(2)}
                                  </td>
                                  <td
                                    className="mono"
                                    style={{ color: ret >= 0 ? 'var(--up-ink)' : 'var(--down-ink)' }}
                                  >
                                    {ret.toFixed(2)}%
                                  </td>
                                </tr>
                              )
                            })}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <div className="muted" style={{ fontSize: 'var(--fs-13)' }}>
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
                    <button
                      className="link-btn"
                      style={{ marginTop: 'var(--sp-1)', alignSelf: 'flex-start' }}
                      onClick={() => {
                        setParams({ ...h.params })
                        setRunResult(h.result)
                        setRunError('')
                        setTab('signals')
                      }}
                    >
                      恢复结果与参数
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <div className="muted" style={{ fontSize: 'var(--fs-13)' }}>
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
                <div className="signal-result-summary" style={{ marginBottom: 'var(--sp-3)' }}>
                  显示最近一次运行（{formatRelativeTime(lastOkRun.ts)}）的 {lastOkRun.result.count} 条信号。
                </div>
                <SignalResults signals={lastOkRun.result.signals} />
              </>
            ) : (
              <div className="empty-hint">请先在「运行」页运行策略以生成信号。</div>
            )}
          </div>
        )}

        {/* 实盘（G5：诚实 paper 模式，无 broker 配置不产生真实成交） */}
        {tab === 'live' && (
          <div className="detail-section">
            <div className="detail-section-title">实盘状态</div>
            {liveInfo.loading ? (
              <div className="muted">加载中…</div>
            ) : (
              <>
                <div className="overview-stats">
                  <div className="stat-tile">
                    <span className="k">实盘能力</span>
                    <span className="v">{liveInfo.data?.live_capable ? '可实盘' : '回测/分析'}</span>
                  </div>
                  <div className="stat-tile">
                    <span className="k">当前模式</span>
                    <span className="v mono">{liveInfo.data?.is_live ? 'LIVE' : 'PAPER'}</span>
                  </div>
                </div>
                <div className="bus-hint warn">
                  {liveInfo.data?.note ||
                    '实盘需要交易所/券商 API 配置；未配置时 live_tick 为 no-op（模拟态），不产生真实成交。'}
                </div>
                <div className="detail-actions">
                  <button
                    className="period-tab"
                    onClick={handleLiveTick}
                    disabled={liveRunning}
                    style={{ background: 'var(--accent)', color: '#fff' }}
                  >
                    {liveRunning ? 'Tick 中…' : '模拟一次 Tick'}
                  </button>
                </div>
                {liveError && <div className="run-error">{liveError}</div>}
                {liveState != null && (
                  <pre className="live-state">{JSON.stringify(liveState, null, 2)}</pre>
                )}
              </>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
