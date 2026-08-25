// 历史模拟实验兼容页：只回读既有 data/demo_runs 记录，绝不创建新运行。

import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { DemoEquityPoint, DemoRunRecord, DemoRunSummary, DemoTrade } from '../api/types'
import { Badge, Panel, Table } from '../components/ui'
import type { Column } from '../components/ui'
import { WorkspaceHeader } from '../components/WorkspaceHeader/WorkspaceHeader'
import s from './DemoLabPage.module.css'

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
  return iso ? iso.slice(0, 10) : '—'
}

function EquityChart({ points, initial }: { points: DemoEquityPoint[]; initial: number }) {
  const W = 960
  const H = 260
  const padX = 12
  const padTop = 12
  const equityH = 180
  const ddTop = equityH + 24
  const ddH = H - ddTop - 8

  if (points.length < 2) return <p className={s.hint}>净值点不足，无法绘制曲线。</p>

  const values = points.map((point) => point.equity)
  const min = Math.min(initial, ...values)
  const max = Math.max(initial, ...values)
  const span = max - min || 1
  const stepX = (W - padX * 2) / (points.length - 1)
  const x = (index: number) => padX + index * stepX
  const y = (value: number) => padTop + equityH - ((value - min) / span) * equityH

  let peak = values[0]
  const drawdowns = values.map((value) => {
    peak = Math.max(peak, value)
    return peak > 0 ? (value - peak) / peak : 0
  })
  const worst = Math.min(...drawdowns, -1e-6)
  const ddY = (value: number) => ddTop + (value / worst) * ddH
  const equityPath = points.map((point, index) => `${index === 0 ? 'M' : 'L'}${x(index).toFixed(1)},${y(point.equity).toFixed(1)}`).join(' ')
  const ddPath = `M${x(0).toFixed(1)},${ddTop} ${drawdowns.map((value, index) => `L${x(index).toFixed(1)},${ddY(value).toFixed(1)}`).join(' ')} L${x(points.length - 1).toFixed(1)},${ddTop} Z`
  const stroke = values[values.length - 1] >= initial ? 'var(--up-ink)' : 'var(--down-ink)'

  return <svg className={s.chart} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label="历史净值与回撤曲线">
    <line x1={padX} y1={y(initial)} x2={W - padX} y2={y(initial)} stroke="var(--border-strong)" strokeDasharray="4 4" />
    <path d={equityPath} fill="none" stroke={stroke} strokeWidth={2} vectorEffect="non-scaling-stroke" />
    <line x1={padX} y1={ddTop} x2={W - padX} y2={ddTop} stroke="var(--border)" />
    <path d={ddPath} fill="var(--down-weak)" stroke="var(--down-ink)" strokeWidth={1} vectorEffect="non-scaling-stroke" />
  </svg>
}

