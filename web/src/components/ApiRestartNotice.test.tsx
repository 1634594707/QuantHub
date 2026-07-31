import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { HealthResp } from '../api/types'
import { ApiRestartNotice } from './ApiRestartNotice'

const health: HealthResp = {
  status: 'ok', time: '2026-07-31T11:00:00+08:00', strategies: 12,
  live_trading: false, version: '0.1.1', deployment_mode: 'local',
  started_at: '2026-07-31T10:00:00+08:00', build_id: 'old-build-id',
  current_source_build_id: 'new-build-id', restart_required: true,
}

afterEach(cleanup)

describe('ApiRestartNotice', () => {
  it('shows exact running and current source identifiers when restart is required', () => {
    const onCheck = vi.fn()
    render(<ApiRestartNotice health={health} checking={false} onCheck={onCheck} />)

    expect(screen.getByRole('alert')).toBeTruthy()
    expect(screen.getByText('API 源码已变化，需要重启服务')).toBeTruthy()
    expect(screen.getByText(/运行中 old-build-id · 当前源码 new-build-id/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '重新检查' }))
    expect(onCheck).toHaveBeenCalledTimes(1)
  })

  it('does not render when the running process matches the source tree', () => {
    render(<ApiRestartNotice health={{ ...health, restart_required: false }} checking={false} onCheck={() => undefined} />)
    expect(screen.queryByRole('alert')).toBeNull()
  })
})
