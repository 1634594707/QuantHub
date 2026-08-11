import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { NAVIGATION_PREFERENCES_KEY } from '../navigation/navigationPreferences'
import Sidebar from './Sidebar'

afterEach(() => {
  cleanup()
  localStorage.clear()
})

function renderSidebar(path: string, strategyList: React.ComponentProps<typeof Sidebar>['strategyList'] = []) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Sidebar
        collapsed={false}
        mobileOpen={false}
        onToggleCollapse={() => undefined}
        onNavigate={() => undefined}
        interfaceMode="advanced"
        strategyList={strategyList}
      />
    </MemoryRouter>,
  )
  return screen.getByRole('complementary', { name: '工作区导航' })
}

describe('Sidebar direct-route ownership', () => {
  it.each([
    ['/demo-lab', '交易'],
    ['/strategy-lab', '策略'],
    ['/governance', '设置'],
  ])('activates workspace %s for %s', (path, workspaceLabel) => {
    const sidebar = renderSidebar(path)
    expect(within(sidebar).getByRole('link', { name: workspaceLabel }).classList.contains('active')).toBe(true)
  })

  it.each([
    ['/strategy-lab', '策略实验'],
    ['/governance', '治理与审计'],
  ])('activates the retained secondary route %s', (path, itemLabel) => {
    const sidebar = renderSidebar(path)
    expect(within(sidebar).getByRole('link', { name: itemLabel }).getAttribute('aria-current')).toBe('page')
  })

  it('pins a secondary route and persists only its route id', () => {
    const sidebar = renderSidebar('/radar')

    fireEvent.click(within(sidebar).getByRole('button', { name: '钉选信号雷达' }))

    expect(within(sidebar).getAllByRole('link', { name: '信号雷达' })).toHaveLength(2)
    expect(JSON.parse(localStorage.getItem(NAVIGATION_PREFERENCES_KEY) ?? '{}').pinnedRouteIds).toEqual(['radar'])
  })

  it('shows only favorite or recent strategies in the context sidebar', () => {
    localStorage.setItem(NAVIGATION_PREFERENCES_KEY, JSON.stringify({
      pinnedRouteIds: ['strategy:favorite_strategy'],
      hiddenWorkspaceIds: [],
      recentRouteIds: ['strategy:recent_strategy'],
    }))
    const sidebar = renderSidebar('/strategies', [
      { name: 'favorite_strategy', description: 'favorite' },
      { name: 'recent_strategy', description: 'recent' },
      { name: 'other_strategy', description: 'not selected' },
    ] as never)

    expect(within(sidebar).getByRole('link', { name: 'favorite_strategy' })).not.toBeNull()
    expect(within(sidebar).getByRole('link', { name: 'recent_strategy' })).not.toBeNull()
    expect(within(sidebar).queryByRole('link', { name: 'other_strategy' })).toBeNull()
  })
})
