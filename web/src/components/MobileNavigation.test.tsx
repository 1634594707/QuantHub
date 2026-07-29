import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { RECENT_RESEARCH_PATH_KEY } from '../navigation/recentResearch'
import MobileNavigation from './MobileNavigation'

afterEach(() => {
  cleanup()
  localStorage.clear()
})

function renderNavigation(path: string, interfaceMode: 'beginner' | 'advanced' = 'advanced') {
  render(
    <MemoryRouter initialEntries={[path]}>
      <MobileNavigation menuOpen={false} onOpenMenu={() => undefined} interfaceMode={interfaceMode} />
    </MemoryRouter>,
  )
  return screen.getByRole('navigation', { name: '移动端导航' })
}

describe('MobileNavigation', () => {
  it('shows the five beginner entries with their exact destinations', () => {
    const navigation = renderNavigation('/', 'beginner')
    const links = within(navigation).getAllByRole('link')

    expect(links.map((link) => link.textContent)).toEqual(['驾驶舱', '评估', '自选', '模拟', '设置'])
    expect(links.map((link) => link.getAttribute('href'))).toEqual([
      '/', '/evaluate', '/#watchlist', '/simulation', '/config',
    ])
  })

  it('activates more for an operations page', () => {
    const navigation = renderNavigation('/incidents')

    expect(within(navigation).getByRole('button', { name: '打开更多工作区' }).classList.contains('active')).toBe(true)
  })

  it('opens the stored research context from the advanced navigation', () => {
    localStorage.setItem(RECENT_RESEARCH_PATH_KEY, '/research/600519?market=a_shares&view=history')
    const navigation = renderNavigation('/')

    expect(within(navigation).getByRole('link', { name: '研究' }).getAttribute('href'))
      .toBe('/research/600519?market=a_shares&view=history')
  })
})
