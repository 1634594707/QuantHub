import { useState } from 'react'
import { Outlet } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import Topbar from './components/Topbar'
import { api } from './api/client'
import { useApi } from './api/useApi'

export default function App() {
  const [collapsed, setCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)

  // 顶栏状态：健康检查 + 信号数量
  const health = useApi(() => api.health(), [])
  const signals = useApi(() => api.signals(50), [])
  const strategies = useApi(() => api.strategies(), [])

  const apiOnline = !health.error && !signals.error
  const signalCount = signals.data?.count ?? 0
  const strategyCount = strategies.data?.count ?? 0

  return (
    <div className={`app-shell ${collapsed ? 'collapsed' : ''} ${mobileOpen ? 'mobile-open' : ''}`}>
      <div className="scrim" onClick={() => setMobileOpen(false)} />
      <Sidebar
        collapsed={collapsed}
        mobileOpen={mobileOpen}
        onToggleCollapse={() => setCollapsed((c) => !c)}
        onNavigate={() => setMobileOpen(false)}
        strategyCount={strategyCount}
      />
      <div className="main">
        <Topbar
          onMenu={() => setMobileOpen((o) => !o)}
          health={health.data}
          apiOnline={apiOnline}
          signalCount={signalCount}
        />
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
