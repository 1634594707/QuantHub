import { useEffect, useState } from 'react'

const API_KEY = 'quanthub:api-base'

export default function ConfigPage() {
  const [base, setBase] = useState(import.meta.env.VITE_API_BASE || 'http://localhost:8000')
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    const stored = localStorage.getItem(API_KEY)
    if (stored) setBase(stored)
  }, [])

  function save(e: React.FormEvent) {
    e.preventDefault()
    localStorage.setItem(API_KEY, base.trim() || 'http://localhost:8000')
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
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
        <form onSubmit={save} style={{ padding: 'var(--sp-3)', display: 'flex', flexDirection: 'column', gap: 'var(--sp-4)' }}>
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
            {saved && <span style={{ color: 'var(--up-ink)', fontSize: 'var(--fs-13)' }}>已保存，请刷新页面</span>}
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
