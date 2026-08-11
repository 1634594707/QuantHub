#!/usr/bin/env node

import fs from 'node:fs/promises'
import path from 'node:path'
import process from 'node:process'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const { chromium } = require('playwright')

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/(.:)/, '$1')), '..')
const baseUrl = process.env.QH_ACCEPTANCE_BASE_URL || 'http://127.0.0.1:5173'
const evidenceRoot = path.resolve(
  repoRoot,
  process.env.QH_ACCEPTANCE_OUTPUT || 'docs/Plan/evidence/pre-m4-web-acceptance',
)

const viewports = [
  { id: 'mobile-390x844', width: 390, height: 844 },
  { id: 'tablet-768x1024', width: 768, height: 1024 },
  { id: 'laptop-1280x720', width: 1280, height: 720 },
  { id: 'desktop-1440x900', width: 1440, height: 900 },
]

const routes = [
  { id: 'overview', path: '/', requiredText: '总览' },
  { id: 'evaluate', path: '/evaluate', requiredText: '标的研究' },
  { id: 'strategies', path: '/strategies', requiredText: '策略' },
  { id: 'signals', path: '/signals', requiredText: '信号' },
  { id: 'trading', path: '/trading', requiredText: 'Demo 交易台' },
  { id: 'account-risk', path: '/account-risk', requiredText: '账户与风控' },
  { id: 'config', path: '/config', requiredText: '系统设置' },
]

function relativeUrl(page) {
  const url = new URL(page.url())
  return `${url.pathname}${url.search}${url.hash}`
}

async function settle(page) {
  await page.waitForLoadState('domcontentloaded')
  await page.locator('#root').waitFor({ state: 'attached', timeout: 10_000 })
  await page.waitForTimeout(900)
}

async function inspectLayout(page) {
  return page.evaluate(() => {
    const root = document.getElementById('root')
    const documentOverflow = Math.max(
      document.documentElement.scrollWidth - document.documentElement.clientWidth,
      document.body.scrollWidth - document.body.clientWidth,
    )
    const clippedText = [...document.querySelectorAll('h1,h2,h3,p,label,button,a,th,td')]
      .filter((element) => {
        const style = getComputedStyle(element)
        const rect = element.getBoundingClientRect()
        if (rect.width < 1 || rect.height < 1 || style.visibility === 'hidden') return false
        if (style.overflowX === 'auto' || style.overflowX === 'scroll') return false
        return element.scrollWidth > element.clientWidth + 2 && style.textOverflow !== 'ellipsis'
      })
      .slice(0, 20)
      .map((element) => ({
        tag: element.tagName.toLowerCase(),
        text: (element.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 100),
        clientWidth: element.clientWidth,
        scrollWidth: element.scrollWidth,
      }))
    return {
      rootTextLength: (root?.textContent || '').trim().length,
      documentOverflow,
      clippedText,
    }
  })
}

async function clickAndExpect(page, locator, expectedPath) {
  const target = page.locator(locator).filter({ visible: true }).first()
  await target.waitFor({ state: 'visible', timeout: 8_000 })
  await target.click()
  await page.waitForURL((url) => url.pathname === expectedPath, { timeout: 8_000 })
  await settle(page)
  // A destination may add a real record selection (for example
  // /signals?signal_id=...), while the navigation contract is route-based.
  return new URL(page.url()).pathname
}

