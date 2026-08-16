#!/usr/bin/env node

import fs from 'node:fs/promises'
import path from 'node:path'
import process from 'node:process'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const { chromium } = require('playwright')

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/(.:)/, '$1')), '..')
const baseUrl = process.env.QH_ACCEPTANCE_BASE_URL || 'http://127.0.0.1:5173'
const apiBase = process.env.QH_ACCEPTANCE_API_BASE || 'http://127.0.0.1:8001'
const outputRoot = path.resolve(
  repoRoot,
  process.env.QH_ACCEPTANCE_OUTPUT
    || 'docs/Plan/evidence/research-risk-execution-attribution-closure-2026-08-16',
)

const viewports = [
  { id: 'mobile-390x844', width: 390, height: 844 },
  { id: 'tablet-768x1024', width: 768, height: 1024 },
  { id: 'desktop-1440x900', width: 1440, height: 900 },
]

const now = 1786848000
const conflictedRun = {
  id: 'run-conflicted', symbol: 'NVDA', market: 'us_stocks', timeframe: '1d',
  status: 'succeeded', modules: ['market', 'pa', 'ensemble'], input: {},
  summary: {
    market: {
      latest_price: 180,
      latest_time: '2026-08-16T00:00:00Z',
      source: 'deterministic_acceptance_fixture',
      quantitative: { metrics: { return_20: 0.08, volatility_20: 0.24, max_drawdown: -0.07, rsi_14: 62 } },
    },
    research_decision: {
      direction: 'conflicted', execution_eligible: false,
      decision_version: 'research-decision-v1',
      module_opinions: [
        { module: 'price_structure', direction: 'long', confidence: 0.74, evidence_at: '2026-08-16T00:00:00Z', status: 'available', reason: '价格结构保持上行', evidence_id: 'price-1' },
        { module: 'model_consensus', direction: 'short', confidence: 0.71, evidence_at: '2026-08-16T00:00:00Z', status: 'available', reason: '模型共识转弱', evidence_id: 'model-1' },
      ],
      conflicts: [{ kind: 'opposite_direction', modules: ['price_structure', 'model_consensus'], reason: '有效模块同时包含做多与做空意见', blocking: true }],
      invalidation_conditions: ['等待价格结构与模型共识重新一致'],
      reevaluate_triggers: ['下一次日线收盘', '基本面证据更新'],
      decided_at: '2026-08-16T00:00:00Z', input_fingerprint: 'a'.repeat(64),
    },
    evidence_fusion: {},
  },
  error: null, note: '', favorite: false, tags: [], archived_at: null,
  created_at: now - 86400, updated_at: now, evidence_count: 3, evidence: [],
}

const previousRun = {
  ...conflictedRun,
  id: 'run-previous',
  summary: {
    ...conflictedRun.summary,
    research_decision: {
      ...conflictedRun.summary.research_decision,
      direction: 'long', execution_eligible: true, conflicts: [],
      module_opinions: conflictedRun.summary.research_decision.module_opinions.map((item) => ({
        ...item, direction: 'long', reason: '模块方向一致偏强',
      })),
    },
  },
  created_at: now - 7 * 86400,
  updated_at: now - 6 * 86400,
}

