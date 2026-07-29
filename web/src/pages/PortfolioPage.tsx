import { useMemo, useState } from 'react'
import { api } from '../api/client'
import { useApi } from '../api/useApi'
import type { PortfolioManageResp } from '../api/types'
import { AsyncStateBoundary } from '../components/ui/AsyncStateBoundary/AsyncStateBoundary'
import { Button } from '../components/ui/Button/Button'
import { ConfirmActionButton } from '../components/ui/ConfirmActionButton/ConfirmActionButton'
import { Input } from '../components/ui/Input/Input'
import { Select } from '../components/ui/Select/Select'
import { WorkspaceHeader } from '../components/WorkspaceHeader/WorkspaceHeader'
import s from './PortfolioPage.module.css'
import '../styles/strategy-module.css'

export default function PortfolioPage() {
  const manage = useApi(() => api.portfolioManage(), [])
  const strategies = useApi(() => api.strategies(), [])

  const list = strategies.data?.strategies ?? []
  const allocs = manage.data?.allocations ?? []
  const summary = manage.data?.summary

  const [strategy, setStrategy] = useState('')
  const [weight, setWeight] = useState(0.1)
  const [symbol, setSymbol] = useState('')
  const [note, setNote] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  const strategyOptions = useMemo(
    () => [
      { value: '', label: '选择策略…' },
      ...list.map((item) => ({ value: item.name, label: item.name })),
    ],
    [list],
  )

  async function handleAdd() {
    if (!strategy) return
    setSaving(true)
    setError('')
    try {
      await api.saveAlloc({
        strategy,
        weight,
        symbol: symbol.trim() || null,
        live: false,
        note: note.trim() || null,
      })
      setSymbol('')
      setNote('')
      setWeight(0.1)
      void manage.refetch()
    } catch (e) {
      setError(e instanceof Error ? e.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete(id: string) {
    setError('')
    setMessage('')
    try {
      await api.deleteAlloc(id)
      setMessage(`策略分配 ${id} 已移除`)
      void manage.refetch()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '策略分配移除失败')
      throw reason
    }
  }

  async function handleLive(id: string, live: boolean) {
    await api.setAllocLive(id, live)
    void manage.refetch()
  }

  return (
    <div className={s.page}>
      <WorkspaceHeader
        context="策略 / 策略分配"
        title="策略分配"
        metrics={[
          { label: '绑定配置', value: allocs.length },
          { label: '可选策略', value: list.length },
        ]}
      />
      <div className="card" data-board="portfolio">
        <div className="card-head">
          <div className="card-title">
            策略分配
            <span className="sub">绑定策略 · 配置权重 · 监控暴露</span>
          </div>
        </div>
        <AsyncStateBoundary
          loading={manage.loading || strategies.loading}
          error={manage.error || strategies.error}
          reconnecting={manage.reconnecting || strategies.reconnecting}
          hasData={manage.data !== null && strategies.data !== null}
          isEmpty={false}
          onRetry={() => { void manage.refetch(); void strategies.refetch() }}
          loadingTitle="正在读取策略分配…"
          emptyTitle="暂无策略分配数据"
        >
          <div className={s.body}>
          {summary && (
            <div className="overview-stats">
              <div className="stat-tile">
                <span className="k">绑定策略</span>
                <span className="v mono">{summary.n_alloc}</span>
              </div>
              <div className="stat-tile">
                <span className="k">总权重</span>
                <span className="v mono">{(summary.total_weight * 100).toFixed(0)}%</span>
              </div>
              <div className="stat-tile">
                <span className="k">实盘数</span>
                <span className="v mono">{summary.live_count}</span>
              </div>
              <div className="stat-tile">
                <span className="k">集中度</span>
                <span className="v mono">{(summary.concentration * 100).toFixed(0)}%</span>
              </div>
              <div className="stat-tile">
                <span className="k">信号暴露(多/空/观)</span>
                <span className={`v mono ${s.exposureValue}`}>
                  {summary.exposure.long} / {summary.exposure.short} / {summary.exposure.hold}
                </span>
              </div>
              <div className="stat-tile">
                <span className="k">信号总数</span>
                <span className="v mono">{summary.exposure.total}</span>
              </div>
            </div>
          )}

          {/* 新增绑定 */}
          <div className={`preset-block ${s.sectionGap}`}>
            <div className="detail-section-title">新增策略绑定</div>
            <div className="bt-form">
              <label className="bt-field">
                <span>策略</span>
                <Select
                  options={strategyOptions}
                  value={strategy}
                  onChange={(e) => setStrategy(e.target.value)}
                />
              </label>
              <label className="bt-field">
                <span>权重</span>
                <Input
                  type="number"
                  step={0.05}
                  min={0}
                  max={1}
                  value={weight}
                  onChange={(e) => setWeight(Number(e.target.value) || 0)}
                />
              </label>
              <label className="bt-field">
                <span>限定标的</span>
                <Input
                  placeholder="可选，如 600519"
                  value={symbol}
                  onChange={(e) => setSymbol(e.target.value)}
                />
              </label>
              <label className="bt-field">
                <span>备注</span>
                <Input
                  placeholder="可选"
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                />
              </label>
            </div>
            <div className="detail-actions">
              <Button
                variant="primary"
                size="sm"
                onClick={handleAdd}
                loading={saving}
                disabled={saving || !strategy}
              >
                {saving ? '保存中…' : '添加绑定'}
              </Button>
            </div>
            {error && <div className="run-error">{error}</div>}
            {message && <div className={s.success} role="status">{message}</div>}
          </div>

          {/* 绑定列表 */}
          <div className={`detail-section-title ${s.sectionGap}`}>
            当前绑定
          </div>
          {allocs.length > 0 ? (
            <div className="preset-list">
              {allocs.map((a) => (
                <div className="preset-row" key={a.id}>
                  <span className="preset-name" title={a.strategy}>
                    {a.strategy}
                    {a.symbol ? ` · ${a.symbol}` : ''}
                    <span className={`muted ${s.weightTag}`}>
                      {(a.weight * 100).toFixed(0)}%
                    </span>
                  </span>
                  <div className="preset-actions">
                    <label className="live-toggle">
                      <input
                        type="checkbox"
                        checked={a.live}
                        onChange={(e) => handleLive(a.id, e.target.checked)}
                      />
                      实盘
                    </label>
                    <ConfirmActionButton
                      label="移除"
                      title="确认移除策略分配"
                      description={`移除 ${a.strategy}${a.symbol ? ` · ${a.symbol}` : ''} 后，该分配不再计入权重与暴露汇总。`}
                      confirmLabel="确认移除"
                      variant="link"
                      onConfirm={() => handleDelete(a.id)}
                    />
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className={`muted ${s.emptyHint}`}>
              暂无绑定。添加策略并配置权重后，这里会汇总暴露与集中度。
            </div>
          )}
          </div>
        </AsyncStateBoundary>
      </div>
    </div>
  )
}
