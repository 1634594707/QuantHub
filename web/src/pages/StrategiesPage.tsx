import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { useApi } from '../api/useApi'
import type { StrategyInfo } from '../api/types'
import { useStrategyRuns } from '../hooks/useStrategyRuns'
import { marketBadge, marketKey, defaultParams } from '../components/StrategyShared'
import { formatRelativeTime } from '../lib/time'
import { AsyncStateBoundary } from '../components/ui/AsyncStateBoundary/AsyncStateBoundary'
import { RefreshControl } from '../components/ui/RefreshControl/RefreshControl'
import { Input } from '../components/ui/Input/Input'
import { Select } from '../components/ui/Select/Select'
import { Toggle } from '../components/ui/Toggle/Toggle'
import { Button } from '../components/ui/Button/Button'
import { SegmentedControl } from '../components/ui/SegmentedControl/SegmentedControl'
import { WorkspaceHeader } from '../components/WorkspaceHeader/WorkspaceHeader'
import s from './StrategiesPage.module.css'

type MarketKey = 'a_shares' | 'crypto' | 'us_stocks' | 'other'

const GROUPS: { key: MarketKey | 'all'; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'a_shares', label: 'A股' },
  { key: 'crypto', label: '加密货币' },
  { key: 'us_stocks', label: '美股' },
  { key: 'other', label: '其他' },
]

const SORT_OPTIONS = [
  { value: 'default', label: '默认排序' },
  { value: 'name', label: '按名称' },
  { value: 'recent', label: '最近运行' },
]

export default function StrategiesPage() {
  const navigate = useNavigate()
  const strategies = useApi(() => api.strategies(), [])
  const { lastRun, addRun, error: runHistoryError } = useStrategyRuns()
  const [runError, setRunError] = useState('')
  const [filter, setFilter] = useState<MarketKey | 'all'>('all')
  const [liveOnly, setLiveOnly] = useState(false)
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState<'default' | 'name' | 'recent'>('default')
  const [running, setRunning] = useState<Set<string>>(new Set())

  const list = strategies.data?.strategies ?? []

  const filtered = useMemo(() => {
    let out = list
    if (filter !== 'all') out = out.filter((st) => marketKey(st.market) === filter)
    if (liveOnly) out = out.filter((st) => st.live_capable)
    const q = search.trim().toLowerCase()
    if (q) {
      out = out.filter(
        (st) =>
          st.name.toLowerCase().includes(q) || st.description.toLowerCase().includes(q),
      )
    }
    if (sort === 'name') return [...out].sort((a, b) => a.name.localeCompare(b.name))
    if (sort === 'recent') {
      return [...out].sort((a, b) => {
        const ta = new Date(lastRun(a.name)?.ts ?? 0).getTime()
        const tb = new Date(lastRun(b.name)?.ts ?? 0).getTime()
        return tb - ta
      })
    }
    return out
  }, [list, filter, liveOnly, search, sort, lastRun])

  const grouped = useMemo<Record<MarketKey | '', StrategyInfo[]>>(() => {
    if (filter !== 'all' || search.trim()) return { '': filtered } as Record<MarketKey | '', StrategyInfo[]>
    const map: Record<MarketKey, StrategyInfo[]> = {
      a_shares: [],
      crypto: [],
      us_stocks: [],
      other: [],
    }
    filtered.forEach((st) => map[marketKey(st.market)].push(st))
    return map as Record<MarketKey | '', StrategyInfo[]>
  }, [filtered, filter, search])

  async function handleQuickRun(e: React.MouseEvent, name: string) {
    e.stopPropagation()
    setRunError('')
    setRunning((prev) => new Set([...prev, name]))
    try {
      const params = defaultParams(name)
      const response = await api.runStrategy(name, params)
      await addRun(name, params, response)
    } catch (reason) {
      setRunError(reason instanceof Error ? reason.message : '策略运行或历史保存失败')
    } finally {
      setRunning((prev) => {
        const next = new Set(prev)
        next.delete(name)
        return next
      })
    }
  }

  return (
    <>
      <WorkspaceHeader
        context="策略 / 策略运行"
        title="已安装策略"
        metrics={[
          { label: '已注册', value: list.length },
          { label: '当前筛选', value: filtered.length },
          // M2-04：live_capable 是策略元数据里的**自声明**字段，不代表已通过实盘核准。
          // 实际能否下单由交易通道（trading_enabled + live_approved）决定，此处如实措辞。
          { label: '声明支持实盘', value: list.filter((strategy) => strategy.live_capable).length },
        ]}
      />
      <div className="card">
        <div className={s.toolbarWrap}>
          {/* 工具栏：搜索 + 分组 + 排序/筛选/刷新（hero 已显示注册数，card-head 不再重复） */}
          <div className={s.toolbar}>
            <Input
              className={s.searchInput}
              placeholder="搜索策略名称或描述…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <SegmentedControl
              value={filter}
              onChange={(v) => setFilter(v as MarketKey | 'all')}
              size="sm"
              options={GROUPS.map((g) => {
                const count =
                  g.key === 'all'
                    ? list.length
                    : list.filter((s) => marketKey(s.market) === g.key).length
                return {
                  value: g.key,
                  label: (
                    <>
                      {g.label}
                      <span className={s.countBadge}>{count}</span>
                    </>
                  ),
                }
              })}
            />
            <div className={s.sortControls}>
              <Toggle
                checked={liveOnly}
                onChange={setLiveOnly}
                label="仅看声明支持实盘"
              />
              <Select
                className={s.sortSelect}
                options={SORT_OPTIONS}
                value={sort}
                onChange={(e) => setSort(e.target.value as typeof sort)}
              />
              <RefreshControl onRefresh={strategies.refetch} refreshing={strategies.loading || strategies.reconnecting} updatedAt={strategies.updatedAt} />
            </div>
          </div>

          {runHistoryError ? <div className="run-error" role="alert">策略运行历史不可用：{runHistoryError}</div> : null}
          {runError ? <div className="run-error" role="alert">{runError}</div> : null}
          <AsyncStateBoundary
            loading={strategies.loading}
            error={strategies.error}
            reconnecting={strategies.reconnecting}
            hasData={strategies.data !== null}
            isEmpty={filtered.length === 0}
            onRetry={strategies.refetch}
            loadingTitle="正在读取策略注册表…"
            emptyTitle={list.length ? '没有匹配的策略' : '策略注册表为空'}
            emptyDescription={list.length ? '尝试调整筛选条件或搜索关键词。' : undefined}
          >
            <div className="stack-4">
              {(Object.keys(grouped) as (MarketKey | '')[])
                .filter((k) => grouped[k].length > 0)
                .map((key) => (
                  <section key={key || 'results'}>
                  {filter === 'all' && !search.trim() && (
                    <div className={s.groupTitle}>
                      {GROUPS.find((g) => g.key === key)?.label}
                      <span className={`sub ${s.groupCount}`}>
                        {grouped[key].length} 个
                      </span>
                    </div>
                  )}
                  <div className={s.grid}>
                    {grouped[key].map((st) => (
                      <StrategyCard
                        key={st.name}
                        st={st}
                        last={lastRun(st.name)}
                        running={running.has(st.name)}
                        onClick={() => navigate(`/strategies/${st.name}`)}
                        onRun={(e) => handleQuickRun(e, st.name)}
                        onBacktest={(e) => {
                          e.stopPropagation()
                          navigate(`/strategies/${st.name}?tab=backtest`)
                        }}
                      />
                    ))}
                  </div>
                  </section>
                ))}
            </div>
          </AsyncStateBoundary>
        </div>
      </div>
    </>
  )
}

