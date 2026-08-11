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
  process.env.QH_ACCEPTANCE_OUTPUT || 'docs/Plan/evidence/F5-factor-brain-workflow-web-2026-08-11',
)
const viewports = [
  { id: 'mobile-390x844', width: 390, height: 844 },
  { id: 'desktop-1440x900', width: 1440, height: 900 },
]

async function inspectPanel(page) {
  return page.evaluate(() => {
    const panel = document.querySelector('section[aria-label="自动因子研究与模拟观察"]')
    if (!panel) return { present: false }
    const panelRect = panel.getBoundingClientRect()
    const clippedText = [...panel.querySelectorAll('h3,p,label,small,strong,span,button')]
      .filter((element) => {
        const style = getComputedStyle(element)
        const rect = element.getBoundingClientRect()
        if (rect.width < 1 || rect.height < 1 || style.visibility === 'hidden') return false
        if (style.textOverflow === 'ellipsis' || style.overflowWrap === 'anywhere') return false
        return element.scrollWidth > element.clientWidth + 2
      })
      .slice(0, 20)
      .map((element) => ({
        tag: element.tagName.toLowerCase(),
        text: (element.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 100),
        clientWidth: element.clientWidth,
        scrollWidth: element.scrollWidth,
      }))
    const overflowingElements = [...panel.querySelectorAll('*')]
      .filter((element) => {
        const style = getComputedStyle(element)
        const rect = element.getBoundingClientRect()
        if (rect.width < 1 || rect.height < 1 || style.visibility === 'hidden') return false
        const scrollContainer = element.closest('*')
        let ancestor = scrollContainer?.parentElement
        while (ancestor && ancestor !== panel) {
          const ancestorStyle = getComputedStyle(ancestor)
          if (ancestorStyle.overflowX === 'auto' || ancestorStyle.overflowX === 'scroll') {
            return false
          }
          ancestor = ancestor.parentElement
        }
        return rect.right > panelRect.right + 2 || rect.left < panelRect.left - 2
      })
      .slice(0, 20)
      .map((element) => ({
        tag: element.tagName.toLowerCase(),
        text: (element.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 80),
        left: Math.round(element.getBoundingClientRect().left),
        right: Math.round(element.getBoundingClientRect().right),
      }))
    const observationInput = [...panel.querySelectorAll('input[type="number"]')]
      .find((input) => input.getAttribute('min') === '7')
    const aiCheckbox = panel.querySelector('input[type="checkbox"]')
    const text = panel.textContent || ''
    return {
      present: true,
      documentOverflow: Math.max(
        document.documentElement.scrollWidth - document.documentElement.clientWidth,
        document.body.scrollWidth - document.body.clientWidth,
      ),
      panelOverflow: panel.scrollWidth - panel.clientWidth,
      clippedText,
      overflowingElements,
      hasBrainEngine: text.includes('BRAIN 式表达式挖掘'),
      hasSafeDslPolicy: text.includes('仅安全 DSL AST'),
      hasFixedBacktestPolicy: text.includes('统一回测与回撤门禁'),
      hasSevenDayPolicy: text.includes('OKX Demo 至少 7 天'),
      observationDays: observationInput?.value || null,
      observationMinimum: observationInput?.min || null,
      aiEnabled: aiCheckbox instanceof HTMLInputElement ? aiCheckbox.checked : null,
    }
  })
}

await fs.mkdir(outputRoot, { recursive: true })
const browser = await chromium.launch({ headless: true })
const results = []

