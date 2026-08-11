import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { ThemeProvider } from '../theme/ThemeContext'
import Topbar from './Topbar'

afterEach(cleanup)

function renderTopbar(liveTrading = false) {
  return render(
    <MemoryRouter>
      <ThemeProvider>
        <Topbar
          onMenu={() => undefined}
          health={{ live_trading: liveTrading } as never}
          connectionState="online"
          signalCount={3}
          onOpenCmdk={() => undefined}
          workspaceLabel="总览"
          pageLabel="总览"
          interfaceMode="advanced"
          onInterfaceModeChange={() => undefined}
        />
      </ThemeProvider>
    </MemoryRouter>,
  )
}

describe('Topbar actionable status', () => {
  it('links the pending signal count to the review queue', () => {
    renderTopbar()
    expect(screen.getByRole('link', { name: '3 条待审核信号' }).getAttribute('href')).toBe('/signals?status=new')
  })

  it.each([
    [false, '/config', '打开系统设置'],
    [true, '/trading', '打开交易工作台'],
  ])('links connection context to the relevant destination', (liveTrading, href, titlePart) => {
    renderTopbar(liveTrading)
    const link = screen.getByTitle(new RegExp(titlePart))
    expect(link.getAttribute('href')).toBe(href)
  })
})
