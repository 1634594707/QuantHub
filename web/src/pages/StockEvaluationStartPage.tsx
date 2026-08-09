import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { AnalysisTask, Instrument } from '../api/types'
import { useApi } from '../api/useApi'
import { IconChart, IconChevron, IconCog, IconSearch } from '../components/icons'
import { AsyncStateBoundary } from '../components/ui/AsyncStateBoundary/AsyncStateBoundary'
import { Button } from '../components/ui/Button/Button'
import { Input } from '../components/ui/Input/Input'
import { SegmentedControl } from '../components/ui/SegmentedControl/SegmentedControl'
import { WorkspaceHeader } from '../components/WorkspaceHeader/WorkspaceHeader'
import { useLocalStorage } from '../hooks/useLocalStorage'
import s from './StockEvaluationStartPage.module.css'

type Horizon = 'short' | 'swing' | 'medium'
type EvaluationProfile = 'quick' | 'balanced' | 'comprehensive'
type StrategyLens = 'trend_following' | 'mean_reversion' | 'risk_first'
type EvaluationMarket = 'a_shares' | 'us_stocks' | 'crypto'

interface RecentInstrument {
  instrument_id: string
  code: string
  name: string
  market: string
}

const MARKETS: Record<EvaluationMarket, {
  label: string
  assetLabel: string
  placeholder: string
  searchHint: string
}> = {
  a_shares: { label: 'A 股', assetLabel: '股票', placeholder: '例如：贵州茅台 或 600519', searchHint: '支持输入中文名称或 6 位股票代码。' },
  us_stocks: { label: '美股', assetLabel: '股票', placeholder: '例如：NVDA 或 AAPL', searchHint: '输入美股代码；已登记标的也可按名称搜索。' },
  crypto: { label: '虚拟货币', assetLabel: '数字资产', placeholder: '例如：BTC-USDT 或 ETH-USDT', searchHint: '输入交易对或币种代码；支持 BTC-USDT、ETH 等格式。' },
}

const HORIZONS: Record<EvaluationMarket, Record<Horizon, { label: string; timeframe: string; description: string }>> = {
  a_shares: {
    short: { label: '短线 1-5 日', timeframe: '1h', description: '关注近期节奏、波动和入场条件' },
    swing: { label: '波段 1-4 周', timeframe: '1d', description: '兼顾趋势、新闻和关键价格位置' },
    medium: { label: '中线 1-6 月', timeframe: '1w', description: '观察更长周期趋势，暂不包含基本面估值' },
  },
  us_stocks: {
    short: { label: '短线 1-10 日', timeframe: '1d', description: '使用日线评估近期趋势，匹配当前美股行情源能力' },
    swing: { label: '波段 2-8 周', timeframe: '1d', description: '结合更长样本观察趋势延续、回撤和价格偏离' },
    medium: { label: '中线 2-12 月', timeframe: '1w', description: '使用周线降低短期噪声，暂不包含基本面估值' },
  },
  crypto: {
    short: { label: '短线 1-5 日', timeframe: '1h', description: '关注 24 小时市场中的短周期动量与波动' },
    swing: { label: '波段 1-4 周', timeframe: '1d', description: '观察日线趋势、回撤和量价变化' },
    medium: { label: '中线 1-6 月', timeframe: '1w', description: '使用周线评估跨周期趋势与风险' },
  },
}

const EVALUATION_PROFILES: Record<EvaluationProfile, {
  label: string
  description: string
  modules: string[]
  methods: string[]
  defaultLenses: StrategyLens[]
  marketLimit: number
}> = {
  quick: {
    label: '快速筛查',
    description: '聚焦趋势、动量与波动，适合快速比较候选标的。',
    modules: ['market', 'ensemble'],
    methods: ['trend', 'momentum', 'volatility'],
    defaultLenses: ['trend_following'],
    marketLimit: 120,
  },
  balanced: {
    label: '均衡评估',
    description: '加入回撤与均值偏离，并结合新闻 AI 和价格结构 AI。',
    modules: ['market', 'news', 'pa', 'ensemble'],
    methods: ['trend', 'momentum', 'volatility', 'drawdown', 'mean_reversion'],
    defaultLenses: ['trend_following', 'mean_reversion', 'risk_first'],
    marketLimit: 240,
  },
  comprehensive: {
    label: '全面评估',
    description: '使用更长样本和完整量价维度，适合形成研究记录。',
    modules: ['market', 'news', 'pa', 'ensemble'],
    methods: ['trend', 'momentum', 'volatility', 'drawdown', 'mean_reversion', 'volume'],
    defaultLenses: ['trend_following', 'mean_reversion', 'risk_first'],
    marketLimit: 480,
  },
}

