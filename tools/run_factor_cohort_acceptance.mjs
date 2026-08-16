#!/usr/bin/env node

import fs from 'node:fs/promises'
import path from 'node:path'
import process from 'node:process'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/(.:)/, '$1')), '..')
let playwright
try {
  playwright = require('playwright')
} catch (error) {
  const bundledCore = path.join(
    repoRoot,
    '.venv',
    'Lib',
    'site-packages',
    'playwright',
    'driver',
    'package',
  )
  try {
    playwright = require(bundledCore)
  } catch {
    throw error
  }
}
const { chromium } = playwright

const baseUrl = process.env.QH_ACCEPTANCE_BASE_URL || 'http://127.0.0.1:5173'
const apiBase = process.env.QH_ACCEPTANCE_API_BASE || 'http://127.0.0.1:8001'
const apiPathPrefix = new URL(apiBase).pathname.replace(/\/$/, '')
const outputRoot = path.resolve(
  repoRoot,
  process.env.QH_ACCEPTANCE_OUTPUT || 'docs/Plan/evidence/factor-cohort-v1-2026-08-12',
)
const viewports = [
  { id: 'mobile-390x844', width: 390, height: 844 },
  { id: 'tablet-768x1024', width: 768, height: 1024 },
  { id: 'laptop-1280x720', width: 1280, height: 720 },
  { id: 'desktop-1440x900', width: 1440, height: 900 },
]

function metrics(afterCostReturn, sharpe, maxDrawdown, finalEquity, utilization, trades, fees) {
  return {
    absolute_return: afterCostReturn,
    after_cost_return: afterCostReturn,
    max_drawdown: maxDrawdown,
    sharpe,
    sortino: sharpe * 1.15,
    calmar: maxDrawdown ? afterCostReturn / maxDrawdown : 0,
    cvar: -0.012,
    turnover: trades * 0.18,
    fill_rate: 1,
    capital_utilization: utilization,
    trade_count: trades,
    fees,
    slippage_cost: trades * 0.75,
    funding_pnl: -trades * 0.12,
    final_equity: finalEquity,
  }
}

function ledger(memberKey, trades) {
  return {
    ledger_id: `fixture:${memberKey}`,
    member_key: memberKey,
    initial_cash: 100000,
    cash: 98000,
    position: { quantity: 20, average_price: 100, realized_pnl: 0 },
    orders: Array.from({ length: trades }, (_, index) => ({ order_id: `${memberKey}:o:${index}` })),
    executions: Array.from({ length: trades }, (_, index) => ({ execution_id: `${memberKey}:e:${index}` })),
    cash_flows: [],
    risk_events: [],
    equity_curve: [
      { t: '2026-08-12T10:00:00+00:00', equity: 100000 },
      { t: '2026-08-12T11:00:00+00:00', equity: 100000 + trades * 80 },
      { t: '2026-08-12T12:00:00+00:00', equity: 100000 + trades * 160 },
    ],
    processed_keys: [],
    turnover_notional: trades * 18000,
    peak_equity: 102500,
  }
}

const ranking = [
  { member_key: 'candidate:momentum-quality:v1', metrics: metrics(0.025, 1.32, 0.041, 102500, 0.48, 9, 38) },
  { member_key: 'grid_arithmetic', metrics: metrics(0.012, 0.67, 0.06, 101200, 0.57, 14, 62) },
  { member_key: 'ma_trend', metrics: metrics(0.019, 1.05, 0.052, 101900, 0.43, 7, 31) },
  { member_key: 'buy_hold', metrics: metrics(0.031, 0.94, 0.086, 103100, 0.99, 1, 6) },
  { member_key: 'fixed_exposure', metrics: metrics(0.014, 0.88, 0.044, 101400, 0.5, 5, 19) },
  { member_key: 'dca', metrics: metrics(0.011, 0.72, 0.035, 101100, 0.36, 6, 17) },
  { member_key: 'cash', metrics: metrics(0, 0, 0, 100000, 0, 0, 0) },
  { member_key: 'grid_adaptive', metrics: metrics(0.009, 0.58, 0.055, 100900, 0.51, 12, 54) },
  ...Array.from({ length: 20 }, (_, seed) => ({
    member_key: `random_${String(seed).padStart(2, '0')}`,
    metrics: metrics(-0.01 + seed * 0.0012, -0.3 + seed * 0.06, 0.07, 99000 + seed * 120, 0.42, 8, 32),
  })),
]

