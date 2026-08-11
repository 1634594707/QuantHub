import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import type { LLMConfigResp } from '../api/types'
import { FactorFactoryWorkflow } from './FactorFactoryWorkflow'

const LLM_CONFIG: LLMConfigResp = {
  ok: true,
  configured: true,
  provider: 'deepseek',
  provider_label: 'DeepSeek',
  official_url: 'https://platform.deepseek.com',
  key_env: 'DEEPSEEK_API_KEY',
  masked: '****test',
  base_url: 'https://api.deepseek.com',
  models_endpoint: 'https://api.deepseek.com/models',
  model: 'deepseek-v4-flash',
  timeout: 60,
  max_retries: 3,
  providers: [
    { id: 'deepseek', label: 'DeepSeek', description: 'DeepSeek', official_url: 'https://platform.deepseek.com', base_url: 'https://api.deepseek.com', model: 'deepseek-v4-flash', key_env: 'DEEPSEEK_API_KEY', configured: true },
    { id: 'openai', label: 'OpenAI', description: 'OpenAI', official_url: 'https://platform.openai.com', base_url: 'https://api.openai.com/v1', model: 'gpt-4o-mini', key_env: 'OPENAI_API_KEY', configured: false },
    { id: 'custom', label: '兼容 API', description: '兼容 API', official_url: '', base_url: 'http://localhost:1234/v1', model: 'local-model', key_env: 'QUANTHUB_CUSTOM_LLM_API_KEY', configured: true },
  ],
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

beforeEach(() => {
  vi.spyOn(api, 'llmConfig').mockResolvedValue(LLM_CONFIG)
  vi.spyOn(api, 'instruments').mockResolvedValue({ count: 0, instruments: [] })
  vi.spyOn(api, 'okxSwapCatalog').mockImplementation(async (query = '') => {
    const normalized = query.toUpperCase()
    const rows = [
      { instrument_id: 'crypto:BTC-USDT-SWAP', code: 'BTC-USDT-SWAP', market: 'crypto', exchange: 'okx', name: '比特币 / Bitcoin 永续', currency: 'USDT', asset_class: 'crypto', base: 'BTC', quote: 'USDT', settle: 'USDT', contract_size: 0.01, price_precision: 0.1, amount_precision: 0.01, minimum_amount: 0.01, linear: true, verified: true as const },
      { instrument_id: 'crypto:NVDA-USDT-SWAP', code: 'NVDA-USDT-SWAP', market: 'crypto', exchange: 'okx', name: '英伟达 / NVIDIA 永续', currency: 'USDT', asset_class: 'crypto', base: 'NVDA', quote: 'USDT', settle: 'USDT', contract_size: 1, price_precision: 0.01, amount_precision: 0.01, minimum_amount: 0.01, linear: true, verified: true as const },
      { instrument_id: 'crypto:AVGO-USDT-SWAP', code: 'AVGO-USDT-SWAP', market: 'crypto', exchange: 'okx', name: '博通 / Broadcom 永续', currency: 'USDT', asset_class: 'crypto', base: 'AVGO', quote: 'USDT', settle: 'USDT', contract_size: 1, price_precision: 0.01, amount_precision: 0.01, minimum_amount: 0.01, linear: true, verified: true as const },
    ]
    const instruments = rows.filter((item) => !normalized || `${item.code} ${item.name}`.toUpperCase().includes(normalized) || (query === '英伟达' && item.base === 'NVDA') || (query === '博通' && item.base === 'AVGO'))
    return { ok: true, source: 'okx_public' as const, query, count: instruments.length, total: rows.length, cache_age_seconds: 1, cache_ttl_seconds: 900, fetched_at: 1, error: null, instruments }
  })
  vi.spyOn(api, 'kline').mockResolvedValue({
    ok: true, source: 'okx', symbol: 'BTC-USDT-SWAP', interval: '4h', count: 2,
    candles: [
      { t: '2026-08-11T00:00:00Z', o: 100, h: 105, l: 99, c: 103, v: 1000 },
      { t: '2026-08-11T04:00:00Z', o: 103, h: 108, l: 102, c: 107, v: 1200 },
    ],
  })
})

describe('FactorFactoryWorkflow', () => {
  it('registers an auditable template and runs its DSL drawdown experiment', async () => {
    vi.spyOn(api, 'factorFactoryArchive').mockResolvedValue({ ok: true, count: 0, total: 0, research_record_count: 0, ineligible_count: 0, verified_count: 0, eligible_only: true, archives: [], live_trading_enabled: false })
    const definition = {
      id: 'definition-1', key: 'volatility_adjusted_momentum', factor_key: 'volatility_adjusted_momentum',
      label: '波动率调整动量', market: 'crypto', input_fields: ['close'],
      ast: { op: 'rolling_zscore', value: { op: 'field', name: 'close' }, window: 60 },
      direction: 'positive', horizon: 5, availability_lag: 1, rationale: '趋势延续 × 风险归一化',
      family: 'factor_factory', version: '1.0.0', parameters: { research_angle: '趋势延续 × 风险归一化', interval: '1d' },
      formula_hash: 'a'.repeat(64), definition_hash: 'b'.repeat(64),
      validation: { unit: 'dimensionless', shape: 'series', fields: ['close'], depth: 3, operators: 4 }, created_at: 1,
    }
    const register = vi.spyOn(api, 'registerFactorDefinition').mockResolvedValue({ ok: true, definition } as never)
    const run = vi.spyOn(api, 'demoRun').mockResolvedValue({
      ok: true, run_id: 'demo-run-1', config: {}, persisted: true,
      data_provenance: { source: 'okx_local', channel: 'archive', fingerprint: 'c'.repeat(64), selected_first: '2025-01-01', selected_last: '2025-12-31' },
      summary: { final_equity: 1_080_000, total_return: 0.08, max_drawdown: -0.09, engine: 'event-signal', n_trades: 4, metrics: { sharpe: 1.2 } },
      equity_curve: [{ datetime: '2025-01-01', equity: 1_000_000 }, { datetime: '2025-12-31', equity: 1_080_000 }],
      trades: [{ datetime: '2025-12-30', side: 'buy', price: 100, qty: 1, realized_pnl: 0 }], run_log: [],
    } as never)

    render(<FactorFactoryWorkflow />)
    fireEvent.click(screen.getByRole('tab', { name: '手动流程' }))
    expect(screen.getByRole('button', { name: /波动率调整动量/ })).toBeTruthy()
    expect(screen.queryByRole('button', { name: '运行回撤实验' })).toBeNull()
    expect((screen.getByRole('button', { name: /固定回测/ }) as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: '登记为 draft' }))

    await waitFor(() => expect(register).toHaveBeenCalledWith(expect.objectContaining({
      key: 'volatility_adjusted_momentum', market: 'crypto', availability_lag: 1, family: 'factor_factory',
    })))
    fireEvent.click(await screen.findByRole('button', { name: '运行回撤实验' }))

    await waitFor(() => expect(run).toHaveBeenCalledWith(expect.objectContaining({
      source: 'okx_local', symbol: 'BTCUSDT', strategy: 'factor_follow',
      factor: 'volatility_adjusted_momentum', factor_ast: definition.ast,
    })))
    fireEvent.click(screen.getByRole('button', { name: /固定回测/ }))
    expect((await screen.findAllByText('8.00%')).length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('固定回测')).toBeTruthy()
  })

  it('starts the persisted automatic research loop from the control surface', async () => {
    vi.spyOn(api, 'factorFactoryArchive').mockResolvedValue({ ok: true, count: 0, total: 0, research_record_count: 0, ineligible_count: 0, verified_count: 0, eligible_only: true, archives: [], live_trading_enabled: false })
    vi.spyOn(api, 'factorFactoryRuns').mockResolvedValue({ ok: true, count: 0, runs: [], live_trading_enabled: false })
    const start = vi.spyOn(api, 'startFactorFactory').mockResolvedValue({
      ok: true,
      run: {
        id: 'auto-run-1', research_plan_id: 'ff-plan', status: 'no_qualified_factor', config: {}, result: { message: '没有候选通过滚动验证门禁' },
        selected_factor_key: null, selected_factor_version: null, selected_experiment_id: null, error: null,
        started_at: 1, updated_at: 1, observation_started_at: null, observation_ends_at: null,
      },
      candidates: [], observations: [], simulation_orders: [], observation_summary: { count: 0, latest_equity: null, after_cost_return: null, max_drawdown: 0 }, live_trading_enabled: false,
    })

    const { container } = render(<FactorFactoryWorkflow />)
    await waitFor(() => expect([...container.querySelectorAll('select')].some((select) => [...select.options].some((option) => option.value === 'custom'))).toBe(true))
    const providerSelect = [...container.querySelectorAll('select')].find((select) => [...select.options].some((option) => option.value === 'custom'))
    fireEvent.change(providerSelect!, { target: { value: 'custom' } })
    fireEvent.click(screen.getByRole('button', { name: '启动自动研究' }))

    await waitFor(() => expect(start).toHaveBeenCalledWith(expect.objectContaining({
      source: 'okx_live', symbol: 'BTC-USDT-SWAP', interval: '4h', candidate_budget: 30,
      n_bars: 720, observation_days: 7, paper_target: 'okx_demo',
      candidate_mode: 'brain', use_ai: true, ai_provider: 'custom', ai_candidate_count: 6,
      alpha_brief: expect.stringContaining('Alpha'), maximum_ai_tokens: 12_000,
      maximum_demo_exposure: 0.1, maximum_demo_loss: 25,
    })))
    expect((await screen.findAllByText('没有候选通过滚动验证门禁')).length).toBeGreaterThanOrEqual(1)
  })

  it('accepts a manual alpha expression and an uploaded JSON batch', async () => {
    vi.spyOn(api, 'factorFactoryArchive').mockResolvedValue({ ok: true, count: 0, total: 0, research_record_count: 0, ineligible_count: 0, verified_count: 0, eligible_only: true, archives: [], live_trading_enabled: false })
    vi.spyOn(api, 'factorFactoryRuns').mockResolvedValue({ ok: true, count: 0, runs: [], live_trading_enabled: false })
    const start = vi.spyOn(api, 'startFactorFactory').mockResolvedValue({
      ok: true,
      run: {
        id: 'manual-run-1', research_plan_id: 'ff-manual', status: 'no_qualified_factor', config: { candidate_mode: 'manual' }, result: { message: '手工批次完成统一回测' },
        selected_factor_key: null, selected_factor_version: null, selected_experiment_id: null, error: null,
        started_at: 1, updated_at: 1, observation_started_at: null, observation_ends_at: null,
      },
      candidates: [], observations: [], simulation_orders: [], observation_summary: { count: 0, latest_equity: null, after_cost_return: null, max_drawdown: 0 }, live_trading_enabled: false,
    })
    const { container } = render(<FactorFactoryWorkflow />)
    const modeSelect = [...container.querySelectorAll('select')].find((select) => [...select.options].some((option) => option.value === 'manual'))
    expect(modeSelect).toBeTruthy()
    fireEvent.change(modeSelect!, { target: { value: 'manual' } })

    expect(screen.getByText('手工 Alpha 表达式')).toBeTruthy()
    expect(screen.getByRole('complementary', { name: 'Alpha 参数手册' })).toBeTruthy()
    expect(screen.getAllByText('periods').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('window').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('lower / upper')).toBeTruthy()
    const presetSelect = [...container.querySelectorAll('select')].find((select) => [...select.options].some((option) => option.value === 'reversal'))
    const profileSelect = [...container.querySelectorAll('select')].find((select) => [...select.options].some((option) => option.value === 'robust'))
    expect(presetSelect).toBeTruthy()
    expect(profileSelect).toBeTruthy()
    fireEvent.change(presetSelect!, { target: { value: 'reversal' } })
    fireEvent.change(profileSelect!, { target: { value: 'robust' } })
    const manualTextarea = [...container.querySelectorAll('textarea')].find((textarea) => textarea.value.includes('neg(rolling_zscore'))
    expect(manualTextarea?.value).toBe('neg(rolling_zscore(pct_change(close, 5), 40))')
    fireEvent.click(screen.getByRole('button', { name: /rolling_zscore\(value, window\).*滚动标准分/ }))
    expect(manualTextarea?.value).toBe('rolling_zscore(pct_change(close, 3), 20)')
    const file = new File(['[]'], 'alphas.json', { type: 'application/json' })
    Object.defineProperty(file, 'text', { value: vi.fn().mockResolvedValue(JSON.stringify({ candidates: [{ candidate_id: 'uploaded_one', expression: 'rolling_zscore(pct_change(close, 5), 20)' }] })) })
    const input = container.querySelector('input[type="file"]') as HTMLInputElement
    fireEvent.change(input, { target: { files: [file] } })
    expect(await screen.findByText('1 个上传候选')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '启动自动研究' }))

    await waitFor(() => expect(start).toHaveBeenCalledWith(expect.objectContaining({
      candidate_mode: 'manual', use_ai: false, ai_candidate_count: 0,
      manual_candidates: expect.arrayContaining([
        expect.objectContaining({ candidate_id: 'manual_alpha_input', expression: expect.stringContaining('rolling_zscore') }),
        expect.objectContaining({ candidate_id: 'uploaded_one' }),
      ]),
    })))
  })

  it('keeps preregistered hypotheses separate from admitted post-study evidence', async () => {
    const definitions = vi.spyOn(api, 'factorDefinitions')
    vi.spyOn(api, 'factorFactoryRuns').mockResolvedValue({ ok: true, count: 0, runs: [], live_trading_enabled: false })
    vi.spyOn(api, 'factorFactoryArchive').mockResolvedValue({
      ok: true, count: 1, total: 1, research_record_count: 4, ineligible_count: 3, verified_count: 1, eligible_only: true, live_trading_enabled: false,
      archives: [{
        archive_id: 'definition-archive-1', verified: true, eligible_for_archive: true, live_trading_enabled: false,
        archive_gate: { eligible: true, required_observation_days: 7, observed_seconds: 604800, observed_days: 7, qualifying_run_id: 'run-1', checks: { minimum_seven_real_days: true, simulation_gate_passed: true, trading_validated_lifecycle: true, qualifying_run_recorded: true }, violations: [] },
        definition: {
          id: 'definition-archive-1', key: 'ff_reversal_10', factor_key: 'ff_reversal_10', label: '短期反转 10', market: 'crypto',
          input_fields: ['close'], ast: { op: 'neg', value: { op: 'pct_change' } }, direction: 'positive', horizon: 5,
          availability_lag: 1, rationale: '短期冲击后存在均值回复。', family: 'short_term_reversal', version: '1.0.0',
          parameters: { invalidation_condition: '锁定确认收益转负', interval: '4h' }, formula_hash: 'a'.repeat(64),
          definition_hash: 'b'.repeat(64), validation: { unit: 'dimensionless', shape: 'series', fields: ['close'], depth: 3, operators: 2 }, created_at: 1,
        },
        lifecycle: { current_state: 'trading_validated', current_event: null, events: [] },
        scope: { market: 'crypto', symbol: 'BTC-USDT-SWAP', interval: '4h', horizon: 5, data_source: 'okx_live' },
        preregistration: {
          definition_hypothesis: '短期冲击后存在均值回复。', invalidation_condition: '锁定确认收益转负',
          experiments: [{
            experiment_id: 'experiment-1', research_plan_id: 'plan-1', attempt_number: 1,
            hypothesis: '价格冲击在十根 K 线内均值回复。', source: 'template', data_window: { start: '2026-01-01', end: '2026-07-01' },
            parameter_grid: {}, parameter_combinations: 1, estimated_compute_units: 480,
            proposal: { applicable_regimes: ['range'], invalidation_conditions: ['确认集收益为负'], falsification_tests: [], ai_trace: {} },
            pre_registration: { primary_metric: 'total_return', secondary_metrics: ['sharpe'], pass_criteria: { minimum_return: 0 }, maximum_candidates: 30, maximum_llm_tokens: 0, confirmation_set_openings: 1 },
            provenance: {}, created_at: 2,
          }],
        },
        post_study_evidence: {
          decision: { state: 'trading_validated', rule: 'target_market_trading_gate', evidence: {}, created_at: 3 }, experiments: [],
          runs: [], latest_run: {
            run_id: 'run-1', research_plan_id: 'plan-1', status: 'trading_validated', started_at: 3, updated_at: 4,
            observation_started_at: null, observation_ends_at: null, scope: { source: 'okx_live', symbol: 'BTC-USDT-SWAP', interval: '4h', paper_target: 'okx_demo' },
            candidate: { id: 'candidate-1', run_id: 'run-1', factor_key: 'ff_reversal_10', factor_version: '1.0.0', source: 'template', experiment_id: 'experiment-1', status: 'research_passed', rank: 1, metrics: { rolling_validation: { summary: { total_return: 0.057 } }, locked_confirmation: { summary: { total_return: 0.018, raw_p_value: 0.05 } } }, gate: {}, created_at: 3, updated_at: 4 },
            data_provenance: { fingerprint: 'c'.repeat(64) }, data_split: {}, confirmation_gate: {}, research_metrics: {}, simulation_validation: {}, paper_evidence: {},
            observation_summary: { count: 0, first_id: null, latest_id: null, observed_from: null, observed_to: null, latest_equity: null, after_cost_return: null, maximum_drawdown: 0, minimum_fill_rate: null }, simulation_orders: [],
          },
        },
        remaining_risks: [],
        evidence_chain: { definition_id: 'definition-archive-1', definition_hash: 'b'.repeat(64), formula_hash: 'a'.repeat(64), lifecycle_event_ids: [], experiment_ids: ['experiment-1'], experiment_event_ids: [], run_ids: ['run-1'], data_snapshot_hashes: ['c'.repeat(64)], simulation_order_ids: [] },
      }],
    } as never)

    render(<FactorFactoryWorkflow />)

    fireEvent.click(screen.getByRole('button', { name: '查看档案' }))
    expect(await screen.findByText('价格冲击在十根 K 线内均值回复。')).toBeTruthy()
    expect(screen.getByText('确认集收益为负')).toBeTruthy()
    expect(screen.getByText('1.80%')).toBeTruthy()
    expect(screen.getByText('7.00')).toBeTruthy()
    expect(screen.getByText('已通过当前预注册门禁')).toBeTruthy()
    expect(definitions).not.toHaveBeenCalled()
  })

  it('finds NVDA by its Chinese name, keeps OKX Demo, and clamps observation to seven days', async () => {
    vi.spyOn(api, 'factorFactoryArchive').mockResolvedValue({ ok: true, count: 0, total: 0, research_record_count: 0, ineligible_count: 0, verified_count: 0, eligible_only: true, archives: [], live_trading_enabled: false })
    vi.spyOn(api, 'factorFactoryRuns').mockResolvedValue({ ok: true, count: 0, runs: [], live_trading_enabled: false })
    const start = vi.spyOn(api, 'startFactorFactory').mockResolvedValue({
      ok: true,
      run: {
        id: 'nvda-run', research_plan_id: 'nvda-plan', status: 'no_qualified_factor', config: {}, result: { message: 'done' },
        selected_factor_key: null, selected_factor_version: null, selected_experiment_id: null, error: null,
        started_at: 1, updated_at: 1, observation_started_at: null, observation_ends_at: null,
      },
      candidates: [], observations: [], simulation_orders: [], observation_summary: { count: 0, latest_equity: null, after_cost_return: null, max_drawdown: 0 }, live_trading_enabled: false,
    })
    const { container } = render(<FactorFactoryWorkflow />)
    const instrumentInput = screen.getByPlaceholderText('代码或名称，如 AVGO / 博通')
    fireEvent.change(instrumentInput, { target: { value: '英伟达' } })
    fireEvent.click(await screen.findByRole('option', { name: /英伟达.*NVDA-USDT-SWAP/ }))
    expect((instrumentInput as HTMLInputElement).value).toBe('NVDA-USDT-SWAP')
    const dayInput = [...container.querySelectorAll('input[type="number"]')].find((input) => input.getAttribute('min') === '7' && input.getAttribute('max') === '365')
    expect(dayInput).toBeTruthy()
    fireEvent.change(dayInput!, { target: { value: '1' } })
    fireEvent.click(screen.getByRole('button', { name: '启动自动研究' }))

    await waitFor(() => expect(start).toHaveBeenCalledWith(expect.objectContaining({
      source: 'okx_live', symbol: 'NVDA-USDT-SWAP', paper_target: 'okx_demo', observation_days: 7,
    })))
  })

  it('finds Broadcom by Chinese name and accepts the AVGO base code directly', async () => {
    vi.spyOn(api, 'factorFactoryArchive').mockResolvedValue({ ok: true, count: 0, total: 0, research_record_count: 0, ineligible_count: 0, verified_count: 0, eligible_only: true, archives: [], live_trading_enabled: false })
    vi.spyOn(api, 'factorFactoryRuns').mockResolvedValue({ ok: true, count: 0, runs: [], live_trading_enabled: false })
    const start = vi.spyOn(api, 'startFactorFactory').mockResolvedValue({
      ok: true,
      run: {
        id: 'avgo-run', research_plan_id: 'avgo-plan', status: 'no_qualified_factor', config: {}, result: { message: 'done' },
        selected_factor_key: null, selected_factor_version: null, selected_experiment_id: null, error: null,
        started_at: 1, updated_at: 1, observation_started_at: null, observation_ends_at: null,
      },
      candidates: [], observations: [], simulation_orders: [], observation_summary: { count: 0, latest_equity: null, after_cost_return: null, max_drawdown: 0 }, live_trading_enabled: false,
    })

    render(<FactorFactoryWorkflow />)
    const instrumentInput = screen.getByPlaceholderText('代码或名称，如 AVGO / 博通')
    fireEvent.change(instrumentInput, { target: { value: '博通' } })
    fireEvent.click(await screen.findByRole('option', { name: /博通.*AVGO-USDT-SWAP/ }))
    expect((instrumentInput as HTMLInputElement).value).toBe('AVGO-USDT-SWAP')

    fireEvent.change(instrumentInput, { target: { value: 'AVGO' } })
    const startButton = screen.getByRole('button', { name: '启动自动研究' }) as HTMLButtonElement
    await waitFor(() => expect(startButton.disabled).toBe(false))
    fireEvent.click(startButton)

    await waitFor(() => expect(start).toHaveBeenCalledWith(expect.objectContaining({
      symbol: 'AVGO-USDT-SWAP', source: 'okx_live', paper_target: 'okx_demo',
    })))
  })

  it('browses the verified OKX directory and opens the shared live kline', async () => {
    vi.spyOn(api, 'factorFactoryArchive').mockResolvedValue({ ok: true, count: 0, total: 0, research_record_count: 0, ineligible_count: 0, verified_count: 0, eligible_only: true, archives: [], live_trading_enabled: false })
    vi.spyOn(api, 'factorFactoryRuns').mockResolvedValue({ ok: true, count: 0, runs: [], live_trading_enabled: false })

    render(<FactorFactoryWorkflow />)
    fireEvent.click(screen.getByRole('button', { name: '合约目录' }))
    expect(await screen.findByRole('region', { name: 'OKX 永续合约目录' })).toBeTruthy()
    const directorySearch = screen.getByPlaceholderText('搜索代码或名称，如 BTC、黄金、石油、博通')
    fireEvent.change(directorySearch, { target: { value: '博通' } })
    fireEvent.click(await screen.findByRole('button', { name: /博通.*AVGO-USDT-SWAP.*面值/ }))

    expect(screen.getByRole('region', { name: 'OKX 实时公共 K 线' })).toBeTruthy()
    await waitFor(() => expect(api.kline).toHaveBeenCalledWith('AVGO-USDT-SWAP', 'crypto', '4h', 240))
    expect((screen.getByPlaceholderText('代码或名称，如 AVGO / 博通') as HTMLInputElement).value).toBe('AVGO-USDT-SWAP')
  })

  it('sanitizes OKX catalogue timeouts and keeps dependent actions disabled', async () => {
    vi.mocked(api.okxSwapCatalog).mockResolvedValue({
      ok: false,
      source: 'unavailable',
      query: 'BTC-USDT-SWAP',
      count: 0,
      total: 0,
      cache_age_seconds: null,
      cache_ttl_seconds: 900,
      fetched_at: null,
      error: "ConnectTimeout: HTTPSConnectionPool(host='www.okx.com', port=443): timed out",
      instruments: [],
    })

    render(<FactorFactoryWorkflow />)
    fireEvent.click(screen.getByRole('button', { name: '合约目录' }))

    expect(await screen.findByText('OKX 公共合约目录连接超时，公共目录暂时不可用，请稍后重试。')).toBeTruthy()
    expect(screen.queryByText(/HTTPSConnectionPool|www\.okx\.com/)).toBeNull()
    expect(screen.getByRole('button', { name: '刷新 OKX 合约目录' })).toBeTruthy()
    await waitFor(() => expect((screen.getByRole('button', { name: '启动自动研究' }) as HTMLButtonElement).disabled).toBe(true))
    expect((screen.getByRole('button', { name: '实时 K 线' }) as HTMLButtonElement).disabled).toBe(true)
  })
})
