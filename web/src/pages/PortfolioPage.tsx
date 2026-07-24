import { useMemo, useState } from 'react'
import { api } from '../api/client'
import { useApi } from '../api/useApi'
import type { PortfolioManageResp } from '../api/types'

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

  const strategyOptions = useMemo(
    () => (strategy ? list : list),
    [list, strategy],
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
    await api.deleteAlloc(id)
    void manage.refetch()
  }

  async function handleLive(id: string, live: boolean) {
    await api.setAllocLive(id, live)
    void manage.refetch()
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-4)' }}>
      <div className="card" data-board="portfolio">
        <div className="card-head">
          <div className="card-title">
            组合管理
            <span className="sub">绑定策略 · 配置权重 · 监控暴露</span>
          </div>
        </div>
        <div style={{ padding: 'var(--sp-3)' }}>
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
                <span className="v mono" style={{ fontSize: 'var(--fs-13)' }}>
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
          <div className="preset-block" style={{ marginTop: 'var(--sp-3)' }}>
            <div className="detail-section-title">新增策略绑定</div>
            <div className="bt-form">
              <label className="bt-field">
                <span>策略</span>
                <select
                  className="edit-input"
                  value={strategy}
                  onChange={(e) => setStrategy(e.target.value)}
                >
                  <option value="">选择策略…</option>
                  {strategyOptions.map((s) => (
                    <option key={s.name} value={s.name}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="bt-field">
                <span>权重</span>
                <input
                  className="edit-input"
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
                <input
                  className="edit-input"
                  placeholder="可选，如 600519"
                  value={symbol}
                  onChange={(e) => setSymbol(e.target.value)}
                />
              </label>
              <label className="bt-field">
                <span>备注</span>
                <input
                  className="edit-input"
                  placeholder="可选"
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                />
              </label>
            </div>
            <div className="detail-actions">
              <button
                className="period-tab"
                onClick={handleAdd}
                disabled={saving || !strategy}
                style={{ background: 'var(--accent)', color: '#fff' }}
              >
                {saving ? '保存中…' : '添加绑定'}
              </button>
            </div>
            {error && <div className="run-error">{error}</div>}
          </div>

          {/* 绑定列表 */}
          <div className="detail-section-title" style={{ marginTop: 'var(--sp-3)' }}>
            当前绑定
          </div>
          {allocs.length > 0 ? (
            <div className="preset-list">
              {allocs.map((a) => (
                <div className="preset-row" key={a.id}>
                  <span className="preset-name" title={a.strategy}>
                    {a.strategy}
                    {a.symbol ? ` · ${a.symbol}` : ''}
                    <span className="muted" style={{ marginLeft: 6, fontSize: 'var(--fs-12)' }}>
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
                    <button className="link-btn" onClick={() => handleDelete(a.id)}>
                      移除
                    </button>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="muted" style={{ fontSize: 'var(--fs-13)' }}>
              暂无绑定。添加策略并配置权重后，这里会汇总暴露与集中度。
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