const comparison = {
  ok: true,
  same_context: true,
  contexts: [
    { symbol: 'NVDA', market: 'us_stocks', timeframe: '1d' },
    { symbol: 'NVDA', market: 'us_stocks', timeframe: '1d' },
  ],
  modules: ['market', 'pa', 'ensemble'],
  summary_keys: ['research_decision'],
  rows: [conflictedRun, previousRun].map((run) => ({
    id: run.id, status: run.status, updated_at: run.updated_at, modules: run.modules,
    module_presence: { market: true, pa: true, ensemble: true }, summary: run.summary,
    evidence_count: run.evidence_count, evidence_kind_counts: { research_decision: 1 },
    snapshot_sha256: ['b'.repeat(64)],
  })),
  structured_snapshots: [
    {
      direction: 'conflicted', execution_eligible: false,
      conflicts: conflictedRun.summary.research_decision.conflicts,
      decision_version: 'research-decision-v1',
      module_opinions: conflictedRun.summary.research_decision.module_opinions,
      metrics: { latest_price: 180, return_20: 0.08, volatility_20: 0.24, max_drawdown: -0.07, rsi_14: 62 },
      levels: { entry: null, invalidation: null, target: null }, news_themes: [],
      invalidation_conditions: ['等待价格结构与模型共识重新一致'],
      reevaluate_triggers: ['下一次日线收盘'],
    },
    {
      direction: 'long', execution_eligible: true, conflicts: [],
      decision_version: 'research-decision-v1', module_opinions: [],
      metrics: { latest_price: 172, return_20: 0.03, volatility_20: 0.2, max_drawdown: -0.05, rsi_14: 55 },
      levels: { entry: 172, invalidation: 165, target: 188 }, news_themes: [],
      invalidation_conditions: ['跌破 165'], reevaluate_triggers: ['下一次日线收盘'],
    },
  ],
  changes: [
    { kind: 'decision', field: 'direction', before: 'long', after: 'conflicted' },
    { kind: 'decision', field: 'execution_eligible', before: true, after: false },
    { kind: 'metric', field: 'latest_price', before: 172, after: 180, delta: 8 },
    { kind: 'metric', field: 'rsi_14', before: 55, after: 62, delta: 7 },
    { kind: 'level', field: 'target', before: 188, after: null },
  ],
}

function performanceGroup(key, netPnl, version) {
  return {
    key, trade_count: 2, wins: 1, win_rate_pct: 50, gross_pnl: netPnl + 12,
    fees: 12, net_pnl: netPnl, fee_drag_pct: 10,
    average_holding_seconds: 86400, max_drawdown: -18,
    links: [{ research_run_id: `research-${version}`, signal_id: `signal-${version}`, simulation_order_id: `order-${version}`, execution_id: `execution-${version}` }],
  }
}

const attribution = {
  ok: true, start_at: null, end_at: null, period: 'month', by_instrument: [],
  by_strategy: [],
  by_direction: [{ key: 'long', trade_count: 3, notional: 68000, fees: 24, cash_flow: -68024 }],
  by_period: [{ key: '2026-08', trade_count: 3, notional: 68000, fees: 24, cash_flow: -68024 }],
  by_factor: [performanceGroup('quality_momentum', 72, 'factor')],
  by_factor_version: [
    performanceGroup('quality_momentum@1.0.0', 42, 'v1'),
    performanceGroup('quality_momentum@2.0.0', 30, 'v2'),
  ],
  by_research_run: [performanceGroup('research-run-20260816', 72, 'research')],
  by_strategy_performance: [performanceGroup('swing-quality@3.1.0', 72, 'strategy')],
  by_signal: [performanceGroup('signal-accepted-001', 72, 'signal')],
  by_market_regime: [performanceGroup('regime-trend-up', 72, 'regime')],
  unknown_attribution: [performanceGroup('unknown', -5, 'unknown')],
  conservation: {
    closed_trade_net_pnl: 72, factor_group_net_pnl: 72, balanced: true,
    matching: { open_lot_count: 0, open_quantity: 0 },
  },
}

function json(route, payload) {
  return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(payload) })
}

async function installShellRoutes(context) {
  const apiOrigin = new URL(apiBase).origin
  const shellPaths = new Set(['/auth/session', '/strategies', '/signals', '/health', '/instruments'])
  await context.route(
    (url) => url.origin === apiOrigin && shellPaths.has(url.pathname),
    (route) => {
      const url = new URL(route.request().url())
      if (url.pathname === '/auth/session') {
        return json(route, {
          ok: true,
          user: {
            id: 'acceptance-user', username: 'acceptance', display_name: '验收用户',
            active: true, created_at: now, roles: ['researcher'], permissions: ['research:read'],
          },
        })
      }
      if (url.pathname === '/strategies') return json(route, { count: 0, strategies: [] })
      if (url.pathname === '/signals') {
        return json(route, { count: 0, total: 0, next_cursor: null, signals: [] })
      }
      if (url.pathname === '/instruments') return json(route, { count: 0, instruments: [] })
      return json(route, {
        status: 'ok', time: '2026-08-16T00:00:00Z', strategies: 0,
        live_trading: false, version: 'acceptance', deployment_mode: 'local',
        started_at: '2026-08-16T00:00:00Z', build_id: 'acceptance',
        current_source_build_id: 'acceptance', restart_required: false,
      })
    },
  )
}

