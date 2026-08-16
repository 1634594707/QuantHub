#!/usr/bin/env node

import fs from 'node:fs/promises'
import path from 'node:path'
import process from 'node:process'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const { chromium } = require('playwright')

const baseUrl = process.env.QH_ACCEPTANCE_BASE_URL || 'http://127.0.0.1:5173'
const outputRoot = path.resolve(
  process.cwd(),
  process.env.QH_ACCEPTANCE_OUTPUT || 'docs/Plan/evidence/stock-research-acceptance',
)
const viewports = [
  { id: 'mobile-390x844', width: 390, height: 844 },
  { id: 'tablet-768x1024', width: 768, height: 1024 },
  { id: 'laptop-1280x720', width: 1280, height: 720 },
  { id: 'desktop-1440x900', width: 1440, height: 900 },
]
const routes = [
  { id: 'evaluate', path: '/evaluate', requiredText: '开始评估' },
  {
    id: 'research',
    path: '/research/600519?market=a_shares&tf=1d&view=overview&mode=investor',
    requiredText: '市场研究',
  },
  {
    id: 'alerts',
    path: '/alerts?action=create&type=valuation_band_crossed&symbol=600519&market=a_shares&threshold=50',
    requiredText: '研究提醒',
  },
]

await fs.mkdir(outputRoot, { recursive: true })
const browser = await chromium.launch({ headless: true })
const results = []

try {
  for (const viewport of viewports) {
    const context = await browser.newContext({ viewport })
    await context.addInitScript(() => {
      localStorage.setItem('quanthub.interface-mode', 'advanced')
    })
    for (const route of routes) {
      const page = await context.newPage()
      const consoleErrors = []
      const failedRequests = []
      page.on('console', (message) => {
        if (message.type() === 'error') consoleErrors.push(message.text())
      })
      page.on('requestfailed', (request) => {
        failedRequests.push(`${request.method()} ${request.url()} ${request.failure()?.errorText || ''}`)
      })
      const response = await page.goto(`${baseUrl}${route.path}`, { waitUntil: 'domcontentloaded' })
      await page.locator('#root').waitFor({ state: 'visible', timeout: 10_000 })
      await page.getByText(route.requiredText, { exact: false }).first().waitFor({ timeout: 10_000 })
      await page.waitForTimeout(900)
      const layout = await page.evaluate(() => {
        const visible = (element) => {
          const style = getComputedStyle(element)
          const rect = element.getBoundingClientRect()
          return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0
        }
        const documentOverflow = Math.max(
          document.documentElement.scrollWidth - document.documentElement.clientWidth,
          document.body.scrollWidth - document.body.clientWidth,
        )
        const outsideViewport = [...document.querySelectorAll('button,a,input,select,textarea,h1,h2,h3')]
          .filter(visible)
          .map((element) => ({
            tag: element.tagName.toLowerCase(),
            text: (element.textContent || element.getAttribute('aria-label') || '').trim().slice(0, 80),
            rect: element.getBoundingClientRect(),
          }))
          .filter((item) => (
            (item.rect.left < -2 && item.rect.right > 0)
            || (item.rect.right > window.innerWidth + 2 && item.rect.left < window.innerWidth)
          ))
          .map((item) => ({ tag: item.tag, text: item.text, left: item.rect.left, right: item.rect.right }))
        const clippedControls = [...document.querySelectorAll('button,a,label,input,select,textarea')]
          .filter(visible)
          .filter((element) => element.scrollWidth > element.clientWidth + 3 || element.scrollHeight > element.clientHeight + 3)
          .map((element) => ({
            tag: element.tagName.toLowerCase(),
            text: (element.textContent || element.getAttribute('aria-label') || '').trim().slice(0, 80),
            client: [element.clientWidth, element.clientHeight],
            scroll: [element.scrollWidth, element.scrollHeight],
          }))
        return { documentOverflow, outsideViewport, clippedControls }
      })
      const screenshot = `${viewport.id}-${route.id}.png`
      await page.screenshot({ path: path.join(outputRoot, screenshot), fullPage: true })
      results.push({
        viewport,
        route,
        status: response?.status() ?? null,
        layout,
        consoleErrors,
        failedRequests: failedRequests.filter((item) => !item.includes('/api/market/')),
        screenshot,
      })
      await page.close()
    }
    await context.close()
  }
} finally {
  await browser.close()
}

const failures = results.filter((item) => (
  item.status === null
  || item.status >= 400
  || item.layout.documentOverflow > 2
  || item.layout.outsideViewport.length > 0
  || item.layout.clippedControls.length > 0
  || item.consoleErrors.length > 0
  || item.failedRequests.length > 0
))
const report = {
  generated_at: new Date().toISOString(),
  base_url: baseUrl,
  viewports,
  routes,
  passed: failures.length === 0,
  failures,
  results,
}
await fs.writeFile(path.join(outputRoot, 'report.json'), JSON.stringify(report, null, 2), 'utf8')
console.log(JSON.stringify({ passed: report.passed, checks: results.length, failures: failures.length }))
if (!report.passed) process.exitCode = 1