try {
  for (const viewport of viewports) {
    const context = await browser.newContext({ viewport })
    await context.addInitScript((value) => {
      localStorage.setItem('quanthub:api-base', value)
    }, apiBase)
    const page = await context.newPage()
    const consoleErrors = []
    page.on('console', (message) => {
      if (message.type() === 'error') consoleErrors.push(message.text())
    })
    await page.goto(`${baseUrl}/factor-research`, { waitUntil: 'domcontentloaded' })
    const panel = page.locator('section[aria-label="自动因子研究与模拟观察"]')
    await panel.waitFor({ state: 'visible', timeout: 20_000 })
    await page.waitForTimeout(500)
    const inspection = await inspectPanel(page)
    await page.screenshot({ path: path.join(outputRoot, `${viewport.id}-page.png`), fullPage: true })
    await panel.screenshot({ path: path.join(outputRoot, `${viewport.id}-panel.png`) })
    const customSymbolInput = panel.locator('input[placeholder="代码或名称，如 AVGO / 博通"]')
    await customSymbolInput.fill('BTC')
    await panel.getByRole('option', { name: /BTC.*OKX 已验证/ }).click()
    const customInstrumentInspection = await page.evaluate(() => {
      const panel = document.querySelector('section[aria-label="自动因子研究与模拟观察"]')
      const symbolInput = panel?.querySelector('input[placeholder="代码或名称，如 AVGO / 博通"]')
      const paperTarget = [...(panel?.querySelectorAll('select') || [])]
        .find((select) => [...select.options].some((option) => option.value === 'okx_demo'))
      const archive = document.querySelector('section[aria-label="因子证据档案"]')
      const archiveText = archive?.textContent || ''
      return {
        symbol: symbolInput instanceof HTMLInputElement ? symbolInput.value : null,
        paperTarget: paperTarget instanceof HTMLSelectElement ? paperTarget.value : null,
        archiveRequiresSevenDays: archiveText.includes('至少 7 个真实自然日模拟'),
        archiveHasExploratoryFilter: [...(archive?.querySelectorAll('option') || [])]
          .some((option) => option.value === 'exploratory'),
      }
    })
    await panel.getByRole('button', { name: '合约目录' }).click()
    const catalog = panel.getByRole('region', { name: 'OKX 永续合约目录' })
    await catalog.waitFor({ state: 'visible' })
    await catalog.getByPlaceholder('搜索代码或名称，如 BTC、黄金、石油、博通').fill('BTC')
    const verifiedContract = catalog.locator('button').filter({ hasText: 'BTC-USDT-SWAP' }).first()
    await verifiedContract.waitFor({ state: 'visible' })
    await verifiedContract.click()
    const liveKline = panel.getByRole('region', { name: 'OKX 实时公共 K 线' })
    await liveKline.waitFor({ state: 'visible' })
    await liveKline.getByText('实时', { exact: true }).waitFor({ state: 'visible', timeout: 20_000 })
    const marketDataInspection = await liveKline.evaluate((element) => ({
      hasVerifiedSymbol: (element.textContent || '').includes('BTC-USDT-SWAP'),
      hasLiveSource: (element.textContent || '').includes('实时'),
      hasEmptyOverlay: Boolean(element.querySelector('.kline-overlay')),
      svgRects: element.querySelectorAll('svg rect').length,
    }))
    await liveKline.screenshot({ path: path.join(outputRoot, `${viewport.id}-okx-live-kline.png`) })
    await liveKline.getByRole('button', { name: '关闭实时 K 线' }).click()
    await panel.locator('select:has(option[value="manual"])').selectOption('manual')
    await panel.locator('input[type="file"]').waitFor({ state: 'attached' })
    const marketSelect = panel.locator('select:has(option[value="a_shares"])')
    await marketSelect.selectOption('a_shares')
    await page.waitForTimeout(200)
    const manualInspection = await page.evaluate(() => {
      const panel = document.querySelector('section[aria-label="自动因子研究与模拟观察"]')
      const text = panel?.textContent || ''
      const stockInput = [...(panel?.querySelectorAll('input') || [])]
        .find((input) => input.getAttribute('placeholder') === '代码或名称，如 600519 / 贵州茅台')
      return {
        hasManualExpression: text.includes('手工 Alpha 表达式'),
        hasAlphaTemplates: text.includes('Alpha 模板'),
        hasParameterProfiles: text.includes('参数风格'),
        hasJsonUpload: text.includes('上传 Alpha JSON'),
        hasDslReference: text.includes('字段与参数'),
        hasPeriodParameter: text.includes('periods'),
        hasWinsorParameters: text.includes('lower / upper'),
        hasZscoreOperator: text.includes('rolling_zscore(value, window)'),
        hasAkshare: text.includes('AkShare 实时行情'),
        stockSymbol: stockInput instanceof HTMLInputElement ? stockInput.value : null,
        fileInputs: panel?.querySelectorAll('input[type="file"]').length || 0,
      }
    })
    await panel.screenshot({ path: path.join(outputRoot, `${viewport.id}-manual-panel.png`) })
    const dslGuide = panel.getByRole('complementary', { name: 'Alpha 参数手册' })
    await dslGuide.scrollIntoViewIfNeeded()
    await dslGuide.screenshot({ path: path.join(outputRoot, `${viewport.id}-manual-dsl-guide.png`) })
    results.push({
      viewport,
      inspection,
      customInstrumentInspection,
      marketDataInspection,
      manualInspection,
      consoleErrors,
    })
    await context.close()
  }
} finally {
  await browser.close()
}

const passed = results.every(({
  inspection,
  customInstrumentInspection,
  marketDataInspection,
  manualInspection,
  consoleErrors,
}) => (
  inspection.present
  && inspection.documentOverflow === 0
  && inspection.panelOverflow === 0
  && inspection.clippedText.length === 0
  && inspection.overflowingElements.length === 0
  && inspection.hasBrainEngine
  && inspection.hasSafeDslPolicy
  && inspection.hasFixedBacktestPolicy
  && inspection.hasSevenDayPolicy
  && inspection.observationDays === '7'
  && inspection.observationMinimum === '7'
  && inspection.aiEnabled === true
  && customInstrumentInspection.symbol === 'BTC-USDT-SWAP'
  && customInstrumentInspection.paperTarget === 'okx_demo'
  && customInstrumentInspection.archiveRequiresSevenDays
  && customInstrumentInspection.archiveHasExploratoryFilter === false
  && marketDataInspection.hasVerifiedSymbol
  && marketDataInspection.hasLiveSource
  && marketDataInspection.hasEmptyOverlay === false
  && marketDataInspection.svgRects > 10
  && manualInspection.hasManualExpression
  && manualInspection.hasAlphaTemplates
  && manualInspection.hasParameterProfiles
  && manualInspection.hasJsonUpload
  && manualInspection.hasDslReference
  && manualInspection.hasPeriodParameter
  && manualInspection.hasWinsorParameters
  && manualInspection.hasZscoreOperator
  && manualInspection.hasAkshare
  && manualInspection.stockSymbol === '600519'
  && manualInspection.fileInputs === 1
  && consoleErrors.length === 0
))
const report = {
  generated_at: new Date().toISOString(),
  base_url: baseUrl,
  api_base: apiBase,
  route: '/factor-research',
  passed,
  results,
}
await fs.writeFile(path.join(outputRoot, 'report.json'), `${JSON.stringify(report, null, 2)}\n`, 'utf8')
process.stdout.write(`${JSON.stringify(report, null, 2)}\n`)
if (!passed) process.exitCode = 1
