import { useTheme } from '../theme/ThemeContext'
import { IconMenu, IconSearch, IconSun, IconMoon, IconBell } from './icons'
import { IconButton } from './ui/IconButton/IconButton'
import type { HealthResp } from '../api/types'
import { CONNECTION_LABELS, type ConnectionState } from '../api/connection'

interface Props {
  onMenu: () => void
  health: HealthResp | null
  connectionState: ConnectionState
  signalCount: number
  onOpenCmdk: () => void
  workspaceLabel: string
  pageLabel: string
}

export default function Topbar({
  onMenu,
  health,
  connectionState,
  signalCount,
  onOpenCmdk,
  workspaceLabel,
  pageLabel,
}: Props) {
  const { theme, toggle } = useTheme()
  const connection = CONNECTION_LABELS[connectionState]
  return (
    <header className="topbar">
      <IconButton className="topbar-menu" label="打开菜单" variant="default" size="md" onClick={onMenu}>
        <IconMenu />
      </IconButton>

      <div className="mobile-context" aria-label="当前工作区">
        <span>{workspaceLabel}</span>
        <strong>{pageLabel}</strong>
      </div>

      <IconButton
        className="mobile-search-button"
        label="打开全局检索"
        variant="default"
        size="md"
        onClick={onOpenCmdk}
      >
        <IconSearch />
      </IconButton>

      <label className="search">
        <IconSearch />
        <input
          placeholder="搜索标的、策略、信号…"
          aria-label="全局搜索"
          onClick={onOpenCmdk}
          readOnly
        />
      </label>

      <div className="topbar-spacer" />

      {/* 实时信号计数（来自信号总线） */}
      <div className="topbar-pill signal-pill" title="实时信号总线">
        <IconBell />
        <span className="mono">{signalCount}</span>
        <span className="pill-label">信号</span>
      </div>

      {/* 后端连接状态 */}
      <div
        className={`topbar-pill connection-pill ${connectionState}`}
        title={`${connection.detail}${health ? ` · ${health.strategies} 策略` : ''}`}
      >
        <span className="dot" />
        {connection.short}
      </div>

      <div className="market-status" title={health ? `版本 ${health.version} · live_trading=${health.live_trading}` : 'A股交易中'}>
        <span className="dot" />
        <span>{health?.live_trading ? '实盘模式' : '研究模式'}</span>
        {health && <span className="time">· {health.strategies} 策略</span>}
      </div>

      <IconButton
        label={theme === 'dark' ? '切换到亮色' : '切换到暗色'}
        variant="default"
        size="md"
        onClick={toggle}
        title={theme === 'dark' ? '亮色模式' : '暗色模式'}
      >
        {theme === 'dark' ? <IconSun /> : <IconMoon />}
      </IconButton>

      <div className="avatar" title="aplicity">
        a
      </div>
    </header>
  )
}
