import { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { StrategyExperiment, StrategyLabComparisonRow, StrategyLabRun, StrategyLabRunDifference } from '../api/types'
import { useApi } from '../api/useApi'
import { AsyncStateBoundary } from '../components/ui/AsyncStateBoundary/AsyncStateBoundary'
import { Button } from '../components/ui/Button/Button'
import { ConfirmActionButton } from '../components/ui/ConfirmActionButton/ConfirmActionButton'
import { RefreshControl } from '../components/ui/RefreshControl/RefreshControl'
import { Input } from '../components/ui/Input/Input'
import { Select } from '../components/ui/Select/Select'
import { Table, type Column } from '../components/ui/Table/Table'
import { WorkspaceHeader } from '../components/WorkspaceHeader/WorkspaceHeader'
import { defaultParams, StructuredParamsEditor } from '../components/StrategyShared'
import { scrollElementWithinMainContent } from '../lib/scroll'
import s from './OperationsPages.module.css'

const MARKETS = [
  { value: 'a_shares', label: 'A股' },
  { value: 'crypto', label: '加密' },
  { value: 'us_stocks', label: '美股' },
  { value: 'mt5', label: 'MT5' },
]

function formatTime(value: number | null): string {
  return value ? new Date(value * 1000).toLocaleString('zh-CN', { hour12: false }) : '—'
}

export default function StrategyLabPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedDefinitionId = searchParams.get('definition_id') || ''
  const requestedExperimentId = searchParams.get('experiment_id') || ''
  const requestedAction = searchParams.get('action') || ''
  const requestedSymbol = (searchParams.get('symbol') || '600519').toUpperCase()
  const requestedMarket = searchParams.get('market') || 'a_shares'
  const requestedTimeframe = searchParams.get('timeframe') || '1d'
  const requestedResearchRunId = searchParams.get('research_run_id') || ''
  const experimentFormRef = useRef<HTMLFormElement>(null)
  const [tick, setTick] = useState(0)
  const definitions = useApi(() => api.strategyLabDefinitions(200), [tick], { retry: false })
  const strategies = useApi(() => api.strategies(), [], { retry: false })
  const [definitionId, setDefinitionId] = useState(requestedDefinitionId)
  const definition = useApi(
    () => api.strategyLabDefinition(definitionId),
    [definitionId, tick],
    { enabled: Boolean(definitionId), retry: false, resetKey: definitionId },
  )
  const experiments = useApi(
    () => api.strategyLabExperiments(definitionId || undefined, 200),
    [definitionId, tick],
    { retry: false, resetKey: definitionId },
  )
  const [experimentId, setExperimentId] = useState(requestedExperimentId)
  const runs = useApi(
    () => api.strategyLabRuns(experimentId),
    [experimentId, tick],
    { enabled: Boolean(experimentId), retry: false, resetKey: experimentId },
  )
  const [selectedRuns, setSelectedRuns] = useState<string[]>([])
  const [comparison, setComparison] = useState<StrategyLabComparisonRow[]>([])
  const [differences, setDifferences] = useState<StrategyLabRunDifference[]>([])
  const [actionError, setActionError] = useState('')
  const [actionMessage, setActionMessage] = useState('')
  const [busy, setBusy] = useState('')
  const [definitionForm, setDefinitionForm] = useState({
    name: '', strategy_key: '', market: requestedMarket, description: '', tags: '',
  })
  const [versionForm, setVersionForm] = useState({ version: 'v1', changelog: '' })
  const [experimentForm, setExperimentForm] = useState({
    symbol: requestedSymbol, market: requestedMarket, timeframe: requestedTimeframe,
    version_id: '', research_run_id: requestedResearchRunId, note: '',
  })
  const [versionParams, setVersionParams] = useState<Record<string, unknown>>({})
  const [experimentParams, setExperimentParams] = useState<Record<string, unknown>>({})
  const [runForm, setRunForm] = useState({ initial_capital: 100000, limit: 300, seed: '' })
  const [definitionEditForm, setDefinitionEditForm] = useState({
    name: '', strategy_key: '', market: 'a_shares', description: '', tags: '', copy_name: '',
  })
  const [versionEditId, setVersionEditId] = useState('')
  const [versionEditForm, setVersionEditForm] = useState({ version: '', changelog: '', copy_version: '' })
  const [versionEditParams, setVersionEditParams] = useState<Record<string, unknown>>({})
  const [experimentEditForm, setExperimentEditForm] = useState({
    symbol: '', market: 'a_shares', timeframe: '1d', version_id: '', research_run_id: '', note: '',
  })
  const [experimentEditParams, setExperimentEditParams] = useState<Record<string, unknown>>({})

  const currentDefinition = definition.data?.definition
  const currentExperiment = experiments.data?.experiments.find((item) => item.id === experimentId)
  const experimentContextLocked = Boolean(currentExperiment?.research_run_id)
  const strategyOptions = useMemo(() => [
    { value: '', label: '选择已注册策略' },
    ...(strategies.data?.strategies ?? []).map((item) => ({ value: item.name, label: `${item.name} · ${item.market}` })),
  ], [strategies.data?.strategies])
  const versionOptions = useMemo(() => [
    { value: '', label: '不绑定版本' },
    ...(currentDefinition?.versions ?? []).map((item) => ({ value: item.id, label: `${item.version} · ${item.code_hash}` })),
  ], [currentDefinition?.versions])

  useEffect(() => {
    setDefinitionId(requestedDefinitionId)
    setExperimentId(requestedExperimentId)
  }, [requestedDefinitionId, requestedExperimentId])

  useEffect(() => {
    if (requestedAction !== 'create_experiment') return
    setExperimentForm((current) => ({
      ...current,
      symbol: requestedSymbol,
      market: requestedMarket,
      timeframe: requestedTimeframe,
      research_run_id: requestedResearchRunId,
    }))
  }, [requestedAction, requestedMarket, requestedResearchRunId, requestedSymbol, requestedTimeframe])

  useEffect(() => {
    if (requestedAction !== 'create_experiment' || definitionId || !definitions.data?.definitions.length) return
    const matchingDefinition = definitions.data.definitions.find((item) => item.market === requestedMarket)
      ?? definitions.data.definitions[0]
    setDefinitionId(matchingDefinition.id)
    const query = new URLSearchParams(searchParams)
    query.set('definition_id', matchingDefinition.id)
    setSearchParams(query, { replace: true })
  }, [definitionId, definitions.data?.definitions, requestedAction, requestedMarket, searchParams, setSearchParams])

  useEffect(() => {
    if (requestedAction !== 'create_experiment' || !currentDefinition) return
    requestAnimationFrame(() => scrollElementWithinMainContent(experimentFormRef.current))
  }, [currentDefinition, requestedAction])

  useEffect(() => {
    if (!currentDefinition) return
    const defaults = defaultParams(currentDefinition.strategy_key)
    setVersionParams(defaults)
    setExperimentParams(defaults)
    setExperimentForm((current) => ({ ...current, version_id: '' }))
    setDefinitionEditForm({
      name: currentDefinition.name, strategy_key: currentDefinition.strategy_key,
      market: currentDefinition.market, description: currentDefinition.description,
      tags: currentDefinition.tags.join(', '), copy_name: `${currentDefinition.name} 副本`,
    })
  }, [currentDefinition?.id, currentDefinition?.strategy_key])

  useEffect(() => {
    if (!versionEditId) return
    const selected = (currentDefinition?.versions ?? []).find((item) => item.id === versionEditId)
    if (!selected) return
    setVersionEditForm({
      version: selected.version, changelog: selected.changelog,
      copy_version: `${selected.version}-copy`,
    })
    setVersionEditParams(selected.params)
  }, [currentDefinition?.versions, versionEditId])

  useEffect(() => {
    if (!currentExperiment) return
    setExperimentEditForm({
      symbol: currentExperiment.symbol, market: currentExperiment.market,
      timeframe: currentExperiment.timeframe, version_id: currentExperiment.version_id ?? '',
      research_run_id: currentExperiment.research_run_id ?? '',
      note: currentExperiment.note,
    })
    setExperimentEditParams(currentExperiment.params)
  }, [currentExperiment?.id])

  function selectDefinition(id: string) {
    setDefinitionId(id)
    setExperimentId('')
    setSelectedRuns([])
    setComparison([])
    setDifferences([])
    const query = new URLSearchParams(searchParams)
    query.set('definition_id', id)
    query.delete('experiment_id')
    query.delete('action')
    setSearchParams(query)
  }

  function selectExperiment(id: string) {
    setExperimentId(id)
    setSelectedRuns([])
    setComparison([])
    setDifferences([])
    const query = new URLSearchParams(searchParams)
    query.set('experiment_id', id)
    query.delete('action')
    setSearchParams(query)
  }

  function changed(message: string) {
    setActionMessage(message)
    setTick((value) => value + 1)
  }

  async function createDefinition(event: React.FormEvent) {
    event.preventDefault()
    if (!definitionForm.name.trim() || !definitionForm.strategy_key) return
    setBusy('definition')
    setActionError('')
    setActionMessage('')
    try {
      const response = await api.createStrategyDefinition({
        name: definitionForm.name.trim(), strategy_key: definitionForm.strategy_key,
        market: definitionForm.market, description: definitionForm.description.trim(),
        tags: definitionForm.tags.split(',').map((tag) => tag.trim()).filter(Boolean),
      })
      selectDefinition(response.definition.id)
      setDefinitionForm((current) => ({ ...current, name: '', description: '', tags: '' }))
      changed('策略定义已创建')
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : '策略定义创建失败')
    } finally {
      setBusy('')
    }
  }

  async function createVersion(event: React.FormEvent) {
    event.preventDefault()
    if (!definitionId || !versionForm.version.trim()) return
    setBusy('version')
    setActionError('')
    setActionMessage('')
    try {
      await api.createStrategyVersion(definitionId, {
        version: versionForm.version.trim(), params: versionParams,
        changelog: versionForm.changelog.trim(),
      })
      changed('策略版本已创建')
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : '策略版本创建失败')
    } finally {
      setBusy('')
    }
  }

  async function createExperiment(event: React.FormEvent) {
    event.preventDefault()
    if (!definitionId || !experimentForm.symbol.trim()) return
    setBusy('experiment')
    setActionError('')
    setActionMessage('')
    try {
      const response = await api.createStrategyExperiment(definitionId, {
        symbol: experimentForm.symbol.trim().toUpperCase(), market: experimentForm.market,
        timeframe: experimentForm.timeframe, version_id: experimentForm.version_id || null,
        research_run_id: experimentForm.research_run_id || null,
        params: experimentParams, note: experimentForm.note.trim(),
      })
      selectExperiment(response.experiment.id)
      changed('实验已创建')
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : '实验创建失败')
    } finally {
      setBusy('')
    }
  }

  async function runBacktest(event: React.FormEvent) {
    event.preventDefault()
    if (!experimentId) return
    setBusy('run')
    setActionError('')
    setActionMessage('')
    try {
      const response = await api.runStrategyExperiment(experimentId, {
        initial_capital: runForm.initial_capital, limit: runForm.limit, seed: runForm.seed.trim() || null,
      })
      if (!response.ok) throw new Error(response.error || '实验回测失败')
      changed(`回测运行已保存${response.run_id ? ` · ${response.run_id.slice(0, 12)}` : ''}`)
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : '实验回测失败')
    } finally {
      setBusy('')
    }
  }

  async function compare() {
    if (!selectedRuns.length) return
    setBusy('compare')
    setActionError('')
    try {
      const response = await api.compareStrategyLabRuns(selectedRuns)
      setComparison(response.comparison)
      setDifferences(response.differences)
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : '运行对比失败')
    } finally {
      setBusy('')
    }
  }

  async function saveDefinition() {
    if (!definitionId || !definitionEditForm.name.trim() || !definitionEditForm.strategy_key) return
    setBusy('definition-edit')
    try {
      await api.updateStrategyDefinition(definitionId, {
        name: definitionEditForm.name.trim(), strategy_key: definitionEditForm.strategy_key,
        market: definitionEditForm.market, description: definitionEditForm.description.trim(),
        tags: definitionEditForm.tags.split(',').map((item) => item.trim()).filter(Boolean),
      })
      changed('策略定义已更新')
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : '策略定义更新失败')
    } finally {
      setBusy('')
    }
  }

  async function copyDefinition() {
    if (!definitionId || !definitionEditForm.copy_name.trim()) return
    const response = await api.copyStrategyDefinition(definitionId, definitionEditForm.copy_name.trim())
    selectDefinition(response.definition.id)
    changed('策略定义及版本已复制')
  }

  async function archiveDefinition() {
    if (!definitionId) return
    await api.archiveStrategyDefinition(definitionId)
    setDefinitionId('')
    setExperimentId('')
    changed('策略定义已归档')
  }

  async function saveVersion() {
    if (!versionEditId || !versionEditForm.version.trim()) return
    await api.updateStrategyVersion(versionEditId, {
      version: versionEditForm.version.trim(), params: versionEditParams,
      changelog: versionEditForm.changelog.trim(),
    })
    changed('策略版本已更新')
  }

  async function copyVersion() {
    if (!versionEditId || !versionEditForm.copy_version.trim()) return
    await api.copyStrategyVersion(versionEditId, versionEditForm.copy_version.trim())
    changed('策略版本已复制')
  }

  async function archiveVersion() {
    if (!versionEditId) return
    await api.archiveStrategyVersion(versionEditId)
    setVersionEditId('')
    changed('策略版本已归档')
  }

  async function saveExperiment() {
    if (!experimentId || !experimentEditForm.symbol.trim()) return
    await api.updateStrategyExperiment(experimentId, {
      symbol: experimentEditForm.symbol.trim().toUpperCase(), market: experimentEditForm.market,
      timeframe: experimentEditForm.timeframe, version_id: experimentEditForm.version_id || null,
      research_run_id: experimentEditForm.research_run_id || null,
      params: experimentEditParams, note: experimentEditForm.note.trim(),
    })
    changed('策略实验已更新')
  }

  async function copyExperiment() {
    if (!experimentId) return
    const response = await api.copyStrategyExperiment(experimentId, experimentEditForm.note.trim())
    selectExperiment(response.experiment.id)
    changed('策略实验已复制')
  }

  async function archiveExperiment() {
    if (!experimentId) return
    await api.archiveStrategyExperiment(experimentId)
    setExperimentId('')
    changed('策略实验已归档')
  }

  function toggleRun(id: string) {
    setSelectedRuns((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id])
  }

  const experimentColumns: Column<StrategyExperiment>[] = [
    { key: 'symbol', header: '实验', render: (row) => <><b className={s.code}>{row.symbol}</b><div className={s.meta}>{row.market} · {row.timeframe}</div></> },
    { key: 'status', header: '状态', render: (row) => row.status },
    { key: 'research_run_id', header: '研究来源', render: (row) => row.research_run_id ? <a href={`/factor-research?run_id=${encodeURIComponent(row.research_run_id)}`} className={s.code} onClick={(event) => event.stopPropagation()}>{row.research_run_id.slice(0, 12)}</a> : '独立实验' },
    { key: 'version_id', header: '版本', render: (row) => row.version_id ? <span className={s.code}>{row.version_id.slice(0, 12)}</span> : '未绑定' },
    { key: 'created_at', header: '创建时间', render: (row) => formatTime(row.created_at) },
    { key: 'note', header: '备注', render: (row) => row.note || '—' },
  ]
  const runColumns: Column<StrategyLabRun>[] = [
    { key: 'select', header: '对比', render: (row) => <input type="checkbox" checked={selectedRuns.includes(row.id)} onChange={() => toggleRun(row.id)} aria-label={`选择运行 ${row.id}`} /> },
    { key: 'id', header: '运行', render: (row) => <><b className={s.code}>{row.id.slice(0, 12)}</b><div className={s.meta}>{formatTime(row.started_at)}</div></> },
    { key: 'status', header: '状态', render: (row) => row.status },
    { key: 'seed', header: '随机种子', render: (row) => <span className={s.code}>{row.seed || '—'}</span> },
    { key: 'snapshot', header: '数据快照', render: (row) => <span className={s.code}>{typeof row.data_snapshot.sha256 === 'string' ? row.data_snapshot.sha256.slice(0, 16) : '—'}</span> },
    { key: 'trades', header: '成交数', align: 'right', render: (row) => <span className={s.code}>{row.trades.length}</span> },
    { key: 'metrics', header: '指标', render: (row) => Object.entries(row.metrics).slice(0, 3).map(([key, value]) => `${key}=${String(value)}`).join(' · ') || '—' },
  ]
  const comparisonColumns: Column<StrategyLabComparisonRow>[] = [
    { key: 'run_id', header: '运行', render: (row) => <span className={s.code}>{row.run_id.slice(0, 12)}</span> },
    { key: 'context', header: '上下文', render: (row) => `${row.symbol} · ${row.market} · ${row.timeframe}` },
    { key: 'seed', header: '种子', render: (row) => row.seed || '—' },
    { key: 'n_trades', header: '成交', align: 'right' },
    { key: 'snapshot', header: '快照 SHA256', render: (row) => <span className={s.code}>{row.data_snapshot_sha256?.slice(0, 16) || '—'}</span> },
    { key: 'metrics', header: '指标', render: (row) => Object.entries(row.metrics).map(([key, value]) => `${key}=${String(value)}`).join(' · ') || '—' },
  ]

  return (
    <div className={s.page}>
      <WorkspaceHeader
        context="策略 / 策略实验"
        title="可复现策略实验"
        metrics={[
          { label: '策略定义', value: definitions.data?.count ?? 0 },
          { label: '当前实验', value: experiments.data?.count ?? 0 },
          { label: '当前运行', value: runs.data?.count ?? 0 },
        ]}
      />
      {actionError && <div className={s.error}>{actionError}</div>}
      {actionMessage && <div className={s.success}>{actionMessage}</div>}
      {requestedAction === 'create_experiment' && (
        <div className={s.contextNotice} role="status">
          <strong>已带入因子研究上下文</strong>
          <span>
            {requestedSymbol} · {requestedMarket} · {requestedTimeframe}
            {requestedResearchRunId ? ` · 研究 ${requestedResearchRunId}` : ''}
            ；选择已有策略定义后可直接创建实验，没有定义时先完成新建。
          </span>
          {requestedResearchRunId && <a href={`/factor-research?run_id=${encodeURIComponent(requestedResearchRunId)}`}>返回因子研究</a>}
        </div>
      )}

      <div className={s.workflowStep}><span>01</span><div><h2>定义与版本</h2><p>策略身份、注册键与可复现参数</p></div></div>
      <div className={s.grid2}>
        <section className={s.section}>
          <div className={s.sectionHead}><div><h2>策略定义</h2><span>绑定已注册策略并建立版本线</span></div></div>
          <AsyncStateBoundary
            loading={definitions.loading}
            error={definitions.error}
            reconnecting={definitions.reconnecting}
            hasData={definitions.data !== null}
            isEmpty={(definitions.data?.definitions.length ?? 0) === 0}
            onRetry={definitions.refetch}
            loadingTitle="正在读取策略定义…"
            emptyTitle="还没有策略定义"
          >
            <div className={s.definitionList}>
              {(definitions.data?.definitions ?? []).map((item) => (
                <button type="button" key={item.id} className={`${s.listButton} ${definitionId === item.id ? s.listButtonActive : ''}`} onClick={() => selectDefinition(item.id)}>
                  <span><b>{item.name}</b><small>{item.strategy_key} · {item.market}</small></span>
                  <span className={s.code}>{item.tags.join(' / ') || '—'}</span>
                </button>
              ))}
            </div>
          </AsyncStateBoundary>
        </section>

        <form className={s.section} onSubmit={createDefinition}>
          <div className={s.sectionHead}><div><h2>新建定义</h2><span>策略键来自当前注册表</span></div></div>
          <AsyncStateBoundary
            loading={strategies.loading}
            error={strategies.error}
            reconnecting={strategies.reconnecting}
            hasData={strategies.data !== null}
            isEmpty={(strategies.data?.strategies.length ?? 0) === 0}
            onRetry={strategies.refetch}
            loadingTitle="正在读取策略注册表…"
            emptyTitle="策略注册表为空"
          >
            <div className={s.formGrid}>
              <label>定义名称<Input value={definitionForm.name} onChange={(event) => setDefinitionForm({ ...definitionForm, name: event.target.value })} /></label>
              <label>策略键<Select options={strategyOptions} value={definitionForm.strategy_key} onChange={(event) => setDefinitionForm({ ...definitionForm, strategy_key: event.target.value })} /></label>
              <label>市场<Select options={MARKETS} value={definitionForm.market} onChange={(event) => setDefinitionForm({ ...definitionForm, market: event.target.value })} /></label>
              <label>标签<Input value={definitionForm.tags} onChange={(event) => setDefinitionForm({ ...definitionForm, tags: event.target.value })} placeholder="逗号分隔" /></label>
              <label>说明<Input value={definitionForm.description} onChange={(event) => setDefinitionForm({ ...definitionForm, description: event.target.value })} /></label>
            </div>
            <div className={s.formActions}><Button type="submit" variant="primary" loading={busy === 'definition'}>创建定义</Button></div>
          </AsyncStateBoundary>
        </form>
      </div>

      {currentDefinition && (
        <div className={s.grid2}>
          <form className={s.section} onSubmit={createVersion}>
            <div className={s.sectionHead}><div><h2>创建版本</h2><span>{currentDefinition.name} · 已有 {currentDefinition.versions?.length ?? 0} 个版本</span></div></div>
            <div className={s.formGrid}>
              <label>版本号<Input value={versionForm.version} onChange={(event) => setVersionForm({ ...versionForm, version: event.target.value })} /></label>
              <label>变更说明<Input value={versionForm.changelog} onChange={(event) => setVersionForm({ ...versionForm, changelog: event.target.value })} /></label>
              <div className={s.controlledParams}><StructuredParamsEditor name={currentDefinition.strategy_key} params={versionParams} onChange={setVersionParams} /></div>
              <div className={s.tagRow}>{(currentDefinition.versions ?? []).map((item) => <span className={s.tag} key={item.id}>{item.version} · {item.code_hash}</span>)}</div>
            </div>
            <div className={s.formActions}><Button type="submit" variant="primary" loading={busy === 'version'}>保存版本</Button></div>
          </form>

          <form ref={experimentFormRef} className={s.section} onSubmit={createExperiment}>
            <div className={s.sectionHead}><div><h2>创建实验</h2><span>定义、版本、标的和周期组成实验上下文</span></div></div>
            <div className={s.formGrid}>
              <label>标的<Input value={experimentForm.symbol} disabled={Boolean(experimentForm.research_run_id)} onChange={(event) => setExperimentForm({ ...experimentForm, symbol: event.target.value })} /></label>
              <label>市场<Select options={MARKETS} value={experimentForm.market} disabled={Boolean(experimentForm.research_run_id)} onChange={(event) => setExperimentForm({ ...experimentForm, market: event.target.value })} /></label>
              <label>周期<Input value={experimentForm.timeframe} disabled={Boolean(experimentForm.research_run_id)} onChange={(event) => setExperimentForm({ ...experimentForm, timeframe: event.target.value })} /></label>
              {experimentForm.research_run_id && <label className={s.grow}>研究运行<Input value={experimentForm.research_run_id} readOnly variant="mono" /></label>}
              <label>版本<Select options={versionOptions} value={experimentForm.version_id} onChange={(event) => {
                const versionId = event.target.value
                setExperimentForm({ ...experimentForm, version_id: versionId })
                const selectedVersion = (currentDefinition.versions ?? []).find((item) => item.id === versionId)
                setExperimentParams(selectedVersion?.params ?? defaultParams(currentDefinition.strategy_key))
              }} /></label>
              <div className={s.controlledParams}><StructuredParamsEditor name={currentDefinition.strategy_key} params={experimentParams} onChange={setExperimentParams} /></div>
              <label>备注<Input value={experimentForm.note} onChange={(event) => setExperimentForm({ ...experimentForm, note: event.target.value })} /></label>
            </div>
            <div className={s.formActions}><Button type="submit" variant="primary" loading={busy === 'experiment'}>创建实验</Button></div>
          </form>

          <section className={s.section}>
            <div className={s.sectionHead}><div><h2>定义生命周期</h2><span>{currentDefinition.id}</span></div></div>
            <div className={s.formGrid}>
              <label>定义名称<Input value={definitionEditForm.name} onChange={(event) => setDefinitionEditForm({ ...definitionEditForm, name: event.target.value })} /></label>
              <label>策略键<Select options={strategyOptions} value={definitionEditForm.strategy_key} onChange={(event) => setDefinitionEditForm({ ...definitionEditForm, strategy_key: event.target.value })} /></label>
              <label>市场<Select options={MARKETS} value={definitionEditForm.market} onChange={(event) => setDefinitionEditForm({ ...definitionEditForm, market: event.target.value })} /></label>
              <label>标签<Input value={definitionEditForm.tags} onChange={(event) => setDefinitionEditForm({ ...definitionEditForm, tags: event.target.value })} /></label>
              <label className={s.grow}>说明<Input value={definitionEditForm.description} onChange={(event) => setDefinitionEditForm({ ...definitionEditForm, description: event.target.value })} /></label>
              <label>副本名称<Input value={definitionEditForm.copy_name} onChange={(event) => setDefinitionEditForm({ ...definitionEditForm, copy_name: event.target.value })} /></label>
            </div>
            <div className={s.formActions}>
              <Button variant="primary" size="sm" onClick={() => void saveDefinition()} loading={busy === 'definition-edit'}>保存定义</Button>
              <Button size="sm" onClick={() => void copyDefinition()}>复制定义</Button>
              <ConfirmActionButton label="归档定义" title="归档策略定义" description={`归档 ${currentDefinition.name}，默认列表将不再显示。`} confirmLabel="确认归档" onConfirm={archiveDefinition} />
            </div>
          </section>

          <section className={s.section}>
            <div className={s.sectionHead}><div><h2>版本生命周期</h2><span>选择版本后编辑、复制或归档</span></div></div>
            <div className={s.tagRow}>
              {(currentDefinition.versions ?? []).filter((item) => !item.archived_at).map((item) => <button type="button" className={`${s.tag} ${versionEditId === item.id ? s.listButtonActive : ''}`} key={item.id} onClick={() => setVersionEditId(item.id)}>{item.version} · {item.code_hash}</button>)}
            </div>
            {versionEditId && <>
              <div className={s.formGrid}>
                <label>版本号<Input value={versionEditForm.version} onChange={(event) => setVersionEditForm({ ...versionEditForm, version: event.target.value })} /></label>
                <label>变更说明<Input value={versionEditForm.changelog} onChange={(event) => setVersionEditForm({ ...versionEditForm, changelog: event.target.value })} /></label>
                <label>副本版本号<Input value={versionEditForm.copy_version} onChange={(event) => setVersionEditForm({ ...versionEditForm, copy_version: event.target.value })} /></label>
                <div className={s.controlledParams}><StructuredParamsEditor name={currentDefinition.strategy_key} params={versionEditParams} onChange={setVersionEditParams} /></div>
              </div>
              <div className={s.formActions}>
                <Button variant="primary" size="sm" onClick={() => void saveVersion()}>保存版本</Button>
                <Button size="sm" onClick={() => void copyVersion()}>复制版本</Button>
                <ConfirmActionButton label="归档版本" title="归档策略版本" description={`归档版本 ${versionEditForm.version}，已有实验与运行记录继续保留。`} confirmLabel="确认归档" onConfirm={archiveVersion} />
              </div>
            </>}
          </section>
        </div>
      )}

      <div className={s.workflowStep}><span>02</span><div><h2>实验</h2><p>选择定义、版本、标的与时间周期</p></div></div>
      <section className={s.section}>
        <div className={s.sectionHead}><div><h2>实验列表</h2><span>{definitionId ? `定义 ${definitionId}` : '全部定义'}</span></div><RefreshControl onRefresh={() => changed('')} refreshing={experiments.loading || experiments.reconnecting} updatedAt={experiments.updatedAt} /></div>
        <AsyncStateBoundary
          loading={experiments.loading}
          error={experiments.error}
          reconnecting={experiments.reconnecting}
          hasData={experiments.data !== null}
          isEmpty={(experiments.data?.experiments.length ?? 0) === 0}
          onRetry={experiments.refetch}
          loadingTitle="正在读取实验列表…"
          emptyTitle={definitionId ? '当前定义还没有实验' : '还没有策略实验'}
        >
          <Table columns={experimentColumns} rows={experiments.data?.experiments ?? []} rowKey={(row) => row.id} density="compact" onRowClick={(row) => selectExperiment(row.id)} />
        </AsyncStateBoundary>
      </section>

      {currentExperiment && (
        <>
        <div className={s.workflowStep}><span>03</span><div><h2>运行与比较</h2><p>保留数据快照、种子、结果与指标差异</p></div></div>
        <section className={s.section}>
          <div className={s.sectionHead}>
            <div><h2>运行回测</h2><span>{currentExperiment.symbol} · {currentExperiment.market} · {currentExperiment.timeframe}</span></div>
            {currentExperiment.research_run_id && <a href={`/factor-research?run_id=${encodeURIComponent(currentExperiment.research_run_id)}`}>返回因子研究</a>}
          </div>
          {currentExperiment.research_run_id && (
            <div className={s.contextNotice} role="status">
              <strong>研究上下文已锁定</strong>
              <span>回测固定使用研究运行 {currentExperiment.research_run_id} 的行情快照，标的、市场、周期和数据哈希不可修改。</span>
            </div>
          )}
          <div className={s.formGrid}>
            <label>实验标的<Input value={experimentEditForm.symbol} disabled={experimentContextLocked} onChange={(event) => setExperimentEditForm({ ...experimentEditForm, symbol: event.target.value })} /></label>
            <label>市场<Select options={MARKETS} value={experimentEditForm.market} disabled={experimentContextLocked} onChange={(event) => setExperimentEditForm({ ...experimentEditForm, market: event.target.value })} /></label>
            <label>周期<Input value={experimentEditForm.timeframe} disabled={experimentContextLocked} onChange={(event) => setExperimentEditForm({ ...experimentEditForm, timeframe: event.target.value })} /></label>
            <label>版本<Select options={versionOptions} value={experimentEditForm.version_id} onChange={(event) => setExperimentEditForm({ ...experimentEditForm, version_id: event.target.value })} /></label>
            <label className={s.grow}>备注<Input value={experimentEditForm.note} onChange={(event) => setExperimentEditForm({ ...experimentEditForm, note: event.target.value })} /></label>
            <div className={s.controlledParams}><StructuredParamsEditor name={currentDefinition?.strategy_key ?? ''} params={experimentEditParams} onChange={setExperimentEditParams} /></div>
          </div>
          <div className={s.formActions}>
            <Button variant="primary" size="sm" onClick={() => void saveExperiment()}>保存实验</Button>
            <Button size="sm" onClick={() => void copyExperiment()}>复制实验</Button>
            <ConfirmActionButton label="归档实验" title="归档策略实验" description={`归档 ${currentExperiment.symbol} 的当前实验，已有运行记录继续保留。`} confirmLabel="确认归档" onConfirm={archiveExperiment} />
          </div>
          <form className={s.toolbar} onSubmit={runBacktest}>
            <label className={s.compact}>初始资金<Input type="number" min="1" value={runForm.initial_capital} onChange={(event) => setRunForm({ ...runForm, initial_capital: Number(event.target.value) })} /></label>
            <label className={s.compact}>{experimentContextLocked ? 'K线数量（研究快照）' : 'K线数量'}<Input type="number" min="2" max="10000" value={runForm.limit} disabled={experimentContextLocked} onChange={(event) => setRunForm({ ...runForm, limit: Number(event.target.value) })} /></label>
            <label className={s.grow}>随机种子<Input value={runForm.seed} onChange={(event) => setRunForm({ ...runForm, seed: event.target.value })} placeholder="可留空" /></label>
            <Button type="submit" variant="primary" loading={busy === 'run'}>运行并保存</Button>
          </form>
          <div className={s.sectionHead}><div><h3>实验运行</h3><span>选择运行后可进行指标对比</span></div><Button variant="secondary" size="sm" onClick={() => void compare()} loading={busy === 'compare'} disabled={!selectedRuns.length}>对比所选 {selectedRuns.length}</Button></div>
          <AsyncStateBoundary
            loading={runs.loading}
            error={runs.error}
            reconnecting={runs.reconnecting}
            hasData={runs.data !== null}
            isEmpty={(runs.data?.runs.length ?? 0) === 0}
            onRetry={runs.refetch}
            loadingTitle="正在读取实验运行…"
            emptyTitle="当前实验还没有运行记录"
          >
            <Table columns={runColumns} rows={runs.data?.runs ?? []} rowKey={(row) => row.id} density="compact" />
          </AsyncStateBoundary>
          {comparison.length > 0 && <Table columns={comparisonColumns} rows={comparison} rowKey={(row) => row.run_id} density="compact" />}
          {differences.map((difference) => (
            <div className={s.logInspector} key={difference.run_id}>
              <div className={s.logHead}><div><b>结构化差异</b><span>{difference.against_run_id.slice(0, 12)} → {difference.run_id.slice(0, 12)}</span></div></div>
              <div className={s.diffGrid}>
                {difference.code_hash.changed && <div><span>代码哈希</span><code>{String(difference.code_hash.before ?? '—')}</code><code>{String(difference.code_hash.after ?? '—')}</code></div>}
                {[
                  { label: '数据快照', rows: difference.data_snapshot },
                  { label: '参数', rows: difference.params },
                  { label: '指标', rows: difference.metrics },
                ].flatMap((group) => group.rows.filter((row) => row.changed).map((row) => <div key={`${group.label}:${row.field}`}><span>{group.label} · {row.field}</span><code>{String(row.before ?? '—')}</code><code>{String(row.after ?? '—')}</code></div>))}
              </div>
            </div>
          ))}
        </section>
        </>
      )}
    </div>
  )
}