const ledgers = Object.fromEntries(ranking.map((item) => [item.member_key, ledger(item.member_key, item.metrics.trade_count)]))
const run = {
  ok: true,
  run: {
    id: 'fixture-factor-cohort-20260812',
    research_plan_id: 'fixture-research-plan-20260812',
    status: 'paper_observing',
    config: {
      market: 'crypto', source: 'okx_live', symbol: 'BTC-USDT-SWAP', interval: '1h',
      candidate_mode: 'brain', candidate_generation: { source_counts: { ai: 2, random_dsl: 2, symbolic_regression: 2 } },
      data_provenance: { bars: 240, requested_bars: 240 }, paper_target: 'okx_demo', live_trading_enabled: false,
    },
    result: {},
    selected_factor_key: 'candidate:momentum-quality:v1',
    selected_factor_version: '1.0.0',
    selected_experiment_id: 'fixture-experiment',
    error: null,
    started_at: 1786536000,
    updated_at: 1786536000,
    observation_started_at: 1786536000,
    observation_ends_at: 1787140800,
  },
  candidates: [{
    id: 'fixture-candidate', run_id: 'fixture-factor-cohort-20260812',
    factor_key: 'candidate:momentum-quality:v1', factor_version: '1.0.0', source: 'ai',
    experiment_id: 'fixture-experiment', status: 'research_passed', rank: 1,
    metrics: { rolling_validation: { summary: { total_return: 0.024, metrics: { sharpe: 1.28 } } } },
    gate: { passed: true }, created_at: 1786536000, updated_at: 1786536000,
    definition: { key: 'candidate:momentum-quality:v1', version: '1.0.0', label: '动量质量候选', family: 'momentum', ast: { op: 'field', name: 'close' }, input_fields: ['close', 'volume'], horizon: 5, formula_hash: 'fixture-formula-hash' },
  }],
  observations: [],
  simulation_orders: [],
  observation_summary: { count: 0, latest_equity: 100000, after_cost_return: 0, max_drawdown: 0 },
  market_data_status: {
    event_time: '2026-08-12T11:59:58+00:00',
    bar_open_time: '2026-08-12T11:00:00+00:00',
    bar_close_time: '2026-08-12T11:59:58+00:00',
    fetched_at: '2026-08-12T12:00:00+00:00',
    received_at: '2026-08-12T12:00:00+00:00',
    is_closed: true,
    age_ms: 2000,
    source: 'deterministic_ui_fixture',
    quality_status: 'fresh',
    event_kind: 'closed_bar_live',
    forming_bars_excluded: 1,
    research_signal_allowed: true,
    market_open: true,
  },
  cohort: {
    definition: { cohort_id: 'factor-cohort-v1-acceptance-20260812', benchmark_pool_version: 'factor-cohort-v2' },
    status: 'cohort_observing',
    engine_version: '1.1.0',
    start_market_time: '2026-08-12T12:00:00+00:00',
    latest_report: {
      ranking,
      ledgers,
      comparison: {
        candidate_key: 'candidate:momentum-quality:v1', candidate_rank: 1, random_percentile: 0.95,
        excess_vs_cash: 0.025, excess_vs_buy_hold: -0.006, excess_vs_best_simple: -0.006,
        excess_vs_grid_median: 0.013, market_tailwind: false,
      },
      fairness: { shared_market_event_count: 240, identical_event_order: true, independent_ledgers: true, same_execution_policy: true },
      benchmark_pool: { version: 'factor-cohort-v2' },
      grid_risk: {
        grid_arithmetic: {
          mode: 'arithmetic', levels: 8,
          range: { lower: 90, center: 100, upper: 110 },
          inventory_quantity: 2, inventory_notional: 200, inventory_risk: 0.02,
          capital_utilization: 0.57, trade_count: 14, fee_share_of_initial_capital: 0.00062,
          outside_range: true, outside_range_loss: 12, idle_cash_ratio: 0.43,
          preregistered: true, exit_rule: 'return_to_center_or_cohort_end',
        },
      },
    },
    program_gate: {
      passed: false,
      checks: {
        minimum_observation_days: false, minimum_rebalances: false, positive_after_cost_return: true,
        risk_adjusted_excess: false, random_distribution: true, not_leverage_driven: true,
        drawdown_within_limit: true, fill_and_capacity: true, risk_limits: false,
        replay_reconciled: true, regime_stability: false,
        freshness: true, reconciliation: false, kill_switch: false,
      },
      violations: ['minimum_observation_days', 'minimum_rebalances', 'risk_adjusted_excess', 'risk_limits', 'regime_stability', 'reconciliation', 'kill_switch'],
      allowed_transition: null,
      manual_approval_required: true,
      live_trading_enabled: false,
    },
    ai_review: {
      effective_recommendation: 'continue_observation',
      review: { remaining_risks: ['真实七日观察尚未完成', '联网重连演练尚未完成'] },
    },
    live_request: null,
    manual_approval: { approval_id: 'fixture-invalidated-approval' },
    manual_approval_validity: { valid: false, reasons: ['program_gate_changed', 'risk_configuration_changed'] },
    live_trading_enabled: false,
  },
  live_trading_enabled: false,
}

