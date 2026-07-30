import { useEffect, useMemo, useState } from 'react'
import {
  ChevronDown,
  ExternalLink,
  Eye,
  EyeOff,
  FlaskConical,
  KeyRound,
  Save,
  Server,
  ShieldCheck,
} from 'lucide-react'
import { api } from '../../api/client'
import type {
  LLMConfigResp,
  LLMConnectionTestResp,
  LLMProviderId,
  LLMSettingsUpdate,
} from '../../api/types'
import { Button } from '../ui/Button/Button'
import { ConfirmActionButton } from '../ui/ConfirmActionButton/ConfirmActionButton'
import { Input } from '../ui/Input/Input'
import { SegmentedControl } from '../ui/SegmentedControl/SegmentedControl'
import s from './LLMProviderSettings.module.css'

interface LLMProviderSettingsProps {
  onChanged?: () => void
}

const FALLBACK_PROVIDERS: LLMConfigResp['providers'] = [
  {
    id: 'deepseek', label: 'DeepSeek', description: 'DeepSeek 官方 OpenAI 兼容接口',
    official_url: 'https://platform.deepseek.com', base_url: 'https://api.deepseek.com',
    model: 'deepseek-v4-flash', key_env: 'DEEPSEEK_API_KEY', configured: false,
  },
  {
    id: 'openai', label: 'OpenAI', description: 'OpenAI 官方 API',
    official_url: 'https://platform.openai.com', base_url: 'https://api.openai.com/v1',
    model: 'gpt-4o-mini', key_env: 'OPENAI_API_KEY', configured: false,
  },
  {
    id: 'custom', label: '兼容 API', description: '自托管或第三方 OpenAI Response 兼容接口',
    official_url: '', base_url: 'http://localhost:1234/v1', model: 'local-model',
    key_env: 'QUANTHUB_CUSTOM_LLM_API_KEY', configured: false,
  },
]

const EMPTY_FORM: LLMSettingsUpdate = {
  provider: 'deepseek',
  base_url: 'https://api.deepseek.com',
  model: 'deepseek-v4-flash',
  timeout: 60,
  max_retries: 3,
}

function formFromStatus(status: LLMConfigResp): LLMSettingsUpdate {
  return {
    provider: status.provider,
    base_url: status.base_url,
    model: status.model,
    timeout: status.timeout,
    max_retries: status.max_retries,
  }
}