async function settle(page) {
  await page.waitForLoadState('domcontentloaded')
  await page.locator('#root').waitFor({ state: 'attached', timeout: 15_000 })
  await page.waitForTimeout(500)
}

async function inspectLayout(page) {
  return page.evaluate(() => {
    const clippedText = [...document.querySelectorAll('h1,h2,h3,p,label,button,a,th,td,span,strong,small')]
      .filter((element) => {
        const rect = element.getBoundingClientRect()
        const style = getComputedStyle(element)
        if (rect.width < 1 || rect.height < 1 || style.visibility === 'hidden') return false
        if (style.textOverflow === 'ellipsis' || style.overflowWrap === 'anywhere') return false
        let parent = element.parentElement
        while (parent) {
          const parentStyle = getComputedStyle(parent)
          if (parentStyle.overflowX === 'auto' || parentStyle.overflowX === 'scroll') return false
          parent = parent.parentElement
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
    return {
      documentOverflow: Math.max(
        document.documentElement.scrollWidth - document.documentElement.clientWidth,
        document.body.scrollWidth - document.body.clientWidth,
      ),
      clippedText,
    }
  })
}

async function runScenario(browser, viewport, scenario) {
  const context = await browser.newContext({ viewport })
  await context.addInitScript(({ apiBase: value }) => {
    localStorage.setItem('quanthub:api-base', value)
    localStorage.setItem('quanthub:api-token', 'local-dev-token')
    localStorage.setItem('quanthub.interface-mode', 'advanced')
  }, { apiBase })
  await installShellRoutes(context)
  await scenario.installRoutes(context)
  const page = await context.newPage()
  const consoleErrors = []
  const failedRequests = []
  const failedResponses = []
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })
  page.on('requestfailed', (request) => {
    failedRequests.push({ url: request.url(), error: request.failure()?.errorText || 'unknown' })
  })
  page.on('response', (response) => {
    if (response.status() >= 400) failedResponses.push({ url: response.url(), status: response.status() })
  })
  await page.goto(`${baseUrl}${scenario.path}`, { waitUntil: 'domcontentloaded' })
  await settle(page)
  const assertions = await scenario.assert(page)
  const layout = await inspectLayout(page)
  await page.screenshot({
    path: path.join(outputRoot, `${viewport.id}-${scenario.id}.png`),
    fullPage: true,
  })
  await context.close()
  return {
    viewport,
    scenario: scenario.id,
    assertions,
    layout,
    consoleErrors,
    failedRequests,
    failedResponses,
    passed: Object.values(assertions).every(Boolean)
      && layout.documentOverflow === 0
      && layout.clippedText.length === 0
      && consoleErrors.length === 0
      && failedRequests.length === 0
      && failedResponses.length === 0,
  }
}

const scenarios = [
  {
    id: 'simulation-risk-blocked',
    path: '/simulation?symbol=AAPL&market=us_stocks',
    async installRoutes(context) {
      await context.route('**/simulation/**', async (route) => {
        const url = new URL(route.request().url())
        if (url.pathname === '/simulation/orders/preview') {
          return json(route, {
            ok: true,
            preview: {
              symbol: 'AAPL', market: 'us_stocks', side: 'buy', quantity: 100,
              price: null, order_notional: null, current_quantity: 0, projected_quantity: 100,
              gross_exposure_before: 0, gross_exposure_after: null,
              cash_before: 1000000, cash_after: null, equity: 1000000,
              risk_evaluated: true, can_submit: false, outcome: 'rejected',
              reason_codes: ['MARKET_PRICE_MISSING'],
              checks: [{ code: 'MARKET_PRICE_MISSING', status: 'failed', actual: null, limit: null, reevaluate_action: '刷新行情后重新预览' }],
              snapshot: { market: {}, account: {}, open_order_count: 0, cost_profile: {}, research_decision: null },
              evaluated_at: '2026-08-16T00:00:00Z', rule_version: 'simulation-risk-v1', input_fingerprint: 'c'.repeat(64),
            },
          })
        }
        if (url.pathname === '/simulation/account') {
          return json(route, {
            ok: true, mode: 'paper', starting_cash: 1000000, cash: 1000000,
            market_value: 0, equity: 1000000, total_fees: 0, realized_pnl: 0,
            unrealized_pnl: 0, positions: [], order_count: 0, execution_count: 0,
            reconciled: true, reconciliation_issues: [],
          })
        }
        if (url.pathname === '/simulation/orders' && route.request().method() === 'GET') {
          return json(route, { ok: true, count: 0, total: 0, next_cursor: null, orders: [] })
        }
        return route.continue()
      })
    },
    async assert(page) {
      await page.getByText('MARKET_PRICE_MISSING', { exact: true }).waitFor({ timeout: 15_000 })
      const create = page.getByRole('button', { name: '创建模拟订单' })
      return {
        blockedStateVisible: await page.getByText('服务端风控未通过', { exact: true }).isVisible(),
        machineReasonVisible: await page.getByText('MARKET_PRICE_MISSING', { exact: true }).isVisible(),
        reevaluateActionVisible: await page.getByText('刷新行情后重新预览', { exact: true }).isVisible(),
        createDisabled: await create.isDisabled(),
      }
    },
  },
  {
    id: 'research-conflict-history-diff',
    path: '/research/NVDA?market=us_stocks&tf=1d&view=history&run_id=run-conflicted',
    async installRoutes(context) {
      await context.route('**/research/**', async (route) => {
        const url = new URL(route.request().url())
        if (url.pathname === '/research/runs/run-conflicted/verify') {
          return json(route, { ok: true, run_id: 'run-conflicted', snapshot_count: 1, snapshots_valid: true, has_analysis_output: true, replay_ready: true, checks: [] })
        }
        if (url.pathname === '/research/runs/run-conflicted') return json(route, { ok: true, run: conflictedRun })
        if (url.pathname === '/research/runs') {
          return json(route, { ok: true, count: 2, total: 2, next_cursor: null, runs: [conflictedRun, previousRun] })
        }
        if (url.pathname === '/research/compare') return json(route, comparison)
        return route.continue()
      })
    },
    async assert(page) {
      await page.getByText('方向分歧', { exact: false }).first().waitFor({ timeout: 15_000 })
      const simulation = page.getByRole('button', { name: '进入模拟交易' })
      const select = page.locator('select[aria-label="选择对比评估记录"]')
      await select.selectOption('run-previous')
      await page.getByText('运行对比', { exact: true }).waitFor({ timeout: 15_000 })
      await page.getByText('decision / direction', { exact: true }).scrollIntoViewIfNeeded()
      return {
        conflictVisible: await page.getByText('有效模块同时包含做多与做空意见', { exact: false }).first().isVisible(),
        executionLanguageHidden: await page.locator('[role="status"]')
          .filter({ hasText: '方向冲突，不展示入场、止损和止盈动作。' })
          .isVisible(),
        simulationDisabled: await simulation.isDisabled(),
        moduleOpinionsVisible: await page.locator('[aria-label="统一研究决策模块意见"]').isVisible(),
        structuredDirectionChange: await page.getByText('decision / direction', { exact: true }).isVisible(),
        structuredMetricChange: await page.getByText('metric / latest_price', { exact: true }).isVisible(),
        structuredLevelChange: await page.getByText('level / target', { exact: true }).isVisible(),
      }
    },
  },
  {
    id: 'ledger-attribution-conservation',
    path: '/ledger?tab=performance',
    async installRoutes(context) {
      await context.route('**/ledger/**', (route) => {
        const url = new URL(route.request().url())
        if (url.pathname === '/ledger/summary') {
          return json(route, { ok: true, summary: { nav: 100072, cash: 100072, market_value: 0, cost_basis: 0, realized_pnl: 72, unrealized_pnl: 0, total_pnl: 72, return_pct: 0.072, n_positions: 0 } })
        }
        if (url.pathname === '/ledger/positions') return json(route, { count: 0, positions: [] })
        if (url.pathname === '/ledger/trades') return json(route, { count: 0, total: 0, next_cursor: null, trades: [] })
        if (url.pathname === '/ledger/cash') return json(route, { count: 0, total: 0, next_cursor: null, entries: [] })
        if (url.pathname === '/ledger/performance') {
          return json(route, { ok: true, equity_curve: [{ t: now, equity: 100000 }, { t: now + 3600, equity: 100072 }], twr_pct: 0.072, max_drawdown: { max_drawdown_pct: -0.02, peak_at: now, trough_at: now + 1800 }, benchmark_excess: null })
        }
        if (url.pathname === '/ledger/trade-analytics') {
          return json(route, {
            ok: true,
            summary: { closed_trades: 3, total_pnl: 72, return_pct: 0.072, win_rate_pct: 66.67, profit_factor: 1.8, average_profit_loss_ratio: 1.4, max_consecutive_losses: 1, average_holding_seconds: 86400, max_stagnation_days: 2 },
            execution_quality: { total_fees: 24, average_fee: 8, fee_drag_pct: 25, slippage_available: true, slippage_note: '已使用模拟成交理论价计算' },
            matching: { open_lot_count: 0, open_quantity: 0 }, cumulative_curve: [], monthly: [], daily: [], directions: [], holding_buckets: [], closed_trade_rows: [],
          })
        }
        if (url.pathname === '/ledger/attribution') return json(route, attribution)
        if (url.pathname === '/ledger/exposures') return json(route, { ok: true, by_market: {}, by_direction: { long: 0, short: 0 }, by_symbol: [], total_market_value: 0, gross_market_value: 0 })
        if (url.pathname === '/ledger/benchmarks') return json(route, { count: 0, benchmarks: [] })
        if (url.pathname === '/ledger/corrections') return json(route, { ok: true, count: 0, corrections: [] })
        return route.continue()
      })
    },
    async assert(page) {
      await page.getByText('研究身份收益归因', { exact: true }).waitFor({ timeout: 15_000 })
      const heading = page.getByText('研究身份收益归因', { exact: true })
      await heading.scrollIntoViewIfNeeded()
      const select = heading.locator('xpath=ancestor::div[contains(@class,"subsection")]').locator('select').first()
      const twoVersions = await page.getByText(/quality_momentum@1\.0\.0/).isVisible()
        && await page.getByText(/quality_momentum@2\.0\.0/).isVisible()
      await select.selectOption('research')
      await page.getByText(/research-run-20260816/).waitFor({ timeout: 10_000 })
      return {
        factorVersionsSeparated: twoVersions,
        dimensionFilterWorks: await page.getByText(/research-run-20260816/).isVisible(),
        conservationBalanced: await page.getByText(/归因守恒：账本净收益 72 \/ 分组净收益 72 · 一致/).isVisible(),
        unknownAttributionVisible: await page.getByText(/未知归因 · 2 笔，不并入任何已知因子或策略/).isVisible(),
        stableBacklinkVisible: await page.getByRole('link', { name: '打开来源' }).first().isVisible(),
      }
    },
  },
]

await fs.mkdir(outputRoot, { recursive: true })
const browser = await chromium.launch({ headless: true })
const results = []

try {
  for (const viewport of viewports) {
    for (const scenario of scenarios) {
      results.push(await runScenario(browser, viewport, scenario))
    }
  }
} finally {
  await browser.close()
}

const report = {
  generated_at: new Date().toISOString(),
  base_url: baseUrl,
  api_base: apiBase,
  browser: 'chromium',
  evidence_kind: 'deterministic_api_fixture_real_page',
  viewports,
  scenarios: scenarios.map(({ id, path: scenarioPath }) => ({ id, path: scenarioPath })),
  passed: results.every((item) => item.passed),
  results,
}

await fs.writeFile(
  path.join(outputRoot, 'browser-acceptance-report.json'),
  `${JSON.stringify(report, null, 2)}\n`,
  'utf8',
)
process.stdout.write(`${JSON.stringify(report, null, 2)}\n`)
if (!report.passed) process.exitCode = 1
