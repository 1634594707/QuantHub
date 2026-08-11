import { useTheme } from '../theme/ThemeContext'
import { IconMenu, IconSearch, IconSun, IconMoon, IconBell } from './icons'
import { IconButton } from './ui/IconButton/IconButton'
import type { HealthResp } from '../api/types'
import { CONNECTION_LABELS, type ConnectionState } from '../api/connection'
import type { InterfaceMode } from '../hooks/useInterfaceMode'
import { useState } from 'react'
import { Link } from 'react-router-dom'

interface Props {
  onMenu: () => void
  health: HealthResp | null
  connectionState: ConnectionState
  signalCount: number | null
  onOpenCmdk: () => void
  workspaceLabel: string
  pageLabel: string
  interfaceMode: InterfaceMode
  onInterfaceModeChange: (mode: InterfaceMode) => void
}

export default function Topbar({
  onMenu,
  health,
  connectionState,
  signalCount,
  onOpenCmdk,
  workspaceLabel,
  pageLabel,
  interfaceMode,
  onInterfaceModeChange,
}: Props) {
  const { theme, toggle } = useTheme()
  const [userMenuOpen, setUserMenuOpen] = useState(false)
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
          placeholder="搜索…"
          aria-label="全局搜索"
          onClick={onOpenCmdk}
          readOnly
        />
      </label>

      <div className="topbar-spacer" />

      {signalCount !== null ? <Link className="topbar-pill signal-pill" title="打开待审核信号" to="/signals?status=new" aria-label={`${signalCount} 条待审核信号`}>
        <IconBell />
        <span className="mono">{signalCount}</span>
      </Link> : null}

      <Link
        className={`topbar-pill connection-pill ${connectionState}`}
        title={`${connection.detail}；打开${health?.live_trading ? '交易工作台' : '系统设置'}`}
        to={health?.live_trading ? '/trading' : '/config'}
      >
        <span className="dot" />
        <span>{connection.short} · {health?.live_trading ? '实盘' : '研究'}</span>
      </Link>

      <IconButton
        label={theme === 'dark' ? '切换到亮色' : '切换到暗色'}
        variant="default"
        size="md"
        onClick={toggle}
        title={theme === 'dark' ? '亮色模式' : '暗色模式'}
      >
        {theme === 'dark' ? <IconSun /> : <IconMoon />}
      </IconButton>

      <div className="topbar-user-menu">
        <button
          type="button"
          className="avatar"
          title="界面与个人偏好"
          aria-label="打开界面与个人偏好"
          aria-expanded={userMenuOpen}
          onClick={() => setUserMenuOpen((open) => !open)}
        >
          a
        </button>
        {userMenuOpen ? (
          <div className="topbar-user-popover" role="menu" aria-label="界面范围">
            <button
              type="button"
              role="menuitemradio"
              aria-checked={interfaceMode === 'beginner'}
              onClick={() => { onInterfaceModeChange('beginner'); setUserMenuOpen(false) }}
            >精简界面</button>
            <button
              type="button"
              role="menuitemradio"
              aria-checked={interfaceMode === 'advanced'}
              onClick={() => { onInterfaceModeChange('advanced'); setUserMenuOpen(false) }}
            >完整界面</button>
          </div>
        ) : null}
      </div>
    </header>
  )
}
