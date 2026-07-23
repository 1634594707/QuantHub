import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { ApiKeyResp } from '../api/types'

const API_BASE_KEY = 'quanthub:api-base'

export default function ConfigPage() {
  const [base, setBase] = useState(import.meta.env.VITE_API_BASE || 'http://localhost:8000')
  const [baseSaved, setBaseSaved] = useState(false)

  const [key, setKey] = useState('')
  const [showKey, setShowKey] = useState(false)
  const [keyStatus, setKeyStatus] = useState<ApiKeyResp | null>(null)
  const [keyLoading, setKeyLoading] = useState(false)
  const [keySaved, setKeySaved] = useState(false)
  const [keyError, setKeyError] = useState('')

  useEffect(() => {
    const stored = localStorage.getItem(API_BASE_KEY)
    if (stored) setBase(stored)
    fetchKeyStatus()
  }, [])

  async function fetchKeyStatus() {
    try {
      const resp = await api.getApiKey()
      setKeyStatus(resp)
    } catch {
      setKeyStatus({ ok: false, configured: false, provider: 'deepseek', key_env: 'DEEPSEEK_API_KEY', masked: null })
    }
  }

  function saveBase(e: React.FormEvent) {
    e.preventDefault()
    localStorage.setItem(API_BASE_KEY, base.trim() || 'http://localhost:8000')
    setBaseSaved(true)
    setTimeout(() => setBaseSaved(false), 2000)
  }

  async function saveKey(e: React.FormEvent) {
    e.preventDefault()
    const trimmed = key.trim()
    if (!trimmed) return
    setKeyLoading(true)
    setKeyError('')
    try {
      const resp = await api.setApiKey(trimmed)
      setKeyStatus(resp)
      setKeySaved(true)
      setKey('')
      setTimeout(() => setKeySaved(false), 2000)
    } catch (err) {
      setKeyError(err instanceof Error ? err.message : '保存失败')
    } finally {
      setKeyLoading(false)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-4)', maxWidth: 720 }}>
      <div className="card">
        <div className="card-head">
          <div className="card-title">
            配置
            <span className="sub">本地运行参数</span>
          </div>
        </div>
        <form onSubmit={saveBase} style={{ padding: 'var(--sp-3)', display: 'flex', flexDirection: 'column', gap: 'var(--sp-4)' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            <label style={{ fontSize: 'var(--fs-13)', fontWeight: 600 }}>网关地址</label>
            <p className="muted" style={{ margin: 0, fontSize: 'var(--fs-12)' }}>
              修改后需刷新页面生效（当前版本通过 localStorage 持久化）
            </p>
            <input
              type="text"
              value={base}
              onChange={(e) => setBase(e.target.value)}
              style={{
                marginTop: 'var(--sp-1)',
                padding: '10px 12px',
                borderRadius: 'var(--r-md)',
                border: '1px solid var(--border)',
                background: 'var(--bg-elevated)',
                color: 'var(--text-1)',
                fontSize: 'var(--fs-14)',
                fontFamily: 'var(--font-mono)',
              }}
              placeholder="http://localhost:8000"
            />
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-3)' }}>
            <button
              type="submit"
              className="period-tab"
              style={{ background: 'var(--accent)', color: '#fff' }}
            >
              保存
            </button>
            {baseSaved && <span style={{ color: 'var(--up-ink)', fontSize: 'var(--fs-13)' }}>已保存，请刷新页面</span>}
          </div>
        </form>
      </div>

      <div className="card">
        <div className="card-head">
          <div className="card-title">
            API Key
            <span className="sub">{keyStatus?.configured ? '已配置' : '未配置'}</span>
          </div>
          {keyStatus && (
            <span
              style={{
                fontSize: 'var(--fs-12)',
                padding: '2px 8px',
                borderRadius: 'var(--r-pill)',
                background: keyStatus.configured ? 'rgba(22,199,132,0.14)' : 'var(--accent-weak)',
                color: keyStatus.configured ? 'var(--up-ink)' : 'var(--accent-strong)',
              }}
            >
              {keyStatus.configured ? keyStatus.masked : '未设置'}
            </span>
          )}
        </div>
        <form onSubmit={saveKey} style={{ padding: 'var(--sp-3)', display: 'flex', flexDirection: 'column', gap: 'var(--sp-4)' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            <label style={{ fontSize: 'var(--fs-13)', fontWeight: 600 }}>DeepSeek API Key</label>
            <p className="muted" style={{ margin: 0, fontSize: 'var(--fs-12)' }}>
              仅保存到本地网关 apps/api/.env，不会进入 Git 仓库；保存后无需重启网关即可生效
            </p>
            <div style={{ position: 'relative', marginTop: 'var(--sp-1)' }}>
              <input
                type={showKey ? 'text' : 'password'}
                value={key}
                onChange={(e) => setKey(e.target.value)}
                style={{
                  width: '100%',
                  boxSizing: 'border-box',
                  padding: '10px 40px 10px 12px',
                  borderRadius: 'var(--r-md)',
                  border: '1px solid var(--border)',
                  background: 'var(--bg-elevated)',
                  color: 'var(--text-1)',
                  fontSize: 'var(--fs-14)',
                  fontFamily: 'var(--font-mono)',
                }}
                placeholder="sk-..."
              />
              <button
                type="button"
                onClick={() => setShowKey((v) => !v)}
                style={{
                  position: 'absolute',
                  right: 8,
                  top: '50%',
                  transform: 'translateY(-50%)',
                  background: 'none',
                  border: 'none',
                  color: 'var(--text-2)',
                  cursor: 'pointer',
                  fontSize: 'var(--fs-12)',
                }}
              >
                {showKey ? '隐藏' : '显示'}
              </button>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-3)' }}>
            <button
              type="submit"
              className="period-tab"
              disabled={keyLoading || !key.trim()}
              style={{
                background: 'var(--accent)',
                color: '#fff',
                opacity: keyLoading || !key.trim() ? 0.6 : 1,
                cursor: keyLoading || !key.trim() ? 'not-allowed' : 'pointer',
              }}
            >
              {keyLoading ? '保存中…' : '保存并热重载'}
            </button>
            {keySaved && <span style={{ color: 'var(--up-ink)', fontSize: 'var(--fs-13)' }}>已保存并热重载</span>}
            {keyError && <span style={{ color: 'var(--down-ink)', fontSize: 'var(--fs-13)' }}>{keyError}</span>}
          </div>
        </form>
      </div>

      <div className="card">
        <div className="card-head">
          <div className="card-title">
            关于
            <span className="sub">QuantHub 设计系统预览</span>
          </div>
        </div>
        <div style={{ padding: 'var(--sp-3)', color: 'var(--text-2)', fontSize: 'var(--fs-13)', lineHeight: 1.6 }}>
          <p>版本：v0.1.0</p>
          <p>前端：React + Vite + TypeScript</p>
          <p>网关：FastAPI（端口 8000）</p>
          <p>启动命令：</p>
          <pre
            style={{
              margin: 'var(--sp-2) 0 0',
              padding: 'var(--sp-2) var(--sp-3)',
              background: 'var(--bg-subtle)',
              borderRadius: 'var(--r-md)',
              fontFamily: 'var(--font-mono)',
              fontSize: 'var(--fs-12)',
              overflow: 'auto',
            }}
          >
            uv run --package quanthub-api uvicorn apps.api.main:app --host 0.0.0.0 --port 8000
          </pre>
        </div>
      </div>
    </div>
  )
}
