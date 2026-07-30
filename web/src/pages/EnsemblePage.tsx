import { useEffect, useMemo, useState } from 'react'
import type { EnsembleContributor, EnsembleResp } from '../api/types'
import { api } from '../api/client'
import { executeAnalysisTask } from '../api/taskRunner'
import { useApi } from '../api/useApi'
import KlineCard from '../components/KlineCard'
import { EmptyState, ErrorState } from '../components/ui/EmptyState/EmptyState'
import { RefreshControl } from '../components/ui/RefreshControl/RefreshControl'
import { Button } from '../components/ui/Button/Button'
import { Input } from '../components/ui/Input/Input'
import { Select } from '../components/ui/Select/Select'
import { SegmentedControl } from '../components/ui/SegmentedControl/SegmentedControl'
import { WorkspaceHeader } from '../components/WorkspaceHeader/WorkspaceHeader'
import s from './EnsemblePage.module.css'
import '../styles/ensemble.css'

const TIMEFRAMES = ['1d', '1h', '1w'] as const
type TF = (typeof TIMEFRAMES)[number]
const LIMIT = 200

// 市场选择：与后端数据源和 _resolve_market 对齐。
const MARKETS = [
  { value: 'a_shares', label: 'A股' },
  { value: 'us_stocks', label: '美股' },
  { value: 'crypto', label: '虚拟货币' },
] as const
type Market = (typeof MARKETS)[number]['value']

const TF_OPTIONS = TIMEFRAMES.map((t) => ({ value: t, label: t }))
const MARKET_OPTIONS = MARKETS.map((m) => ({ value: m.value, label: m.label }))

type Dir = 'buy' | 'sell' | 'hold'

function dirLabel(d: string): { title: string; sub: string } {
  if (d === 'buy') return { title: '看多', sub: '多数算法倾向买入' }
  if (d === 'sell') return { title: '看空', sub: '多数算法倾向卖出' }
  return { title: '观望', sub: '多空分歧，等待确认' }
}
function dirClass(d: string): 'long' | 'short' | 'hold' {
  return d === 'buy' ? 'long' : d === 'sell' ? 'short' : 'hold'
}
function dirColor(d: string): string {
  return d === 'buy' ? 'var(--up)' : d === 'sell' ? 'var(--down)' : 'var(--accent)'
}
function kindLabel(k: string): string {
  return k === 'llm' ? 'LLM' : k === 'news' ? '新闻' : '技术'
}

function scoreRing(score: number, color: string) {
  const R = 34
  const C = 2 * Math.PI * R
  const off = C * (1 - Math.max(0, Math.min(1, score)))
  return (
    <svg className="ens-ring" viewBox="0 0 80 80" role="img" aria-label={`综合强度 ${Math.round(score * 100)}%`}>
      <circle className="ens-ring-bg" cx={40} cy={40} r={R} />
      <circle
        className="ens-ring-fg"
        cx={40}
        cy={40}
        r={R}
        style={{ stroke: color, strokeDasharray: C, strokeDashoffset: off }}
        transform="rotate(-90 40 40)"
      />
      <text className="ens-ring-num" x={40} y={40}>
        {Math.round(score * 100)}
      </text>
    </svg>
  )
}

function contribCard(c: EnsembleContributor) {
  const cls = dirClass(c.direction)
  return (
    <div className={`ens-contrib ${cls}`} key={c.name}>
      <div className="ens-contrib-head">
        <span className="ens-contrib-name">{c.name}</span>
        <span className={`ens-kind-pill ${c.kind}`}>{kindLabel(c.kind)}</span>
        <span className={`ens-dir-pill ${cls}`}>{dirLabel(c.direction).title}</span>
      </div>
      <div className="ens-bars">
        <div className="ens-bar-row">
          <span className="ens-bar-label">强度</span>
          <div className="ens-bar-track">
            <div className="ens-bar-fill" style={{ width: `${(c.score * 100).toFixed(0)}%`, background: dirColor(c.direction) }} />
          </div>
          <span className="ens-bar-val mono">{(c.score * 100).toFixed(0)}</span>
        </div>
        <div className="ens-bar-row">
          <span className="ens-bar-label">置信</span>
          <div className="ens-bar-track">
            <div className="ens-bar-fill weak" style={{ width: `${(c.confidence * 100).toFixed(0)}%` }} />
          </div>
          <span className="ens-bar-val mono">{(c.confidence * 100).toFixed(0)}</span>
        </div>
      </div>
      <div className="ens-contrib-foot">
        <span className="ens-weight mono">权重 {(c.weight * 100).toFixed(0)}%</span>
        {c.rationale && <span className="ens-rationale">{c.rationale}</span>}
      </div>
    </div>
  )
}

interface EnsemblePageProps {
  initialSymbol?: string
  initialTimeframe?: TF
  initialMarket?: Market
  researchRunId?: string | null
  onResearchRunId?: (runId: string) => void
  embedded?: boolean
}

