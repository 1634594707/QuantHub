import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, Database, FileUp, Play, Plus, RefreshCw, RotateCcw } from 'lucide-react'
import { api } from '../api/client'
import type { CrossMarketFactorStatus, CrossSectionResearchResp, FactorStatusMatrix, FactorUniverse, FactorUniverseBatchDiff, FactorUniverseMember, FactorUniverseVersion } from '../api/types'
import { Button } from '../components/ui/Button/Button'
import { Input } from '../components/ui/Input/Input'
import { Select } from '../components/ui/Select/Select'
import { Table } from '../components/ui/Table'
import s from './CrossSectionResearchPanel.module.css'

const MARKETS = [
  { value: 'a_shares', label: 'A 股' },
  { value: 'us_stocks', label: '美股' },
  { value: 'crypto', label: '加密资产' },
  { value: 'mt5', label: 'MT5' },
]

const FACTORS = [
  { value: 'trend_strength', label: '趋势强度' },
  { value: 'momentum_20', label: '20 周期动量' },
  { value: 'macd_histogram', label: 'MACD 柱' },
  { value: 'adx_direction', label: 'ADX 方向' },
  { value: 'mean_reversion', label: '均值回归' },
  { value: 'rsi_reversal', label: 'RSI 反转' },
  { value: 'bollinger_reversal', label: '布林反转' },
  { value: 'breakout_20', label: '20 周期突破' },
  { value: 'volume_confirmation', label: '量价确认' },
  { value: 'obv_momentum', label: 'OBV 动量' },
  { value: 'chaikin_flow', label: 'Chaikin 资金流' },
  { value: 'low_volatility', label: '低波动' },
  { value: 'atr_contraction', label: 'ATR 收缩' },
  { value: 'downside_risk', label: '下行波动' },
]

const MEMBER_STATUSES = [
  { value: 'active', label: '正常' },
  { value: 'suspended', label: '停牌' },
  { value: 'delisted', label: '退市' },
]

const PORTFOLIO_MODES = [
  { value: 'cohort', label: '每日批次重叠持有' },
  { value: 'non_overlapping', label: '预测周期无重叠调仓' },
]

function pct(value: number): string {
  return `${(value * 100).toFixed(2)}%`
}

async function fileBase64(file: File): Promise<string> {
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result ?? ''))
    reader.onerror = () => reject(reader.error ?? new Error('文件读取失败'))
    reader.readAsDataURL(file)
  })
  return dataUrl.split(',', 2)[1] ?? ''
}

