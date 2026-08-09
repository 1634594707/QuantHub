#!/usr/bin/env node

import fs from 'node:fs/promises'
import path from 'node:path'
import process from 'node:process'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const { chromium } = require('playwright')
const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/(.:)/, '$1')), '..')
const outputRoot = path.join(repoRoot, 'docs', 'Plan', 'evidence', 'M4-01-okx-settings')
const baseUrl = process.env.QH_ACCEPTANCE_BASE_URL || 'http://127.0.0.1:5173'
const viewports = [
  { id: 'mobile-390x844', width: 390, height: 844 },
  { id: 'desktop-1440x900', width: 1440, height: 900 },
]

await fs.mkdir(outputRoot, { recursive: true })
const browser = await chromium.launch({ headless: true })
const results = []

try {
  for (const viewport of viewports) {
    const page = await browser.newPage({ viewport })
    const runtimeErrors = []
    page.on('console', (message) => {
      if (message.type() === 'error') runtimeErrors.push(message.text())
    })
    page.on('pageerror', (error) => runtimeErrors.push(error.message))
    await page.goto(`${baseUrl}/config`, { waitUntil: 'domcontentloaded' })
    const title = page.locator('.card-title').filter({ hasText: 'OKX Demo 凭据' }).first()
    await title.waitFor({ state: 'attached', timeout: 10_000 })
    const card = title.locator('xpath=ancestor::div[contains(concat(" ",normalize-space(@class)," ")," card ")][1]')
    await card.scrollIntoViewIfNeeded()
    await title.waitFor({ state: 'visible', timeout: 10_000 })
    await page.waitForTimeout(300)
    const inputInfo = await card.locator('input').evaluateAll((inputs) => inputs.map((input) => ({
      type: input.type,
      autocomplete: input.autocomplete,
      value: input.value,
      width: input.getBoundingClientRect().width,
      scrollWidth: input.scrollWidth,
    })))
    const box = await card.boundingBox()
    const labels = await card.locator('label').allTextContents()
    const screenshot = `${viewport.id}.png`
    await card.screenshot({ path: path.join(outputRoot, screenshot) })
    const passed = Boolean(
      box
      && box.width <= viewport.width
      && inputInfo.length === 3
      && inputInfo.every((input) => input.type === 'password' && input.autocomplete === 'new-password' && input.value === '' && input.scrollWidth <= input.width + 2)
      && ['API Key', 'Secret Key', 'API Passphrase'].every((label) => labels.some((value) => value.includes(label)))
      && runtimeErrors.length === 0
    )
    results.push({ viewport: viewport.id, box, labels, inputInfo, runtimeErrors, screenshot, passed })
    await page.close()
  }
} finally {
  await browser.close()
}

const report = { generatedAt: new Date().toISOString(), baseUrl, results, passed: results.every((item) => item.passed) }
await fs.writeFile(path.join(outputRoot, 'report.json'), `${JSON.stringify(report, null, 2)}\n`, 'utf8')
console.log(JSON.stringify(report, null, 2))
if (!report.passed) process.exitCode = 1
