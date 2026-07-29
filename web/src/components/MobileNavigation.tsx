import { NavLink, useLocation } from 'react-router-dom'
import { getRecentResearchPath } from '../navigation/recentResearch'
import { workspaceForPath } from '../navigation/workspaces'
import type { InterfaceMode } from '../hooks/useInterfaceMode'
import { IconBeaker, IconChart, IconCog, IconGrid, IconMenu, IconSearch, IconSignal } from './icons'

interface Props {
  menuOpen: boolean
  onOpenMenu: () => void
  interfaceMode: InterfaceMode
}

export default function MobileNavigation({ menuOpen, onOpenMenu, interfaceMode }: Props) {
  const { pathname, hash } = useLocation()
  const workspace = workspaceForPath(pathname)
  const moreActive = workspace.key === 'strategy' || workspace.key === 'operations'

  if (interfaceMode === 'beginner') {
    return <nav className="mobile-navigation beginner" aria-label="移动端导航">
      <NavLink to="/" end className={({ isActive }) => `mobile-nav-item ${isActive && !hash ? 'active' : ''}`}><IconGrid size={19} /><span>驾驶舱</span></NavLink>
      <NavLink to="/evaluate" className={`mobile-nav-item ${pathname === '/evaluate' || pathname.startsWith('/research/') ? 'active' : ''}`}><IconChart size={19} /><span>评估</span></NavLink>
      <NavLink to="/#watchlist" className={`mobile-nav-item ${pathname === '/' && hash === '#watchlist' ? 'active' : ''}`}><IconSearch size={19} /><span>自选</span></NavLink>
      <NavLink to="/simulation" className={`mobile-nav-item ${pathname === '/simulation' ? 'active' : ''}`}><IconBeaker size={19} /><span>模拟</span></NavLink>
      <NavLink to="/config" className={`mobile-nav-item ${pathname === '/config' ? 'active' : ''}`}><IconCog size={19} /><span>设置</span></NavLink>
    </nav>
  }

  return (
    <nav className="mobile-navigation" aria-label="移动端导航">
      <NavLink to="/" end className={({ isActive }) => `mobile-nav-item ${isActive ? 'active' : ''}`}>
        <IconGrid size={19} />
        <span>驾驶舱</span>
      </NavLink>
      <NavLink
        to={getRecentResearchPath()}
        className={`mobile-nav-item ${workspace.key === 'research' ? 'active' : ''}`}
      >
        <IconChart size={19} />
        <span>研究</span>
      </NavLink>
      <NavLink
        to="/signals"
        className={`mobile-nav-item ${workspace.key === 'execution' ? 'active' : ''}`}
      >
        <IconSignal size={19} />
        <span>信号</span>
      </NavLink>
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