export default function DemoLabPage() {
  const [history, setHistory] = useState<DemoRunSummary[]>([])
  const [result, setResult] = useState<DemoRunRecord | null>(null)
  const [error, setError] = useState('')

  const loadHistory = useCallback(async () => {
    setError('')
    try {
      const response = await api.demoRuns(15)
      setHistory(response.runs)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '历史运行记录加载失败')
    }
  }, [])

  useEffect(() => {
    void loadHistory()
  }, [loadHistory])

  const openHistoryRun = useCallback(async (runId: string) => {
    setError('')
    try {
      const response = await api.demoRunDetail(runId)
      setResult(response.run)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '历史运行记录加载失败')
    }
  }, [])

  const metrics = result?.summary.metrics ?? {}
  const provenance = result?.data_provenance
  const tradeColumns: Column<DemoTrade>[] = [
    { key: 'datetime', header: '时间', render: (row) => shortTime(row.datetime), width: 130 },
    { key: 'side', header: '方向', width: 64, render: (row) => <Badge variant={row.side === 'buy' ? 'up' : 'down'}>{row.side === 'buy' ? '买入' : '卖出'}</Badge> },
    { key: 'price', header: '价格', align: 'right', render: (row) => <span className={s.num}>{num(row.price, 4)}</span> },
    { key: 'qty', header: '数量', align: 'right', render: (row) => <span className={s.num}>{num(row.qty, 0)}</span> },
    { key: 'realized_pnl', header: '已实现盈亏', align: 'right', render: (row) => row.side === 'sell' ? <span className={`${s.num} ${row.realized_pnl >= 0 ? s.up : s.down}`}>{num(row.realized_pnl, 2)}</span> : <span className={s.num}>—</span> },
  ]
  const historyColumns: Column<DemoRunSummary>[] = [
    { key: 'created_at', header: '时间', render: (row) => shortTime(row.created_at), width: 120 },
    { key: 'source', header: '数据源', width: 110, render: (row) => <Badge variant={row.source === 'synthetic' ? 'neutral' : 'accent'}>{row.source === 'okx_local' ? 'OKX 归档' : row.source === 'okx_live' ? 'OKX 实时' : '合成'}</Badge> },
    { key: 'symbol', header: '标的', render: (row) => row.symbol ?? '—', width: 110 },
    { key: 'interval', header: '周期', render: (row) => row.interval ?? '—', width: 60 },
    { key: 'strategy', header: '策略', render: (row) => `${row.strategy ?? '—'}${row.factor ? ` · ${row.factor}` : ''}` },
    { key: 'total_return', header: '收益', align: 'right', width: 88, render: (row) => <span className={`${s.num} ${(row.total_return ?? 0) >= 0 ? s.up : s.down}`}>{pct(row.total_return)}</span> },
    { key: 'max_drawdown', header: '回撤', align: 'right', width: 88, render: (row) => <span className={s.num}>{pct(row.max_drawdown)}</span> },
    { key: 'sharpe', header: '夏普', align: 'right', width: 72, render: (row) => <span className={s.num}>{num(row.sharpe)}</span> },
  ]
  const headerMetrics = result
    ? [{ label: '历史收益', value: pct(result.summary.total_return) }, { label: '最大回撤', value: pct(result.summary.max_drawdown) }, { label: '运行编号', value: result.run_id }]
    : [{ label: '历史运行', value: history.length }, { label: '页面状态', value: '兼容只读' }]

  return <div className={s.page}>
    <WorkspaceHeader context="交易 / 模拟实验室" title="模拟实验历史" description="仅回读既有模拟实验记录；此入口不创建新运行。" metrics={headerMetrics} />
    <section className={s.legacyRoute} aria-labelledby="legacy-route-title">
      <div><span>兼容入口</span><h2 id="legacy-route-title">选择新运行的职责页面</h2><p>此页只保留旧记录及其绩效、成交和可复现凭据。新因子验证或策略回测不会写入旧 Demo 目录。</p></div>
      <nav aria-label="新运行入口"><Link to="/factor-research">验证因子</Link><Link to="/strategies">回测已安装策略</Link><Link to="/strategy-lab">管理策略实验</Link></nav>
    </section>
    {error ? <div className={s.errorBox}>{error}</div> : null}
    {result && provenance ? <>
      <Panel title="历史绩效指标" subtitle={`${result.summary.engine} · ${result.summary.n_trades} 笔成交`}>
        <div className={s.kpiGrid}>
          <div className={s.kpiCard}><span className={s.kpiLabel}>总收益</span><span className={`${s.kpiValue} ${result.summary.total_return >= 0 ? s.up : s.down}`}>{pct(result.summary.total_return)}</span><span className={s.kpiSub}>期末权益 {num(result.summary.final_equity, 0)}</span></div>
          <div className={s.kpiCard}><span className={s.kpiLabel}>最大回撤</span><span className={`${s.kpiValue} ${s.down}`}>{pct(result.summary.max_drawdown)}</span><span className={s.kpiSub}>Calmar {num(metrics.calmar)}</span></div>
          <div className={s.kpiCard}><span className={s.kpiLabel}>夏普比率</span><span className={s.kpiValue}>{num(metrics.sharpe)}</span><span className={s.kpiSub}>Sortino {num(metrics.sortino)}</span></div>
          <div className={s.kpiCard}><span className={s.kpiLabel}>交易胜率</span><span className={s.kpiValue}>{pct(metrics.trade_win_rate, 1)}</span><span className={s.kpiSub}>{metrics.trade_count ?? 0} 次平仓</span></div>
        </div>
      </Panel>
      <Panel title="历史净值与回撤"><div className={s.chartWrap}><EquityChart points={result.equity_curve} initial={Number(result.config.initial_capital) || 1} /></div></Panel>
      <Panel title="历史数据来源与可复现凭据">
        <div className={s.provGrid}>
          <div className={s.provItem}><span className={s.provLabel}>数据通道</span><span className={s.provValue}>{provenance.channel}</span></div>
          <div className={s.provItem}><span className={s.provLabel}>数据指纹 (sha256)</span><span className={s.provValue}>{provenance.fingerprint}</span></div>
          <div className={s.provItem}><span className={s.provLabel}>覆盖区间</span><span className={s.provValue}>{provenance.selected_first ? `${dayOnly(provenance.selected_first)} ~ ${dayOnly(provenance.selected_last)}` : '—'}{provenance.bars ? ` · ${provenance.bars} 根` : ''}</span></div>
          <div className={s.provItem}><span className={s.provLabel}>历史记录</span><span className={s.provValue}>data/demo_runs/{result.run_id}.json（只读）</span></div>
        </div>
      </Panel>
      <Panel title="历史运行日志" subtitle={`${result.run_log.length} 条`} collapsible defaultOpen>
        <ol className={s.logList}>{result.run_log.map((entry, index) => <li key={index} className={s.logItem}><span className={s.logTime}>{new Date(entry.at).toLocaleTimeString('zh-CN', { hour12: false })}</span><span className={s.logStep}>{entry.step}</span><span className={s.logMsg}>{entry.message}</span></li>)}</ol>
      </Panel>
      <Panel title="历史成交明细" subtitle={`共 ${result.trades.length} 笔，展示最近 100 笔`} collapsible defaultOpen={false}><Table columns={tradeColumns} rows={result.trades.slice(-100).reverse()} rowKey={(row, index) => `${row.datetime}-${index}`} density="compact" empty="本次回测没有产生成交" /></Panel>
    </> : null}
    <Panel title="历史运行" subtitle="点击任意一行回读完整历史结果" collapsible defaultOpen={!result}><Table columns={historyColumns} rows={history} rowKey={(row) => row.run_id} density="compact" onRowClick={(row) => void openHistoryRun(row.run_id)} activeRowKey={result?.run_id ?? null} empty="没有保留的历史运行记录" /></Panel>
  </div>
}