async function inspect(page) {
  return page.evaluate(() => {
    const root = document.querySelector('section[aria-label="同期评估"]')
    if (!root) return { present: false }
    const rootRect = root.getBoundingClientRect()
    const clippedText = [...root.querySelectorAll('h4,p,small,strong,b,span,button,dt,dd')]
      .filter((element) => {
        const style = getComputedStyle(element)
        const rect = element.getBoundingClientRect()
        if (rect.width < 1 || rect.height < 1 || style.visibility === 'hidden') return false
        if (style.textOverflow === 'ellipsis' || style.overflowWrap === 'anywhere') return false
        let ancestor = element.parentElement
        while (ancestor && ancestor !== root) {
          const ancestorStyle = getComputedStyle(ancestor)
          if (ancestorStyle.overflowX === 'auto' || ancestorStyle.overflowX === 'scroll') return false
          ancestor = ancestor.parentElement
        }
        return element.scrollWidth > element.clientWidth + 2
      })
      .slice(0, 20)
      .map((element) => ({
        tag: element.tagName.toLowerCase(),
        text: (element.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 100),
        clientWidth: element.clientWidth,
        scrollWidth: element.scrollWidth,
      }))
    const overflowingElements = [...root.querySelectorAll('*')]
      .filter((element) => {
        const style = getComputedStyle(element)
        const rect = element.getBoundingClientRect()
        if (rect.width < 1 || rect.height < 1 || style.visibility === 'hidden') return false
        return rect.right > rootRect.right + 2 || rect.left < rootRect.left - 2
      })
      .slice(0, 20)
      .map((element) => ({
        tag: element.tagName.toLowerCase(),
        text: (element.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 80),
        left: Math.round(element.getBoundingClientRect().left),
        right: Math.round(element.getBoundingClientRect().right),
      }))
    const submit = [...root.querySelectorAll('button')].find((button) => button.textContent?.includes('提交人工审批'))
    const text = root.textContent || ''
    return {
      present: true,
      documentOverflow: Math.max(
        document.documentElement.scrollWidth - document.documentElement.clientWidth,
        document.body.scrollWidth - document.body.clientWidth,
      ),
      panelOverflow: root.scrollWidth - root.clientWidth,
      clippedText,
      overflowingElements,
      hasFreshness: text.includes('接收延迟') && text.includes('已收盘') && text.includes('deterministic_ui_fixture'),
      hasBenchmarks: text.includes('关键基准') && text.includes('相对买入持有') && text.includes('buy_hold'),
      hasRandomPercentile: text.includes('随机分位') && text.includes('95.00%'),
      hasMarketState: text.includes('无普遍顺风'),
      hasIndependentLedger: text.includes('独立账本') && text.includes('订单'),
      hasProgramGate: text.includes('小额实盘准入') && text.includes('继续观察'),
      hasAiRecommendation: text.includes('AI 建议：continue_observation'),
      hasFailedGateEvidence: text.includes('失败门禁') && text.includes('风险上限') && text.includes('状态稳定性'),
      hasRemainingRisks: text.includes('真实七日观察尚未完成') && text.includes('联网重连演练尚未完成'),
      hasApprovalInvalidation: text.includes('已失效：program_gate_changed、risk_configuration_changed'),
      rankingTabSelected: root.querySelector('button[role="tab"][aria-selected="true"]')?.textContent?.includes('关键基准') || false,
      detailTabSelected: root.querySelector('button[role="tab"][aria-selected="true"]')?.textContent?.includes('账本详情') || false,
      hasEquityOverlay: Boolean(root.querySelector('svg[aria-label="候选、买入持有与当前账本权益曲线"] path[d]')),
      hasGridRisk: text.includes('网格预注册风险') && text.includes('90.00 – 110.00') && text.includes('区间外损失'),
      hasCostAttribution: text.includes('手续费') && text.includes('滑点成本') && text.includes('资金费率'),
      liveSubmissionDisabled: submit instanceof HTMLButtonElement && submit.disabled,
      activeLedger: root.querySelector('button[aria-pressed="true"]')?.textContent?.trim().replace(/\s+/g, ' ')
        || [...root.querySelectorAll('section > header > strong')]
          .map((element) => element.textContent?.trim())
          .find((value) => value === 'grid_arithmetic')
        || null,
    }
  })
}