export function LLMProviderSettings({ onChanged }: LLMProviderSettingsProps) {
  const [status, setStatus] = useState<LLMConfigResp | null>(null)
  const [form, setForm] = useState<LLMSettingsUpdate>(EMPTY_FORM)
  const [apiKey, setApiKey] = useState('')
  const [showKey, setShowKey] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [testResult, setTestResult] = useState<LLMConnectionTestResp | null>(null)
  const [discoveredModels, setDiscoveredModels] = useState<string[]>([])

  useEffect(() => {
    void loadConfig()
  }, [])

  const providers = status?.providers ?? FALLBACK_PROVIDERS
  const selectedProvider = providers.find((item) => item.id === form.provider) ?? providers[0]
  const isActiveProvider = status?.provider === form.provider
  const providerConfigured = selectedProvider?.configured ?? false
  const isDirty = Boolean(status) && (
    form.provider !== status?.provider
    || form.base_url !== status?.base_url
    || form.model !== status?.model
    || form.timeout !== status?.timeout
    || form.max_retries !== status?.max_retries
    || Boolean(apiKey.trim())
  )

  const providerOptions = useMemo(
    () => providers.map((item) => ({ value: item.id, label: item.label })),
    [providers],
  )

  async function loadConfig() {
    setLoading(true)
    setError('')
    try {
      const response = await api.llmConfig()
      setStatus(response)
      setForm(formFromStatus(response))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '模型配置读取失败')
    } finally {
      setLoading(false)
    }
  }

  function selectProvider(provider: LLMProviderId) {
    const preset = providers.find((item) => item.id === provider)
    if (!preset) return
    if (status?.provider === provider) {
      setForm(formFromStatus(status))
    } else {
      setForm({
        provider,
        base_url: preset.base_url,
        model: preset.model,
        timeout: 60,
        max_retries: 3,
      })
    }
    setApiKey('')
    setMessage('')
    setError('')
    setTestResult(null)
    setDiscoveredModels([])
  }

  async function save(event: React.FormEvent) {
    event.preventDefault()
    setSaving(true)
    setMessage('')
    setError('')
    setTestResult(null)
    try {
      const response = await api.updateLLMConfig({
        ...form,
        ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
      })
      setStatus(response)
      setForm(formFromStatus(response))
      setApiKey('')
      setMessage(`${response.provider_label} 配置已保存并热重载`)
      onChanged?.()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '模型配置保存失败')
    } finally {
      setSaving(false)
    }
  }

  async function testConnection() {
    setTesting(true)
    setMessage('')
    setError('')
    try {
      const result = await api.testLLMConnection()
      setTestResult(result)
      setDiscoveredModels(result.models)
      if (result.ok) setMessage(`${result.latency_ms} ms · ${result.models.length} 个可用模型`)
      else setError(result.error ?? '连接测试失败')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '连接测试失败')
    } finally {
      setTesting(false)
    }
  }

  async function removeKey() {
    const response = await api.removeLLMKey()
    setStatus(response)
    setForm(formFromStatus(response))
    setApiKey('')
    setTestResult(null)
    setMessage(`${response.provider_label} 密钥已移除`)
    onChanged?.()
  }

  return (
    <>
      <div className="card-head">
        <div className="card-title">
          模型供应商
          <span className="sub">OpenAI 兼容 API 与默认模型</span>
        </div>
        <span className={[s.statusBadge, status?.configured ? s.statusReady : s.statusPending].join(' ')}>
          <span aria-hidden="true" />
          {loading ? '读取中' : status?.configured ? `${status.provider_label} 已配置` : '等待配置'}
        </span>
      </div>

      <form className={s.form} onSubmit={save}>
        <div className={s.providerBand}>
          <SegmentedControl
            value={form.provider}
            onChange={(value) => selectProvider(value as LLMProviderId)}
            options={providerOptions}
            fullWidth
            className={s.providerSwitch}
          />
          <div className={s.providerMeta}>
            <span>{selectedProvider?.description}</span>
            {selectedProvider?.official_url ? (
              <a href={selectedProvider.official_url} target="_blank" rel="noreferrer">
                官方控制台 <ExternalLink size={14} aria-hidden="true" />
              </a>
            ) : (
              <span>自定义服务</span>
            )}
          </div>
        </div>

        <div className={s.fieldStack}>
          <label className={s.field}>
            <span><KeyRound size={15} aria-hidden="true" />API Key</span>
            <Input
              type={showKey ? 'text' : 'password'}
              variant="mono"
              autoComplete="new-password"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              placeholder={providerConfigured ? `留空则保留 ${isActiveProvider ? status?.masked : '现有密钥'}` : '输入 API Key'}
              invalid={!providerConfigured && !apiKey.trim()}
              suffix={(
                <button
                  type="button"
                  className={s.iconButton}
                  onClick={() => setShowKey((current) => !current)}
                  aria-label={showKey ? '隐藏 API Key' : '显示 API Key'}
                  title={showKey ? '隐藏 API Key' : '显示 API Key'}
                >
                  {showKey ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              )}
            />
            <small>{selectedProvider?.key_env} · {providerConfigured ? '已有密钥' : '未保存密钥'}</small>
          </label>

          <label className={s.field}>
            <span><Server size={15} aria-hidden="true" />API 请求地址</span>
            <Input
              type="url"
              variant="mono"
              value={form.base_url}
              onChange={(event) => setForm((current) => ({ ...current, base_url: event.target.value }))}
              placeholder="https://api.example.com/v1"
              required
            />
            <small>{form.base_url.replace(/\/+$/, '')}/models</small>
          </label>

          <label className={s.field}>
            <span>默认模型</span>
            <Input
              variant="mono"
              value={form.model}
              onChange={(event) => setForm((current) => ({ ...current, model: event.target.value }))}
              list="llm-discovered-models"
              placeholder="model-name"
              required
            />
            <datalist id="llm-discovered-models">
              {discoveredModels.map((model) => <option key={model} value={model} />)}
            </datalist>
            <small>{discoveredModels.length ? `${discoveredModels.length} 个模型可选择` : '连接测试后自动载入模型列表'}</small>
          </label>
        </div>

        <details className={s.advanced}>
          <summary><ChevronDown size={16} aria-hidden="true" />高级选项</summary>
          <div className={s.advancedGrid}>
            <label className={s.field}>
              <span>请求超时</span>
              <Input
                type="number"
                min={5}
                max={600}
                value={form.timeout}
                onChange={(event) => setForm((current) => ({ ...current, timeout: Number(event.target.value) }))}
                suffix="秒"
              />
            </label>
            <label className={s.field}>
              <span>失败重试</span>
              <Input
                type="number"
                min={0}
                max={10}
                value={form.max_retries}
                onChange={(event) => setForm((current) => ({ ...current, max_retries: Number(event.target.value) }))}
                suffix="次"
              />
            </label>
          </div>
        </details>

        <div className={s.securityNote}>
          <ShieldCheck size={17} aria-hidden="true" />
          <span>密钥仅保存在本机私有环境文件中，界面与接口只返回脱敏值。</span>
        </div>

        {isDirty && <div className={s.changeNotice}>当前有未保存修改，连接测试将继续使用已生效配置。</div>}
        {testResult && (
          <div className={[s.testResult, testResult.ok ? s.testSuccess : s.testFailure].join(' ')}>
            <b>{testResult.ok ? '连接正常' : '连接失败'}</b>
            <span>{testResult.status_code ? `HTTP ${testResult.status_code} · ` : ''}{testResult.latency_ms} ms</span>
            <code>{testResult.endpoint}</code>
          </div>
        )}

        <div className={s.actions}>
          <Button
            type="submit"
            variant="primary"
            icon={<Save size={16} />}
            loading={saving}
            disabled={loading || (!providerConfigured && !apiKey.trim())}
          >
            保存并应用
          </Button>
          <Button
            type="button"
            icon={<FlaskConical size={16} />}
            loading={testing}
            disabled={!status?.configured || isDirty || saving}
            onClick={() => void testConnection()}
          >
            连接测试
          </Button>
          {status?.configured && isActiveProvider && (
            <ConfirmActionButton
              label="移除密钥"
              title="移除模型密钥"
              description={`将从本机环境文件移除 ${status.provider_label} 的 API Key，模型请求会立即停止。`}
              confirmLabel="确认移除"
              onConfirm={removeKey}
            />
          )}
          <div className={s.feedback} aria-live="polite">
            {message && <span className={s.successMessage}>{message}</span>}
            {error && <span className={s.errorMessage}>{error}</span>}
          </div>
        </div>
      </form>
    </>
  )
}
