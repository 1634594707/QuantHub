import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import type { ContractEnvelope, ContractStatus } from '../../api/types'
import { ContractStatusBar } from './ContractStatusBar'

afterEach(() => cleanup())

function contract(status: ContractStatus): ContractEnvelope<unknown> {
  return {
    status,
    source: { kind: 'runner', name: 'okx_runner', environment: 'demo' },
    observed_at: '2026-08-09T14:30:00+08:00',
    freshness: {
      age_seconds: status === 'stale' ? 90 : 3,
      ttl_seconds: 30,
      expired: status === 'stale',
    },
    error_code: status === 'error' ? 'TRADING_RUNNER_UNAVAILABLE' : null,
    message: status === 'error' ? '交易服务不可用' : null,
    hint: status === 'error' ? '检查 Runner 状态' : null,
    data: status === 'empty' || status === 'error' ? null : { value: 1 },
  }
}

describe('ContractStatusBar source and freshness states (M3-04)', () => {
  it.each([
    ['ok', '实时'],
    ['empty', '无数据'],
    ['stale', '已过期'],
    ['error', '源异常'],
  ] as const)('renders %s without substituting mock data', (status, label) => {
    render(<ContractStatusBar envelope={contract(status)} label="账户快照" />)
    expect(screen.queryByText(label)).not.toBeNull()
    expect(screen.queryByText('账户快照')).not.toBeNull()
    expect(screen.queryByText(/来源 OKX Runner/)).not.toBeNull()
    expect(screen.queryByText(/观测于/)).not.toBeNull()
    expect(screen.queryByText(/模拟数据|演示数据|mock/i)).toBeNull()
  })

  it('shows stable error code and operator hint for source errors', () => {
    render(<ContractStatusBar envelope={contract('error')} />)
    expect(screen.queryByText(/错误码 TRADING_RUNNER_UNAVAILABLE/)).not.toBeNull()
    expect(screen.queryByText(/处理建议：检查 Runner 状态/)).not.toBeNull()
  })

  it('distinguishes transport failure from a source error envelope', () => {
    render(<ContractStatusBar envelope={null} transportError="HTTP 502" />)
    expect(screen.queryByText('网关异常')).not.toBeNull()
    expect(screen.queryByText('HTTP 502')).not.toBeNull()
    expect(screen.queryByText('源异常')).toBeNull()
  })
})
