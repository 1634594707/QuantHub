import { NavLink, useLocation } from 'react-router-dom'
import { getRecentResearchPath } from '../navigation/recentResearch'
import { workspaceForPath } from '../navigation/workspaces'
import type { InterfaceMode } from '../hooks/useInterfaceMode'
import { useNavigationPreferences } from '../navigation/navigationPreferences'
import { IconBeaker, IconChart, IconCog, IconGrid, IconMenu, IconSearch, IconSignal } from './icons'

interface Props {
  menuOpen: boolean
  onOpenMenu: () => void
  interfaceMode: InterfaceMode
}

export default function MobileNavigation({ menuOpen, onOpenMenu, interfaceMode }: Props) {
  const { pathname, hash } = useLocation()
  const workspace = workspaceForPath(pathname)
  const { hiddenWorkspaceIds } = useNavigationPreferences()
  const moreActive = workspace.key === 'strategy'
    || workspace.key === 'risk'
    || workspace.key === 'settings'
    || hiddenWorkspaceIds.includes(workspace.key)

  if (interfaceMode === 'beginner') {
    return <nav className="mobile-navigation beginner" aria-label="移动端导航">
      <NavLink to="/" end className={({ isActive }) => `mobile-nav-item ${isActive && !hash ? 'active' : ''}`}><IconGrid size={19} /><span>总览</span></NavLink>
      {!hiddenWorkspaceIds.includes('market') ? <>
        <NavLink to="/evaluate" className={`mobile-nav-item ${['/evaluate', '/news', '/pa', '/ensemble'].includes(pathname) || pathname.startsWith('/research/') ? 'active' : ''}`}><IconChart size={19} /><span>评估</span></NavLink>
        <NavLink to="/#watchlist" className={`mobile-nav-item ${pathname === '/' && hash === '#watchlist' ? 'active' : ''}`}><IconSearch size={19} /><span>自选</span></NavLink>
      </> : null}
      {!hiddenWorkspaceIds.includes('trading') ? <NavLink to="/simulation" className={`mobile-nav-item ${pathname === '/simulation' ? 'active' : ''}`}><IconBeaker size={19} /><span>模拟</span></NavLink> : null}
      <NavLink to="/config" className={`mobile-nav-item ${pathname === '/config' ? 'active' : ''}`}><IconCog size={19} /><span>设置</span></NavLink>
    </nav>
  }

  return (
    <nav className="mobile-navigation" aria-label="移动端导航">
      <NavLink to="/" end className={({ isActive }) => `mobile-nav-item ${isActive ? 'active' : ''}`}>
        <IconGrid size={19} />
        <span>总览</span>
      </NavLink>
      {!hiddenWorkspaceIds.includes('market') ? <NavLink
        to={getRecentResearchPath()}
        className={`mobile-nav-item ${workspace.key === 'market' ? 'active' : ''}`}
      >
        <IconChart size={19} />
        <span>研究</span>
      </NavLink> : null}
      {!hiddenWorkspaceIds.includes('trading') ? <NavLink
        to="/trading"
        className={`mobile-nav-item ${workspace.key === 'trading' ? 'active' : ''}`}
      >
        <IconSignal size={19} />
        <span>交易</span>
      </NavLink> : null}
      <button
        type="button"
        className={`mobile-nav-item ${menuOpen || moreActive ? 'active' : ''}`}
        onClick={onOpenMenu}
        aria-label="打开更多工作区"
        aria-expanded={menuOpen}
      >
        <IconMenu size={19} />
        <span>更多</span>
      </button>
    </nav>
  )
}