const METHOD_LABELS: Record<string, string> = {
  trend: '趋势结构',
  momentum: '多周期动量',
  volatility: '年化波动',
  drawdown: '最大回撤',
  mean_reversion: '均值偏离',
  volume: '量价状态',
}

const STRATEGY_LENSES: Record<StrategyLens, { label: string; description: string }> = {
  trend_following: { label: '趋势跟随', description: '判断趋势与动量是否共振' },
  mean_reversion: { label: '均值回归', description: '识别超买、超卖与价格偏离' },
  risk_first: { label: '风险优先', description: '优先审视波动与历史回撤' },
}

const STRATEGY_METHODS: Record<StrategyLens, string[]> = {
  trend_following: ['trend', 'momentum'],
  mean_reversion: ['mean_reversion'],
  risk_first: ['volatility', 'drawdown'],
}

const MODULE_LABELS: Record<string, string> = {
  market: '量化快照',
  news: '新闻 AI',
  pa: '价格结构 AI',
  ensemble: '模型共识',
}

const SAMPLE_INSTRUMENTS: Record<EvaluationMarket, Instrument> = {
  a_shares: { instrument_id: 'a_shares:600519', code: '600519', market: 'a_shares', exchange: 'sse', name: '贵州茅台', currency: 'CNY', asset_class: 'stock' },
  us_stocks: { instrument_id: 'us_stocks:NVDA', code: 'NVDA', market: 'us_stocks', exchange: 'nasdaq', name: '英伟达', currency: 'USD', asset_class: 'stock' },
  crypto: { instrument_id: 'crypto:BTC-USDT', code: 'BTC-USDT', market: 'crypto', exchange: 'okx', name: '比特币', currency: 'USDT', asset_class: 'crypto' },
}

function exchangeLabel(instrument: Instrument) {
  const normalized = instrument.exchange.toLowerCase()
  if (normalized === 'sse' || normalized === 'sh') return '上海证券交易所'
  if (normalized === 'szse' || normalized === 'sz') return '深圳证券交易所'
  if (normalized === 'bse' || normalized === 'bj') return '北京证券交易所'
  if (normalized === 'nasdaq') return 'NASDAQ'
  if (normalized === 'nyse') return 'NYSE'
  if (normalized === 'okx') return 'OKX'
  return instrument.exchange || MARKETS[instrument.market as EvaluationMarket]?.label || instrument.market
}

