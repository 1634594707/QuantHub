import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../../api/client'
import type { LLMConfigResp } from '../../api/types'
import { LLMProviderSettings } from './LLMProviderSettings'

const CONFIGURED_STATUS: LLMConfigResp = {
  ok: true,
  configured: true,
  provider: 'deepseek',
  provider_label: 'DeepSeek',
  official_url: 'https://platform.deepseek.com',
  key_env: 'DEEPSEEK_API_KEY',
  masked: 'sk-****7890',
  base_url: 'https://api.deepseek.com',
  models_endpoint: 'https://api.deepseek.com/models',
  model: 'deepseek-v4-flash',
  timeout: 60,
  max_retries: 3,
  providers: [
    {
      id: 'deepseek',
      label: 'DeepSeek',
      description: 'DeepSeek 官方 OpenAI 兼容接口',
      official_url: 'https://platform.deepseek.com',
      base_url: 'https://api.deepseek.com',
      model: 'deepseek-v4-flash',
      key_env: 'DEEPSEEK_API_KEY',
      configured: true,
    },
    {
      id: 'openai',
      label: 'OpenAI',
      description: 'OpenAI 官方 API',
      official_url: 'https://platform.openai.com',
      base_url: 'https://api.openai.com/v1',
      model: 'gpt-4o-mini',
      key_env: 'OPENAI_API_KEY',
      configured: false,
    },
    {
      id: 'custom',
      label: '兼容 API',
      description: '自托管或第三方 OpenAI Response 兼容接口',
      official_url: '',
      base_url: 'http://localhost:1234/v1',
      model: 'local-model',
      key_env: 'QUANTHUB_CUSTOM_LLM_API_KEY',
      configured: false,
    },
  ],
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('LLMProviderSettings', () => {
  it('loads the provider state without placing the saved key in the input', async () => {
    vi.spyOn(api, 'llmConfig').mockResolvedValue(CONFIGURED_STATUS)

    const { container } = render(<LLMProviderSettings />)

    await screen.findByText('DeepSeek 已配置')
    const keyInput = container.querySelector<HTMLInputElement>('input[type="password"]')
    expect(keyInput?.value).toBe('')
    expect(keyInput?.placeholder).toContain(CONFIGURED_STATUS.masked)
    expect(screen.getByText('DEEPSEEK_API_KEY · 已有密钥')).toBeTruthy()
  })

  it('saves a complete custom OpenAI-compatible provider configuration', async () => {
    vi.spyOn(api, 'llmConfig').mockResolvedValue(CONFIGURED_STATUS)
    const update = vi.spyOn(api, 'updateLLMConfig').mockImplementation(async (payload) => ({
      ...CONFIGURED_STATUS,
      configured: true,
      provider: 'custom',
      provider_label: '兼容 API',
      official_url: '',
      key_env: 'QUANTHUB_CUSTOM_LLM_API_KEY',
      masked: '****alue',
      base_url: payload.base_url,
      models_endpoint: `${payload.base_url}/models`,
      model: payload.model,
      timeout: payload.timeout,
      max_retries: payload.max_retries,
      providers: CONFIGURED_STATUS.providers.map((provider) => ({
        ...provider,
        configured: provider.id === 'custom' ? true : provider.configured,
      })),
    }))

    const { container } = render(<LLMProviderSettings />)
    await screen.findByText('DeepSeek 已配置')
    fireEvent.click(screen.getByRole('tab', { name: '兼容 API' }))

    const keyInput = container.querySelector<HTMLInputElement>('input[type="password"]')
    fireEvent.change(keyInput!, { target: { value: 'test-key-value' } })
    fireEvent.change(screen.getByDisplayValue('http://localhost:1234/v1'), {
      target: { value: 'https://gateway.example.test/v1' },
    })
    fireEvent.change(screen.getByDisplayValue('local-model'), {
      target: { value: 'research-model' },
    })
    fireEvent.click(screen.getByRole('button', { name: '保存并应用' }))

    await waitFor(() => {
      expect(update).toHaveBeenCalledWith({
        provider: 'custom',
        api_key: 'test-key-value',
        base_url: 'https://gateway.example.test/v1',
        model: 'research-model',
        timeout: 60,
        max_retries: 3,
      })
    })
    expect(await screen.findByText('兼容 API 配置已保存并热重载')).toBeTruthy()
  })

  it('disables connection testing while the form has unsaved changes', async () => {
    vi.spyOn(api, 'llmConfig').mockResolvedValue(CONFIGURED_STATUS)
    const testConnection = vi.spyOn(api, 'testLLMConnection')

    render(<LLMProviderSettings />)
    await screen.findByText('DeepSeek 已配置')
    fireEvent.change(screen.getByDisplayValue('deepseek-v4-flash'), {
      target: { value: 'deepseek-reasoner' },
    })

    expect(screen.getByText('当前有未保存修改，连接测试将继续使用已生效配置。')).toBeTruthy()
    const testButton = screen.getByRole('button', { name: '连接测试' }) as HTMLButtonElement
    expect(testButton.disabled).toBe(true)
    fireEvent.click(testButton)
    expect(testConnection).not.toHaveBeenCalled()
  })
})
