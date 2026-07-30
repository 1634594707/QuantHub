import { useMemo } from 'react'
import type { LedgerTradeAnalytics } from '../../api/types'
import s from './TradeAnalyticsPanel.module.css'

function money(value: number): string {
  const sign = value > 0 ? '+' : ''
  return `${sign}${value.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`
}

function duration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)} 秒`
  if (seconds < 3600) return `${Math.round(seconds / 60)} 分钟`
  if (seconds < 86_400) return `${(seconds / 3600).toFixed(1)} 小时`
  return `${(seconds / 86_400).toFixed(1)} 天`
}

function EquityCurve({ points }: { points: LedgerTradeAnalytics['cumulative_curve'] }) {
  const geometry = useMemo(() => {
    if (!points.length) return null
    const values = points.map((point) => point.pnl)
    const min = Math.min(0, ...values)
    const max = Math.max(0, ...values)
    const span = Math.max(1, max - min)
    const coords = points.map((point, index) => ({
      x: points.length === 1 ? 300 : 18 + (index / (points.length - 1)) * 564,
      y: 142 - ((point.pnl - min) / span) * 124,
    }))
    return {
      line: coords.map((point) => `${point.x},${point.y}`).join(' '),
      area: `18,142 ${coords.map((point) => `${point.x},${point.y}`).join(' ')} 582,142`,
      zeroY: 142 - ((0 - min) / span) * 124,
    }
  }, [points])

  if (!geometry) return <div className={s.emptyChart}>闭合交易形成后显示累计盈亏</div>
  return (
    <svg className={s.equityChart} viewBox="0 0 600 160" role="img" aria-label="闭合交易累计盈亏曲线">
      <line x1="18" x2="582" y1={geometry.zeroY} y2={geometry.zeroY} className={s.zeroLine} />
      <polygon points={geometry.area} className={s.equityArea} />
      <polyline points={geometry.line} className={s.equityLine} />
    </svg>
  )
}

function MonthlyBars({ rows }: { rows: LedgerTradeAnalytics['monthly'] }) {
  const visible = rows.slice(-12)
  const max = Math.max(1, ...visible.map((row) => Math.abs(row.pnl)))
  if (!visible.length) return <div className={s.emptyChart}>暂无月度闭合盈亏</div>
  return (
    <div className={s.monthlyBars} aria-label="月度闭合盈亏">
      {visible.map((row) => (
        <div className={s.monthColumn} key={row.key} title={`${row.key} ${money(row.pnl)}`}>
          <span className={row.pnl >= 0 ? s.barPositive : s.barNegative} style={{ height: `${Math.max(6, Math.abs(row.pnl) / max * 82)}%` }} />
          <small>{row.key.slice(5)}</small>
        </div>
      ))}
    </div>
  )
}

export function TradeAnalyticsPanel({ data }: { data: LedgerTradeAnalytics | null }) {
  if (!data) return null
  const summary = data.summary
  const maxHoldingShare = Math.max(1, ...data.holding_buckets.map((item) => item.share_pct))
  const latestDays = data.daily.slice(-28)

  return (
    <div className={s.report}>
      <header className={s.reportHeader}>
        <div>
          <span className={s.eyebrow}>闭合交易口径</span>
          <h3>交易质量分析</h3>
        </div>
        <div className={s.coverage}>
          <span>{summary.closed_trades} 笔已闭合</span>
          <span>{data.matching.open_lot_count} 个未闭合批次</span>
        </div>
      </header>

      <div className={s.kpiGrid}>
        <div><span>净盈亏</span><b className={summary.total_pnl >= 0 ? s.positive : s.negative}>{money(summary.total_pnl)}</b><small>已扣费用</small></div>
        <div><span>闭合收益率</span><b>{summary.return_pct.toFixed(2)}%</b><small>按入场名义金额</small></div>
        <div><span>胜率</span><b>{summary.win_rate_pct.toFixed(1)}%</b><small>{summary.closed_trades} 笔样本</small></div>
        <div><span>利润因子</span><b>{summary.profit_factor?.toFixed(2) ?? '—'}</b><small>总盈利 / 总亏损</small></div>
        <div><span>平均盈亏比</span><b>{summary.average_profit_loss_ratio?.toFixed(2) ?? '—'}</b><small>平均盈利 / 平均亏损</small></div>
        <div><span>最大连续亏损</span><b className={summary.max_consecutive_losses > 2 ? s.negative : ''}>{summary.max_consecutive_losses}</b><small>闭合交易序列</small></div>
        <div><span>平均持仓</span><b>{duration(summary.average_holding_seconds)}</b><small>按配对批次</small></div>
        <div><span>最长停滞</span><b>{summary.max_stagnation_days.toFixed(1)} 天</b><small>未创新高时段</small></div>
      </div>

      <div className={s.visualGrid}>
        <section className={s.widePanel}>
          <div className={s.panelHead}><h4>累计盈亏</h4><span>每笔闭合后更新</span></div>
          <EquityCurve points={data.cumulative_curve} />
        </section>
        <section>
          <div className={s.panelHead}><h4>月度盈亏</h4><span>最近 12 个月</span></div>
          <MonthlyBars rows={data.monthly} />
        </section>
        <section>
          <div className={s.panelHead}><h4>持仓时间分布</h4><span>按闭合批次</span></div>
          <div className={s.distribution}>
            {data.holding_buckets.map((item) => (
              <div key={item.key}>
                <span>{item.key}</span>
                <i><em style={{ width: `${item.share_pct / maxHoldingShare * 100}%` }} /></i>
                <b>{item.share_pct.toFixed(1)}%</b>
              </div>
            ))}
          </div>
        </section>
        <section>
          <div className={s.panelHead}><h4>多空质量</h4><span>方向拆分</span></div>
          <div className={s.directionRows}>
            {data.directions.map((item) => (
              <div key={item.key}>
                <span>{item.key === 'long' ? '多头' : '空头'}</span>
                <b className={item.pnl >= 0 ? s.positive : s.negative}>{money(item.pnl)}</b>
                <small>{item.count} 笔 · 胜率 {item.win_rate_pct.toFixed(1)}%</small>
              </div>
            ))}
            {!data.directions.length && <div className={s.emptyInline}>暂无方向数据</div>}
          </div>
        </section>
        <section>
          <div className={s.panelHead}><h4>盈亏日历</h4><span>最近 28 个交易日</span></div>
          <div className={s.calendar}>
            {latestDays.map((item) => (
              <div key={item.key} className={item.pnl > 0 ? s.dayWin : item.pnl < 0 ? s.dayLoss : s.dayFlat} title={`${item.key} ${money(item.pnl)}`}>
                <span>{item.key.slice(8)}</span><b>{item.pnl === 0 ? '0' : money(item.pnl)}</b>
              </div>
            ))}
            {!latestDays.length && <div className={s.emptyInline}>暂无闭合交易日</div>}
          </div>
        </section>
        <section>
          <div className={s.panelHead}><h4>执行成本</h4><span>仅使用可验证字段</span></div>
          <div className={s.costRows}>
            <div><span>总费用</span><b>{money(-data.execution_quality.total_fees)}</b></div>
            <div><span>平均每笔</span><b>{money(-data.execution_quality.average_fee)}</b></div>
            <div><span>费用侵蚀</span><b>{data.execution_quality.fee_drag_pct.toFixed(2)}%</b></div>
          </div>
          <p className={s.dataNote}>{data.execution_quality.slippage_note}</p>
        </section>
      </div>

      {!!data.closed_trade_rows.length && (
        <div className={s.recentTrades}>
          <div className={s.panelHead}><h4>最近闭合交易</h4><span>FIFO 配对</span></div>
          <div className={s.tradeHeader}><span>标的</span><span>方向</span><span>持仓</span><span>费用</span><span>净盈亏</span></div>
          {data.closed_trade_rows.slice(0, 8).map((item) => (
            <div className={s.tradeRow} key={`${item.entry_at}:${item.exit_at}:${item.code}`}>
              <span><b>{item.code}</b><small>{item.market}</small></span>
              <span>{item.direction === 'long' ? '多头' : '空头'}</span>
              <span>{duration(item.holding_seconds)}</span>
              <span>{money(-item.fees)}</span>
              <strong className={item.pnl >= 0 ? s.positive : s.negative}>{money(item.pnl)}</strong>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
