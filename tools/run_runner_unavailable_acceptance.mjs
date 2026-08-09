import fs from 'node:fs/promises'
import path from 'node:path'
import process from 'node:process'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const { chromium } = require('playwright')

const baseUrl = 'http://127.0.0.1:5173'
const evidenceRoot = path.resolve('docs/Plan/evidence/M1-06-runner-unavailable')
await fs.mkdir(evidenceRoot, { recursive: true })

const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({ viewport: { width: 1280, height: 720 } })
const page = await context.newPage()
const consoleErrors = []
const pageErrors = []
page.on('console', (message) => {
  if (message.type() === 'error') consoleErrors.push(message.text())
})
page.on('pageerror', (error) => pageErrors.push(String(error)))

const researchResponse = await page.goto(`${baseUrl}/evaluate`, { waitUntil: 'networkidle' })
const researchVisible = await page.getByText('标的研究', { exact: false }).first().isVisible()
await page.screenshot({
  path: path.join(evidenceRoot, 'runner-down-research.png'),
  fullPage: true,
})

const tradingResponse = await page.goto(`${baseUrl}/trading`, { waitUntil: 'networkidle' })
await page.getByRole('heading', { name: '交易工作台', exact: true }).waitFor()
const sourceErrorVisible = await page.getByText('源异常', { exact: true }).first().isVisible()
const disabledActions = await page.locator('button:disabled').allTextContents()
const submitDisabled = disabledActions.some((text) => text.includes('提交订单'))
const cancelDisabled = disabledActions.some((text) => text.includes('撤单'))
await page.screenshot({
  path: path.join(evidenceRoot, 'runner-down-trading.png'),
  fullPage: true,
})

const report = {
  task: 'M1-06 Runner unavailable browser acceptance',
  generated_at: new Date().toISOString(),
  mutation_policy: 'Read-only; Runner is unavailable and no mutation is submitted.',
  research: {
    status: researchResponse?.status() ?? null,
    required_text_visible: researchVisible,
    screenshot: 'runner-down-research.png',
  },
  trading: {
    status: tradingResponse?.status() ?? null,
    source_error_visible: sourceErrorVisible,
    submit_disabled: submitDisabled,
    cancel_disabled: cancelDisabled,
    screenshot: 'runner-down-trading.png',
  },
  console_errors: consoleErrors,
  page_errors: pageErrors,
}
report.passed = Boolean(
  report.research.status === 200
  && researchVisible
  && report.trading.status === 200
  && sourceErrorVisible
  && submitDisabled
  && cancelDisabled
  && consoleErrors.length === 0
  && pageErrors.length === 0
)

await fs.writeFile(
  path.join(evidenceRoot, 'report.json'),
  `${JSON.stringify(report, null, 2)}\n`,
  'utf8',
)
await browser.close()
console.log(JSON.stringify(report, null, 2))
process.exitCode = report.passed ? 0 : 1
