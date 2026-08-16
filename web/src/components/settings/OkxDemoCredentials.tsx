import { PlugZap, RefreshCw, Save } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import type { OkxDemoConnectionTest, OkxDemoCredentialStatus } from '../../api/types'
import { Button } from '../ui/Button/Button'
import { ConfirmActionButton } from '../ui/ConfirmActionButton/ConfirmActionButton'
import { Input } from '../ui/Input/Input'
import s from './OkxDemoCredentials.module.css'

const EMPTY_FORM = { api_key: '', secret_key: '', passphrase: '' }

function dateTime(value: string | null | undefined) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '尚未验证'
}

export function OkxDemoCredentials() {
  const [form, setForm] = useState(EMPTY_FORM)
  const [status, setStatus] = useState<OkxDemoCredentialStatus | null>(null)
  const [testResult, setTestResult] = useState<OkxDemoConnectionTest | null>(null)
  const [busy, setBusy] = useState<'load' | 'reload' | 'save' | 'test' | 'delete' | ''>('load')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  async function loadStatus(kind: 'load' | 'reload' = 'reload') {
    setBusy(kind)
    setError('')
    try {
      const result = await api.okxDemoCredentialStatus()
      setStatus(result)
      if (kind === 'reload') setMessage(result.available === false ? '' : '凭据库状态已刷新')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '读取凭据状态失败')
    } finally {
      setBusy('')
    }
  }

  useEffect(() => {
    let active = true
    api.okxDemoCredentialStatus()
      .then((result) => { if (active) setStatus(result) })
      .catch((reason) => { if (active) setError(reason instanceof Error ? reason.message : '读取凭据状态失败') })
      .finally(() => { if (active) setBusy('') })
    return () => { active = false }
  }, [])

  const complete = Object.values(form).every((value) => value.trim())

  async function save() {
    setBusy('save')
    setMessage('')
    setError('')
    try {
      const result = await api.saveOkxDemoCredentials({
        api_key: form.api_key.trim(),
        secret_key: form.secret_key.trim(),
        passphrase: form.passphrase.trim(),
      })
      setStatus(result)
      setTestResult(null)
      setForm(EMPTY_FORM)
      setMessage('凭据已由 Windows 当前用户加密保存，请执行只读连接测试')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '凭据保存失败')
    } finally {
      setBusy('')
    }
  }

  async function testConnection() {
    setBusy('test')
    setMessage('')
    setError('')
    try {
      const result = await api.testOkxDemoConnection()
      setTestResult(result)
      setStatus(result)
      if (result.ok) {
        setMessage(`OKX Demo 只读连接成功 · ${result.latency_ms ?? 0} ms`)
      } else {
        const diagnostic = [result.error_code, result.exchange_code].filter(Boolean).join(' / ')
        setError(`${result.error ?? 'OKX Demo 只读连接失败'}${diagnostic ? ` (${diagnostic})` : ''}`)
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'OKX Demo 只读连接失败')
    } finally {
      setBusy('')
    }
  }

  async function remove() {
    setBusy('delete')
    setMessage('')
    setError('')
    try {
      const result = await api.deleteOkxDemoCredentials()
      setStatus(result)
      setTestResult(null)
      setForm(EMPTY_FORM)
      setMessage('本机 OKX Demo 凭据已删除')
    } finally {
      setBusy('')
    }
  }

  return (
    <div className="card">
      <div className="card-head">
        <div className="card-title">
          OKX Demo 凭据
          <span className="sub">本机加密保存，仅执行账户只读连接测试</span>
        </div>
        <span className={status?.available === false ? s.unavailable : status?.configured ? s.configured : s.unconfigured}>
          {busy === 'load' ? '读取中' : status?.available === false ? '凭据库异常' : status?.configured ? '已配置' : '未配置'}
        </span>
      </div>
      <div className={s.body}>
        <div className={s.securityNotice}>
          当前固定为 OKX Demo。保存内容不写入项目、数据库或浏览器，Runner 仍保持 shadow，不会下单。
        </div>
        {status?.available === false && (
          <div className={s.recoveryNotice} role="alert">
            <div>
              <strong>{status.error ?? '本机凭据库不可用'}</strong>
              <span>{status.recovery_action ?? '请重新检测或重建凭据'}</span>
              {status.runtime_identity && <small>当前 API 账户：{status.runtime_identity}</small>}
            </div>
            <Button size="sm" icon={<RefreshCw size={15} />} loading={busy === 'reload'} onClick={() => void loadStatus()}>
              重新检测
            </Button>
          </div>
        )}
        <div className={s.fields}>
          <label>
            <span>API Key</span>
            <Input
              type="password"
              autoComplete="new-password"
              variant="mono"
              value={form.api_key}
              placeholder="填写 OKX 创建的 API Key"
              onChange={(event) => setForm((current) => ({ ...current, api_key: event.target.value }))}
            />
          </label>
          <label>
            <span>Secret Key</span>
            <Input
              type="password"
              autoComplete="new-password"
              variant="mono"
              value={form.secret_key}
              placeholder="填写创建时显示的 Secret Key"
              onChange={(event) => setForm((current) => ({ ...current, secret_key: event.target.value }))}
            />
          </label>
          <label>
            <span>API Passphrase</span>
            <Input
              type="password"
              autoComplete="new-password"
              variant="mono"
              value={form.passphrase}
              placeholder="创建 API Key 时设置，不是登录或查看密码"
              onChange={(event) => setForm((current) => ({ ...current, passphrase: event.target.value }))}
            />
          </label>
        </div>
        <div className={s.actions}>
          <Button size="sm" variant="primary" icon={<Save size={15} />} disabled={!complete} loading={busy === 'save'} onClick={() => void save()}>
            {status?.available === false ? '重建凭据' : status?.configured ? '替换凭据' : '加密保存'}
          </Button>
          <Button size="sm" icon={<PlugZap size={15} />} disabled={!status?.configured || status.available === false} loading={busy === 'test'} onClick={() => void testConnection()}>
            测试只读连接
          </Button>
          <ConfirmActionButton
            label="删除凭据"
            title="删除 OKX Demo 凭据"
            description="将删除当前 Windows 用户下的加密凭据文件。删除后 Runner 和连接测试都无法读取该凭据。"
            confirmLabel="确认删除"
            disabled={!status?.configured || status.available === false || busy === 'delete'}
            onConfirm={remove}
          />
        </div>
        {status?.configured && (
          <div className={s.statusGrid}>
            <span>凭据指纹<b>{status.fingerprint ?? '—'}</b></span>
            <span>保存位置<b>Windows 当前用户凭据库</b></span>
            <span>最近验证<b>{dateTime(status.validated_at)}</b></span>
            <span>测试权限<b>只读账户查询</b></span>
            {testResult?.ok && <span>返回币种<b>{testResult.currency_count ?? 0} 个</b></span>}
            {testResult?.ok && <span>非零币种<b>{testResult.nonzero_currency_count ?? 0} 个</b></span>}
          </div>
        )}
        {message && <div className={s.success} role="status">{message}</div>}
        {error && <div className={s.error} role="alert">{error}</div>}
      </div>
    </div>
  )
}
