// 模拟实验室兼容页：保留历史运行回读，不再创建与因子/策略职责重叠的新运行。
//
// 三条数据通道统一在此页驱动：
//   okx_local  本地归档的真实 OKX K 线（离线，完全可复现）
//   okx_live   OKX 公共行情接口实时拉取（首拉落盘快照后可复现）
//   synthetic  确定性合成行情（按 seed 复现，用于压力形态测试）
//
// 页面职责：参数配置 → 一键运行 → KPI / 净值曲线 / 成交明细 / 运行日志 / 可复现凭据。

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type {
  DemoCatalog,
  DemoEquityPoint,
  DemoRunPayload,
  DemoRunResult,
  DemoRunSummary,
  DemoSourceKey,
  DemoSourceOption,
  DemoTrade,
} from '../api/types'
import { Badge, Button, Field, Input, Panel, SegmentedControl, Select, Table, Toggle } from '../components/ui'
import type { Column } from '../components/ui'
import { WorkspaceHeader } from '../components/WorkspaceHeader/WorkspaceHeader'
import s from './DemoLabPage.module.css'

interface FormState {
  source: DemoSourceKey
  symbol: string
  dataset: string
  seed: number
  interval: string
  nBars: number
  start: string
  end: string
  useCache: boolean
  initialCapital: number
  commission: number
  positionFraction: number
  strategy: string
  factor: string
  factorParams: Record<string, number>
}

const FALLBACK_FORM: FormState = {
  source: 'okx_local',
  symbol: 'BTCUSDT',
  dataset: 'uptrend',
  seed: 12,
  interval: '1d',
  nBars: 300,
  start: '',
  end: '',
  useCache: true,
  initialCapital: 1_000_000,
  commission: 0.0003,
  positionFraction: 1,
  strategy: 'factor_follow',
  factor: 'momentum',
  factorParams: {},
}

function pct(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `${(value * 100).toFixed(digits)}%`
}

function num(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return value.toLocaleString('zh-CN', { maximumFractionDigits: digits, minimumFractionDigits: digits })
}