function StrategyCard({
  st,
  last,
  running,
  onClick,
  onRun,
  onBacktest,
}: {
  st: StrategyInfo
  last?: { result: { ok: boolean; count: number; error?: string }; ts: number }
  running: boolean
  onClick: () => void
  onRun: (e: React.MouseEvent) => void
  onBacktest: (e: React.MouseEvent) => void
}) {
  const statusKey: 'idle' | 'running' | 'ok' | 'err' = running
    ? 'running'
    : last
      ? last.result.ok
        ? 'ok'
        : 'err'
      : 'idle'
  const statusClass =
    statusKey === 'running'
      ? s.isRunning
      : statusKey === 'ok'
        ? s.isOk
        : statusKey === 'err'
          ? s.isErr
          : s.isIdle

  const recent = last
    ? last.result.ok
      ? `最近运行 ${last.result.count} 条信号 · ${formatRelativeTime(last.ts)}`
      : `最近运行失败 · ${formatRelativeTime(last.ts)}`
    : '未运行过'

  return (
    <div className={`${s.card} ${statusClass}`} role="button" tabIndex={0} onClick={onClick} onKeyDown={(event) => { if (event.key === 'Enter') onClick() }}>
      <div className={s.cardHead}>
        <div className={s.cardTitle}>
          <span className={s.stratName}>{st.name}</span>
        </div>
        <div className={s.cardMeta}>
          <span className={`${s.stratTag} ${s.stratTagMarket}`}>{marketBadge(st.market)}</span>
          {st.live_capable && <span className={`${s.stratTag} ${s.stratTagLive}`}>实盘</span>}
        </div>
      </div>
      <p className={s.cardDesc}>{st.description || '—'}</p>
      <div className={s.cardFoot}>
        <div className={s.stratStatus}>
          <span className={`${s.stratStatusDot} ${statusClass}`} />
          <span className={`${s.stratStatusText} ${statusClass}`}>{recent}</span>
        </div>
        <div className={s.cardActions}>
          <Button
            variant="primary"
            size="sm"
            onClick={onRun}
            disabled={running}
            loading={running}
          >
            {running ? '运行中…' : '快速运行'}
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={onBacktest}
            title="进入该策略的回测 Tab"
          >
            回测
          </Button>
          <Button
            variant="link"
            size="sm"
            onClick={(e) => {
              e.stopPropagation()
              onClick()
            }}
            title="进入策略工作台"
          >
            详情 →
          </Button>
        </div>
      </div>
    </div>
  )
}
