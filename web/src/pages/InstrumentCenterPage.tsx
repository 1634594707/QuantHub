import { useState } from 'react'
import { api } from '../api/client'
import type { Instrument } from '../api/types'
import { useApi } from '../api/useApi'
import { AsyncStateBoundary } from '../components/ui/AsyncStateBoundary/AsyncStateBoundary'
import { Button } from '../components/ui/Button/Button'
import { RefreshControl } from '../components/ui/RefreshControl/RefreshControl'
import { Input } from '../components/ui/Input/Input'
import { Select } from '../components/ui/Select/Select'
import { Table, type Column } from '../components/ui/Table/Table'
import { WorkspaceHeader } from '../components/WorkspaceHeader/WorkspaceHeader'
import s from './OperationsPages.module.css'

const MARKETS = [
  { value: 'a_shares', label: 'A股' },
  { value: 'crypto', label: '加密' },
  { value: 'us_stocks', label: '美股' },
  { value: 'mt5', label: 'MT5' },
]

const ASSET_CLASSES = [
  { value: 'stock', label: '股票' },
  { value: 'etf', label: 'ETF' },
  { value: 'crypto', label: '加密资产' },
  { value: 'forex', label: '外汇' },
  { value: 'index', label: '指数' },
]

export default function InstrumentCenterPage() {
  const [query, setQuery] = useState('')
  const [activeQuery, setActiveQuery] = useState('')
  const instruments = useApi(
    () => api.instruments(activeQuery, 100),
    [activeQuery],
    { retry: false, resetKey: activeQuery },
  )
  const [form, setForm] = useState({
    code: '', market: 'a_shares', name: '', exchange: '', currency: '', asset_class: 'stock',
  })
  const [saving, setSaving] = useState(false)
  const [formOpen, setFormOpen] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  async function register(event: React.FormEvent) {
    event.preventDefault()
    const code = form.code.trim().toUpperCase()
    if (!code) return
    setSaving(true)
    setMessage('')
    setError('')
    try {
      const response = await api.registerInstrument({ ...form, code })
      setMessage(`已保存 ${response.instrument.instrument_id}`)
      setForm((current) => ({ ...current, code: '', name: '' }))
      void instruments.refetch()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '标的保存失败')
    } finally {
      setSaving(false)
    }
  }

  const columns: Column<Instrument>[] = [
    { key: 'instrument_id', header: 'Instrument ID', render: (row) => <span className={s.code}>{row.instrument_id}</span> },
    { key: 'name', header: '名称', render: (row) => row.name || '—' },
    { key: 'market', header: '市场', render: (row) => <span className={s.code}>{row.market}</span> },
    { key: 'exchange', header: '交易所', render: (row) => row.exchange || '—' },
    { key: 'currency', header: '币种', render: (row) => row.currency || '—' },
    { key: 'asset_class', header: '资产类别', render: (row) => row.asset_class || '—' },
  ]

  return (
    <div className={s.page}>
      <WorkspaceHeader
        context="运营 / 标的中心"
        title="标的主数据"
        metrics={[
          { label: '当前结果', value: instruments.data?.count ?? 0 },
          { label: '稳定引用', value: 'market:code' },
        ]}
      />

      <form className={s.toolbar} onSubmit={(event) => { event.preventDefault(); setActiveQuery(query.trim()) }}>
        <label className={s.grow}>代码或名称
          <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索已登记标的" />
        </label>
        <Button type="submit" variant="primary">搜索</Button>
        <Button type="button" variant="ghost" onClick={() => { setQuery(''); setActiveQuery('') }}>显示最近更新</Button>
      </form>

      <section className={s.section}>
        <div className={s.sectionHead}>
          <h2>标的目录</h2>
          <RefreshControl onRefresh={instruments.refetch} refreshing={instruments.loading || instruments.reconnecting} updatedAt={instruments.updatedAt} />
        </div>
        <AsyncStateBoundary
          loading={instruments.loading}
          error={instruments.error}
          reconnecting={instruments.reconnecting}
          hasData={instruments.data !== null}
          isEmpty={(instruments.data?.instruments.length ?? 0) === 0}
          onRetry={instruments.refetch}
          loadingTitle="正在读取标的目录…"
          emptyTitle="没有匹配的标的"
          emptyDescription="调整搜索条件，或在下方登记新的标的主数据。"
        >
          <div className={s.instrumentDesktopTable}>
            <Table columns={columns} rows={instruments.data?.instruments ?? []} rowKey={(row) => row.instrument_id} density="compact" />
          </div>
          <div className={s.instrumentMobileRecords}>
            {(instruments.data?.instruments ?? []).map((instrument) => (
              <details key={instrument.instrument_id}>
                <summary>
                  <b className={s.code}>{instrument.instrument_id}</b>
                  <span>{instrument.market}</span>
                </summary>
                <div>
                  <span>名称<b>{instrument.name || '—'}</b></span>
                  <span>交易所<b>{instrument.exchange || '—'}</b></span>
                  <span>币种<b>{instrument.currency || '—'}</b></span>
                  <span>资产类别<b>{instrument.asset_class || '—'}</b></span>
                </div>
              </details>
            ))}
          </div>
        </AsyncStateBoundary>
      </section>

      <section className={s.section}>
        <div className={s.sectionHead}>
          <div><h2>登记或更新标的</h2><span>显式提交后端 Instrument 字段</span></div>
          <Button type="button" variant="ghost" onClick={() => setFormOpen((value) => !value)} aria-expanded={formOpen}>
            {formOpen ? '收起登记' : '登记标的'}
          </Button>
        </div>
        {formOpen && <form onSubmit={register}>
        <div className={s.formGrid}>
          <label>代码<Input value={form.code} onChange={(event) => setForm({ ...form, code: event.target.value })} placeholder="600519" /></label>
          <label>名称<Input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label>
          <label>市场<Select value={form.market} onChange={(event) => setForm({ ...form, market: event.target.value })} options={MARKETS} /></label>
          <label>交易所<Input value={form.exchange} onChange={(event) => setForm({ ...form, exchange: event.target.value })} placeholder="可留空" /></label>
          <label>币种<Input value={form.currency} onChange={(event) => setForm({ ...form, currency: event.target.value })} placeholder="可留空" /></label>
          <label>资产类别<Select value={form.asset_class} onChange={(event) => setForm({ ...form, asset_class: event.target.value })} options={ASSET_CLASSES} /></label>
        </div>
        <div className={s.formActions}><Button type="submit" variant="primary" loading={saving} disabled={!form.code.trim()}>保存标的</Button></div>
        {message && <div className={s.success}>{message}</div>}
        {error && <div className={s.error}>{error}</div>}
        </form>}
      </section>
    </div>
  )
}
