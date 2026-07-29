import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { AnalysisTask, Instrument } from '../api/types'
import { useApi } from '../api/useApi'
import { IconChart, IconCog, IconSearch } from '../components/icons'
import { AsyncStateBoundary } from '../components/ui/AsyncStateBoundary/AsyncStateBoundary'
import { Button } from '../components/ui/Button/Button'
import { Input } from '../components/ui/Input/Input'
import { SegmentedControl } from '../components/ui/SegmentedControl/SegmentedControl'
import { WorkspaceHeader } from '../components/WorkspaceHeader/WorkspaceHeader'
import { useLocalStorage } from '../hooks/useLocalStorage'
import s from './StockEvaluationStartPage.module.css'

type Horizon = 'short' | 'swing' | 'medium'

interface RecentInstrument {
  instrument_id: string
  code: string
  name: string
  market: string
}

const HORIZONS: Record<Horizon, { label: string; timeframe: string; description: string }> = {
  short: { label: '短线 1-5 日', timeframe: '1h', description: '关注近期节奏、波动和入场条件' },
  swing: { label: '波段 1-4 周', timeframe: '1d', description: '兼顾趋势、新闻和关键价格位置' },
  medium: { label: '中线 1-6 月', timeframe: '1w', description: '观察更长周期趋势，暂不包含基本面估值' },
}

const SAMPLE_STOCK: Instrument = {
  instrument_id: 'a_shares:600519',
  code: '600519',
  market: 'a_shares',
  exchange: 'sse',
  name: '贵州茅台',
  currency: 'CNY',
  asset_class: 'stock',
}

function exchangeLabel(exchange: string) {
  const normalized = exchange.toLowerCase()
  if (normalized === 'sse' || normalized === 'sh') return '上海证券交易所'
  if (normalized === 'szse' || normalized === 'sz') return '深圳证券交易所'
  if (normalized === 'bse' || normalized === 'bj') return '北京证券交易所'
  return exchange || 'A 股'
}

