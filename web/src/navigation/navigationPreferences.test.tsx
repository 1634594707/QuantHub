import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { NAVIGATION_PREFERENCES_KEY, useNavigationPreferences } from './navigationPreferences'

function Harness() {
  const preferences = useNavigationPreferences()
  return (
    <>
      <output aria-label="偏好值">{JSON.stringify({
        pinnedRouteIds: preferences.pinnedRouteIds,
        hiddenWorkspaceIds: preferences.hiddenWorkspaceIds,
        recentRouteIds: preferences.recentRouteIds,
      })}</output>
      <button type="button" onClick={() => preferences.togglePinnedRoute('radar')}>钉选雷达</button>
      <button type="button" onClick={() => preferences.toggleWorkspaceHidden('market')}>隐藏研究</button>
      <button type="button" onClick={() => preferences.toggleWorkspaceHidden('settings')}>隐藏设置</button>
      <button type="button" onClick={() => preferences.recordRecentRoute('factor-factory')}>记录最近</button>
    </>
  )
}

afterEach(() => {
  cleanup()
  localStorage.clear()
})

describe('navigation preferences', () => {
  it('persists route identifiers and keeps recovery workspaces visible', () => {
    render(<Harness />)
    fireEvent.click(screen.getByRole('button', { name: '钉选雷达' }))
    fireEvent.click(screen.getByRole('button', { name: '隐藏研究' }))
    fireEvent.click(screen.getByRole('button', { name: '隐藏设置' }))
    fireEvent.click(screen.getByRole('button', { name: '记录最近' }))

    const stored = JSON.parse(localStorage.getItem(NAVIGATION_PREFERENCES_KEY) ?? '{}')
    expect(stored).toEqual({
      pinnedRouteIds: ['radar'],
      hiddenWorkspaceIds: ['market'],
      recentRouteIds: ['factor-factory'],
    })
    expect(screen.getByLabelText('偏好值').textContent).not.toContain('symbol')
    expect(screen.getByLabelText('偏好值').textContent).not.toContain('holding')
  })
})
