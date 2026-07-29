import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { AlertEvent, AlertRule, AlertRuleType } from '../api/types'
import { useApi } from '../api/useApi'
import { AsyncStateBoundary } from '../components/ui/AsyncStateBoundary/AsyncStateBoundary'
import { Button } from '../components/ui/Button/Button'
import { ConfirmActionButton } from '../components/ui/ConfirmActionButton/ConfirmActionButton'
import { RefreshControl } from '../components/ui/RefreshControl/RefreshControl'
import { Table, type Column } from '../components/ui/Table/Table'
import { WorkspaceHeader } from '../components/WorkspaceHeader/WorkspaceHeader'
import { alertEventHref } from '../lib/alerts'
import s from './OperationsPages.module.css'

const RULE_LABELS: Record<AlertRuleType, string> = {
  price_above: '价格达到或高于',
  price_below: '价格达到或低于',
  change_pct_above: '涨跌幅达到或高于',
  change_pct_below: '涨跌幅达到或低于',
  volatility_above: '日波动率达到或高于',
  signal_created: '出现新信号',
  evaluation_changed: '评估结论变化',
  risk_invalidated: '风险失效位触发',
}

const THRESHOLD_TYPES = new Set<AlertRuleType>([
  'price_above', 'price_below', 'change_pct_above', 'change_pct_below',
  'volatility_above', 'risk_invalidated',
])

function formatTime(value: number | null) {
  return value ? new Date(value * 1000).toLocaleString('zh-CN', { hour12: false }) : '—'
}