export function CrossSectionResearchPanel() {
  const [universes, setUniverses] = useState<FactorUniverse[]>([])
  const [universeId, setUniverseId] = useState('')
  const [members, setMembers] = useState<FactorUniverseMember[]>([])
  const [versions, setVersions] = useState<FactorUniverseVersion[]>([])
  const [batchFile, setBatchFile] = useState<File | null>(null)
  const [batchPayload, setBatchPayload] = useState<{ idempotency_key: string; source: string; filename: string; content_base64: string } | null>(null)
  const [batchPreview, setBatchPreview] = useState<FactorUniverseBatchDiff | null>(null)
  const [rollbackVersionId, setRollbackVersionId] = useState('')
  const [loading, setLoading] = useState('')
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [result, setResult] = useState<CrossSectionResearchResp | null>(null)
  const [marketStatus, setMarketStatus] = useState<CrossMarketFactorStatus | null>(null)
  const [statusMatrix, setStatusMatrix] = useState<FactorStatusMatrix | null>(null)
  const [universeForm, setUniverseForm] = useState({ name: '', market: 'a_shares', description: '' })
  const [memberForm, setMemberForm] = useState({
    symbol: '', effective_from: new Date().toISOString().slice(0, 10), effective_to: '',
    status: 'active' as 'active' | 'suspended' | 'delisted', industry: '', market_cap: '', beta: '',
    is_st: false, listed_at: '', delisted_at: '',
  })
  const [researchForm, setResearchForm] = useState({
    factor_key: 'trend_strength', limit: 500, horizon: 5, start_date: '', end_date: '',
    quantiles: 5, min_assets: 5, transaction_cost_bps: 10, participation_rate: 0.1,
    portfolio_mode: 'cohort' as 'cohort' | 'non_overlapping',
    neutralize_industry: true, neutralize_market_cap: true, neutralize_beta: true,
    retry_attempts: 2,
  })

  const selectedUniverse = useMemo(
    () => universes.find((item) => item.id === universeId) ?? null,
    [universeId, universes],
  )
  const universeOptions = useMemo(() => [
    { value: '', label: '选择股票池' },
    ...universes.map((item) => ({ value: item.id, label: `${item.name} · ${item.market}` })),
  ], [universes])

  async function loadUniverses(preferredId?: string) {
    setLoading('universes')
    setError('')
    try {
      const response = await api.factorUniverses()
      setUniverses(response.universes)
      setUniverseId((current) => preferredId || current || response.universes[0]?.id || '')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '股票池读取失败')
    } finally {
      setLoading('')
    }
  }

  async function loadMembers(id: string) {
    if (!id) {
      setMembers([])
      setVersions([])
      return
    }
    setLoading('members')
    setError('')
    try {
      const response = await api.factorUniverseMembers(id)
      if (!response.ok) throw new Error('股票池成员读取失败')
      setMembers(response.members)
      setVersions(response.versions ?? [])
      setRollbackVersionId(response.universe.current_version_id ?? '')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '股票池成员读取失败')
    } finally {
      setLoading('')
    }
  }

  useEffect(() => { void loadUniverses() }, [])
  useEffect(() => { void loadMembers(universeId) }, [universeId])

  async function createUniverse(event: React.FormEvent) {
    event.preventDefault()
    if (!universeForm.name.trim()) return
    setLoading('create-universe')
    setError('')
    try {
      const response = await api.createFactorUniverse({
        ...universeForm,
        name: universeForm.name.trim(),
        description: universeForm.description.trim(),
      })
      if (!response.ok) throw new Error(response.error || '股票池创建失败')
      setUniverseForm((current) => ({ ...current, name: '', description: '' }))
      setMessage('股票池已创建')
      await loadUniverses(response.universe.id)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '股票池创建失败')
    } finally {
      setLoading('')
    }
  }

  async function saveMember(event: React.FormEvent) {
    event.preventDefault()
    if (!universeId || !memberForm.symbol.trim() || !memberForm.effective_from) return
    setLoading('member')
    setError('')
    try {
      const response = await api.upsertFactorUniverseMember(universeId, {
        symbol: memberForm.symbol.trim().toUpperCase(),
        effective_from: memberForm.effective_from,
        effective_to: memberForm.effective_to || null,
        status: memberForm.status,
        industry: memberForm.industry.trim(),
        market_cap: memberForm.market_cap ? Number(memberForm.market_cap) : null,
        beta: memberForm.beta ? Number(memberForm.beta) : null,
        is_st: memberForm.is_st,
        listed_at: memberForm.listed_at || null,
        delisted_at: memberForm.delisted_at || null,
      })
      if (!response.ok) throw new Error(response.error || '成员保存失败')
      setMemberForm((current) => ({ ...current, symbol: '', industry: '', market_cap: '', beta: '' }))
      setMessage('成员生效记录已保存')
      await loadMembers(universeId)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '成员保存失败')
    } finally {
      setLoading('')
    }
  }

  async function previewBatch() {
    if (!universeId || !batchFile) return
    setLoading('batch-preview')
    setError('')
    try {
      const payload = {
        idempotency_key: crypto.randomUUID(),
        source: 'workbench_import',
        filename: batchFile.name,
        content_base64: await fileBase64(batchFile),
      }
      const response = await api.previewFactorUniverseBatch(universeId, payload)
      setBatchPayload(payload)
      setBatchPreview(response.diff)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '批量预览失败')
    } finally {
      setLoading('')
    }
  }

  async function applyBatch() {
    if (!universeId || !batchPayload || !batchPreview) return
    setLoading('batch-apply')
    setError('')
    try {
      const response = await api.applyFactorUniverseBatch(universeId, batchPayload)
      setMessage(response.ok ? '批次已写入新版本' : '批次部分写入，请查看失败报告')
      setBatchPreview(null)
      setBatchPayload(null)
      setBatchFile(null)
      await loadMembers(universeId)
      await loadUniverses(universeId)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '批量写入失败')
    } finally {
      setLoading('')
    }
  }

  async function rollbackUniverse() {
    if (!universeId || !rollbackVersionId || rollbackVersionId === selectedUniverse?.current_version_id) return
    setLoading('rollback')
    setError('')
    try {
      await api.rollbackFactorUniverse(universeId, rollbackVersionId, 'operator_selected_version')
      setMessage('股票池当前版本已回滚')
      await loadMembers(universeId)
      await loadUniverses(universeId)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '版本回滚失败')
    } finally {
      setLoading('')
    }
  }

  async function runResearch(event?: React.FormEvent, resumeRunId?: string) {
    event?.preventDefault()
    if (!universeId) return
    setLoading('research')
    setError('')
    setMessage('')
    setResult(null)
    setMarketStatus(null)
    setStatusMatrix(null)
    try {
      const response = await api.crossSectionResearch({
        run_id: resumeRunId,
        universe_id: universeId,
        factor_key: researchForm.factor_key,
        interval: '1d',
        limit: researchForm.limit,
        horizon: researchForm.horizon,
        start_date: researchForm.start_date || undefined,
        end_date: researchForm.end_date || undefined,
        quantiles: researchForm.quantiles,
        min_assets: researchForm.min_assets,
        portfolio_mode: researchForm.portfolio_mode,
        transaction_cost_bps: researchForm.transaction_cost_bps,
        cost_profile_id: selectedUniverse?.market === 'a_shares'
          ? 'a-shares-reference'
          : selectedUniverse?.market === 'us_stocks'
            ? 'us-stocks-reference'
            : 'okx-reference',
        cost_profile_version: '1.0.0',
        participation_rate: researchForm.participation_rate,
        neutralize_industry: researchForm.neutralize_industry,
        neutralize_market_cap: researchForm.neutralize_market_cap,
        neutralize_beta: researchForm.neutralize_beta,
        retry_attempts: researchForm.retry_attempts,
      })
      if (!response.ok) throw new Error(response.error || '横截面研究失败')
      setResult(response)
      setMessage(`横截面研究已保存 · ${response.run_id.slice(0, 12)}`)
      const factorKey = response.factor?.key ?? researchForm.factor_key
      try {
        setMarketStatus(await api.crossMarketFactorStatus(factorKey, selectedUniverse?.market))
      } catch {
        setMarketStatus(null)
      }
      try {
        setStatusMatrix(await api.factorStatusMatrix(factorKey))
      } catch {
        setStatusMatrix(null)
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '横截面研究失败')
    } finally {
      setLoading('')
    }
  }

  return (
    <div className={s.workspace}>
      {error && <div className={s.error} role="alert"><AlertTriangle size={17} /><span>{error}</span></div>}
      {message && <div className={s.success} role="status"><Database size={16} /><span>{message}</span></div>}

      <section className={s.band} aria-label="历史股票池">
        <header><div><span>POINT-IN-TIME UNIVERSE</span><h2>历史股票池</h2><p>成分记录按生效区间参与每日横截面，不使用当前成分回填历史。</p></div><Button variant="ghost" size="sm" icon={<RefreshCw size={15} />} loading={loading === 'universes'} onClick={() => void loadUniverses()}>刷新</Button></header>
        <div className={s.universeGrid}>
          <div className={s.selector}>
            <label><span>当前股票池</span><Select aria-label="当前股票池" value={universeId} options={universeOptions} onChange={(event) => setUniverseId(event.target.value)} /></label>
            {selectedUniverse && <dl><div><dt>市场</dt><dd>{selectedUniverse.market}</dd></div><div><dt>成员记录</dt><dd>{members.length}</dd></div><div><dt>说明</dt><dd>{selectedUniverse.description || '—'}</dd></div></dl>}
          </div>
          <form onSubmit={createUniverse} className={s.inlineForm}>
            <label><span>股票池名称</span><Input value={universeForm.name} onChange={(event) => setUniverseForm({ ...universeForm, name: event.target.value })} /></label>
            <label><span>市场</span><Select value={universeForm.market} options={MARKETS} onChange={(event) => setUniverseForm({ ...universeForm, market: event.target.value })} /></label>
            <label className={s.grow}><span>说明</span><Input value={universeForm.description} onChange={(event) => setUniverseForm({ ...universeForm, description: event.target.value })} /></label>
            <Button type="submit" variant="primary" icon={<Plus size={16} />} loading={loading === 'create-universe'}>创建股票池</Button>
          </form>
        </div>
      </section>

      {selectedUniverse && <section className={s.band} aria-label="股票池成员生效记录">
        <header><div><span>MEMBERSHIP LEDGER</span><h2>成员生效记录</h2><p>停牌、退市、ST、上市时间和风险暴露均作为当日可用性依据。</p></div><strong>{members.length} 条</strong></header>
        <div className={s.batchBar}>
          <label className={s.fileControl}><FileUp size={16} /><span>{batchFile?.name ?? 'CSV / XLSX'}</span><input type="file" accept=".csv,.xlsx" onChange={(event) => { setBatchFile(event.target.files?.[0] ?? null); setBatchPreview(null); setBatchPayload(null) }} /></label>
          <Button type="button" variant="secondary" size="sm" onClick={() => void previewBatch()} loading={loading === 'batch-preview'} disabled={!batchFile}>差异预览</Button>
          {batchPreview && <div className={s.diffCounts}>
            <span><small>新增</small><b>{batchPreview.counts.additions}</b></span>
            <span><small>更新</small><b>{batchPreview.counts.updates}</b></span>
            <span data-alert={batchPreview.counts.conflicts > 0}><small>冲突</small><b>{batchPreview.counts.conflicts}</b></span>
            <span><small>忽略</small><b>{batchPreview.counts.ignored}</b></span>
            <Button type="button" variant="primary" size="sm" onClick={() => void applyBatch()} loading={loading === 'batch-apply'} disabled={batchPreview.counts.conflicts > 0}>写入版本</Button>
          </div>}
          <div className={s.versionControl}>
            <Select aria-label="股票池版本" value={rollbackVersionId} options={versions.map((version) => ({ value: version.id, label: `v${version.version} · ${version.source}` }))} onChange={(event) => setRollbackVersionId(event.target.value)} />
            <Button type="button" variant="ghost" size="sm" icon={<RotateCcw size={15} />} onClick={() => void rollbackUniverse()} loading={loading === 'rollback'} disabled={!rollbackVersionId || rollbackVersionId === selectedUniverse.current_version_id}>回滚</Button>
          </div>
        </div>
        <form onSubmit={saveMember} className={s.memberForm}>
          <label><span>标的</span><Input aria-label="成员标的" variant="mono" value={memberForm.symbol} onChange={(event) => setMemberForm({ ...memberForm, symbol: event.target.value })} /></label>
          <label><span>生效日期</span><Input type="date" value={memberForm.effective_from} onChange={(event) => setMemberForm({ ...memberForm, effective_from: event.target.value })} /></label>
          <label><span>失效日期</span><Input type="date" value={memberForm.effective_to} min={memberForm.effective_from} onChange={(event) => setMemberForm({ ...memberForm, effective_to: event.target.value })} /></label>
          <label><span>状态</span><Select value={memberForm.status} options={MEMBER_STATUSES} onChange={(event) => setMemberForm({ ...memberForm, status: event.target.value as typeof memberForm.status })} /></label>
          <label><span>行业</span><Input value={memberForm.industry} onChange={(event) => setMemberForm({ ...memberForm, industry: event.target.value })} /></label>
          <label><span>市值</span><Input type="number" min="0" value={memberForm.market_cap} onChange={(event) => setMemberForm({ ...memberForm, market_cap: event.target.value })} /></label>
          <label><span>Beta</span><Input type="number" step="0.01" min="-10" max="10" value={memberForm.beta} onChange={(event) => setMemberForm({ ...memberForm, beta: event.target.value })} /></label>
          <label><span>上市日期</span><Input type="date" value={memberForm.listed_at} onChange={(event) => setMemberForm({ ...memberForm, listed_at: event.target.value })} /></label>
          <label><span>退市日期</span><Input type="date" value={memberForm.delisted_at} min={memberForm.listed_at} onChange={(event) => setMemberForm({ ...memberForm, delisted_at: event.target.value })} /></label>
          <label className={s.check}><input type="checkbox" checked={memberForm.is_st} onChange={(event) => setMemberForm({ ...memberForm, is_st: event.target.checked })} /><span>ST</span></label>
          <Button type="submit" variant="primary" loading={loading === 'member'}>保存成员</Button>
        </form>
        <div className={s.tableWrap}>
          <Table
            rows={members}
            rowKey={(item) => item.id}
            columns={[
              { key: 'symbol', header: '标的', render: (item) => (<span><b>{item.symbol}</b>{item.is_st ? <small>ST</small> : null}</span>) },
              { key: 'range', header: '生效区间', render: (item) => `${item.effective_from} → ${item.effective_to || '持续'}` },
              { key: 'status', header: '状态', render: (item) => MEMBER_STATUSES.find((status) => status.value === item.status)?.label },
              { key: 'industry', header: '行业', render: (item) => item.industry || '—' },
              { key: 'market_cap', header: '市值', align: 'right', render: (item) => item.market_cap?.toLocaleString('zh-CN') || '—' },
              { key: 'beta', header: 'Beta', align: 'right', render: (item) => item.beta?.toFixed(2) || '—' },
              { key: 'dates', header: '上市 / 退市', render: (item) => `${item.listed_at || '—'} / ${item.delisted_at || '—'}` },
            ]}
          />
        </div>
      </section>}

      {selectedUniverse && <section className={s.band} aria-label="横截面因子验证">
        <header><div><span>CROSS-SECTIONAL VALIDATION</span><h2>横截面因子验证</h2><p>日频 Rank IC、分层收益与可交易约束使用同一历史股票池快照。</p></div></header>
        <form onSubmit={runResearch} className={s.researchForm}>
          <label><span>因子</span><Select value={researchForm.factor_key} options={FACTORS} onChange={(event) => setResearchForm({ ...researchForm, factor_key: event.target.value })} /></label>
          <label><span>历史长度</span><Input type="number" min="120" max="5000" value={researchForm.limit} onChange={(event) => setResearchForm({ ...researchForm, limit: Number(event.target.value) })} /></label>
          <label><span>预测窗口</span><Input type="number" min="1" max="60" value={researchForm.horizon} onChange={(event) => setResearchForm({ ...researchForm, horizon: Number(event.target.value) })} /></label>
          <label><span>分层数</span><Input type="number" min="2" max="10" value={researchForm.quantiles} onChange={(event) => setResearchForm({ ...researchForm, quantiles: Number(event.target.value) })} /></label>
          <label><span>最少标的</span><Input type="number" min="3" max="500" value={researchForm.min_assets} onChange={(event) => setResearchForm({ ...researchForm, min_assets: Number(event.target.value) })} /></label>
          <label><span>组合计账</span><Select value={researchForm.portfolio_mode} options={PORTFOLIO_MODES} onChange={(event) => setResearchForm({ ...researchForm, portfolio_mode: event.target.value as 'cohort' | 'non_overlapping' })} /></label>
          <label><span>单边成本</span><Input type="number" min="0" max="200" suffix="bp" value={researchForm.transaction_cost_bps} onChange={(event) => setResearchForm({ ...researchForm, transaction_cost_bps: Number(event.target.value) })} /></label>
          <label><span>参与率</span><Input type="number" min="0.01" max="0.5" step="0.01" value={researchForm.participation_rate} onChange={(event) => setResearchForm({ ...researchForm, participation_rate: Number(event.target.value) })} /></label>
          <label><span>开始日期</span><Input type="date" value={researchForm.start_date} max={researchForm.end_date || undefined} onChange={(event) => setResearchForm({ ...researchForm, start_date: event.target.value })} /></label>
          <label><span>结束日期</span><Input type="date" value={researchForm.end_date} min={researchForm.start_date || undefined} onChange={(event) => setResearchForm({ ...researchForm, end_date: event.target.value })} /></label>
          <label><span>失败重试</span><Input type="number" min="1" max="5" value={researchForm.retry_attempts} onChange={(event) => setResearchForm({ ...researchForm, retry_attempts: Number(event.target.value) })} /></label>
          <div className={s.neutralization}><span>中性化</span>{([
            ['neutralize_industry', '行业'], ['neutralize_market_cap', '市值'], ['neutralize_beta', 'Beta'],
          ] as const).map(([key, label]) => <label key={key}><input type="checkbox" checked={researchForm[key]} onChange={(event) => setResearchForm({ ...researchForm, [key]: event.target.checked })} /><span>{label}</span></label>)}</div>
          <Button type="submit" variant="primary" icon={<Play size={16} />} loading={loading === 'research'} disabled={members.length < 3}>运行横截面研究</Button>
        </form>

        {result?.summary && <div className={s.results}>
          <div className={s.metrics}>
            <div><span>Rank IC 均值</span><strong>{result.summary.rank_ic_mean.toFixed(3)}</strong></div>
            <div><span>HAC 显著性</span><strong>{result.summary.rank_ic_p_value?.toFixed(4) ?? '旧记录未保存'}</strong></div>
            <div><span>ICIR</span><strong>{result.summary.icir.toFixed(2)}</strong></div>
            <div><span>{result.summary.primary_portfolio_key === 'long_only_excess' ? '多头相对基准' : '成本后理论多空'}</span><strong>{pct(result.summary.primary_total_return ?? result.summary.net_long_short_total_return ?? result.summary.long_short_total_return)}</strong></div>
            <div><span>覆盖率</span><strong>{pct(result.summary.coverage)}</strong></div>
            <div><span>平均换手</span><strong>{pct(result.summary.average_turnover)}</strong></div>
            <div><span>中位容量代理</span><strong>{result.summary.median_capacity.toLocaleString('zh-CN')}</strong></div>
            <div><span>拥挤度 HHI</span><strong>{result.summary.median_crowding_hhi.toFixed(3)}</strong></div>
            <div><span>有效日期</span><strong>{result.summary.dates}</strong></div>
            <div><span>组合计账期</span><strong>{result.summary.portfolio_observations ?? result.summary.dates}</strong></div>
          </div>
          <div className={s.resultSplit}>
            <div><h3>分层未来收益</h3>{result.quantile_returns?.map((item) => <div className={s.quantile} key={item.quantile}><span>Q{item.quantile}</span><i style={{ width: `${Math.min(100, Math.abs(item.mean_forward_return) * 2000)}%` }} /><b>{pct(item.mean_forward_return)}</b></div>)}</div>
            <div><h3>证据状态</h3><dl><div><dt>行情成功 / 失败</dt><dd>{result.loaded_symbols} / {result.failed_symbols}</dd></div><div><dt>中性化失败日期</dt><dd>{result.summary.neutralization_failures}</dd></div><div><dt>理论多空</dt><dd>{pct(result.summary.net_long_short_total_return ?? result.summary.long_short_total_return)}{result.summary.portfolio_variants?.theoretical_long_short?.executable === false ? ' · 仅研究' : ''}</dd></div><div><dt>多头成本后</dt><dd>{result.summary.long_only_total_return === undefined ? '旧记录未保存' : pct(result.summary.long_only_total_return)}</dd></div><div><dt>等权基准</dt><dd>{result.summary.benchmark_total_return === undefined ? '旧记录未保存' : pct(result.summary.benchmark_total_return)}</dd></div><div><dt>数据指纹</dt><dd className={s.mono}>{result.summary.data_fingerprint}</dd></div></dl></div>
          </div>
          {marketStatus && <div className={s.marketMatrix}>
            <div><h3>目标市场交易验证门禁</h3><strong data-passed={marketStatus.trading_validation_passed}>{marketStatus.trading_validation_passed ? '交易验证通过' : '目标市场证据不足'}</strong><p>{marketStatus.rule}</p></div>
            <div>{marketStatus.rows.map((row) => <div key={row.market} data-state={row.state}><b>{MARKETS.find((market) => market.value === row.market)?.label ?? row.market}</b><span>{row.state === 'passed' ? '通过' : row.state === 'failed' ? '未通过' : '缺少记录'}</span><small>{row.dates ?? 0} 日 · 最少 {row.minimum_valid_assets ?? 0} 标的 · IC {row.rank_ic_mean?.toFixed(3) ?? '—'}</small></div>)}</div>
          </div>}
          {statusMatrix && <section className={s.statusMatrix} aria-label="因子研究状态矩阵">
            <header><div><h3>研究状态矩阵</h3><p>窗口、横截面和市场门禁均保留同一条规则与原始研究运行引用。</p></div><dl><div><dt>通过</dt><dd>{statusMatrix.counts.passed}</dd></div><div><dt>未通过</dt><dd>{statusMatrix.counts.failed}</dd></div><div><dt>缺少</dt><dd>{statusMatrix.counts.missing}</dd></div></dl></header>
            <div className={s.statusRows}>
              {statusMatrix.rows.map((row) => <details key={`${row.dimension}:${row.key}:${row.run_id ?? 'none'}`} data-state={row.state}>
                <summary><span>{row.dimension === 'window' ? '窗口' : row.dimension === 'cross_symbol' ? '跨标的' : '跨市场'}</span><b>{row.label}</b><strong>{row.state === 'passed' ? '通过' : row.state === 'failed' ? '未通过' : '缺少记录'}</strong></summary>
                <dl><div><dt>计算规则</dt><dd>{row.rule}</dd></div><div><dt>研究运行</dt><dd>{row.run_id ?? '没有关联运行'}</dd></div><div><dt>原始证据</dt><dd><code>{JSON.stringify(row.evidence)}</code></dd></div></dl>
              </details>)}
            </div>
          </section>}
          {result.failures.length > 0 && <div className={s.failures}><h3>取数失败明细</h3>{result.failures.map((item) => <div key={item.symbol}><b>{item.symbol}</b><span>{item.attempts} 次</span><code>{item.error}</code></div>)}<Button type="button" size="sm" variant="secondary" onClick={() => void runResearch(undefined, result.run_id)} loading={loading === 'research'}>从断点重试失败标的</Button></div>}
        </div>}
      </section>}
    </div>
  )
}
