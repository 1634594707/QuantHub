import { useTheme } from '../theme/ThemeContext'
import { IconMenu, IconSearch, IconSun, IconMoon, IconBell } from './icons'
import type { HealthResp } from '../api/types'

interface Props {
  onMenu: () => void
  health: HealthResp | null
  apiOnline: boolean
  signalCount: number
}

export default function Topbar({ onMenu, health, apiOnline, signalCount }: Props) {
  const { theme, toggle } = useTheme()
  return (
    <header className="topbar">
      <button className="icon-btn" onClick={onMenu} aria-label="打开菜单">
        <IconMenu />
      </button>

      <label className="search">
        <IconSearch />
        <input placeholder="搜索标的、策略、信号…" aria-label="全局搜索" />
        <span className="mono" style={{ fontSize: 11, opacity: 0.6 }}>
          ⌘K
        </span>
      </label>

      <div className="topbar-spacer" />

      {/* 实时信号计数（来自信号总线） */}
      <div className="topbar-pill" title="实时信号总线">
        <IconBell />
        <span className="mono">{signalCount}</span>
        <span className="pill-label">信号</span>
      </div>

      {/* 后端连接状态 */}
      <div
        className={`topbar-pill ${apiOnline ? 'online' : 'offline'}`}
        title={apiOnline ? `已连接网关 · ${health?.strategies ?? 0} 策略` : '后端未连接（模拟数据）'}
      >
        <span className="dot" />
        {apiOnline ? '实时' : '离线'}
      </div>

      <div className="market-status" title={health ? `版本 ${health.version} · live_trading=${health.live_trading}` : 'A股交易中'}>
        <span className="dot" />
        <span>{health?.live_trading ? '实盘模式' : '研究模式'}</span>
        {health && <span className="time">· {health.strategies} 策略</span>}
      </div>

      <button
        className="icon-btn"
        onClick={toggle}
        aria-label={theme === 'dark' ? '切换到亮色' : '切换到暗色'}
        title={theme === 'dark' ? '亮色模式' : '暗色模式'}
      >
        {theme === 'dark' ? <IconSun /> : <IconMoon />}
      </button>

      <div className="avatar" title="aplicity">
        a
      </div>
    </header>
  )
}