await fs.mkdir(outputRoot, { recursive: true })
const browser = await chromium.launch({ headless: true })
const results = []

try {
  for (const viewport of viewports) {
    const context = await browser.newContext({ viewport })
    await context.addInitScript(({ apiBase: value }) => {
      localStorage.setItem('quanthub:api-base', value)
      localStorage.setItem('quanthub:api-token', 'local-dev-token')
      localStorage.setItem('quanthub.interface-mode', 'advanced')
    }, { apiBase })
    await context.route('**/factor-factory/**', async (route) => {
      const requestUrl = new URL(route.request().url())
      const requestPath = apiPathPrefix && requestUrl.pathname.startsWith(`${apiPathPrefix}/`)
        ? requestUrl.pathname.slice(apiPathPrefix.length)
        : requestUrl.pathname
      if (requestPath === '/factor-factory/runs') {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, count: 1, runs: [run.run], live_trading_enabled: false }) })
        return
      }
      if (requestPath === '/factor-factory/runs/fixture-factor-cohort-20260812') {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(run) })
        return
      }
      await route.continue()
    })
    const page = await context.newPage()
    const consoleErrors = []
    const failedRequests = []
    const factorRequests = []
    page.on('console', (message) => {
      if (message.type() === 'error') consoleErrors.push(message.text())
    })
    page.on('requestfailed', (request) => failedRequests.push({ url: request.url(), error: request.failure()?.errorText || 'unknown' }))
    page.on('request', (request) => {
      if (request.url().includes('/factor-factory/')) factorRequests.push(request.url())
    })
    await page.goto(`${baseUrl}/factor-research`, { waitUntil: 'domcontentloaded' })
    const factory = page.locator('section[aria-label="自动因子研究与模拟观察"]')
    await factory.waitFor({ state: 'visible', timeout: 20_000 })
    const cohortTab = factory.getByText('同期评估', { exact: true }).last()
    try {
      await cohortTab.waitFor({ state: 'visible', timeout: 20_000 })
    } catch (error) {
      const debug = {
        viewport,
        consoleErrors,
        failedRequests,
        factorRequests,
        factoryText: (await factory.textContent())?.slice(0, 3000),
      }
      await fs.writeFile(path.join(outputRoot, `${viewport.id}-debug.json`), `${JSON.stringify(debug, null, 2)}\n`, 'utf8')
      await page.screenshot({ path: path.join(outputRoot, `${viewport.id}-debug.png`), fullPage: true })
      throw error
    }
    await cohortTab.click()
    const panel = factory.locator('section[aria-label="同期评估"]')
    await panel.waitFor({ state: 'visible', timeout: 20_000 })
    await page.waitForTimeout(300)
    const beforeLedgerSwitch = await inspect(page)
    await panel.getByRole('button', { name: /grid_arithmetic/ }).click()
    await page.waitForTimeout(100)
    const afterLedgerSwitch = await inspect(page)
    await panel.evaluate((element) => element.scrollIntoView({ block: 'start' }))
    await page.waitForTimeout(100)
    await page.screenshot({ path: path.join(outputRoot, `${viewport.id}-page.png`), fullPage: true })
    if (viewport.width <= 768) {
      await page.screenshot({ path: path.join(outputRoot, `${viewport.id}-cohort.png`) })
      const admission = panel.locator('section').filter({ hasText: '小额实盘准入' }).last()
      await admission.evaluate((element) => element.scrollIntoView({ block: 'start' }))
      await page.waitForTimeout(100)
      await page.screenshot({ path: path.join(outputRoot, `${viewport.id}-cohort-admission.png`) })
    } else {
      await panel.screenshot({ path: path.join(outputRoot, `${viewport.id}-cohort.png`) })
    }
    results.push({
      viewport,
      interactionCountToCohort: 1,
      interactionCountToLedgerDetail: 2,
      beforeLedgerSwitch,
      afterLedgerSwitch,
      consoleErrors,
      failedRequests,
    })
    await Promise.all([
      fs.rm(path.join(outputRoot, `${viewport.id}-debug.json`), { force: true }),
      fs.rm(path.join(outputRoot, `${viewport.id}-debug.png`), { force: true }),
    ])
    await context.close()
  }
} finally {
  await browser.close()
}

