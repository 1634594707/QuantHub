import { NavLink } from 'react-router-dom'
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
}

const NAV = (strategyCount: number) => [
  { section: '分析' },
  { key: 'overview', label: '概览', icon: IconGrid, to: '/', end: true },
  { key: 'signal', label: '信号', icon: IconSignal, to: '/signals' },
  { key: 'backtest', label: '回测', icon: IconChart, to: '/backtest' },
  { key: 'strategy', label: '策略模块', icon: IconLayers, to: '/strategies', badge: String(strategyCount) },
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
  strategyCount = 0,
}: Props) {
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
          <IconChevron
            size={14}
            className={collapsed ? 'chevron-flip' : undefined}
          />
        </button>
      </div>

      <nav className="nav">
        {NAV(strategyCount).map((it, i) =>
          'section' in it ? (
            <div key={`s${i}`} className="nav-section">
              {it.section}
            </div>
          ) : (
            <NavLink
              key={it.key}
              to={it.to}
              end={it.end}
              className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
              onClick={onNavigate}
              title={it.label}
            >
              <it.icon className="nav-icon" />
              <span className="nav-label">{it.label}</span>
              {it.badge && <span className="nav-badge">{it.badge}</span>}
            </NavLink>
          ),
        )}
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