export default function EnsemblePage({
  initialSymbol = '600519',
  initialTimeframe = '1d',
  initialMarket = 'a_shares',
  researchRunId,
  onResearchRunId,
  embedded = false,
}: EnsemblePageProps) {
  const [symbol, setSymbol] = useState(initialSymbol)
  const [tf, setTf] = useState<TF>(initialTimeframe)
  const [market, setMarket] = useState<Market>(initialMarket)
  const [active, setActive] = useState<{
    symbol: string
    timeframe: TF
    market: Market
  }>({ symbol: initialSymbol, timeframe: initialTimeframe, market: initialMarket })
  const [requestKey, setRequestKey] = useState(0)
  const [publishing, setPublishing] = useState(false)
  const [publishMessage, setPublishMessage] = useState('')

  function run() {
    const normalized = symbol.trim().toUpperCase()
    if (!normalized) return
    setActive({ symbol: normalized, timeframe: tf, market })
    setRequestKey((key) => key + 1)
  }

  const { data, loading, error, reconnecting, updatedAt, refetch } = useApi(
    () => executeAnalysisTask<EnsembleResp>({
      kind: 'ensemble',
      symbol: active.symbol,
      market: active.market,
      timeframe: active.timeframe,
      payload: {
        limit: LIMIT,
        research_run_id: researchRunId ?? undefined,
      },
      timeoutSeconds: 90,
    }),
    [active.symbol, active.timeframe, active.market, requestKey],
    { enabled: requestKey > 0, retry: false },
  )

  useEffect(() => {
    if (data?.research_run_id) onResearchRunId?.(data.research_run_id)
  }, [data?.research_run_id, onResearchRunId])
  const cons = data?.consensus
  const contributors = data?.contributors ?? []
  const isReal = !!data?.ok

  const votes = useMemo(() => {
    let b = 0
    let s = 0
    let h = 0
    for (const c of contributors) {
      const w = c.weight || 0.1
      if (c.direction === 'buy') b += c.confidence * w
      else if (c.direction === 'sell') s += c.confidence * w
      else h += c.confidence * w
    }
    const total = b + s + h
    return {
      buy: total > 0 ? b / total : 0,
      sell: total > 0 ? s / total : 0,
      hold: total > 0 ? h / total : 0,
    }
  }, [contributors])

  const verdict = cons ? dirLabel(cons.direction) : dirLabel('hold')
  const verdictCls = cons ? dirClass(cons.direction) : 'hold'
  const verdictColor = cons ? dirColor(cons.direction) : 'var(--accent)'
  const src = data?.data_source ?? ''
  // local = 本地 parquet 缓存（真实历史数据，非离线）；empty = 无数据；其余无源 = 离线
  const srcLabel =
    src === 'tencent' || src === 'akshare'
      ? '实时'
      : src === 'local'
        ? '本地缓存'
        : src === 'empty'
          ? '无数据'
          : '离线'
  const srcCls =
    src === 'tencent' || src === 'akshare'
      ? 'live'
      : src === 'local'
        ? 'loading'
        : src === 'empty'
          ? 'mock'
          : 'warn'

  async function publishConsensus() {
    if (!data?.ok || !data.consensus) return
    setPublishing(true)
    setPublishMessage('')
    try {
      const runId = data.research_run_id ?? researchRunId ?? null
      const response = await api.publishSignal({
        symbol: data.symbol,
        market: data.market ?? active.market,
        timeframe: data.timeframe ?? active.timeframe,
        direction: data.consensus.direction,
        score: data.consensus.score,
        confidence: data.consensus.confidence,
        source: 'ensemble',
        tags: ['ensemble', 'consensus', 'research'],
        meta: {
          research_run_id: runId,
          agreement: data.consensus.agreement,
          buy_votes: data.consensus.buy_votes,
          sell_votes: data.consensus.sell_votes,
          contributors: data.contributors ?? [],
        },
      })
      if (runId) {
        await api.addResearchEvidence(runId, {
          kind: 'signal',
          source: 'signals',
          title: `${data.symbol} 协同预测待审核信号`,
          payload: { signal: response.signal },
        })
      }
      setPublishMessage(response.ok ? '信号已进入审核队列' : '信号发布失败')
    } catch (reason) {
      setPublishMessage(reason instanceof Error ? reason.message : '信号发布失败')
    } finally {
      setPublishing(false)
    }
  }

  return (
    <div className={s.page}>
      {!embedded && (
        <WorkspaceHeader
          context="研究 / 综合评估 / 模型共识"
          title="模型共识"
          metrics={[
            { label: '数据源', value: srcLabel },
            { label: '参与算法', value: cons?.n ?? 0 },
            { label: '共识度', value: `${Math.round((cons?.agreement ?? 0) * 100)}%` },
            { label: '综合置信', value: `${Math.round((cons?.confidence ?? 0) * 100)}%` },
          ]}
        />
      )}
      {/* 控制条 */}
      <div className="card">
        <div className="card-head">
          <div className="card-title">
            算法协同预测
            <span className="sub">多种算法同屏预测 · 加权共识</span>
          </div>
        </div>
        <div className={s.controlBar}>
          <div className={s.fieldGroup}>
            <label className={s.fieldLabel}>标的代码</label>
            <Input
              className={s.symbolInput}
              type="text"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && run()}
              placeholder="如 600519"
            />
          </div>
          <div className={s.fieldGroup}>
            <label className={s.fieldLabel}>周期</label>
            <SegmentedControl
              value={tf}
              onChange={(v) => setTf(v as TF)}
              options={TF_OPTIONS}
              size="sm"
            />
          </div>
          <div className={s.fieldGroup}>
            <label className={s.fieldLabel}>市场</label>
            <Select
              className={s.marketSelect}
              options={MARKET_OPTIONS}
              value={market}
              onChange={(e) => setMarket(e.target.value as Market)}
            />
          </div>
          <Button
            variant="primary"
            className={s.runBtn}
            onClick={run}
            loading={loading}
          >
            {loading ? '预测中…' : '运行协同预测'}
          </Button>
        </div>
      </div>

      {/* 共识大牌 */}
      <div className="card ens-consensus">
        <div className="card-head">
          <div className="card-title">
            协同共识
            <span className="sub">{active.symbol} · {active.timeframe}</span>
          </div>
          <span className={`src-pill ${srcCls}`}>{srcLabel}</span>
        </div>

        {isReal && cons && (
          <div className={s.publishBar}>
            <Button variant="primary" size="sm" onClick={() => void publishConsensus()} loading={publishing}>
              生成待审核信号
            </Button>
            {publishMessage && <span>{publishMessage} · <a href="/signals">打开信号审核</a></span>}
          </div>
        )}

        {!isReal && !loading ? (
          error ? (
            <ErrorState message={error} onRetry={refetch} retrying={loading} />
          ) : (
            <EmptyState
              title="尚未运行"
              desc="输入标的后点击「运行协同预测」"
            />
          )
        ) : (
          <div className="ens-verdict">
            <div className="ens-verdict-main">
              <span className={`ens-dir-pill lg ${verdictCls}`}>{verdict.title}</span>
              <div className="ens-verdict-sub">{verdict.sub}</div>
            </div>
            {cons && scoreRing(cons.score, verdictColor)}
            <div className="ens-stats">
              <div className="ens-stat">
                <span className="k">共识度</span>
                <span className="v mono">{Math.round((cons?.agreement ?? 0) * 100)}%</span>
              </div>
              <div className="ens-stat">
                <span className="k">综合置信</span>
                <span className="v mono">{Math.round((cons?.confidence ?? 0) * 100)}%</span>
              </div>
              <div className="ens-stat">
                <span className="k">参与算法</span>
                <span className="v mono">{cons?.n ?? 0}</span>
              </div>
            </div>
          </div>
        )}

        {/* 多空分歧条 */}
        {isReal && contributors.length > 0 && (
          <div className="ens-votes-wrap">
            <div className="ens-votes">
              <i className="buy" style={{ width: `${(votes.buy * 100).toFixed(1)}%` }} />
              <i className="hold" style={{ width: `${(votes.hold * 100).toFixed(1)}%` }} />
              <i className="sell" style={{ width: `${(votes.sell * 100).toFixed(1)}%` }} />
            </div>
            <div className="ens-vote-legend">
              <span><b className="up">{Math.round(votes.buy * 100)}%</b> 看多</span>
              <span><b>{Math.round(votes.hold * 100)}%</b> 观望</span>
              <span><b className="down">{Math.round(votes.sell * 100)}%</b> 看空</span>
            </div>
          </div>
        )}

        {/* 预警：缺 Key 的算法 */}
        {isReal && data?.warnings && data.warnings.length > 0 && (
          <div className="ens-warnings">
            {data.warnings.map((w, i) => (
              <div key={i} className="ens-warn-item">ⓘ {w}</div>
            ))}
          </div>
        )}
      </div>

      {/* K 线（真实场景上下文） + 算法贡献者 */}
      <div className="grid-2">
        <div className="col-left">
          <KlineCard symbol={active.symbol} market={active.market} />
        </div>
        <div className="col-right">
          <div className="card">
            <div className="card-head">
              <div className="card-title">
                算法贡献者
                <span className="sub">每个算法的方向与强度</span>
              </div>
              {requestKey > 0 && (
                <RefreshControl onRefresh={refetch} refreshing={loading || reconnecting} updatedAt={updatedAt} />
              )}
            </div>
            <div className="ens-contrib-grid">
              {loading && contributors.length === 0 ? (
                <div className={`muted ${s.contribHint}`}>
                  加载中…
                </div>
              ) : contributors.length === 0 ? (
                <div className={`muted ${s.contribHint}`}>
                  暂无可用算法（检查标的与数据源）
                </div>
              ) : (
                contributors.map(contribCard)
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
