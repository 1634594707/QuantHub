import { useTheme } from '../theme/ThemeContext'
import { useLanguage } from '../i18n'
import { IconMenu, IconSearch, IconSun, IconMoon, IconBell } from './icons'
import { IconButton } from './ui/IconButton/IconButton'
import type { HealthResp, WorkspaceProfile } from '../api/types'
import { CONNECTION_LABELS, type ConnectionState } from '../api/connection'
import type { InterfaceMode } from '../hooks/useInterfaceMode'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { LanguageToggle } from './LanguageToggle'

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
  workspaceProfile?: WorkspaceProfile | null
  onWorkspaceProfileChange?: (profile: WorkspaceProfile) => Promise<void>
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
  workspaceProfile,
  onWorkspaceProfileChange,
}: Props) {
  const { theme, toggle } = useTheme()
  const { locale, t } = useLanguage()
  const [userMenuOpen, setUserMenuOpen] = useState(false)
  const connection = CONNECTION_LABELS[connectionState]
  return (
    <header className="topbar">
      <IconButton className="topbar-menu" label={t('打开菜单')} variant="default" size="md" onClick={onMenu}>
        <IconMenu />
      </IconButton>

      <div className="mobile-context" aria-label={t('当前工作区')}>
        <span>{workspaceLabel}</span>
        <strong>{pageLabel}</strong>
      </div>

      <IconButton
        className="mobile-search-button"
        label={t('打开全局检索')}
        variant="default"
        size="md"
        onClick={onOpenCmdk}
      >
        <IconSearch />
      </IconButton>

      <label className="search">
        <IconSearch />
        <input
          placeholder={t('搜索…')}
          aria-label={t('全局搜索')}
          onClick={onOpenCmdk}
          readOnly
        />
      </label>

      <div className="topbar-spacer" />

      {signalCount !== null ? <Link className="topbar-pill signal-pill" title={t('打开待审核信号')} to="/signals?status=new" aria-label={locale === 'en' ? `${signalCount} ${t('条待审核信号')}` : `${signalCount} 条待审核信号`}>
        <IconBell />
        <span className="mono">{signalCount}</span>
      </Link> : null}

      <Link
        className={`topbar-pill connection-pill ${connectionState}`}
        title={`${t(connection.detail)}; ${health?.live_trading ? t('打开交易工作台') : t('打开系统设置')}`}
        to={health?.live_trading ? '/trading' : '/config'}
      >
        <span className="dot" />
        <span>{t(connection.short)} · {health?.live_trading ? t('实盘') : t('研究')}</span>
      </Link>

      <LanguageToggle className="topbar-language" />

      <IconButton
        label={theme === 'dark' ? t('切换到亮色') : t('切换到暗色')}
        variant="default"
        size="md"
        onClick={toggle}
        title={theme === 'dark' ? t('亮色模式') : t('暗色模式')}
      >
        {theme === 'dark' ? <IconSun /> : <IconMoon />}
      </IconButton>

      <div className="topbar-user-menu">
        <button
          type="button"
          className="avatar"
          title={t('界面与个人偏好')}
          aria-label={t('打开界面与个人偏好')}
          aria-expanded={userMenuOpen}
          onClick={() => setUserMenuOpen((open) => !open)}
        >
          a
        </button>
        {userMenuOpen ? (
          <div className="topbar-user-popover" role="menu" aria-label={t('界面与工作台画像')}>
            {onWorkspaceProfileChange ? <div className="profile-picker" role="group" aria-label={t('工作台画像')}>
              {([
                ['stock_investor', '股票投资'],
                ['active_trader', '主动交易'],
                ['quant_research', '量化研究'],
                ['operations', '运营管理'],
                ['custom', '自定义'],
              ] as Array<[WorkspaceProfile, string]>).map(([id, label]) => (
                <button key={id} type="button" role="menuitemradio" aria-checked={workspaceProfile === id}
                  onClick={() => { void onWorkspaceProfileChange(id); setUserMenuOpen(false) }}>{t(label)}</button>
              ))}
            </div> : null}
            <div className="profile-language">
              <span>{t('界面语言')}</span>
              <LanguageToggle />
            </div>
            <button
              type="button"
              role="menuitemradio"
              aria-checked={interfaceMode === 'beginner'}
              onClick={() => { onInterfaceModeChange('beginner'); setUserMenuOpen(false) }}
            >{t('精简界面')}</button>
            <button
              type="button"
              role="menuitemradio"
              aria-checked={interfaceMode === 'advanced'}
              onClick={() => { onInterfaceModeChange('advanced'); setUserMenuOpen(false) }}
            >{t('完整界面')}</button>
          </div>
        ) : null}
      </div>
    </header>
  )
}
