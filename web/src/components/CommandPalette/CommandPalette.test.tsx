import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { NAVIGATION_PREFERENCES_KEY } from '../../navigation/navigationPreferences'
import { CommandPalette } from './CommandPalette'

afterEach(() => {
  cleanup()
  localStorage.clear()
  vi.restoreAllMocks()
})

describe('CommandPalette navigation preferences', () => {
  it('shows visible recent routes and omits hidden workspaces from recent, pages, and actions', () => {
    localStorage.setItem(NAVIGATION_PREFERENCES_KEY, JSON.stringify({
      pinnedRouteIds: [],
      hiddenWorkspaceIds: ['market', 'trading'],
      recentRouteIds: ['radar', 'signal', 'config'],
    }))
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      callback(0)
      return 1
    })

    render(
      <MemoryRouter>
        <CommandPalette open onClose={() => undefined} interfaceMode="advanced" />
      </MemoryRouter>,
    )

    const recent = screen.getByRole('region', { name: '最近使用' })
    expect(within(recent).getByText('系统设置')).not.toBeNull()
    expect(within(recent).queryByText('信号雷达')).toBeNull()
    expect(within(recent).queryByText('信号审核')).toBeNull()

    const pages = screen.getByRole('region', { name: '页面' })
    expect(within(pages).queryByText('信号雷达')).toBeNull()
    expect(within(pages).queryByText('信号审核')).toBeNull()
    expect(screen.queryByRole('button', { name: /待审核信号/ })).toBeNull()
  })
})