async function runNavigationChecks(browser) {
  const checks = []

  const desktop = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  await desktop.goto(baseUrl)
  await settle(desktop)
  for (const item of [
    { label: '市场研究', path: '/evaluate' },
    { label: '策略', path: '/strategies' },
    { label: '交易', path: '/trading' },
    { label: '账户风控', path: '/account-risk' },
  ]) {
    await desktop.goto(baseUrl)
    await settle(desktop)
    const actual = await clickAndExpect(desktop, `a.workspace-tab[aria-label="${item.label}"]`, item.path)
    checks.push({ viewport: 'desktop', flow: item.label, expected: item.path, actual, passed: actual === item.path })
  }
  await desktop.goto(`${baseUrl}/trading`)
  await settle(desktop)
  for (const item of [
    { label: '审信号', href: '/signals' },
    { label: '停机与对账', href: '/account-risk' },
  ]) {
    await desktop.goto(`${baseUrl}/trading`)
    await settle(desktop)
    const actual = await clickAndExpect(desktop, `nav[aria-label="交易工作区快捷入口"] a[href="${item.href}"]`, item.href)
    checks.push({ viewport: 'desktop', flow: item.label, expected: item.href, actual, passed: actual === item.href })
  }
  await desktop.close()

  const mobile = await browser.newPage({ viewport: { width: 390, height: 844 } })
  await mobile.goto(baseUrl)
  await settle(mobile)
  let actual = await clickAndExpect(mobile, 'nav[aria-label="移动端导航"] a:has-text("研究")', '/evaluate')
  checks.push({ viewport: 'mobile', flow: '查标的', expected: '/evaluate', actual, passed: actual === '/evaluate' })

  await mobile.goto(baseUrl)
  await settle(mobile)
  actual = await clickAndExpect(mobile, 'nav[aria-label="移动端导航"] a:has-text("交易")', '/trading')
  checks.push({ viewport: 'mobile', flow: '下单/撤单', expected: '/trading', actual, passed: actual === '/trading' })

  for (const item of [
    { label: '审信号', href: '/signals' },
    { label: '停机与对账', href: '/account-risk' },
  ]) {
    await mobile.goto(`${baseUrl}/trading`)
    await settle(mobile)
    actual = await clickAndExpect(mobile, `nav[aria-label="交易工作区快捷入口"] a[href="${item.href}"]`, item.href)
    checks.push({ viewport: 'mobile', flow: item.label, expected: item.href, actual, passed: actual === item.href })
  }

  await mobile.goto(baseUrl)
  await settle(mobile)
  await mobile.getByRole('button', { name: '打开更多工作区' }).click()
  actual = await clickAndExpect(mobile, 'a.workspace-tab[aria-label="策略"]', '/strategies')
  checks.push({ viewport: 'mobile', flow: '看策略', expected: '/strategies', actual, passed: actual === '/strategies' })
  await mobile.close()

  return checks
}

async function runShadowSafetyChecks(browser) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  const checks = []

  await page.goto(`${baseUrl}/trading`)
  await settle(page)
  const tradingText = await page.locator('body').innerText()
  const submitDisabled = await page.getByRole('button', { name: /提交 Demo 订单|再次验证幂等/ }).isDisabled()
  const isShadow = tradingText.includes('影子（只读）')
  if (isShadow) {
    checks.push({
      check: 'shadow-trading-blocked',
      environmentVisible: true,
      submitDisabled,
      passed: submitDisabled,
    })
  } else {
    const riskLocked = tradingText.includes('cancel_only') && tradingText.includes('新订单已锁定')
    const recoveryVisible = await page.getByRole('button', { name: '恢复未决订单' }).isVisible()
    const reconciliationVisible = await page.getByRole('button', { name: '立即对账' }).isVisible()
    checks.push({
      check: 'demo-risk-lock-and-operations',
      environmentVisible: tradingText.includes('OKX 模拟盘'),
      riskLocked,
      submitDisabled,
      recoveryVisible,
      reconciliationVisible,
      passed: tradingText.includes('OKX 模拟盘') && riskLocked && submitDisabled && recoveryVisible && reconciliationVisible,
    })
  }

  await page.goto(`${baseUrl}/account-risk`)
  await settle(page)
  const riskText = await page.locator('body').innerText()
  const reconcileDisabled = await page.getByRole('button', { name: '发起对账' }).isDisabled()
  const riskModeDisabled = await page.getByRole('button', { name: '应用风险模式' }).isDisabled()
  if (isShadow) {
    checks.push({
      check: 'shadow-risk-mutations-blocked',
      environmentVisible: riskText.includes('影子（只读）'),
      reconcileDisabled,
      riskModeDisabled,
      passed: riskText.includes('影子（只读）') && reconcileDisabled && riskModeDisabled,
    })
  } else {
    const resolveButtons = page.getByRole('button', { name: '关闭差异' })
    const firstResolveDisabled = await resolveButtons.first().isDisabled()
    checks.push({
      check: 'demo-diff-resolution-requires-conclusion',
      environmentVisible: riskText.includes('OKX 模拟盘'),
      openDiffsVisible: (await resolveButtons.count()) > 0,
      firstResolveDisabled,
      passed: riskText.includes('OKX 模拟盘') && (await resolveButtons.count()) > 0 && firstResolveDisabled,
    })
  }

  await page.close()
  return checks
}