const passed = results.every(({ beforeLedgerSwitch, afterLedgerSwitch, consoleErrors, failedRequests }) => (
  beforeLedgerSwitch.present
  && beforeLedgerSwitch.documentOverflow === 0
  && beforeLedgerSwitch.panelOverflow === 0
  && beforeLedgerSwitch.clippedText.length === 0
  && beforeLedgerSwitch.overflowingElements.length === 0
  && beforeLedgerSwitch.hasFreshness
  && beforeLedgerSwitch.hasBenchmarks
  && beforeLedgerSwitch.hasRandomPercentile
  && beforeLedgerSwitch.hasMarketState
  && beforeLedgerSwitch.hasIndependentLedger
  && beforeLedgerSwitch.hasProgramGate
  && beforeLedgerSwitch.hasAiRecommendation
  && beforeLedgerSwitch.hasFailedGateEvidence
  && beforeLedgerSwitch.hasRemainingRisks
  && beforeLedgerSwitch.hasApprovalInvalidation
  && beforeLedgerSwitch.rankingTabSelected
  && beforeLedgerSwitch.liveSubmissionDisabled
  && afterLedgerSwitch.activeLedger?.includes('grid_arithmetic')
  && afterLedgerSwitch.detailTabSelected
  && afterLedgerSwitch.hasEquityOverlay
  && afterLedgerSwitch.hasGridRisk
  && afterLedgerSwitch.hasCostAttribution
  && consoleErrors.length === 0
  && failedRequests.length === 0
))

const report = {
  generated_at: new Date().toISOString(),
  evidence_kind: 'deterministic_ui_fixture',
  base_url: baseUrl,
  api_base: apiBase,
  route: '/factor-research',
  browser: 'chromium',
  passed,
  contract: {
    viewports,
    maximum_interactions_to_cohort: 3,
    fixture_scope: 'factor-factory read endpoints only',
    real_page_code: true,
    real_css_and_interactions: true,
    real_market_observation_claimed: false,
  },
  results,
}
await fs.writeFile(path.join(outputRoot, 'web-acceptance-report.json'), `${JSON.stringify(report, null, 2)}\n`, 'utf8')
const manifestPath = path.join(outputRoot, 'manifest.json')
try {
  const manifest = JSON.parse(await fs.readFile(manifestPath, 'utf8'))
  const existingJson = await fs.readdir(outputRoot)
  manifest.files = existingJson
    .filter((name) => name.endsWith('.json') && name !== 'manifest.json' && !name.includes('-debug'))
    .sort()
  manifest.browser_acceptance = {
    status: passed ? 'passed' : 'failed',
    evidence_kind: 'deterministic_ui_fixture',
    browser: 'chromium',
    viewports,
    real_market_observation_claimed: false,
  }
  await fs.writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, 'utf8')
} catch {
  // The acceptance report remains authoritative when no generator manifest exists.
}
process.stdout.write(`${JSON.stringify(report, null, 2)}\n`)
if (!passed) process.exitCode = 1