export default function StockEvaluationStartPage() {
  const navigate = useNavigate()
  const health = useApi(() => api.health(), [], { retryInterval: 15000 })
  const [query, setQuery] = useState('')
  const [activeQuery, setActiveQuery] = useState('')
  const [selected, setSelected] = useState<Instrument | null>(null)
  const [horizon, setHorizon] = useState<Horizon>('swing')
  const [queryError, setQueryError] = useState('')
  const [starting, setStarting] = useState(false)
  const [startError, setStartError] = useState('')
  const [recentTask, setRecentTask] = useState<AnalysisTask | null>(null)
  const [recentInstruments, setRecentInstruments] = useLocalStorage<RecentInstrument[]>(
    'quanthub.evaluate.recent-instruments',
    [],
  )
  const watchlist = useApi(() => api.watchlist(), [], { retry: false })
  const directory = useApi(
    () => api.instruments(activeQuery, 30),
    [activeQuery],
    { enabled: Boolean(activeQuery), retry: false, resetKey: activeQuery },
  )
  const results = useMemo(
    () => (directory.data?.instruments ?? []).filter((item) => (
      item.market === 'a_shares'
      && /^\d{6}$/.test(item.code)
      && !item.code.toUpperCase().startsWith('E2E')
    )),
    [directory.data],
  )

  function search(event: React.FormEvent) {
    event.preventDefault()
    const normalized = query.trim()
    if (!normalized) {
      setQueryError('请输入股票名称或 6 位代码')
      return
    }
    setQueryError('')
    setSelected(null)
    setActiveQuery(normalized)
  }

  function queryInstrument(code: string) {
    setQuery(code)
    setQueryError('')
    setSelected(null)
    setActiveQuery(code)
  }

  function selectInstrument(instrument: Instrument) {
    setSelected(instrument)
    setRecentInstruments((current) => [
      {
        instrument_id: instrument.instrument_id,
        code: instrument.code,
        name: instrument.name,
        market: instrument.market,
      },
      ...current.filter((item) => item.instrument_id !== instrument.instrument_id),
    ].slice(0, 6))
  }

  function openTask(instrument: Instrument, timeframe: string, taskId: string) {
    const params = new URLSearchParams({
      market: instrument.market,
      tf: timeframe,
      from: 'evaluate',
      evaluation_task_id: taskId,
    })
    navigate(`/research/${encodeURIComponent(instrument.code)}?${params.toString()}`)
  }

  async function beginEvaluation(instrument = selected, targetHorizon = horizon, createNew = false) {
    if (!instrument) return
    setStarting(true)
    setStartError('')
    try {
      const timeframe = HORIZONS[targetHorizon].timeframe
      if (!createNew) {
        const recent = await api.recentAnalysisTask(
          'evaluation', instrument.code, instrument.market, timeframe, 900,
        )
        if (recent.task) {
          setRecentTask(recent.task)
          return
        }
      }
      const created = await api.createAnalysisTask({
        kind: 'evaluation',
        symbol: instrument.code,
        market: instrument.market,
        timeframe,
        payload: { modules: ['market', 'news', 'pa', 'ensemble'] },
        timeout_seconds: 360,
      })
      setRecentTask(null)
      openTask(instrument, timeframe, created.task.id)
    } catch (error) {
      setStartError(error instanceof Error ? error.message : '股票评估任务创建失败')
    } finally {
      setStarting(false)
    }
  }

  const serviceReady = Boolean(health.data && !health.error)

  return (
    <div className={s.page}>
      <WorkspaceHeader
        context="研究 / 股票评估"
        title="评估一只股票"
        description="输入名称或代码，选择关注周期"
        metrics={[
          { label: '首选市场', value: 'A 股' },
          { label: '当前模式', value: '研究模式' },
          { label: '分析服务', value: serviceReady ? '可用' : health.loading ? '检查中' : '需检查' },
        ]}
      />

      <div className={s.flow} aria-label="股票评估步骤">
        <div className={s.flowStepActive}><span>1</span><strong>选择股票</strong></div>
        <div><span>2</span><strong>选择周期</strong></div>
        <div><span>3</span><strong>查看评估</strong></div>
      </div>

      <div className={s.workspace}>
        <section className={s.searchSection}>
          <div className={s.sectionTitle}>
            <span>第一步</span>
            <h2>你想评估哪只股票？</h2>
            <p>支持输入中文名称或 6 位股票代码。</p>
          </div>

          <form className={s.searchForm} onSubmit={search}>
            <Input
              value={query}
              onChange={(event) => {
                setQuery(event.target.value)
                if (event.target.value.trim()) setQueryError('')
              }}
              prefix={<IconSearch size={17} />}
              placeholder="例如：贵州茅台 或 600519"
              aria-label="股票名称或代码"
              invalid={Boolean(queryError)}
              autoComplete="off"
            />
            <Button type="submit" variant="primary">查找股票</Button>
          </form>
          {queryError && <div className={s.fieldError} role="alert">{queryError}</div>}

          {!activeQuery && (recentInstruments.length > 0 || (watchlist.data?.items ?? []).some((item) => item.market === 'a_shares')) && (
            <div className={s.quickPickGroups}>
              {recentInstruments.length > 0 && (
                <div className={s.quickPickGroup}>
                  <span>最近搜索</span>
                  <div>{recentInstruments.map((item) => <button type="button" key={item.instrument_id} onClick={() => queryInstrument(item.code)}><b>{item.name || item.code}</b><small>{item.code} · {item.market}</small></button>)}</div>
                </div>
              )}
              {(watchlist.data?.items ?? []).some((item) => item.market === 'a_shares') && (
                <div className={s.quickPickGroup}>
                  <span>自选股票</span>
                  <div>{(watchlist.data?.items ?? []).filter((item) => item.market === 'a_shares').slice(0, 6).map((item) => <button type="button" key={item.id ?? `${item.market}:${item.sym}`} onClick={() => queryInstrument(item.sym)}><b>{item.name || item.sym}</b><small>{item.sym} · {item.market}</small></button>)}</div>
                </div>
              )}
            </div>
          )}

          {!activeQuery && (
            <div className={s.sampleBand}>
              <div>
                <span>还不确定从哪里开始</span>
                <strong>使用贵州茅台查看示例流程</strong>
              </div>
              <Button variant="secondary" size="sm" onClick={() => {
                setSelected(SAMPLE_STOCK)
                setQuery('600519')
              }}>选择示例股票</Button>
            </div>
          )}

          {activeQuery && (
            <AsyncStateBoundary
              loading={directory.loading}
              error={directory.error}
              reconnecting={directory.reconnecting}
              hasData={directory.data !== null}
              isEmpty={results.length === 0}
              onRetry={directory.refetch}
              loadingTitle="正在查找股票…"
              emptyTitle="没有找到这只股票"
              emptyDescription="请检查名称或代码；也可以前往股票与市场登记。"
              emptyAction={{ label: '前往股票与市场', onClick: () => navigate('/instruments') }}
            >
              <div className={s.resultList} aria-label="股票搜索结果">
                {results.map((instrument) => (
                  <button
                    key={instrument.instrument_id}
                    type="button"
                    className={selected?.instrument_id === instrument.instrument_id ? s.resultSelected : ''}
                    onClick={() => selectInstrument(instrument)}
                  >
                    <span className={s.stockMark}>{instrument.name.slice(0, 1) || instrument.code.slice(0, 1)}</span>
                    <span className={s.stockIdentity}>
                      <strong>{instrument.name || instrument.code}</strong>
                      <small>{instrument.code} · {exchangeLabel(instrument.exchange)}</small>
                    </span>
                    <span className={s.selectState}>{selected?.instrument_id === instrument.instrument_id ? '已选择' : '选择'}</span>
                  </button>
                ))}
              </div>
            </AsyncStateBoundary>
          )}

          {selected && !activeQuery && (
            <div className={s.resultList} aria-label="已选择的示例股票">
              <button type="button" className={s.resultSelected} onClick={() => setSelected(SAMPLE_STOCK)}>
                <span className={s.stockMark}>贵</span>
                <span className={s.stockIdentity}><strong>贵州茅台</strong><small>600519 · 上海证券交易所 · 示例</small></span>
                <span className={s.selectState}>已选择</span>
              </button>
            </div>
          )}
        </section>

        <aside className={s.setupSection}>
          <div className={s.sectionTitle}>
            <span>第二步</span>
            <h2>你更关注多长时间？</h2>
            <p>系统会据此选择合适的行情周期。</p>
          </div>

          <SegmentedControl
            value={horizon}
            onChange={(value) => setHorizon(value as Horizon)}
            fullWidth
            options={(Object.keys(HORIZONS) as Horizon[]).map((value) => ({
              value,
              label: HORIZONS[value].label,
            }))}
          />
          <div className={s.horizonDescription}>{HORIZONS[horizon].description}</div>

          <div className={s.readiness}>
            <div><span className={serviceReady ? s.readyDot : s.pendingDot} /><strong>分析服务</strong><em>{serviceReady ? '连接正常' : health.loading ? '正在检查' : '需要检查设置'}</em></div>
            <div><span className={s.readyDot} /><strong>交易方式</strong><em>仅研究和模拟</em></div>
            <div><span className={s.readyDot} /><strong>评估范围</strong><em>行情、新闻、价格行为、策略</em></div>
          </div>

          <Button
            variant="primary"
            size="lg"
            fullWidth
            icon={<IconChart size={18} />}
            disabled={!selected || starting}
            loading={starting}
            onClick={() => void beginEvaluation()}
          >进入评估工作区</Button>
          {recentTask && selected && (
            <div className={s.reuseNotice} role="status">
              <div>
                <strong>15 分钟内已有同股票、市场和周期的评估</strong>
                <span>{new Date(recentTask.created_at * 1000).toLocaleString('zh-CN', { hour12: false })} · {recentTask.status}</span>
              </div>
              <div>
                <Button variant="primary" size="sm" onClick={() => openTask(selected, HORIZONS[horizon].timeframe, recentTask.id)}>复用已有评估</Button>
                <Button variant="secondary" size="sm" onClick={() => void beginEvaluation(selected, horizon, true)}>仍然新建</Button>
              </div>
            </div>
          )}
          {startError && <p className={s.fieldError} role="alert">{startError}</p>}
          {!selected && <p className={s.actionHint}>先从左侧选择一只股票</p>}
        </aside>
      </div>

      <section className={s.secondaryActions}>
        <button type="button" disabled={starting} onClick={() => navigate('/example')}>
          <IconChart size={19} />
          <span><strong>查看示例评估</strong><small>使用贵州茅台和波段周期</small></span>
        </button>
        <button type="button" onClick={() => navigate('/config')}>
          <IconCog size={19} />
          <span><strong>检查数据设置</strong><small>行情或模型不可用时从这里开始</small></span>
        </button>
      </section>

      <p className={s.disclaimer}>评估结果用于辅助研究，不构成投资建议；数据不足时系统应降低结论置信度。</p>
    </div>
  )
}