async function main() {
  await fs.mkdir(evidenceRoot, { recursive: true })
  const browser = await chromium.launch({ headless: true })
  const pageResults = []
  const runtime = { consoleErrors: [], pageErrors: [], failedResources: [], apiErrors: [] }

  try {
    for (const viewport of viewports) {
      const page = await browser.newPage({ viewport: { width: viewport.width, height: viewport.height } })
      page.on('console', (message) => {
        if (message.type() === 'error') runtime.consoleErrors.push({ viewport: viewport.id, url: page.url(), text: message.text() })
      })
      page.on('pageerror', (error) => runtime.pageErrors.push({ viewport: viewport.id, url: page.url(), text: error.message }))
      page.on('response', (response) => {
        if (response.status() < 400) return
        const record = { viewport: viewport.id, url: response.url(), status: response.status() }
        if (response.url().includes('/api/')) runtime.apiErrors.push(record)
        else runtime.failedResources.push(record)
      })

      for (const route of routes) {
        const response = await page.goto(`${baseUrl}${route.path}`, { waitUntil: 'domcontentloaded' })
        await settle(page)
        const bodyText = await page.locator('body').innerText()
        const layout = await inspectLayout(page)
        const screenshot = `${viewport.id}-${route.id}.png`
        await page.screenshot({ path: path.join(evidenceRoot, screenshot), fullPage: true })
        const result = {
          viewport: viewport.id,
          route: route.path,
          documentStatus: response?.status() ?? null,
          requiredText: route.requiredText,
          requiredTextVisible: bodyText.includes(route.requiredText),
          screenshot,
          ...layout,
        }
        result.passed = Boolean(
          result.documentStatus === 200
          && result.requiredTextVisible
          && result.rootTextLength > 20
          && result.documentOverflow <= 1
          && result.clippedText.length === 0
        )
        pageResults.push(result)
      }
      await page.close()
    }

    const navigation = await runNavigationChecks(browser)
    const shadowSafety = await runShadowSafetyChecks(browser)
    const passed = Boolean(
      pageResults.every((item) => item.passed)
      && navigation.every((item) => item.passed)
      && shadowSafety.every((item) => item.passed)
      && runtime.pageErrors.length === 0
      && runtime.failedResources.length === 0
    )
    const report = {
      task: 'P0-04/M2-08/Q0-01 pre-M4 browser acceptance',
      generatedAt: new Date().toISOString(),
      baseUrl,
      browser: 'Chromium',
      viewports,
      routes: routes.map(({ id, path: routePath }) => ({ id, path: routePath })),
      mutationPolicy: 'Read-only; no order, risk-mode, recovery, or reconciliation mutation is submitted.',
      pageResults,
      navigation,
      shadowSafety,
      runtime,
      passed,
    }
    await fs.writeFile(path.join(evidenceRoot, 'report.json'), `${JSON.stringify(report, null, 2)}\n`, 'utf8')
    console.log(JSON.stringify({
      evidenceRoot,
      pages: pageResults.length,
      navigationChecks: navigation.length,
      shadowSafetyChecks: shadowSafety.length,
      consoleErrors: runtime.consoleErrors.length,
      pageErrors: runtime.pageErrors.length,
      failedResources: runtime.failedResources.length,
      apiErrors: runtime.apiErrors.length,
      failedPages: pageResults.filter((item) => !item.passed).map((item) => `${item.viewport}:${item.route}`),
      passed,
    }, null, 2))
    return passed ? 0 : 1
  } finally {
    await browser.close()
  }
}

process.exitCode = await main()
