/* Browser acceptance for the OKX public catalogue unavailable state. */
const fs = require('fs')
const path = require('path')
const { chromium } = require('playwright')

const repoRoot = path.resolve(__dirname, '..')
const baseUrl = (process.argv[2] || 'http://127.0.0.1:5173').replace(/\/$/, '')
const apiBase = (process.argv[3] || 'http://127.0.0.1:8001').replace(/\/$/, '')
const outputRoot = path.resolve(process.argv[4] || path.join(
  repoRoot,
  'docs',
  'Plan',
  'evidence',
  'R8-okx-catalog-timeout-web-2026-08-11',
))
const viewports = [
  ['desktop-1440x900', 1440, 900],
  ['mobile-390x844', 390, 844],
]
const safeTimeoutMessage = 'OKX 公共合约目录连接超时，公共目录暂时不可用，请稍后重试。'

async function main() {
  fs.mkdirSync(outputRoot, { recursive: true })
  const browser = await chromium.launch({ headless: true })
  const cases = []
  try {
    for (const [name, width, height] of viewports) {
      const context = await browser.newContext({ viewport: { width, height }, locale: 'zh-CN' })
      await context.addInitScript(({ api }) => {
        localStorage.setItem('quanthub:api-base', api)
        localStorage.setItem('quanthub.interface-mode', 'advanced')
        localStorage.setItem('qh-theme', 'light')
      }, { api: apiBase })
      const page = await context.newPage()
      const consoleErrors = []
      page.on('console', (message) => {
        if (message.type() === 'error') consoleErrors.push(message.text())
      })
      await page.goto(`${baseUrl}/factor-research`, { waitUntil: 'domcontentloaded' })
      const panel = page.getByRole('region', { name: '自动因子研究与模拟观察' })
      await panel.waitFor({ state: 'visible', timeout: 20_000 })
      await panel.getByRole('button', { name: '合约目录' }).click()
      const catalog = panel.getByRole('region', { name: 'OKX 永续合约目录' })
      await catalog.waitFor({ state: 'visible' })
      await catalog.getByText(safeTimeoutMessage, { exact: true }).waitFor({ timeout: 20_000 })
      const inspection = await catalog.evaluate((element, expected) => {
        const text = element.textContent || ''
        const panel = element.closest('section[aria-label="自动因子研究与模拟观察"]')
        const buttons = [...(panel?.querySelectorAll('button') || [])]
        const start = buttons.find((button) => button.textContent?.includes('启动自动研究'))
        const kline = buttons.find((button) => button.textContent?.includes('实时 K 线'))
        return {
          safeMessageVisible: text.includes(expected),
          leaksTransportDetails: /HTTPSConnectionPool|www\.okx\.com|port=443|ConnectTimeoutError/.test(text),
          retryAvailable: Boolean(element.querySelector('button[aria-label="刷新 OKX 合约目录"]')),
          startDisabled: start instanceof HTMLButtonElement ? start.disabled : null,
          klineDisabled: kline instanceof HTMLButtonElement ? kline.disabled : null,
          horizontalOverflow: Math.max(
            document.documentElement.scrollWidth - document.documentElement.clientWidth,
            document.body.scrollWidth - document.body.clientWidth,
          ),
        }
      }, safeTimeoutMessage)
      await catalog.screenshot({ path: path.join(outputRoot, `${name}-catalog.png`) })
      cases.push({ viewport: { name, width, height }, inspection, consoleErrors })
      await context.close()
    }
  } finally {
    await browser.close()
  }

  const passed = cases.every(({ inspection }) => (
    inspection.safeMessageVisible
    && !inspection.leaksTransportDetails
    && inspection.retryAvailable
    && inspection.startDisabled === true
    && inspection.klineDisabled === true
    && inspection.horizontalOverflow === 0
  ))
  const report = { generated_at: new Date().toISOString(), base_url: baseUrl, api_base: apiBase, passed, cases }
  fs.writeFileSync(path.join(outputRoot, 'report.json'), `${JSON.stringify(report, null, 2)}\n`)
  console.log(JSON.stringify(report, null, 2))
  if (!passed) process.exitCode = 1
}

main().catch((error) => {
  console.error(error)
  process.exitCode = 1
})
