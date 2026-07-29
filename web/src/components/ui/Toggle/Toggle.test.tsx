import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Toggle } from './Toggle'

afterEach(cleanup)

describe('Toggle', () => {
  it('reports the next checked value', () => {
    const onChange = vi.fn()
    render(<Toggle checked={false} onChange={onChange} label="通知" />)

    fireEvent.click(screen.getByRole('switch', { name: '通知' }))

    expect(onChange).toHaveBeenCalledWith(true)
  })

  it('does not change when disabled', () => {
    const onChange = vi.fn()
    render(<Toggle checked disabled onChange={onChange} label="通知" />)

    fireEvent.click(screen.getByRole('switch', { name: '通知' }))

    expect(onChange).not.toHaveBeenCalled()
  })
})
