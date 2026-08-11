/* QuantHub R7 responsive browser acceptance. Uses the host Playwright runtime. */
const fs = require('fs')
const path = require('path')
const { chromium } = require('playwright')
const sharp = require('sharp')

const repoRoot = path.resolve(__dirname, '..')
const baseUrl = (process.argv[2] || 'http://127.0.0.1:5173').replace(/\/$/, '')
const outputRoot = path.resolve(process.argv[3] || path.join(
  repoRoot,
  'docs',
  'Plan',
  'evidence',
  'R7-web-acceptance-2026-08-11',
))

const allRoutes = [
  ['/', 'overview'],
  ['/radar', 'radar'],
  ['/factor-research', 'factor-research'],
  ['/demo-lab', 'demo-lab'],
  ['/strategy-lab', 'strategy-lab'],
  ['/governance', 'governance'],
  ['/config', 'config'],
]
const allViewports = [
  ['desktop', 1440, 900],
  ['laptop', 1280, 720],
  ['tablet', 768, 1024],
  ['mobile', 390, 844],
]
const allThemes = ['dark', 'light']
const routes = process.env.R7_ROUTE
  ? allRoutes.filter(([route]) => route === process.env.R7_ROUTE)
  : allRoutes
const viewports = process.env.R7_VIEWPORT
  ? allViewports.filter(([name]) => name === process.env.R7_VIEWPORT)
  : allViewports
const themes = process.env.R7_THEME ? [process.env.R7_THEME] : allThemes

function cleanMessage(value) {
  return String(value).replace(/\s+/g, ' ').trim().slice(0, 500)
}

async function pixelStats(file) {
  const { data, info } = await sharp(file)
    .resize(64, 64, { fit: 'fill' })
    .removeAlpha()
    .raw()
    .toBuffer({ resolveWithObject: true })
  let sum = 0
  let sumSquares = 0
  const colors = new Set()
  for (let offset = 0; offset < data.length; offset += info.channels) {
    const r = data[offset]
    const g = data[offset + 1]
    const b = data[offset + 2]
    const luminance = (r * 299 + g * 587 + b * 114) / 1000
    sum += luminance
    sumSquares += luminance * luminance
    colors.add(`${r >> 4}:${g >> 4}:${b >> 4}`)
  }
  const pixels = data.length / info.channels
  const mean = sum / pixels
  const variance = Math.max(0, sumSquares / pixels - mean * mean)
  return {
    luminance_mean: Number(mean.toFixed(2)),
    luminance_stddev: Number(Math.sqrt(variance).toFixed(2)),
    quantized_colors: colors.size,
  }
}

async function inspectPage(page, width) {
  return page.evaluate((mobileWidth) => {
    const visible = (element) => {
      const style = getComputedStyle(element)
      const rect = element.getBoundingClientRect()
      return style.display !== 'none'
        && style.visibility !== 'hidden'
        && style.pointerEvents !== 'none'
        && rect.width > 0
        && rect.height > 0
        && rect.right > 0
        && rect.bottom > 0
        && rect.left < window.innerWidth
        && rect.top < window.innerHeight
    }
    const describe = (element) => {
      const text = (element.getAttribute('aria-label')
        || element.getAttribute('title')
        || element.textContent
        || element.tagName).replace(/\s+/g, ' ').trim().slice(0, 80)
      const label = element.closest('label')
      const rect = label && visible(label) ? label.getBoundingClientRect() : element.getBoundingClientRect()
      return {
        tag: element.tagName.toLowerCase(),
        text,
        width: Number(rect.width.toFixed(1)),
        height: Number(rect.height.toFixed(1)),
      }
    }
    const touchViolations = mobileWidth <= 390
      ? Array.from(document.querySelectorAll(
        'button:not([disabled]), a[href], input:not([disabled]):not([type="hidden"]), select:not([disabled]), summary',
      ))
        .filter(visible)
        .map(describe)
        .filter((item) => item.width < 43.5 || item.height < 43.5)
        .slice(0, 40)
      : []
    const textClips = Array.from(document.querySelectorAll(
      'button, h1, h2, h3, summary, .topbar-pill, .mobile-context strong',
    ))
      .filter(visible)
      .filter((element) => element.scrollWidth > element.clientWidth + 1 || element.scrollHeight > element.clientHeight + 1)
      .map(describe)
      .slice(0, 20)
    const root = document.documentElement
    const body = document.body
    return {
      title: document.title,
      h1: document.querySelector('h1')?.textContent?.trim() || null,
      theme: root.getAttribute('data-theme'),
      root_width: root.clientWidth,
      root_scroll_width: root.scrollWidth,
      body_width: body.clientWidth,
      body_scroll_width: body.scrollWidth,
      horizontal_overflow: Math.max(root.scrollWidth - root.clientWidth, body.scrollWidth - body.clientWidth),
      touch_violations: touchViolations,
      text_clips: textClips,
      active_workspace: document.querySelector('.workspace-link.active')?.textContent?.replace(/\s+/g, ' ').trim() || null,
      mode_notice: document.querySelector('.mode-scope-notice')?.textContent?.replace(/\s+/g, ' ').trim() || null,
    }
  }, width)
}

