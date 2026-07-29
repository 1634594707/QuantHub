import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ResponsiveDetails } from './ResponsiveDetails'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function stubMatchMedia(matches: boolean) {
  vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({
    matches,
    media: '(max-width: 820px)',
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }))
}

describe('ResponsiveDetails', () => {
  it('starts collapsed on compact screens and exposes the record operation after expansion', () => {
    stubMatchMedia(true)
    const onAction = vi.fn()
    const { container } = render(
      <ResponsiveDetails compactAt={820} summary="查看成交与账本详情">
        <button type="button" onClick={onAction}>成交</button>
      </ResponsiveDetails>,
    )
    const details = container.querySelector('details')

    expect(details?.open).toBe(false)
    fireEvent.click(screen.getByText('查看成交与账本详情'))
    expect(details?.open).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: '成交' }))
    expect(onAction).toHaveBeenCalledOnce()
  })

  it('starts expanded above the compact breakpoint', () => {
    stubMatchMedia(false)
    const { container } = render(
      <ResponsiveDetails compactAt={820} summary="查看成交与账本详情">
        <span>账本同步状态</span>
      </ResponsiveDetails>,
    )

    expect(container.querySelector('details')?.open).toBe(true)
  })
})
