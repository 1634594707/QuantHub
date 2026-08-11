import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { api } from './api/client'
import { ThemeProvider } from './theme/ThemeContext'
import { AppShell } from './App'

vi.mock('./components/ApiRestartNotice', () => ({ ApiRestartNotice: () => null }))

afterEach(() => {
  cleanup()
  localStorage.clear()
  vi.restoreAllMocks()
})

function renderShell(path: string) {
  const router = createMemoryRouter([
    {
      path: '/',
      element: (
        <ThemeProvider>
          <AppShell interfaceMode="beginner" onInterfaceModeChange={() => undefined} />
        </ThemeProvider>
      ),
      children: [
        { index: true, element: <div>总览内容</div> },
        { path: 'governance', element: <div>治理内容</div> },
      ],
    },
  ], { initialEntries: [path] })
  return render(<RouterProvider router={router} />)
}

describe('compact App shell', () => {
  it('keeps advanced shell collections idle and explains an advanced deep link', async () => {
    const health = vi.spyOn(api, 'health').mockResolvedValue({ live_trading: false } as never)
    vi.spyOn(api, 'governanceSession').mockResolvedValue({} as never)
    const signals = vi.spyOn(api, 'signals').mockResolvedValue({ total: 0, signals: [] } as never)
    const strategies = vi.spyOn(api, 'strategies').mockResolvedValue({ count: 0, strategies: [] } as never)

    renderShell('/governance')

    await waitFor(() => expect(health).toHaveBeenCalledTimes(1))
    expect(signals).not.toHaveBeenCalled()
    expect(strategies).not.toHaveBeenCalled()
    expect(screen.getByRole('status').textContent).toContain('此页面不在精简界面导航中')
    expect(screen.getByText('治理内容')).not.toBeNull()
    expect(screen.queryByTitle('打开待审核信号')).toBeNull()
  })
})