export default function StockEvaluationStartPage() {
  const navigate = useNavigate()
  const health = useApi(() => api.health(), [], { retryInterval: 15000 })
  const [query, setQuery] = useState('')
  const [activeQuery, setActiveQuery] = useState('')
  const [selected, setSelected] = useState<Instrument | null>(null)
  const [market, setMarket] = useState<EvaluationMarket>('a_shares')
  const [horizon, setHorizon] = useState<Horizon>('swing')
  const [profile, setProfile] = useState<EvaluationProfile>('balanced')
  const [strategyLenses, setStrategyLenses] = useState<StrategyLens[]>([
    'trend_following', 'mean_reversion', 'risk_first',
  ])
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
    () => api.instruments(activeQuery, 30, market),
    [activeQuery, market],
    { enabled: Boolean(activeQuery), retry: false, resetKey: `${market}:${activeQuery}` },
  )
  const results = useMemo(
    () => (directory.data?.instruments ?? []).filter((item) => (
      item.market === market
      && !item.code.toUpperCase().startsWith('E2E')
    )),
    [directory.data, market],
  )
  const profileConfig = EVALUATION_PROFILES[profile]
  const horizonConfig = HORIZONS[market][horizon]
  const activeModules = useMemo(
    () => profileConfig.modules.filter((module) => module !== 'news' || market === 'a_shares'),
    [market, profileConfig.modules],
  )
  const activeMethods = useMemo(
    () => Array.from(new Set([
      ...profileConfig.methods,
      ...strategyLenses.flatMap((lens) => STRATEGY_METHODS[lens]),
    ])),
    [profileConfig, strategyLenses],
  )
  const profileDescription = market !== 'a_shares' && profile === 'balanced'
    ? '加入回撤与均值偏离，并结合价格结构 AI 和模型共识。'
    : profileConfig.description

  function search(event: React.FormEvent) {
    event.preventDefault()
    const normalized = query.trim()
    if (!normalized) {
      setQueryError(`请输入${MARKETS[market].assetLabel}名称或代码`)
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

  function changeMarket(nextMarket: EvaluationMarket) {
    setMarket(nextMarket)
    setQuery('')
    setActiveQuery('')
    setSelected(null)
    setRecentTask(null)
    setStartError('')
    setQueryError('')
    setHorizon('swing')
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

  function openWorkspace(instrument = selected, targetHorizon = horizon) {
    if (!instrument) return
    const timeframe = HORIZONS[instrument.market as EvaluationMarket][targetHorizon].timeframe
    const params = new URLSearchParams({
      market: instrument.market,
      tf: timeframe,
      from: 'evaluate',
      view: 'overview',
    })
    navigate(`/research/${encodeURIComponent(instrument.code)}?${params.toString()}`)
  }

  async function beginEvaluation(instrument = selected, targetHorizon = horizon, createNew = false) {
    if (!instrument) return
    setStarting(true)
    setStartError('')
    try {
      const timeframe = HORIZONS[instrument.market as EvaluationMarket][targetHorizon].timeframe
      if (!createNew) {
        const recent = await api.recentAnalysisTask(
          'evaluation', instrument.code, instrument.market, timeframe, 900,
        )
        const recentRequest = recent.task?.request
        const sameProfile = recentRequest?.evaluation_profile === profile
        const sameHorizon = recentRequest?.evaluation_horizon === targetHorizon
        const recentLenses = Array.isArray(recentRequest?.strategy_lenses)
          ? recentRequest.strategy_lenses.filter((item): item is string => typeof item === 'string')
          : []
        const sameLenses = recentLenses.length === strategyLenses.length
          && strategyLenses.every((lens) => recentLenses.includes(lens))
        if (recent.task && sameProfile && sameHorizon && sameLenses) {
          setRecentTask(recent.task)
          return
        }
      }
      const created = await api.createAnalysisTask({
        kind: 'evaluation',
        symbol: instrument.code,
        market: instrument.market,
        timeframe,
        payload: {
          modules: activeModules,
          evaluation_horizon: targetHorizon,
          evaluation_profile: profile,
          market_methods: activeMethods,
          strategy_lenses: strategyLenses,
          market_limit: profileConfig.marketLimit,
        },
        timeout_seconds: 360,
      })
      setRecentTask(null)
      openTask(instrument, timeframe, created.task.id)
    } catch (error) {
      setStartError(error instanceof Error ? error.message : '综合评估任务创建失败')
    } finally {
      setStarting(false)
    }
  }

  const serviceReady = Boolean(health.data && !health.error)
  function toggleStrategyLens(lens: StrategyLens) {
    setRecentTask(null)
    setStrategyLenses((current) => {
      const selected = new Set(current)
      if (selected.has(lens)) selected.delete(lens)
      else selected.add(lens)
      return (Object.keys(STRATEGY_LENSES) as StrategyLens[]).filter((item) => selected.has(item))
    })
  }

  return (
    <div className={s.page}>
      <WorkspaceHeader
        context="研究 / 综合评估"
        title="标的评估"
        description="行情快照、新闻与价格结构归档到同一研究记录"
        metrics={[
          { label: '当前市场', value: MARKETS[market].label },
          { label: '当前模式', value: '研究模式' },
          { label: '分析服务', value: serviceReady ? '可用' : health.loading ? '检查中' : '需检查' },
        ]}
      />

      <div className={s.flow} aria-label="标的评估步骤">
        <div className={s.flowStepActive}><span>1</span><strong>选择标的</strong></div>
        <div><span>2</span><strong>选择周期</strong></div>
        <div><span>3</span><strong>查看评估</strong></div>
      </div>

      <div className={s.workspace}>
        <section className={s.searchSection}>
          <div className={s.sectionTitle}>
            <span>第一步</span>
            <h2>你想评估哪个标的？</h2>
            <p>{MARKETS[market].searchHint}</p>
          </div>

          <div className={s.marketField}>
            <span>市场</span>
            <SegmentedControl
              value={market}
              onChange={(value) => changeMarket(value as EvaluationMarket)}
              fullWidth
              options={(Object.keys(MARKETS) as EvaluationMarket[]).map((value) => ({
                value,
                label: MARKETS[value].label,
              }))}
            />
          </div>

          <form className={s.searchForm} onSubmit={search}>
            <Input
              value={query}
              onChange={(event) => {
                setQuery(event.target.value)
                if (event.target.value.trim()) setQueryError('')
              }}
              prefix={<IconSearch size={17} />}
              placeholder={MARKETS[market].placeholder}
              aria-label={`${MARKETS[market].assetLabel}名称或代码`}
              invalid={Boolean(queryError)}
              autoComplete="off"
            />
            <Button type="submit" variant="primary">查找标的</Button>
          </form>
          {queryError && <div className={s.fieldError} role="alert">{queryError}</div>}

          {!activeQuery && (recentInstruments.some((item) => item.market === market) || (watchlist.data?.items ?? []).some((item) => item.market === market)) && (
            <div className={s.quickPickGroups}>
              {recentInstruments.some((item) => item.market === market) && (
                <div className={s.quickPickGroup}>
                  <span>最近搜索</span>
                  <div>{recentInstruments.filter((item) => item.market === market).map((item) => <button type="button" key={item.instrument_id} onClick={() => queryInstrument(item.code)}><b>{item.name || item.code}</b><small>{item.code} · {MARKETS[market].label}</small></button>)}</div>
                </div>
              )}
              {(watchlist.data?.items ?? []).some((item) => item.market === market) && (
                <div className={s.quickPickGroup}>
                  <span>自选标的</span>
                  <div>{(watchlist.data?.items ?? []).filter((item) => item.market === market).slice(0, 6).map((item) => <button type="button" key={item.id ?? `${item.market}:${item.sym}`} onClick={() => queryInstrument(item.sym)}><b>{item.name || item.sym}</b><small>{item.sym} · {MARKETS[market].label}</small></button>)}</div>
                </div>
              )}
            </div>
          )}

          {!activeQuery && (
            <div className={s.sampleBand}>
              <div>
                <span>还不确定从哪里开始</span>
                <strong>使用{SAMPLE_INSTRUMENTS[market].name}查看示例流程</strong>
              </div>
              <Button variant="secondary" size="sm" onClick={() => {
                setSelected(SAMPLE_INSTRUMENTS[market])
                setQuery(SAMPLE_INSTRUMENTS[market].code)
              }}>选择示例标的</Button>
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
              emptyDescription="请检查名称或代码；也可以前往标的与数据登记。"
              emptyAction={{ label: '前往标的与数据', onClick: () => navigate('/instruments') }}
            >
              <div className={s.resultList} aria-label="标的搜索结果">
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
                      <small>{instrument.code} · {exchangeLabel(instrument)}</small>
                    </span>
                    <span className={s.selectState}>{selected?.instrument_id === instrument.instrument_id ? '已选择' : '选择'}</span>
                  </button>
                ))}
              </div>
            </AsyncStateBoundary>
          )}

          {selected && !activeQuery && (
            <div className={s.resultList} aria-label="已选择的示例标的">
              <button type="button" className={s.resultSelected} onClick={() => setSelected(SAMPLE_INSTRUMENTS[market])}>
                <span className={s.stockMark}>{selected.name.slice(0, 1) || selected.code.slice(0, 1)}</span>
                <span className={s.stockIdentity}><strong>{selected.name || selected.code}</strong><small>{selected.code} · {exchangeLabel(selected)} · 示例</small></span>
                <span className={s.selectState}>已选择</span>
              </button>
            </div>
          )}
        </section>

        <aside className={s.setupSection}>
          <div className={s.sectionTitle}>
            <span>第二步</span>
            <h2>选择周期与评估规模</h2>
            <p>周期决定 K 线粒度，规模决定方法数量与样本长度。</p>
          </div>

          <SegmentedControl
            value={horizon}
            onChange={(value) => {
              setHorizon(value as Horizon)
              setRecentTask(null)
            }}
            fullWidth
            options={(Object.keys(HORIZONS[market]) as Horizon[]).map((value) => ({
              value,
              label: HORIZONS[market][value].label,
            }))}
          />
          <div className={s.horizonDescription}>{horizonConfig.description}</div>

          <div className={s.profileField}>
            <span>评估规模</span>
            <SegmentedControl
              value={profile}
              onChange={(value) => {
                const nextProfile = value as EvaluationProfile
                setProfile(nextProfile)
                setStrategyLenses(EVALUATION_PROFILES[nextProfile].defaultLenses)
                setRecentTask(null)
              }}
              fullWidth
              options={(Object.keys(EVALUATION_PROFILES) as EvaluationProfile[]).map((value) => ({
                value,
                label: EVALUATION_PROFILES[value].label,
              }))}
            />
            <p>{profileDescription}</p>
            {market !== 'a_shares' && <p className={s.marketCapability}>当前市场按所选规模运行可用模块；独立新闻模块暂不运行。</p>}
            <div className={s.methodList} aria-label="本次量化评估方法">
              {activeMethods.map((method) => <span key={method}>{METHOD_LABELS[method]}</span>)}
            </div>
          </div>

          <fieldset className={s.strategyField}>
            <legend>策略视角</legend>
            <div>
              {(Object.keys(STRATEGY_LENSES) as StrategyLens[]).map((lens) => (
                <label key={lens}>
                  <input
                    type="checkbox"
                    checked={strategyLenses.includes(lens)}
                    onChange={() => toggleStrategyLens(lens)}
                  />
                  <span><strong>{STRATEGY_LENSES[lens].label}</strong><small>{STRATEGY_LENSES[lens].description}</small></span>
                </label>
              ))}
            </div>
          </fieldset>

          <div className={s.readiness}>
            <div><span className={serviceReady ? s.readyDot : s.pendingDot} /><strong>分析服务</strong><em>{serviceReady ? '连接正常' : health.loading ? '正在检查' : '需要检查设置'}</em></div>
            <div><span className={s.readyDot} /><strong>交易方式</strong><em>仅研究和模拟</em></div>
            <div><span className={s.readyDot} /><strong>量化方法</strong><em>{activeMethods.length} 项 · {profileConfig.marketLimit} 根样本</em></div>
            <div><span className={s.readyDot} /><strong>评估模块</strong><em>{activeModules.map((module) => MODULE_LABELS[module]).join('、')}</em></div>
            <div><span className={strategyLenses.length ? s.readyDot : s.pendingDot} /><strong>策略视角</strong><em>{strategyLenses.length ? `${strategyLenses.length} 种` : '至少选择一种'}</em></div>
          </div>

          <div className={s.primaryActions}>
            <Button
              variant="secondary"
              size="lg"
              fullWidth
              icon={<IconChevron size={18} />}
              disabled={!selected || starting}
              onClick={() => openWorkspace()}
            >进入评估工作区</Button>
            <Button
              variant="primary"
              size="lg"
              fullWidth
              icon={<IconChart size={18} />}
              disabled={!selected || starting || strategyLenses.length === 0}
              loading={starting}
              onClick={() => void beginEvaluation()}
            >开始评估</Button>
          </div>
          {recentTask && selected && (
            <div className={s.reuseNotice} role="status">
              <div>
                <strong>15 分钟内已有同股票、市场和周期的评估</strong>
                <span>{new Date(recentTask.created_at * 1000).toLocaleString('zh-CN', { hour12: false })} · {recentTask.status}</span>
              </div>
              <div>
                <Button variant="primary" size="sm" onClick={() => openTask(selected, horizonConfig.timeframe, recentTask.id)}>复用已有评估</Button>
                <Button variant="secondary" size="sm" onClick={() => void beginEvaluation(selected, horizon, true)}>仍然新建</Button>
              </div>
            </div>
          )}
          {startError && <p className={s.fieldError} role="alert">{startError}</p>}
          {!selected && <p className={s.actionHint}>先从左侧选择一个标的</p>}
        </aside>
      </div>

      {/* M2-03：新闻证据 / 价格结构 / 模型共识 已从一级导航折叠进「市场研究」，
          此处提供页内模块入口，保证三个二级页仍然可达（原「查看示例评估」按钮指向已删除的
          /example 路由，且属于示例数据入口，按 M2-02 / M3-02 一并移除）。 */}
      <section className={s.secondaryActions}>
        <button type="button" onClick={() => navigate('/news')}>
          <IconSearch size={19} />
          <span><strong>新闻证据</strong><small>事件与情绪，按标的检索原文</small></span>
        </button>
        <button type="button" onClick={() => navigate('/pa')}>
          <IconChart size={19} />
          <span><strong>价格结构</strong><small>两阶段价格行为分析</small></span>
        </button>
        <button type="button" onClick={() => navigate('/ensemble')}>
          <IconChart size={19} />
          <span><strong>模型共识</strong><small>多模型协同结论对比</small></span>
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
