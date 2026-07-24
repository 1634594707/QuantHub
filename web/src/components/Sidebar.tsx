import { useEffect, useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import type { StrategyInfo } from '../api/types'
import {
  IconGrid,
  IconSignal,
  IconChart,
  IconCog,
  IconLayers,
  IconActivity,
  IconHeart,
  IconChevron,
} from './icons'

interface Props {
  collapsed: boolean
  mobileOpen: boolean
  onToggleCollapse: () => void
  onNavigate: () => void
  strategyCount?: number
  strategyList?: StrategyInfo[]
}

interface NavChild {
  key: string
  label: string
  to: string
}
interface NavItem {
  key: string
  label: string
  icon?: typeof IconGrid
  to?: string
  end?: boolean
  badge?: string
  children?: NavChild[]
}
type NavEntry = NavItem | { section: string }

const NAV = (strategyList: StrategyInfo[]): NavEntry[] => [
  { section: '分析' },
  { key: 'overview', label: '概览', icon: IconGrid, to: '/', end: true },
  { key: 'signal', label: '信号', icon: IconSignal, to: '/signals' },
  { key: 'backtest', label: '回测', icon: IconChart, to: '/backtest' },
  {
    key: 'strategy',
    label: '策略模块',
    icon: IconLayers,
    to: '/strategies',
    children: strategyList.map((s) => ({
      key: `strat-${s.name}`,
      label: s.name,
      to: `/strategies/${s.name}`,
    })),
  },
  { section: '工作台' },
  { key: 'pa', label: 'PA 分析工作台', icon: IconActivity, to: '/pa', badge: 'AI' },
  { key: 'sentiment', label: '情感分析', icon: IconHeart, to: '/sentiment' },
  { key: 'config', label: '配置', icon: IconCog, to: '/config' },
]

export default function Sidebar({
  collapsed,
  mobileOpen,
  onToggleCollapse,
  onNavigate,
  strategyList = [],
}: Props) {
  const location = useLocation()
  const onStratDetail = location.pathname.startsWith('/strategies/')
  const [stratOpen, setStratOpen] = useState(onStratDetail)

  useEffect(() => {
    if (onStratDetail) setStratOpen(true)
  }, [onStratDetail])

  const items: NavEntry[] = NAV(strategyList)

  return (
    <aside className={`sidebar ${collapsed ? 'collapsed' : ''} ${mobileOpen ? 'mobile-open' : ''}`} aria-label="主导航">
      <div className="brand">
        <div className="brand-logo">Q</div>
        <span className="brand-name">QuantHub</span>
        <button
          className="collapse-btn"
          onClick={onToggleCollapse}
          aria-label={collapsed ? '展开侧边栏' : '折叠侧边栏'}
          title={collapsed ? '展开' : '折叠'}
        >
          <IconChevron size={14} className={collapsed ? 'chevron-flip' : undefined} />
        </button>
      </div>

      <nav className="nav">
        {items.map((it, i) => {
          if ('section' in it) {
            return (
              <div key={`s${i}`} className="nav-section">
                {it.section}
              </div>
            )
          }

          const Icon = it.icon!

          // 可展开子菜单（策略模块）：折叠态下退化为图标链接到列表页
          if (it.children) {
            if (collapsed) {
              return (
                <NavLink
                  key={it.key}
                  to={it.to!}
                  className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
                  onClick={onNavigate}
                  title={it.label}
                >
                  <Icon className="nav-icon" />
                </NavLink>
              )
            }
            const isParentActive =
              location.pathname === it.to || location.pathname.startsWith(`${it.to}/`)
            return (
              <div key={it.key} className="nav-group">
                <button
                  type="button"
                  className={`nav-item ${isParentActive ? 'active' : ''}`}
                  onClick={() => setStratOpen((v) => !v)}
                  title={it.label}
                  aria-expanded={stratOpen}
                >
                  <Icon className="nav-icon" />
                  <span className="nav-label">{it.label}</span>
                  <IconChevron size={14} className={`nav-caret ${stratOpen ? 'open' : ''}`} />
                </button>
                {stratOpen && (
                  <div className="nav-sub">
                    {it.children.map((c) => (
                      <NavLink
                        key={c.key}
                        to={c.to}
                        className={({ isActive }) => `nav-subitem ${isActive ? 'active' : ''}`}
                        onClick={onNavigate}
                        title={c.label}
                      >
                        {c.label}
                      </NavLink>
                    ))}
                  </div>
                )}
              </div>
            )
          }

          return (
            <NavLink
              key={it.key}
              to={it.to!}
              end={it.end}
              className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
              onClick={onNavigate}
              title={it.label}
            >
              <Icon className="nav-icon" />
              <span className="nav-label">{it.label}</span>
              {it.badge && <span className="nav-badge">{it.badge}</span>}
            </NavLink>
          )
        })}
      </nav>

      <div className="sidebar-foot">
        <div className="avatar" style={{ width: 30, height: 30, fontSize: 12 }}>
          a
        </div>
        <span>v0.1 · 设计系统预览</span>
      </div>
    </aside>
  )
}
