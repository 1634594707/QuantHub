import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../../api/client'
import type { OkxDemoCredentialStatus } from '../../api/types'
import { OkxDemoCredentials } from './OkxDemoCredentials'

const UNCONFIGURED: OkxDemoCredentialStatus = {
  ok: true,
  configured: false,
  environment: 'demo',
  source: 'local_vault',
  fingerprint: null,
  updated_at: null,
  validated_at: null,
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('OkxDemoCredentials', () => {
  it('saves all three fields and clears their plaintext values', async () => {
    vi.spyOn(api, 'okxDemoCredentialStatus').mockResolvedValue(UNCONFIGURED)
    const save = vi.spyOn(api, 'saveOkxDemoCredentials').mockResolvedValue({
      ...UNCONFIGURED,
      configured: true,
      fingerprint: '0123456789ab',
      updated_at: '2026-08-10T00:00:00+00:00',
    })
    render(<OkxDemoCredentials />)
    await screen.findByText('未配置')

    fireEvent.change(screen.getByLabelText('API Key'), { target: { value: 'api-value' } })
    fireEvent.change(screen.getByLabelText('Secret Key'), { target: { value: 'secret-value' } })
    fireEvent.change(screen.getByLabelText('API Passphrase'), { target: { value: 'pass-value' } })
    fireEvent.click(screen.getByRole('button', { name: '加密保存' }))

    await waitFor(() => expect(save).toHaveBeenCalledWith({
      api_key: 'api-value',
      secret_key: 'secret-value',
      passphrase: 'pass-value',
    }))
    expect(screen.getByLabelText<HTMLInputElement>('API Key').value).toBe('')
    expect(screen.getByLabelText<HTMLInputElement>('Secret Key').value).toBe('')
    expect(screen.getByLabelText<HTMLInputElement>('API Passphrase').value).toBe('')
    expect(screen.getByText('0123456789ab')).toBeTruthy()
  })

  it('tests the saved credential without exposing any secret field', async () => {
    vi.spyOn(api, 'okxDemoCredentialStatus').mockResolvedValue({
      ...UNCONFIGURED,
      configured: true,
      fingerprint: 'fedcba987654',
    })
    const testConnection = vi.spyOn(api, 'testOkxDemoConnection').mockResolvedValue({
      ...UNCONFIGURED,
      ok: true,
      configured: true,
      fingerprint: 'fedcba987654',
      latency_ms: 85,
      currency_count: 2,
      nonzero_currency_count: 1,
      permission: 'read_only_test',
    })
    render(<OkxDemoCredentials />)

    fireEvent.click(await screen.findByRole('button', { name: '测试只读连接' }))
    await waitFor(() => expect(testConnection).toHaveBeenCalledOnce())
    expect(await screen.findByText('OKX Demo 只读连接成功 · 85 ms')).toBeTruthy()
    expect(screen.getByText('2 个')).toBeTruthy()
  })
})
