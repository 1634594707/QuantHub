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
  process.env.QH_ACCEPTANCE_OUTPUT || 'docs/Plan/evidence/F4-factor-archive-web-2026-08-11',
)
const viewports = [
  { id: 'mobile-390x844', width: 390, height: 844 },
  { id: 'desktop-1440x900', width: 1440, height: 900 },
]

async function inspectArchive(page) {
  return page.evaluate(() => {
    const archive = document.querySelector('section[aria-label="因子证据档案"]')
    if (!archive) return { present: false }
    const archiveRect = archive.getBoundingClientRect()
    const clippedText = [...archive.querySelectorAll('h3,h4,h5,p,dt,dd,small,strong,code,span')]
      .filter((element) => {
        const style = getComputedStyle(element)
        const rect = element.getBoundingClientRect()
        if (rect.width < 1 || rect.height < 1 || style.visibility === 'hidden') return false
        if (style.overflowX === 'auto' || style.overflowX === 'scroll') return false
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
    const overflowingElements = [...archive.querySelectorAll('*')]
      .filter((element) => {
        const style = getComputedStyle(element)
        const rect = element.getBoundingClientRect()
        if (rect.width < 1 || rect.height < 1 || style.visibility === 'hidden') return false
        return rect.right > archiveRect.right + 2 || rect.left < archiveRect.left - 2
      })
      .slice(0, 20)
      .map((element) => ({
        tag: element.tagName.toLowerCase(),
        text: (element.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 80),
        left: Math.round(element.getBoundingClientRect().left),
        right: Math.round(element.getBoundingClientRect().right),
        archiveLeft: Math.round(archiveRect.left),
        archiveRight: Math.round(archiveRect.right),
      }))
    return {
      present: true,
      documentOverflow: Math.max(
        document.documentElement.scrollWidth - document.documentElement.clientWidth,
        document.body.scrollWidth - document.body.clientWidth,
      ),
      archiveOverflow: archive.scrollWidth - archive.clientWidth,
      clippedText,
      overflowingElements,
      selectedRows: archive.querySelectorAll('button[aria-pressed="true"]').length,
      liveTradingClosed: archive.textContent?.includes('实盘权限关闭') ?? false,
      hasPreregistration: archive.textContent?.includes('事前假设') ?? false,
      hasPostStudyEvidence: archive.textContent?.includes('事后证据') ?? false,
      hasRemainingRisk: archive.textContent?.includes('剩余风险') ?? false,
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
    const archive = page.locator('section[aria-label="因子证据档案"]')
    await archive.waitFor({ state: 'visible', timeout: 20_000 })
    await archive.locator('button[aria-pressed="true"]').waitFor({ state: 'visible', timeout: 20_000 })
    await archive.scrollIntoViewIfNeeded()
    await page.waitForTimeout(300)
    const inspection = await inspectArchive(page)
    await page.screenshot({ path: path.join(outputRoot, `${viewport.id}-page.png`), fullPage: true })
    await archive.screenshot({ path: path.join(outputRoot, `${viewport.id}-archive.png`) })
    results.push({ viewport, inspection, consoleErrors })
    await context.close()
  }
} finally {
  await browser.close()
}

const passed = results.every(({ inspection, consoleErrors }) => (
  inspection.present
  && inspection.documentOverflow === 0
  && inspection.archiveOverflow === 0
  && inspection.clippedText.length === 0
  && inspection.overflowingElements.length === 0
  && inspection.selectedRows === 1
  && inspection.liveTradingClosed
  && inspection.hasPreregistration
  && inspection.hasPostStudyEvidence
  && inspection.hasRemainingRisk
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