async function main() {
  fs.mkdirSync(outputRoot, { recursive: true })
  const browser = await chromium.launch({ headless: true })
  const cases = []
  try {
    for (const theme of themes) {
      for (const [viewportName, width, height] of viewports) {
        const context = await browser.newContext({
          viewport: { width, height },
          colorScheme: theme,
          locale: 'zh-CN',
          reducedMotion: 'reduce',
        })
        await context.addInitScript(({ selectedTheme }) => {
          localStorage.setItem('quanthub.interface-mode', 'advanced')
          localStorage.setItem('qh-theme', selectedTheme)
          localStorage.setItem('quanthub.sidebar.collapsed', 'false')
          localStorage.setItem('quanthub.navigation.preferences.v1', JSON.stringify({
            pinnedRouteIds: [],
            hiddenWorkspaceIds: [],
            recentRouteIds: [],
          }))
        }, { selectedTheme: theme })

        for (const [route, slug] of routes) {
          const page = await context.newPage()
          const consoleErrors = []
          const ignoredConsoleErrors = []
          const pageErrors = []
          const failedRequests = []
          const badResponses = []
          const expectedResponses = []
          page.on('console', (message) => {
            if (message.type() !== 'error') return
            const text = cleanMessage(message.text())
            if (/^Failed to load resource: the server responded with a status of \d+/.test(text)) {
              ignoredConsoleErrors.push(text)
            } else {
              consoleErrors.push(text)
            }
          })
          page.on('pageerror', (error) => pageErrors.push(cleanMessage(error.message)))
          page.on('requestfailed', (request) => {
            if (['document', 'script', 'stylesheet', 'xhr', 'fetch', 'image'].includes(request.resourceType())) {
              failedRequests.push({
                url: request.url(),
                method: request.method(),
                reason: cleanMessage(request.failure()?.errorText || 'request failed'),
              })
            }
          })
          page.on('response', (response) => {
            if (response.status() >= 400 && response.url().startsWith(baseUrl)) {
              const pathname = new URL(response.url()).pathname
              const expected = (pathname === '/api/market/breadth' && response.status() === 500)
                || (pathname === '/api/config/okx-demo' && response.status() === 503)
              const target = expected ? expectedResponses : badResponses
              target.push({ status: response.status(), url: response.url() })
            }
          })

          let navigationError = null
          try {
            await page.goto(`${baseUrl}${route}`, { waitUntil: 'domcontentloaded', timeout: 30_000 })
            await page.waitForSelector('#main-content', { timeout: 15_000 })
            await page.addStyleTag({
              content: '*,*::before,*::after{animation-duration:.01ms!important;animation-delay:0ms!important;transition-duration:.01ms!important}',
            })
            await page.waitForTimeout(route === '/factor-research' ? 1800 : 1000)
          } catch (error) {
            navigationError = cleanMessage(error.message)
          }

          const inspection = navigationError
            ? null
            : await inspectPage(page, width)
          const screenshot = path.join(outputRoot, `${theme}-${viewportName}-${slug}.png`)
          await page.screenshot({ path: screenshot, fullPage: false })
          const pixels = await pixelStats(screenshot)
          const issues = []
          if (navigationError) issues.push(`navigation: ${navigationError}`)
          if (inspection?.horizontal_overflow > 1) issues.push(`horizontal overflow ${inspection.horizontal_overflow}px`)
          if (!inspection?.h1) issues.push('missing h1')
          if (inspection && inspection.theme !== theme) issues.push(`theme mismatch: ${inspection.theme}`)
          if (inspection?.mode_notice) issues.push('unexpected interface mode notice')
          if (inspection?.touch_violations.length) issues.push(`${inspection.touch_violations.length} mobile touch targets below 44px`)
          if (inspection?.text_clips.length) issues.push(`${inspection.text_clips.length} clipped text elements`)
          if (consoleErrors.length) issues.push(`${consoleErrors.length} console errors`)
          if (pageErrors.length) issues.push(`${pageErrors.length} page errors`)
          if (failedRequests.length) issues.push(`${failedRequests.length} failed primary requests`)
          if (badResponses.length) issues.push(`${badResponses.length} same-origin HTTP errors`)
          if (pixels.luminance_stddev < 2 || pixels.quantized_colors < 4) issues.push('screenshot appears blank')

          const record = {
            route,
            theme,
            viewport: { name: viewportName, width, height },
            screenshot: path.relative(repoRoot, screenshot).replace(/\\/g, '/'),
            inspection,
            pixels,
            console_errors: consoleErrors,
            ignored_console_errors: ignoredConsoleErrors,
            page_errors: pageErrors,
            failed_requests: failedRequests,
            bad_responses: badResponses,
            expected_degraded_responses: expectedResponses,
            issues,
          }
          cases.push(record)
          process.stdout.write(`${issues.length ? 'FAIL' : 'PASS'} ${theme} ${viewportName} ${route}${issues.length ? `: ${issues.join('; ')}` : ''}\n`)
          await page.close()
        }
        await context.close()
      }
    }
  } finally {
    await browser.close()
  }

  const failures = cases.filter((item) => item.issues.length > 0)
  const report = {
    task: 'R7 browser acceptance',
    generated_at: new Date().toISOString(),
    base_url: baseUrl,
    browser: 'Chromium',
    case_count: cases.length,
    passed_count: cases.length - failures.length,
    failed_count: failures.length,
    passed: failures.length === 0,
    routes: routes.map(([route]) => route),
    viewports: viewports.map(([name, width, height]) => ({ name, width, height })),
    themes,
    cases,
  }
  fs.writeFileSync(path.join(outputRoot, 'report.json'), `${JSON.stringify(report, null, 2)}\n`, 'utf8')
  process.stdout.write(`Report: ${path.join(outputRoot, 'report.json')}\n`)
  process.exitCode = failures.length ? 1 : 0
}

main().catch((error) => {
  console.error(error)
  process.exitCode = 1
})
