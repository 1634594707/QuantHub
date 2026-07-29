import { NavLink, useLocation } from 'react-router-dom'
import type { StrategyInfo } from '../api/types'
import {
  isWorkspaceItemActive,
  workspacesForMode,
  workspaceForPath,
} from '../navigation/workspaces'
import type { InterfaceMode } from '../hooks/useInterfaceMode'
import { IconChevron } from './icons'

interface Props {
  collapsed: boolean
  mobileOpen: boolean
  onToggleCollapse: () => void
  onNavigate: () => void
  strategyCount?: number
  strategyList?: StrategyInfo[]
  clock: Date
  interfaceMode: InterfaceMode
}

export default function Sidebar({
  collapsed,
  mobileOpen,
  onToggleCollapse,
  onNavigate,
  strategyCount,
  strategyList = [],
  clock,
  interfaceMode,
}: Props) {
  const location = useLocation()
  const activeWorkspace = workspaceForPath(location.pathname)
  const clockText = clock.toLocaleTimeString('zh-CN', { hour12: false })
  const visibleWorkspaces = workspacesForMode(interfaceMode)

  return (
    <aside
      className={`sidebar ${collapsed ? 'collapsed' : ''} ${mobileOpen ? 'mobile-open' : ''}`}
      aria-label="工作区导航"
    >
      <div className="workspace-rail">
        <NavLink className="rail-brand" to="/" onClick={onNavigate} aria-label="QuantHub 驾驶舱">
          <span>Q</span>
        </NavLink>

        <nav className="workspace-tabs" aria-label="一级工作区">
          {visibleWorkspaces.map((workspace) => {
            const Icon = workspace.icon
            const active = workspace.key === activeWorkspace.key
            return (
              <NavLink
                key={workspace.key}
                to={workspace.to}
                className={`workspace-tab ${active ? 'active' : ''}`}
                onClick={onNavigate}
                title={workspace.label}
                aria-label={workspace.label}
                aria-current={active ? 'page' : undefined}
              >
                <Icon size={20} />
                <span>{workspace.shortLabel}</span>
              </NavLink>
            )
          })}
        </nav>

        <button
          type="button"
          className="rail-collapse"
          onClick={onToggleCollapse}
          aria-label="展开侧边栏"
          aria-pressed={collapsed}
          title="展开侧边栏"
        >
          <IconChevron size={16} />
        </button>
      </div>

      <div className="context-nav-shell">
        <header className="context-nav-head">
          <div>
            <strong>QuantHub</strong>
            <span>{activeWorkspace.label}工作区</span>
          </div>
          <div className="context-nav-tools">
            <span className="context-nav-count">
              {activeWorkspace.key === 'strategy' ? `${strategyCount ?? 0} 策略` : `${activeWorkspace.items.length} 入口`}
            </span>
            <button
              type="button"
              className="context-collapse"
              onClick={onToggleCollapse}
              aria-label="收起侧边栏"
              title="收起侧边栏"
            >
              <IconChevron size={15} className="chevron-flip" />
            </button>
          </div>
        </header>

        <nav className="context-nav" aria-label={`${activeWorkspace.label}二级导航`}>
          {(visibleWorkspaces.find((workspace) => workspace.key === activeWorkspace.key)?.items ?? []).map((item) => {
            const Icon = item.icon
            const active = isWorkspaceItemActive(item, location.pathname)
            return (
              <NavLink
                key={item.key}
                to={item.to}
                end={item.end}
                className={`context-nav-item ${active ? 'active' : ''}`}
                onClick={onNavigate}
                aria-current={active ? 'page' : undefined}
              >
                <Icon size={17} />
                <span>{item.label}</span>
                {item.key === 'strategy' && strategyCount ? (
                  <span className="context-nav-badge">{strategyCount}</span>
                ) : null}
              </NavLink>
            )
          })}

          {activeWorkspace.key === 'strategy' && strategyList.length > 0 ? (
            <div className="context-strategies">
              <span className="context-strategies-label">已注册策略</span>
              {strategyList.map((strategy) => (
                <NavLink
                  key={strategy.name}
                  to={`/strategies/${strategy.name}`}
                  className={({ isActive }) => `context-strategy ${isActive ? 'active' : ''}`}
                  onClick={onNavigate}
                  title={strategy.description ? `${strategy.name} - ${strategy.description}` : strategy.name}
                >
                  <span className="context-strategy-dot" aria-hidden="true" />
                  <span>{strategy.name}</span>
                </NavLink>
              ))}
            </div>
          ) : null}
        </nav>

        <footer className="context-nav-foot" title={`v0.1 · 本地终端 · ${clockText}`}>
          <span>v0.1 · 本地终端</span>
          <span className="mono-num">{clockText}</span>
        </footer>
      </div>
    </aside>
  )
}
