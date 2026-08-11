import { useState, useEffect } from 'react'
import { Link, Outlet, useLocation } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import Topbar from './components/Topbar'
import MobileNavigation from './components/MobileNavigation'
import { StatusBar } from './components/StatusBar/StatusBar'
import { CommandPalette } from './components/CommandPalette/CommandPalette'
import { api } from './api/client'
import type { ConnectionState } from './api/connection'
import { useApi } from './api/useApi'
import { isPathVisibleInMode, presentationForPath, routeIdForPath, workspaceForPath } from './navigation/workspaces'
import { useInterfaceMode, type InterfaceMode } from './hooks/useInterfaceMode'
import { useNavigationPreferences } from './navigation/navigationPreferences'
import { ApiRestartNotice } from './components/ApiRestartNotice'
import { InterfaceModeSetup } from './components/InterfaceModeSetup/InterfaceModeSetup'

export default function App() {
  const [interfaceMode, setInterfaceMode] = useInterfaceMode()
  if (!interfaceMode) return <InterfaceModeSetup onSelect={setInterfaceMode} />
  return <AppShell interfaceMode={interfaceMode} onInterfaceModeChange={setInterfaceMode} />
}

export function AppShell({
  interfaceMode,
  onInterfaceModeChange,
}: {
  interfaceMode: InterfaceMode
  onInterfaceModeChange: (mode: InterfaceMode) => void
}) {
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem('quanthub.sidebar.collapsed') === 'true')
  const [mobileOpen, setMobileOpen] = useState(false)
  const [cmdkOpen, setCmdkOpen] = useState(false)
  const { pathname, hash } = useLocation()
  const presentation = presentationForPath(pathname)
  const board = presentation.board
  const workspace = workspaceForPath(pathname)
  const { recordRecentRoute } = useNavigationPreferences()
  const advancedShellDataEnabled = interfaceMode === 'advanced'

  // 顶栏状态：健康检查 + 信号数量
  // signals 仅用于顶栏计数，重试间隔放宽到 30s，避免后端波动时高频轮询
  const health = useApi(() => api.health(), [], { pollInterval: 15000 })
  const session = useApi(() => api.governanceSession(), [], { retry: false, pollInterval: 60000 })
  const signals = useApi(
    () => api.signals(50, undefined, 'new'),
    [],
    { enabled: advancedShellDataEnabled, retryInterval: 30000, pollInterval: 15000 },
  )
  const strategies = useApi(() => api.strategies(), [], { enabled: advancedShellDataEnabled, pollInterval: 60000 })

  let connectionState: ConnectionState = 'online'
  if (health.errorKind === 'network' || (!health.loading && !health.data)) connectionState = 'offline'
  else if (session.errorStatus === 401) connectionState = 'unauthorized'
  else if (session.errorStatus === 403) connectionState = 'forbidden'
  else if (health.error || session.error || (advancedShellDataEnabled && (signals.error || strategies.error))) connectionState = 'degraded'
  // 后端短暂波动时 useApi 保留旧 data 并标记 reconnecting，状态栏据此显示「重连中」而非「离线」
  const reconnecting =
    connectionState === 'offline' && (health.reconnecting || signals.reconnecting || strategies.reconnecting)
  const signalCount = signals.data?.total ?? 0
  const strategyCount = strategies.data?.count ?? 0
  const lastUpdatedAt = Math.max(health.updatedAt ?? 0, session.updatedAt ?? 0, signals.updatedAt ?? 0, strategies.updatedAt ?? 0) || null
  const showContextStatus = connectionState !== 'online'
    || reconnecting
    || board === 'trading'
    || board === 'automation'

  useEffect(() => {
    if (hash === '#main-content') {
      document.getElementById('main-content')?.focus()
    }
  }, [hash])

  useEffect(() => {
    const routeId = routeIdForPath(pathname)
    if (routeId) recordRecentRoute(routeId)
  }, [pathname, recordRecentRoute])

  useEffect(() => {
    localStorage.setItem('quanthub.sidebar.collapsed', String(collapsed))
  }, [collapsed])

  // Ctrl/Cmd+Shift+K 避开 Chrome 对 Ctrl/Cmd+K 的地址栏搜索占用。
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setCmdkOpen((o) => !o)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <div
      className={`app-shell ${collapsed ? 'collapsed' : ''} ${mobileOpen ? 'mobile-open' : ''}`}
      data-board={board}
    >
      <button
        type="button"
        className="scrim"
        onClick={() => setMobileOpen(false)}
        aria-label="关闭导航"
      />
      <Sidebar
        collapsed={collapsed}
        mobileOpen={mobileOpen}
        onToggleCollapse={() => setCollapsed((c) => !c)}
        onNavigate={() => setMobileOpen(false)}
        strategyCount={strategyCount}
        strategyList={strategies.data?.strategies ?? []}
        interfaceMode={interfaceMode}
      />
      <div className="main">
        <Topbar
          onMenu={() => setMobileOpen((o) => !o)}
          health={health.data}
          connectionState={connectionState}
          signalCount={advancedShellDataEnabled ? signalCount : null}
          onOpenCmdk={() => setCmdkOpen(true)}
          workspaceLabel={workspace.label}
          pageLabel={presentation.label}
          interfaceMode={interfaceMode}
          onInterfaceModeChange={onInterfaceModeChange}
        />
        <ApiRestartNotice health={health.data} checking={health.loading} onCheck={health.refetch} />
        <main id="main-content" className="content" tabIndex={-1}>
          {!isPathVisibleInMode(interfaceMode, pathname) ? (
            <div className="mode-scope-notice" role="status">
              <div>
                <strong>此页面不在精简界面导航中</strong>
                <span>页面仍可使用；切换到完整界面后会恢复对应导航入口。</span>
              </div>
              <div>
                <Link to="/">返回总览</Link>
                <button type="button" onClick={() => onInterfaceModeChange('advanced')}>切换到完整界面</button>
              </div>
            </div>
          ) : null}
          <Outlet />
        </main>
        {showContextStatus ? <StatusBar
          connectionState={connectionState}
          reconnecting={reconnecting}
          boardLabel={presentation.label}
          updatedAt={lastUpdatedAt}
        /> : null}
        <CommandPalette open={cmdkOpen} onClose={() => setCmdkOpen(false)} interfaceMode={interfaceMode} />
        <MobileNavigation
          menuOpen={mobileOpen}
          onOpenMenu={() => setMobileOpen((open) => !open)}
          interfaceMode={interfaceMode}
        />
      </div>
    </div>
  )
}
