import { NavLink, useLocation } from 'react-router-dom'
import packageMetadata from '../../package.json'
import type { StrategyInfo } from '../api/types'
import {
  isWorkspaceItemActive,
  navigationItemForId,
  workspacesForMode,
  workspaceForPath,
} from '../navigation/workspaces'
import type { InterfaceMode } from '../hooks/useInterfaceMode'
import type { WorkspaceProfile } from '../api/types'
import { strategyRouteId, useNavigationPreferences } from '../navigation/navigationPreferences'
import { IconChevron } from './icons'
import { Star } from 'lucide-react'
import { useLanguage } from '../i18n'

interface Props {
  collapsed: boolean
  mobileOpen: boolean
  onToggleCollapse: () => void
  onNavigate: () => void
  strategyCount?: number
  strategyList?: StrategyInfo[]
  interfaceMode: InterfaceMode
  workspaceProfile?: WorkspaceProfile | null
}

export default function Sidebar({
  collapsed,
  mobileOpen,
  onToggleCollapse,
  onNavigate,
  strategyCount,
  strategyList = [],
  interfaceMode,
  workspaceProfile,
}: Props) {
  const location = useLocation()
  const { locale, t } = useLanguage()
  const activeWorkspace = workspaceForPath(location.pathname)
  const {
    hiddenWorkspaceIds,
    pinnedRouteIds,
    recentRouteIds,
    togglePinnedRoute,
  } = useNavigationPreferences()
  const modeWorkspaces = workspacesForMode(interfaceMode, workspaceProfile)
  const visibleWorkspaces = modeWorkspaces.filter((workspace) => !hiddenWorkspaceIds.includes(workspace.key))
  const activeWorkspaceItems = modeWorkspaces.find((workspace) => workspace.key === activeWorkspace.key)?.items ?? []
  const pinnedItems = pinnedRouteIds
    .map(navigationItemForId)
    .filter((item): item is NonNullable<typeof item> => Boolean(
      item && modeWorkspaces.some((workspace) => workspace.items.some((candidate) => candidate.key === item.key)),
    ))
  const visibleStrategies = strategyList.filter((strategy) => {
    const routeId = strategyRouteId(strategy.name)
    return pinnedRouteIds.includes(routeId) || recentRouteIds.includes(routeId)
  })

  return (
    <aside
      className={`sidebar ${collapsed ? 'collapsed' : ''} ${mobileOpen ? 'mobile-open' : ''}`}
      aria-label={t('工作区导航')}
    >
      <div className="workspace-rail">
        <NavLink className="rail-brand" to="/" onClick={onNavigate} aria-label={`QuantHub ${t('驾驶舱')}`}>
          <span>Q</span>
        </NavLink>

        <nav className="workspace-tabs" aria-label={t('一级工作区')}>
          {visibleWorkspaces.map((workspace) => {
            const Icon = workspace.icon
            const active = workspace.key === activeWorkspace.key
            return (
              <NavLink
                key={workspace.key}
                to={workspace.to}
                className={`workspace-tab ${active ? 'active' : ''}`}
                onClick={onNavigate}
                title={t(workspace.label)}
                aria-label={t(workspace.label)}
                aria-current={active ? 'page' : undefined}
              >
                <Icon size={20} />
                <span>{t(workspace.shortLabel)}</span>
              </NavLink>
            )
          })}
        </nav>

        <button
          type="button"
          className="rail-collapse"
          onClick={onToggleCollapse}
          aria-label={t('展开侧边栏')}
          aria-pressed={collapsed}
          title={t('展开侧边栏')}
        >
          <IconChevron size={16} />
        </button>
      </div>

      <div className="context-nav-shell">
        <header className="context-nav-head">
          <div>
            <strong>QuantHub</strong>
            <span>{t(activeWorkspace.label)}{locale === 'en' ? ' ' : ''}{t('工作区')}</span>
          </div>
          <div className="context-nav-tools">
            <span className="context-nav-count">
              {activeWorkspace.key === 'strategy'
                ? locale === 'en' ? `${strategyCount ?? 0} ${t('策略')}` : `${strategyCount ?? 0} 策略`
                : locale === 'en' ? `${activeWorkspace.items.length} ${t('入口')}` : `${activeWorkspace.items.length} 入口`}
            </span>
            <button
              type="button"
              className="context-collapse"
              onClick={onToggleCollapse}
              aria-label={t('收起侧边栏')}
              title={t('收起侧边栏')}
            >
              <IconChevron size={15} className="chevron-flip" />
            </button>
          </div>
        </header>

        <nav className="context-nav" aria-label={`${t(activeWorkspace.label)} ${t('二级导航')}`}>
          {pinnedItems.length > 0 ? (
            <div className="context-pinned">
              <span className="context-strategies-label">{t('钉选入口')}</span>
              {pinnedItems.map((item) => {
                const Icon = item.icon
                return (
                  <NavLink key={item.key} to={item.to} className="context-pinned-item" onClick={onNavigate}>
                    <Icon size={15} />
                    <span>{t(item.label)}</span>
                  </NavLink>
                )
              })}
            </div>
          ) : null}

          {activeWorkspaceItems.map((item) => {
            const Icon = item.icon
            const active = isWorkspaceItemActive(item, location.pathname)
            return (
              <div className="context-nav-row" key={item.key}>
                <NavLink
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
                <button
                  type="button"
                  className={`context-pin ${pinnedRouteIds.includes(item.key) ? 'active' : ''}`}
                  onClick={() => togglePinnedRoute(item.key)}
                  aria-label={`${t(pinnedRouteIds.includes(item.key) ? '取消钉选' : '钉选')}${t(item.label)}`}
                  title={`${t(pinnedRouteIds.includes(item.key) ? '取消钉选' : '钉选')}${t(item.label)}`}
                >
                  <Star size={14} fill={pinnedRouteIds.includes(item.key) ? 'currentColor' : 'none'} />
                </button>
              </div>
            )
          })}

          {activeWorkspace.key === 'strategy' && visibleStrategies.length > 0 ? (
            <div className="context-strategies">
              <span className="context-strategies-label">{t('收藏与最近使用')}</span>
              {visibleStrategies.map((strategy) => (
                <div className="context-strategy-row" key={strategy.name}>
                  <NavLink
                    to={`/strategies/${strategy.name}`}
                    className={({ isActive }) => `context-strategy ${isActive ? 'active' : ''}`}
                    onClick={onNavigate}
                    title={strategy.description ? `${strategy.name} - ${strategy.description}` : strategy.name}
                  >
                    <span className="context-strategy-dot" aria-hidden="true" />
                    <span>{strategy.name}</span>
                  </NavLink>
                  <button
                    type="button"
                    className={`context-pin ${pinnedRouteIds.includes(strategyRouteId(strategy.name)) ? 'active' : ''}`}
                    onClick={() => togglePinnedRoute(strategyRouteId(strategy.name))}
                    aria-label={`${t(pinnedRouteIds.includes(strategyRouteId(strategy.name)) ? '取消收藏' : '收藏')}${t('策略')} ${strategy.name}`}
                    title={`${t(pinnedRouteIds.includes(strategyRouteId(strategy.name)) ? '取消收藏' : '收藏')}${t('策略')}`}
                  >
                    <Star size={14} fill={pinnedRouteIds.includes(strategyRouteId(strategy.name)) ? 'currentColor' : 'none'} />
                  </button>
                </div>
              ))}
            </div>
          ) : null}
        </nav>

        <footer className="context-nav-foot" title={`v${packageMetadata.version}`}>
          <span>v{packageMetadata.version}</span>
        </footer>
      </div>
    </aside>
  )
}