export default function AlertsPage() {
  const [searchParams] = useSearchParams()
  const requestedType = searchParams.get('type')
  const initialType = requestedType !== null && Object.prototype.hasOwnProperty.call(RULE_LABELS, requestedType)
    ? requestedType as AlertRuleType
    : 'price_above'
  const [tick, setTick] = useState(0)
  const rules = useApi(() => api.alertRules(), [tick], { retry: false })
  const events = useApi(() => api.alertEvents(false, 200), [tick], { retry: false })
  const [form, setForm] = useState({
    name: '',
    ruleType: initialType,
    symbol: (searchParams.get('symbol') || '').toUpperCase(),
    market: searchParams.get('market') || 'a_shares',
    threshold: searchParams.get('threshold') || '',
    frequencyMinutes: '15',
    quietStart: '',
    quietEnd: '',
    expiresAt: '',
    riskCondition: searchParams.get('condition') === 'below' ? 'below' : 'above',
  })
  const [saving, setSaving] = useState(false)
  const [busy, setBusy] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const ruleRows = useMemo(() => rules.data?.rules ?? [], [rules.data])
  const eventRows = useMemo(() => events.data?.events ?? [], [events.data])
  const pendingCount = eventRows.filter((event) => event.status === 'pending').length

  function refresh() {
    setTick((value) => value + 1)
  }

  async function createRule(event: React.FormEvent) {
    event.preventDefault()
    const requiresThreshold = THRESHOLD_TYPES.has(form.ruleType)
    const threshold = form.threshold === '' ? null : Number(form.threshold)
    if (!form.name.trim() || !form.symbol.trim() || (requiresThreshold && (threshold === null || !Number.isFinite(threshold)))) return
    if ((form.quietStart && !form.quietEnd) || (!form.quietStart && form.quietEnd)) {
      setError('静默开始和结束时间必须同时填写')
      return
    }
    setSaving(true)
    setError('')
    setMessage('')
    try {
      await api.createAlertRule({
        name: form.name.trim(), rule_type: form.ruleType, symbol: form.symbol.trim().toUpperCase(),
        market: form.market, threshold, frequency_minutes: Number(form.frequencyMinutes),
        quiet_start: form.quietStart || null, quiet_end: form.quietEnd || null,
        expires_at: form.expiresAt ? new Date(`${form.expiresAt}T23:59:59`).getTime() / 1000 : null,
        context: form.ruleType === 'risk_invalidated' ? { condition: form.riskCondition } : {},
      })
      setForm((current) => ({ ...current, name: '', threshold: '' }))
      setMessage('提醒规则已创建，后台检查器会按频率执行')
      refresh()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '提醒规则创建失败')
    } finally {
      setSaving(false)
    }
  }

  async function act(key: string, action: () => Promise<unknown>, success: string) {
    setBusy(key)
    setError('')
    setMessage('')
    try {
      await action()
      setMessage(success)
      refresh()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
      throw cause
    } finally {
      setBusy('')
    }
  }

  const ruleColumns: Column<AlertRule>[] = [
    { key: 'name', header: '规则', render: (row) => <div className={s.taskIdentity}><strong>{row.name}</strong><span>{RULE_LABELS[row.rule_type]}</span></div> },
    { key: 'symbol', header: '标的', width: 130, render: (row) => <span className={s.code}>{row.symbol} · {row.market}</span> },
    { key: 'threshold', header: '阈值', width: 90, render: (row) => row.threshold ?? '—' },
    { key: 'frequency', header: '频率', width: 90, render: (row) => `${row.frequency_minutes} 分钟` },
    { key: 'last', header: '最近触发', width: 170, render: (row) => formatTime(row.last_triggered_at) },
    { key: 'state', header: '状态', width: 72, render: (row) => <span className={row.enabled ? s.positive : s.meta}>{row.enabled ? '启用' : '停用'}</span> },
    { key: 'actions', header: '操作', width: 230, render: (row) => <div className={s.rowActions}>
      <Button size="sm" variant="link" disabled={Boolean(busy)} onClick={() => void act(`toggle:${row.id}`, () => api.updateAlertRule(row.id, { enabled: !row.enabled }), row.enabled ? '提醒已停用' : '提醒已启用')}>{row.enabled ? '停用' : '启用'}</Button>
      <Button size="sm" variant="link" disabled={Boolean(busy)} loading={busy === `check:${row.id}`} onClick={() => void act(`check:${row.id}`, () => api.checkAlertRule(row.id), '提醒已检查')}>立即检查</Button>
      <ConfirmActionButton label="删除" title="确认删除提醒" description={`删除“${row.name}”后，历史触发记录也会一并删除。`} confirmLabel="确认删除" onConfirm={() => act(`delete:${row.id}`, () => api.deleteAlertRule(row.id), '提醒已删除')} />
    </div> },
  ]

  const eventColumns: Column<AlertEvent>[] = [
    { key: 'time', header: '触发时间', width: 170, render: (row) => formatTime(row.triggered_at) },
    { key: 'message', header: '提醒内容', render: (row) => row.message },
    { key: 'related', header: '关联记录', width: 170, render: (row) => <Link to={alertEventHref(row)} className={s.recordLink}><b>{row.rule_name}</b><span>{row.symbol} · {row.market}</span></Link> },
    { key: 'value', header: '观测值', width: 100, render: (row) => row.observed_value ?? '—' },
    { key: 'delivery', header: '通知发送', width: 150, render: (row) => Object.entries(row.delivery).map(([channel, ok]) => `${channel}:${ok ? '成功' : '失败'}`).join(' · ') || '未配置通道' },
    { key: 'status', header: '状态', width: 90, render: (row) => row.status === 'pending' ? <span className={s.negative}>待确认</span> : <span className={s.positive}>已确认</span> },
    { key: 'action', header: '操作', width: 80, render: (row) => row.status === 'pending' ? <Button size="sm" variant="link" onClick={() => void act(`ack:${row.id}`, () => api.acknowledgeAlertEvent(row.id), '提醒已确认')}>确认</Button> : '—' },
  ]

  return <div className={s.page}>
    <WorkspaceHeader context="研究 / 提醒中心" title="提醒中心" metrics={[
      { label: '提醒规则', value: ruleRows.length },
      { label: '已启用', value: ruleRows.filter((rule) => rule.enabled).length },
      { label: '待确认', value: pendingCount },
    ]} />
    <form className={s.section} onSubmit={createRule}>
      <div className={s.sectionHead}><div><h2>新建提醒</h2><span>规则持久化保存，后台每分钟检查到期规则</span></div></div>
      <div className={s.formGrid}>
        <label>名称<input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label>
        <label>类型<select value={form.ruleType} onChange={(event) => setForm({ ...form, ruleType: event.target.value as AlertRuleType })}>{Object.entries(RULE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <label>标的<input value={form.symbol} onChange={(event) => setForm({ ...form, symbol: event.target.value })} /></label>
        <label>市场<select value={form.market} onChange={(event) => setForm({ ...form, market: event.target.value })}><option value="a_shares">a_shares</option><option value="us_stocks">us_stocks</option><option value="crypto">crypto</option><option value="mt5">mt5</option></select></label>
        {THRESHOLD_TYPES.has(form.ruleType) && <label>阈值<input type="number" step="any" value={form.threshold} onChange={(event) => setForm({ ...form, threshold: event.target.value })} /></label>}
        {form.ruleType === 'risk_invalidated' && <label>触发方向<select value={form.riskCondition} onChange={(event) => setForm({ ...form, riskCondition: event.target.value })}><option value="below">价格低于失效位</option><option value="above">价格高于失效位</option></select></label>}
        <label>检查频率（分钟）<input type="number" min="1" max="10080" value={form.frequencyMinutes} onChange={(event) => setForm({ ...form, frequencyMinutes: event.target.value })} /></label>
        <label>静默开始<input type="time" value={form.quietStart} onChange={(event) => setForm({ ...form, quietStart: event.target.value })} /></label>
        <label>静默结束<input type="time" value={form.quietEnd} onChange={(event) => setForm({ ...form, quietEnd: event.target.value })} /></label>
        <label>到期日期<input type="date" value={form.expiresAt} onChange={(event) => setForm({ ...form, expiresAt: event.target.value })} /></label>
      </div>
      <div className={s.formActions}><Button type="submit" variant="primary" loading={saving}>创建提醒</Button><Button type="button" variant="secondary" onClick={() => void act('check-all', () => api.checkAllAlerts(), '全部规则已检查')}>检查全部</Button></div>
    </form>
    {error && <div className={s.error} role="alert">{error}</div>}
    {message && <div className={s.success} role="status">{message}</div>}
    <section className={s.section}>
      <div className={s.sectionHead}><div><h2>提醒规则</h2><span>支持启停、阈值、频率、静默时段和到期时间</span></div><RefreshControl onRefresh={refresh} refreshing={rules.loading || events.loading} updatedAt={Math.max(rules.updatedAt ?? 0, events.updatedAt ?? 0) || null} /></div>
      <AsyncStateBoundary loading={rules.loading} error={rules.error} reconnecting={rules.reconnecting} hasData={rules.data !== null} isEmpty={ruleRows.length === 0} onRetry={rules.refetch} loadingTitle="正在读取提醒规则…" emptyTitle="还没有提醒规则"><Table columns={ruleColumns} rows={ruleRows} rowKey={(row) => row.id} density="compact" /></AsyncStateBoundary>
    </section>
    <section className={s.section}>
      <div className={s.sectionHead}><div><h2>触发历史</h2><span>通知通道发送结果不会显示任何密钥</span></div></div>
      <AsyncStateBoundary loading={events.loading} error={events.error} reconnecting={events.reconnecting} hasData={events.data !== null} isEmpty={eventRows.length === 0} onRetry={events.refetch} loadingTitle="正在读取触发历史…" emptyTitle="还没有触发记录"><Table columns={eventColumns} rows={eventRows} rowKey={(row) => row.id} density="compact" /></AsyncStateBoundary>
    </section>
  </div>
}