function shortTime(iso: string | null | undefined) {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString('zh-CN', { hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function dayOnly(iso: string | null | undefined) {
  if (!iso) return '—'
  return iso.slice(0, 10)
}

/** 净值 + 回撤双轨图（纯 SVG，零依赖）。 */
function EquityChart({ points, initial }: { points: DemoEquityPoint[]; initial: number }) {
  const W = 960
  const H = 260
  const padX = 12
  const padTop = 12
  const equityH = 180
  const ddTop = equityH + 24
  const ddH = H - ddTop - 8

  if (points.length < 2) return <p className={s.hint}>净值点不足，无法绘制曲线。</p>

  const values = points.map((p) => p.equity)
  const min = Math.min(initial, ...values)
  const max = Math.max(initial, ...values)
  const span = max - min || 1
  const stepX = (W - padX * 2) / (points.length - 1)
  const x = (i: number) => padX + i * stepX
  const y = (v: number) => padTop + equityH - ((v - min) / span) * equityH

  let peak = values[0]
  const drawdowns = values.map((v) => {
    peak = Math.max(peak, v)
    return peak > 0 ? (v - peak) / peak : 0
  })
  const worst = Math.min(...drawdowns, -1e-6)
  const ddY = (v: number) => ddTop + (v / worst) * ddH

  const equityPath = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(p.equity).toFixed(1)}`).join(' ')
  const ddPath = `M${x(0).toFixed(1)},${ddTop} ${drawdowns
    .map((v, i) => `L${x(i).toFixed(1)},${ddY(v).toFixed(1)}`)
    .join(' ')} L${x(points.length - 1).toFixed(1)},${ddTop} Z`

  const up = values[values.length - 1] >= initial
  const stroke = up ? 'var(--up-ink)' : 'var(--down-ink)'

  return (
    <svg className={s.chart} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label="净值与回撤曲线">
      <line x1={padX} y1={y(initial)} x2={W - padX} y2={y(initial)} stroke="var(--border-strong)" strokeDasharray="4 4" />
      <path d={equityPath} fill="none" stroke={stroke} strokeWidth={2} vectorEffect="non-scaling-stroke" />
      <line x1={padX} y1={ddTop} x2={W - padX} y2={ddTop} stroke="var(--border)" />
      <path d={ddPath} fill="var(--down-weak)" stroke="var(--down-ink)" strokeWidth={1} vectorEffect="non-scaling-stroke" />
    </svg>
  )
}

export default function DemoLabPage() {
  const [catalog, setCatalog] = useState<DemoCatalog | null>(null)
  const [catalogError, setCatalogError] = useState('')
  const [form, setForm] = useState<FormState>(FALLBACK_FORM)
  const [result, setResult] = useState<DemoRunResult | null>(null)
  const [history, setHistory] = useState<DemoRunSummary[]>([])
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')

  const patch = useCallback((changes: Partial<FormState>) => {
    setForm((prev) => ({ ...prev, ...changes }))
  }, [])

  const loadHistory = useCallback(async () => {
    try {
      const resp = await api.demoRuns(15)
      setHistory(resp.runs)
    } catch {
      /* 历史记录属于辅助信息，失败不打断主流程 */
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    api
      .demoPresets()
      .then((data) => {
        if (cancelled) return
        setCatalog(data)
        const d = data.defaults
        setForm((prev) => ({
          ...prev,
          source: d.source,
          symbol: d.symbol,
          dataset: d.dataset,
          seed: d.seed,
          interval: d.interval,
          nBars: Math.max(prev.nBars, d.n_bars),
          initialCapital: d.initial_capital,
          commission: d.commission,
          positionFraction: d.position_fraction,
          strategy: d.strategy,
          factor: d.factor,
        }))
      })
      .catch((e: unknown) => {
        if (!cancelled) setCatalogError(e instanceof Error ? e.message : String(e))
      })
    void loadHistory()
    return () => {
      cancelled = true
    }
  }, [loadHistory])

  const sources: DemoSourceOption[] = catalog?.sources ?? []
  const activeSource = sources.find((item) => item.key === form.source) ?? null
  const strategyMeta = catalog?.strategies.find((item) => item.key === form.strategy) ?? null
  const factorMeta = catalog?.factors.find((item) => item.key === form.factor) ?? null
  const isSynthetic = form.source === 'synthetic'

  // 切换数据源时，把标的与周期收敛到该通道真正支持的取值，避免提交非法组合
  useEffect(() => {
    if (!activeSource) return
    setForm((prev) => {
      const next: Partial<FormState> = {}
      if (activeSource.symbols.length > 0 && !activeSource.symbols.some((item) => item.symbol === prev.symbol)) {
        next.symbol = activeSource.symbols[0].symbol
      }
      if (!activeSource.intervals.includes(prev.interval)) {
        next.interval = activeSource.intervals.includes('1d') ? '1d' : activeSource.intervals[0]
      }
      return Object.keys(next).length ? { ...prev, ...next } : prev
    })
  }, [activeSource])

  // 因子切换时载入其默认参数，用户可继续微调
  useEffect(() => {
    if (!factorMeta) return
    setForm((prev) => ({ ...prev, factorParams: { ...factorMeta.default_params } }))
  }, [factorMeta])

  const coverage = useMemo(() => {
    if (!activeSource || activeSource.key !== 'okx_local') return null
    return activeSource.symbol_coverage[form.symbol]?.[form.interval] ?? null
  }, [activeSource, form.symbol, form.interval])

  const runDemo = useCallback(async () => {
    setRunning(true)
    setError('')
    const payload: DemoRunPayload = {
      source: form.source,
      symbol: isSynthetic ? null : form.symbol,
      dataset: form.dataset,
      seed: form.seed,
      n_bars: form.nBars,
      interval: form.interval,
      start: form.start || null,
      end: form.end || null,
      use_cache: form.useCache,
      initial_capital: form.initialCapital,
      commission: form.commission,
      position_fraction: form.positionFraction,
      strategy: form.strategy,
      factor: strategyMeta?.uses_factor ? form.factor : null,
      factor_params: strategyMeta?.uses_factor ? form.factorParams : {},
    }
    try {
      const resp = await api.demoRun(payload)
      setResult(resp)
      void loadHistory()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setRunning(false)
    }
  }, [form, isSynthetic, strategyMeta, loadHistory])

  const openHistoryRun = useCallback(async (runId: string) => {
    setError('')
    try {
      const resp = await api.demoRunDetail(runId)
      const run = resp.run
      setResult({
        ok: true,
        run_id: run.run_id,
        config: run.config,
        data_provenance: run.data_provenance,
        summary: run.summary,
        equity_curve: run.equity_curve,
        trades: run.trades,
        run_log: run.run_log,
        persisted: true,
      })
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [])

  const metrics = result?.summary.metrics ?? {}
  const provenance = result?.data_provenance ?? null

  const tradeColumns: Column<DemoTrade>[] = [
    { key: 'datetime', header: '时间', render: (row) => shortTime(row.datetime), width: 130 },
    {
      key: 'side',
      header: '方向',
      width: 64,
      render: (row) => <Badge variant={row.side === 'buy' ? 'up' : 'down'}>{row.side === 'buy' ? '买入' : '卖出'}</Badge>,
    },
    { key: 'price', header: '价格', align: 'right', render: (row) => <span className={s.num}>{num(row.price, 4)}</span> },
    { key: 'qty', header: '数量', align: 'right', render: (row) => <span className={s.num}>{num(row.qty, 0)}</span> },
    {
      key: 'realized_pnl',
      header: '已实现盈亏',
      align: 'right',
      render: (row) =>
        row.side === 'sell' ? (
          <span className={`${s.num} ${row.realized_pnl >= 0 ? s.up : s.down}`}>{num(row.realized_pnl, 2)}</span>
        ) : (
          <span className={s.num}>—</span>
        ),
    },
  ]

  const historyColumns: Column<DemoRunSummary>[] = [
    { key: 'created_at', header: '时间', render: (row) => shortTime(row.created_at), width: 120 },
    {
      key: 'source',
      header: '数据源',
      width: 110,
      render: (row) => (
        <Badge variant={row.source === 'synthetic' ? 'neutral' : 'accent'}>
          {row.source === 'okx_local' ? 'OKX 归档' : row.source === 'okx_live' ? 'OKX 实时' : '合成'}
        </Badge>
      ),
    },
    { key: 'symbol', header: '标的', render: (row) => row.symbol ?? '—', width: 110 },
    { key: 'interval', header: '周期', render: (row) => row.interval ?? '—', width: 60 },
    { key: 'strategy', header: '策略', render: (row) => `${row.strategy ?? '—'}${row.factor ? ` · ${row.factor}` : ''}` },
    {
      key: 'total_return',
      header: '收益',
      align: 'right',
      width: 88,
      render: (row) => (
        <span className={`${s.num} ${(row.total_return ?? 0) >= 0 ? s.up : s.down}`}>{pct(row.total_return)}</span>
      ),
    },
    { key: 'max_drawdown', header: '回撤', align: 'right', width: 88, render: (row) => <span className={s.num}>{pct(row.max_drawdown)}</span> },
    { key: 'sharpe', header: '夏普', align: 'right', width: 72, render: (row) => <span className={s.num}>{num(row.sharpe)}</span> },
  ]

  const headerMetrics = result
    ? [
        { label: '本次收益', value: pct(result.summary.total_return) },
        { label: '最大回撤', value: pct(result.summary.max_drawdown) },
        { label: '运行编号', value: result.run_id },
      ]
    : [
        { label: '历史运行', value: history.length },
        { label: '页面状态', value: '兼容只读' },
      ]

  return (
    <div className={s.page}>
      <WorkspaceHeader
        context="交易 / 模拟实验室"
        title="模拟实验历史"
        description="回读既有模拟实验记录；新的因子验证和策略回测已回到各自职责页面。"
        metrics={headerMetrics}
      />

      {catalogError ? <div className={s.errorBox}>加载配置目录失败：{catalogError}</div> : null}

      <section className={s.legacyRoute} aria-labelledby="legacy-route-title">
        <div>
          <span>兼容入口</span>
          <h2 id="legacy-route-title">选择新运行的职责页面</h2>
          <p>此页不再创建重复回测；下方历史记录及其绩效、成交和可复现凭据保持可读。</p>
        </div>
        <nav aria-label="新运行入口">
          <Link to="/factor-research">验证因子</Link>
          <Link to="/strategies">回测已安装策略</Link>
          <Link to="/strategy-lab">管理策略实验</Link>
        </nav>
      </section>

      {error ? <div className={s.errorBox}>{error}</div> : null}

      {result ? (
        <>
          <Panel title="绩效指标" subtitle={`${result.summary.engine} · ${result.summary.n_trades} 笔成交`}>
            <div className={s.formGrid}>
              <div className={s.kpiGrid} style={{ gridColumn: '1 / -1' }}>
                <div className={s.kpiCard}>
                  <span className={s.kpiLabel}>总收益</span>
                  <span className={`${s.kpiValue} ${result.summary.total_return >= 0 ? s.up : s.down}`}>
                    {pct(result.summary.total_return)}
                  </span>
                  <span className={s.kpiSub}>期末权益 {num(result.summary.final_equity, 0)}</span>
                </div>
                <div className={s.kpiCard}>
                  <span className={s.kpiLabel}>最大回撤</span>
                  <span className={`${s.kpiValue} ${s.down}`}>{pct(result.summary.max_drawdown)}</span>
                  <span className={s.kpiSub}>Calmar {num(metrics.calmar)}</span>
                </div>
                <div className={s.kpiCard}>
                  <span className={s.kpiLabel}>夏普比率</span>
                  <span className={s.kpiValue}>{num(metrics.sharpe)}</span>
                  <span className={s.kpiSub}>Sortino {num(metrics.sortino)}</span>
                </div>
                <div className={s.kpiCard}>
                  <span className={s.kpiLabel}>交易胜率</span>
                  <span className={s.kpiValue}>{pct(metrics.trade_win_rate, 1)}</span>
                  <span className={s.kpiSub}>{metrics.trade_count ?? 0} 次平仓</span>
                </div>
                <div className={s.kpiCard}>
                  <span className={s.kpiLabel}>盈亏比</span>
                  <span className={s.kpiValue}>
                    {metrics.profit_factor !== undefined && !Number.isFinite(metrics.profit_factor)
                      ? '∞'
                      : num(metrics.profit_factor)}
                  </span>
                  <span className={s.kpiSub}>
                    均盈 {num(metrics.avg_win, 0)} / 均亏 {num(metrics.avg_loss, 0)}
                  </span>
                </div>
                <div className={s.kpiCard}>
                  <span className={s.kpiLabel}>年化收益</span>
                  <span className={`${s.kpiValue} ${(metrics.annual_return ?? 0) >= 0 ? s.up : s.down}`}>
                    {pct(metrics.annual_return)}
                  </span>
                  <span className={s.kpiSub}>年化波动 {pct(metrics.annual_volatility)}</span>
                </div>
              </div>
            </div>
          </Panel>

          <Panel title="净值与回撤">
            <div className={s.chartWrap}>
              <EquityChart points={result.equity_curve} initial={Number(result.config.initial_capital) || 1} />
            </div>
            <div className={s.chartLegend}>
              <span>
                <i className={s.swatch} style={{ background: 'var(--up-ink)' }} />
                净值曲线（虚线为初始资金基准）
              </span>
              <span>
                <i className={s.swatch} style={{ background: 'var(--down-ink)' }} />
                回撤（下轨，越深越差）
              </span>
            </div>
          </Panel>

          <Panel title="数据来源与可复现凭据" subtitle="用同一组参数复跑即可得到完全相同的结果">
            <div className={s.provGrid}>
              <div className={s.provItem}>
                <span className={s.provLabel}>数据通道</span>
                <span className={s.provValue}>{provenance?.channel}</span>
              </div>
              <div className={s.provItem}>
                <span className={s.provLabel}>数据指纹 (sha256)</span>
                <span className={s.provValue}>{provenance?.fingerprint}</span>
              </div>
              <div className={s.provItem}>
                <span className={s.provLabel}>覆盖区间</span>
                <span className={s.provValue}>
                  {provenance?.selected_first ? `${dayOnly(provenance.selected_first)} ~ ${dayOnly(provenance.selected_last)}` : '—'}
                  {provenance?.bars ? ` · ${provenance.bars} 根` : ''}
                </span>
              </div>
              <div className={s.provItem}>
                <span className={s.provLabel}>{provenance?.cache_file ? '行情快照' : '数据文件'}</span>
                <span className={s.provValue}>{provenance?.cache_file ?? provenance?.file ?? '内存生成（合成）'}</span>
              </div>
              <div className={s.provItem}>
                <span className={s.provLabel}>复现方式</span>
                <span className={s.provValue}>{provenance?.reproducible}</span>
              </div>
              <div className={s.provItem}>
                <span className={s.provLabel}>运行记录</span>
                <span className={s.provValue}>
                  {result.persisted ? `data/demo_runs/${result.run_id}.json` : '未落盘（写入失败）'}
                </span>
              </div>
            </div>
            <div className={s.badgeRow}>
              <Badge variant={provenance?.offline ? 'up' : 'warn'}>{provenance?.offline ? '离线可复现' : '实时取数'}</Badge>
              {provenance?.cache_hit !== undefined ? (
                <Badge variant={provenance.cache_hit ? 'accent' : 'info'}>
                  {provenance.cache_hit ? '命中快照' : '新建快照'}
                </Badge>
              ) : null}
              {provenance?.fetched_at ? <Badge variant="neutral">取数于 {shortTime(provenance.fetched_at)}</Badge> : null}
            </div>
          </Panel>

          <Panel title="运行日志" subtitle={`${result.run_log.length} 条`} collapsible defaultOpen>
            <ol className={s.logList}>
              {result.run_log.map((entry, index) => (
                <li key={index} className={s.logItem}>
                  <span className={s.logTime}>{new Date(entry.at).toLocaleTimeString('zh-CN', { hour12: false })}</span>
                  <span className={s.logStep}>{entry.step}</span>
                  <span className={s.logMsg}>{entry.message}</span>
                </li>
              ))}
            </ol>
          </Panel>

          <Panel title="成交明细" subtitle={`共 ${result.trades.length} 笔，展示最近 100 笔`} collapsible defaultOpen={false}>
            <Table
              columns={tradeColumns}
              rows={result.trades.slice(-100).reverse()}
              rowKey={(row, index) => `${row.datetime}-${index}`}
              density="compact"
              empty="本次回测没有产生成交"
            />
          </Panel>
        </>
      ) : null}

      <Panel title="历史运行" subtitle="点击任意一行可回读完整结果，用于对比不同因子与策略" collapsible defaultOpen={!result}>
        <Table
          columns={historyColumns}
          rows={history}
          rowKey={(row) => row.run_id}
          density="compact"
          onRowClick={(row) => void openHistoryRun(row.run_id)}
          activeRowKey={result?.run_id ?? null}
          empty="还没有运行记录，先点上面的「运行回测」"
        />
      </Panel>
    </div>
  )
}
