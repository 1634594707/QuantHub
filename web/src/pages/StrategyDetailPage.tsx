import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { useApi } from '../api/useApi'
import type { RunResp, SignalResp } from '../api/types'
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

type Tab = 'overview' | 'params' | 'run' | 'history' | 'signals'

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

export default function StrategyDetailPage() {
  const { name } = useParams<{ name: string }>()
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
  const [tab, setTab] = useState<Tab>('overview')

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
    { key: 'history', label: '历史' },
    { key: 'signals', label: '信号' },
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
      </div>
    </div>
  )
}
