import { useEffect, useState } from 'react'
import { api, getApiToken, getBase, setApiToken } from '../api/client'
import type { BackupRetentionResult, BackupVerification, DataSourceCheckResult, DataSourceOperation, NotificationChannelName } from '../api/types'
import { useApi } from '../api/useApi'
import { AsyncStateBoundary } from '../components/ui/AsyncStateBoundary/AsyncStateBoundary'
import { Button } from '../components/ui/Button/Button'
import { ConfirmActionButton } from '../components/ui/ConfirmActionButton/ConfirmActionButton'
import { Input } from '../components/ui/Input/Input'
import { RefreshControl } from '../components/ui/RefreshControl/RefreshControl'
import { Toggle } from '../components/ui/Toggle/Toggle'
import { WorkspaceHeader } from '../components/WorkspaceHeader/WorkspaceHeader'
import { useInterfaceMode } from '../hooks/useInterfaceMode'
import { SegmentedControl } from '../components/ui/SegmentedControl/SegmentedControl'
import { LLMProviderSettings } from '../components/settings/LLMProviderSettings'
import { OkxDemoCredentials } from '../components/settings/OkxDemoCredentials'
import { navigationItemForId, WORKSPACES } from '../navigation/workspaces'
import { useNavigationPreferences } from '../navigation/navigationPreferences'
import s from './ConfigPage.module.css'

const API_BASE_KEY = 'quanthub:api-base'

export default function ConfigPage() {
  // 初始化为当前生效的 base（localStorage > VITE_API_BASE > '/api'）
  const [base, setBase] = useState(getBase())
  const [baseSaved, setBaseSaved] = useState('')
  const [baseError, setBaseError] = useState('')

  const [resetting, setResetting] = useState(false)
  const [backupBusy, setBackupBusy] = useState<string | null>(null)
  const [backupMessage, setBackupMessage] = useState('')
  const [backupError, setBackupError] = useState('')
  const [restoreConfirm, setRestoreConfirm] = useState<Record<string, string>>({})
  const [verification, setVerification] = useState<Record<string, BackupVerification>>({})
  const [retentionKeep, setRetentionKeep] = useState(14)
  const [retentionPreview, setRetentionPreview] = useState<BackupRetentionResult | null>(null)
  const [sourceCheckForm, setSourceCheckForm] = useState({ market: '', symbol: '', interval: '' })
  const [sourceChecking, setSourceChecking] = useState('')
  const [sourceCheckError, setSourceCheckError] = useState('')
  const [sourceCheckResults, setSourceCheckResults] = useState<Record<string, DataSourceCheckResult>>({})
  const [notificationEnabled, setNotificationEnabled] = useState(false)
  const [channelEnabled, setChannelEnabled] = useState<Record<NotificationChannelName, boolean>>({
    wecom: false,
    webhook: false,
    telegram: false,
  })
  const [notificationFields, setNotificationFields] = useState({
    wecom: { webhook_url: '', mentioned_mobile: '' },
    webhook: { url: '' },
    telegram: { bot_token: '', chat_id: '' },
  })
  const [notificationBusy, setNotificationBusy] = useState('')
  const [notificationMessage, setNotificationMessage] = useState('')
  const [notificationError, setNotificationError] = useState('')
  const [interfaceMode, setInterfaceMode] = useInterfaceMode()
  const {
    hiddenWorkspaceIds,
    pinnedRouteIds,
    togglePinnedRoute,
    toggleWorkspaceHidden,
  } = useNavigationPreferences()
  // M2-07：API 访问凭据的唯一设置入口（原治理页已下线）。
  // 安全约束：凭据只写不回显，界面仅展示「是否已配置 + 末 4 位」。
  const [credentialInput, setCredentialInput] = useState('')
  const [credentialSaved, setCredentialSaved] = useState(() => getApiToken())
  const [credentialNotice, setCredentialNotice] = useState('')
  const tradingHealth = useApi(() => api.tradingHealth(), [], { retry: false })
  const dataStatus = useApi(
    () => api.dataSourceStatus(),
    [],
    { retryInterval: 15000 },
  )
  const health = useApi(() => api.health(), [], { retry: false })
  const backupStatus = useApi(() => api.backupStatus(), [], { retry: false })
  const backups = useApi(() => api.backups(), [], { retry: false })
  const systemStatus = useApi(() => api.configSystemStatus(), [], { retry: false })
  const notifications = useApi(() => api.notificationStatus(), [], { retry: false })

  useEffect(() => {
    if (!notifications.data) return
    setNotificationEnabled(notifications.data.enabled)
    setChannelEnabled({
      wecom: notifications.data.channels.find((item) => item.channel === 'wecom')?.enabled ?? false,
      webhook: notifications.data.channels.find((item) => item.channel === 'webhook')?.enabled ?? false,
      telegram: notifications.data.channels.find((item) => item.channel === 'telegram')?.enabled ?? false,
    })
  }, [notifications.data])

  function saveBase(e: React.FormEvent) {
    e.preventDefault()
    const v = base.trim()
    setBaseError('')
    try {
      if (v) {
        localStorage.setItem(API_BASE_KEY, v)
      } else {
        localStorage.removeItem(API_BASE_KEY)
      }
      setBaseSaved(`当前生效：${getBase()}`)
      setTimeout(() => setBaseSaved(''), 4000)
    } catch (error) {
      setBaseError(error instanceof Error ? error.message : '网关地址保存失败')
    }
  }

  function resetLocalData() {
    localStorage.removeItem('qh.holdings.v1')
    localStorage.removeItem('qh.watchlist.v1')
    localStorage.removeItem('qh.portfolio.cash.v1')
    setResetting(true)
    // 清除后 useEditableHoldings/Watchlist 的 seeded state 仍为 true，
    // 需刷新页面让 hooks 重新挂载并从后端 /portfolio、/market/watchlist 播种
    setTimeout(() => window.location.reload(), 1200)
  }

  function refreshBackups() {
    void backupStatus.refetch()
    void backups.refetch()
  }

  async function runBackupAction(key: string, action: () => Promise<void>) {
    setBackupBusy(key)
    setBackupError('')
    setBackupMessage('')
    try {
      await action()
      refreshBackups()
    } catch (error) {
      setBackupError(error instanceof Error ? error.message : String(error))
    } finally {
      setBackupBusy(null)
    }
  }

  async function checkSource(source: string, operation: DataSourceOperation) {
    const market = sourceCheckForm.market
    const symbol = sourceCheckForm.symbol.trim()
    const interval = sourceCheckForm.interval.trim()
    if (!market || !symbol || !interval) return
    const resultKey = `${source}:${operation}`
    setSourceChecking(resultKey)
    setSourceCheckError('')
    try {
      const result = await api.checkDataSource({ market, source, operation, symbol, interval })
      setSourceCheckResults((current) => ({ ...current, [resultKey]: result }))
      void dataStatus.refetch()
    } catch (error) {
      setSourceCheckError(error instanceof Error ? error.message : '数据源检查失败')
    } finally {
      setSourceChecking('')
    }
  }

  function refreshNotifications() {
    void notifications.refetch()
    void systemStatus.refetch()
  }

  async function updateGlobalNotifications(enabled: boolean) {
    setNotificationBusy('global')
    setNotificationMessage('')
    setNotificationError('')
    try {
      await api.updateNotificationsEnabled(enabled)
      setNotificationEnabled(enabled)
      setNotificationMessage(enabled ? '通知总开关已开启' : '通知总开关已关闭')
      refreshNotifications()
    } catch (error) {
      setNotificationError(error instanceof Error ? error.message : '通知总开关更新失败')
    } finally {
      setNotificationBusy('')
    }
  }

  async function saveNotificationChannel(channel: NotificationChannelName) {
    setNotificationBusy(`save:${channel}`)
    setNotificationMessage('')
    setNotificationError('')
    try {
      if (channel === 'wecom') {
        const fields = notificationFields.wecom
        await api.updateNotificationChannel(channel, {
          enabled: channelEnabled.wecom,
          ...(fields.webhook_url.trim() ? { webhook_url: fields.webhook_url.trim() } : {}),
          ...(fields.mentioned_mobile.trim() ? { mentioned_mobile: fields.mentioned_mobile.trim() } : {}),
        })
        setNotificationFields((current) => ({ ...current, wecom: { webhook_url: '', mentioned_mobile: '' } }))
      } else if (channel === 'webhook') {
        const fields = notificationFields.webhook
        await api.updateNotificationChannel(channel, {
          enabled: channelEnabled.webhook,
          ...(fields.url.trim() ? { url: fields.url.trim() } : {}),
        })
        setNotificationFields((current) => ({ ...current, webhook: { url: '' } }))
      } else {
        const fields = notificationFields.telegram
        await api.updateNotificationChannel(channel, {
          enabled: channelEnabled.telegram,
          ...(fields.bot_token.trim() ? { bot_token: fields.bot_token.trim() } : {}),
          ...(fields.chat_id.trim() ? { chat_id: fields.chat_id.trim() } : {}),
        })
        setNotificationFields((current) => ({ ...current, telegram: { bot_token: '', chat_id: '' } }))
      }
      setNotificationMessage(`${channel} 通道配置已保存`)
      refreshNotifications()
    } catch (error) {
      setNotificationError(error instanceof Error ? error.message : `${channel} 通道保存失败`)
    } finally {
      setNotificationBusy('')
    }
  }

  async function testNotificationChannel(channel: NotificationChannelName) {
    setNotificationBusy(`test:${channel}`)
    setNotificationMessage('')
    setNotificationError('')
    try {
      const result = await api.testNotificationChannel(channel)
      setNotificationMessage(result.sent ? `${channel} 测试通知已发送` : `${channel} 测试通知未发送`)
    } catch (error) {
      setNotificationError(error instanceof Error ? error.message : `${channel} 测试发送失败`)
    } finally {
      setNotificationBusy('')
    }
  }

  return (
    <div className={s.page}>
      <WorkspaceHeader
        context="设置"
        title="系统设置"
        description="界面、连接与本地运行维护"
        metrics={[{
          label: '网关',
          value: health.data ? `v${health.data.version} · ${health.data.build_id}` : '版本：—',
        }]}
      />
      <nav className={s.sectionNav} aria-label="设置分区">
        <a href="#preferences">界面与个人偏好</a>
        <a href="#connections">连接与凭据</a>
        <a href="#maintenance">运行与维护</a>
      </nav>

      <section id="preferences" className={s.settingsSection} aria-labelledby="preferences-title">
        <header className={s.sectionHeading}>
          <div><h2 id="preferences-title">界面与个人偏好</h2><p>控制界面范围、工作区可见性与高频入口。</p></div>
        </header>
        <div className="card">
          <div className="card-head">
            <div className="card-title">界面范围<span className="sub">选择当前工作流需要的能力范围</span></div>
          </div>
          <div className={s.interfaceModeBody}>
            <SegmentedControl
              value={interfaceMode ?? 'beginner'}
              onChange={(value) => setInterfaceMode(value as 'beginner' | 'advanced')}
              options={[
                { value: 'beginner', label: '精简界面' },
                { value: 'advanced', label: '完整界面' },
              ]}
            />
            <span>{interfaceMode === 'beginner' ? '显示总览、自选、标的研究、模拟交易、账户账本与系统设置。' : '显示总览、市场研究、策略、交易、账户风控、设置六大工作区。'}</span>
          </div>
          <div className={s.workspacePreferences}>
            <div className={s.preferenceTitle}><strong>工作区显示</strong><span>总览与设置始终保留，确保偏好可以恢复。</span></div>
            <div className={s.workspaceToggles}>
              {WORKSPACES.filter((workspace) => ['market', 'strategy', 'trading', 'risk'].includes(workspace.key)).map((workspace) => {
                const visible = !hiddenWorkspaceIds.includes(workspace.key)
                return <div key={workspace.key}><span>{workspace.label}</span><Toggle size="sm" checked={visible} onChange={() => toggleWorkspaceHidden(workspace.key)} label={visible ? '显示' : '隐藏'} /></div>
              })}
            </div>
          </div>
          <div className={s.pinnedPreferences}>
            <div className={s.preferenceTitle}><strong>已钉选入口</strong><span>侧栏星标入口会在这里集中显示。</span></div>
            {pinnedRouteIds.length > 0 ? <div className={s.pinnedList}>{pinnedRouteIds.map((routeId) => {
              const item = navigationItemForId(routeId)
              const label = item?.label ?? (routeId.startsWith('strategy:') ? routeId.slice('strategy:'.length) : routeId)
              return <button type="button" key={routeId} onClick={() => togglePinnedRoute(routeId)} title={`取消钉选 ${label}`}>{label}<span>移除</span></button>
            })}</div> : <p className="muted">尚未钉选入口，可在侧栏使用星标添加。</p>}
          </div>
        </div>
      </section>

      <section id="connections" className={s.settingsSection} aria-labelledby="connections-title">
        <header className={s.sectionHeading}>
          <div><h2 id="connections-title">连接与凭据</h2><p>查看网关状态并管理只写凭据、交易通道与通知连接。</p></div>
        </header>
      <div className="card">
        <div className="card-head">
          <div className="card-title">
            运行状态
            <span className="sub">网关、模型、通知、调度器与安全边界</span>
          </div>
          <RefreshControl onRefresh={systemStatus.refetch} refreshing={systemStatus.loading || systemStatus.reconnecting} updatedAt={systemStatus.updatedAt} />
        </div>
        <AsyncStateBoundary
          loading={systemStatus.loading}
          error={systemStatus.error}
          reconnecting={systemStatus.reconnecting}
          hasData={systemStatus.data !== null}
          isEmpty={false}
          onRetry={systemStatus.refetch}
          loadingTitle="正在读取运行状态…"
          emptyTitle="暂无运行状态"
        >
          <div className={s.systemGrid}>
            <span>运行模式<b>{systemStatus.data?.gateway.live_trading ? '实盘开关已开启' : '研究 / 模拟'}</b></span>
            <span>部署模式<b>{systemStatus.data?.gateway.deployment_mode ?? '读取中'}</b></span>
            <span>源码标识<b>{systemStatus.data?.gateway.build_id ?? '读取中'}</b></span>
            <span>进程启动<b>{systemStatus.data?.gateway.started_at ? new Date(systemStatus.data.gateway.started_at).toLocaleString('zh-CN', { hour12: false }) : '读取中'}</b></span>
            <span>模型密钥<b>{systemStatus.data?.llm.configured ? `${systemStatus.data.llm.provider} 已配置` : '未配置'}</b></span>
            <span>A 股扩展<b>{systemStatus.data?.capabilities.a_shares.akshare ? 'akshare 可用' : 'akshare 未安装'}</b></span>
            <span>新闻情绪<b>{systemStatus.data ? `${systemStatus.data.capabilities.news_sentiment.engine} · ${systemStatus.data.capabilities.news_sentiment.model_available ? '模型可用' : '本地模型不可用'}` : '读取中'}</b></span>
            <span>调度器<b>{systemStatus.data?.scheduler.ok ? `${systemStatus.data.scheduler.enabled_count} / ${systemStatus.data.scheduler.total} 个任务启用` : '不可用'}</b></span>
            <span>通知<b>{systemStatus.data?.notifications.enabled ? (systemStatus.data.notifications.channels.map((item) => `${item.channel}:${item.configured ? '已配置' : '未配置'}`).join(' · ') || '未启用通道') : '已关闭'}</b></span>
            <span>实盘确认<b>{systemStatus.data?.live_confirm.enabled ? `${systemStatus.data.live_confirm.mode} · ${systemStatus.data.live_confirm.timeout_seconds}s` : '未启用'}</b></span>
            <span>备份<b>{systemStatus.data?.backups.supported === false ? '由 PostgreSQL 管理' : systemStatus.data?.backups.source_exists ? `${systemStatus.data.backups.backup_count} 份` : '数据库不存在'}</b></span>
          </div>
        </AsyncStateBoundary>
      </div>
      <div className="card">
        <div className="card-head">
          <div className="card-title">
            接入凭据
            <span className="sub">连接远程 / 局域网网关时所需的访问令牌</span>
          </div>
        </div>
        <div className={s.credentialBody}>
          <div className={s.credentialStatus}>
            当前状态：
            <b>
              {credentialSaved
                ? `已配置 · 末 4 位 ${credentialSaved.slice(-4)}`
                : '未配置（本机直连无需令牌）'}
            </b>
          </div>
          <Input
            type="password"
            autoComplete="off"
            value={credentialInput}
            placeholder="粘贴访问令牌；保存后不再回显"
            onChange={(event) => setCredentialInput(event.target.value)}
          />
          <div className={s.credentialActions}>
            <Button
              size="sm"
              variant="primary"
              disabled={!credentialInput.trim()}
              onClick={() => {
                const next = credentialInput.trim()
                setApiToken(next)
                setCredentialSaved(next)
                setCredentialInput('')
                setCredentialNotice('访问令牌已保存，后续请求将携带该凭据')
                void systemStatus.refetch()
              }}
            >
              保存
            </Button>
            <Button
              size="sm"
              variant="ghost"
              disabled={!credentialSaved}
              onClick={() => {
                setApiToken('')
                setCredentialSaved('')
                setCredentialInput('')
                setCredentialNotice('访问令牌已清除')
                void systemStatus.refetch()
              }}
            >
              清除
            </Button>
          </div>
          {credentialNotice && <div className={s.credentialNotice}>{credentialNotice}</div>}
        </div>
      </div>
      <OkxDemoCredentials />
      <div className="card">
        <div className="card-head">
          <div className="card-title">
            OKX 交易通道
            <span className="sub">Runner 连通性与实盘开关，只读展示</span>
          </div>
          <RefreshControl
            onRefresh={tradingHealth.refetch}
            refreshing={tradingHealth.loading || tradingHealth.reconnecting}
            updatedAt={tradingHealth.updatedAt}
          />
        </div>
        <div className={s.systemGrid}>
          <span>
            通道配置
            <b>{tradingHealth.data?.data?.configured ? '已配置 Runner 地址' : '未配置'}</b>
          </span>
          <span>
            连通性
            <b>
              {tradingHealth.error
                ? '网关不可达'
                : tradingHealth.data?.data?.reachable
                  ? '可达'
                  : '不可达'}
            </b>
          </span>
          <span>
            运行环境
            <b>{tradingHealth.data?.data?.environment ?? '未知'}</b>
          </span>
          <span>
            下单开关
            <b>{tradingHealth.data?.data?.trading_enabled ? '已开启' : '已关闭'}</b>
          </span>
          <span>
            实盘审批
            <b>{tradingHealth.data?.data?.live_approved ? '已审批' : '未审批'}</b>
          </span>
          <span>
            契约状态
            <b>{tradingHealth.data?.status ?? '未读取'}</b>
          </span>
        </div>
      </div>
      <div className="card">
        <div className="card-head">
          <div className="card-title">
            通知渠道
            <span className="sub">提醒事件的外部发送配置</span>
          </div>
          <RefreshControl onRefresh={refreshNotifications} refreshing={notifications.loading || notifications.reconnecting} updatedAt={notifications.updatedAt} />
        </div>
        <AsyncStateBoundary
          loading={notifications.loading}
          error={notifications.error}
          reconnecting={notifications.reconnecting}
          hasData={notifications.data !== null}
          isEmpty={false}
          onRetry={notifications.refetch}
          loadingTitle="正在读取通知配置…"
          emptyTitle="暂无通知配置"
        >
          <div className={s.notificationBody}>
            <div className={s.notificationMaster}>
              <div>
                <strong>通知总开关</strong>
                <span>关闭后提醒事件仍会记录，但不会向外部渠道发送。</span>
              </div>
              <Toggle
                checked={notificationEnabled}
                disabled={Boolean(notificationBusy)}
                onChange={(checked) => void updateGlobalNotifications(checked)}
                label={notificationEnabled ? '已开启' : '已关闭'}
              />
            </div>

            <div className={s.channelList}>
              <section className={s.channelSection}>
                <div className={s.channelHead}>
                  <div><strong>企业微信</strong><span>{notifications.data?.channels.find((item) => item.channel === 'wecom')?.configured ? '配置完整' : '配置不完整'}</span></div>
                  <Toggle checked={channelEnabled.wecom} disabled={Boolean(notificationBusy)} onChange={(checked) => setChannelEnabled((current) => ({ ...current, wecom: checked }))} label={channelEnabled.wecom ? '启用' : '停用'} size="sm" />
                </div>
                <div className={s.channelFields}>
                  <label>Webhook URL<Input type="password" variant="mono" autoComplete="new-password" value={notificationFields.wecom.webhook_url} onChange={(event) => setNotificationFields((current) => ({ ...current, wecom: { ...current.wecom, webhook_url: event.target.value } }))} placeholder="留空则保留现有值" /><small>当前：{notifications.data?.channels.find((item) => item.channel === 'wecom')?.fields.webhook_url ?? '未配置'}</small></label>
                  <label>提醒手机号<Input type="password" variant="mono" autoComplete="new-password" value={notificationFields.wecom.mentioned_mobile} onChange={(event) => setNotificationFields((current) => ({ ...current, wecom: { ...current.wecom, mentioned_mobile: event.target.value } }))} placeholder="留空则保留现有值" /><small>当前：{notifications.data?.channels.find((item) => item.channel === 'wecom')?.fields.mentioned_mobile ?? '未配置'}</small></label>
                </div>
                <div className={s.channelActions}><Button size="sm" variant="primary" loading={notificationBusy === 'save:wecom'} disabled={Boolean(notificationBusy)} onClick={() => void saveNotificationChannel('wecom')}>保存</Button><Button size="sm" loading={notificationBusy === 'test:wecom'} disabled={Boolean(notificationBusy) || !notifications.data?.channels.find((item) => item.channel === 'wecom')?.configured} onClick={() => void testNotificationChannel('wecom')}>发送测试</Button></div>
              </section>

              <section className={s.channelSection}>
                <div className={s.channelHead}>
                  <div><strong>Webhook</strong><span>{notifications.data?.channels.find((item) => item.channel === 'webhook')?.configured ? '配置完整' : '配置不完整'}</span></div>
                  <Toggle checked={channelEnabled.webhook} disabled={Boolean(notificationBusy)} onChange={(checked) => setChannelEnabled((current) => ({ ...current, webhook: checked }))} label={channelEnabled.webhook ? '启用' : '停用'} size="sm" />
                </div>
                <div className={s.channelFields}>
                  <label>URL<Input type="password" variant="mono" autoComplete="new-password" value={notificationFields.webhook.url} onChange={(event) => setNotificationFields((current) => ({ ...current, webhook: { url: event.target.value } }))} placeholder="留空则保留现有值" /><small>当前：{notifications.data?.channels.find((item) => item.channel === 'webhook')?.fields.url ?? '未配置'}</small></label>
                </div>
                <div className={s.channelActions}><Button size="sm" variant="primary" loading={notificationBusy === 'save:webhook'} disabled={Boolean(notificationBusy)} onClick={() => void saveNotificationChannel('webhook')}>保存</Button><Button size="sm" loading={notificationBusy === 'test:webhook'} disabled={Boolean(notificationBusy) || !notifications.data?.channels.find((item) => item.channel === 'webhook')?.configured} onClick={() => void testNotificationChannel('webhook')}>发送测试</Button></div>
              </section>

              <section className={s.channelSection}>
                <div className={s.channelHead}>
                  <div><strong>Telegram</strong><span>{notifications.data?.channels.find((item) => item.channel === 'telegram')?.configured ? '配置完整' : '配置不完整'}</span></div>
                  <Toggle checked={channelEnabled.telegram} disabled={Boolean(notificationBusy)} onChange={(checked) => setChannelEnabled((current) => ({ ...current, telegram: checked }))} label={channelEnabled.telegram ? '启用' : '停用'} size="sm" />
                </div>
                <div className={s.channelFields}>
                  <label>Bot Token<Input type="password" variant="mono" autoComplete="new-password" value={notificationFields.telegram.bot_token} onChange={(event) => setNotificationFields((current) => ({ ...current, telegram: { ...current.telegram, bot_token: event.target.value } }))} placeholder="留空则保留现有值" /><small>当前：{notifications.data?.channels.find((item) => item.channel === 'telegram')?.fields.bot_token ?? '未配置'}</small></label>
                  <label>Chat ID<Input type="password" variant="mono" autoComplete="new-password" value={notificationFields.telegram.chat_id} onChange={(event) => setNotificationFields((current) => ({ ...current, telegram: { ...current.telegram, chat_id: event.target.value } }))} placeholder="留空则保留现有值" /><small>当前：{notifications.data?.channels.find((item) => item.channel === 'telegram')?.fields.chat_id ?? '未配置'}</small></label>
                </div>
                <div className={s.channelActions}><Button size="sm" variant="primary" loading={notificationBusy === 'save:telegram'} disabled={Boolean(notificationBusy)} onClick={() => void saveNotificationChannel('telegram')}>保存</Button><Button size="sm" loading={notificationBusy === 'test:telegram'} disabled={Boolean(notificationBusy) || !notifications.data?.channels.find((item) => item.channel === 'telegram')?.configured} onClick={() => void testNotificationChannel('telegram')}>发送测试</Button></div>
              </section>
            </div>
            {notificationMessage && <div className={s.statusOk} role="status">{notificationMessage}</div>}
            {notificationError && <div className={s.statusErr} role="alert">{notificationError}</div>}
          </div>
        </AsyncStateBoundary>
      </div>
      </section>

      <section id="maintenance" className={s.settingsSection} aria-labelledby="maintenance-title">
        <header className={s.sectionHeading}>
          <div><h2 id="maintenance-title">运行与维护</h2><p>备份、数据源、模型接入和本地运行参数。</p></div>
        </header>
      <div className="card">
        <div className="card-head">
          <div className="card-title">
            数据库备份
            <span className="sub">创建、完整性验证、恢复与保留策略</span>
          </div>
          <RefreshControl
            onRefresh={refreshBackups}
            refreshing={backupStatus.loading || backupStatus.reconnecting || backups.loading || backups.reconnecting}
            updatedAt={backups.updatedAt}
          />
        </div>
        <AsyncStateBoundary
          loading={backupStatus.loading || backups.loading}
          error={backupStatus.error || backups.error}
          reconnecting={backupStatus.reconnecting || backups.reconnecting}
          hasData={backupStatus.data !== null && backups.data !== null}
          isEmpty={false}
          onRetry={refreshBackups}
          loadingTitle="正在读取备份状态…"
          emptyTitle="暂无备份状态"
        >
          <div className={s.backupBody}>
          <div className={s.backupStatusGrid}>
            <span>当前数据库<b>{backupStatus.data?.source_path || '读取中…'}</b></span>
            <span>受控备份目录<b>{backupStatus.data?.backup_directory || '读取中…'}</b></span>
            <span>备份数量<b>{backupStatus.data?.backup_count ?? 0}</b></span>
          </div>
          <div className={s.submitRow}>
            <Button
              variant="primary"
              size="sm"
              loading={backupBusy === 'create'}
              disabled={backupBusy !== null || backupStatus.data?.source_exists === false || backupStatus.data?.supported === false}
              onClick={() => void runBackupAction('create', async () => {
                const result = await api.createBackup()
                setBackupMessage(`已创建并验证：${result.backup.path}`)
              })}
            >创建备份</Button>
            {backupMessage && <span className={s.statusOk}>{backupMessage}</span>}
            {backupError && <span className={s.statusErr}>{backupError}</span>}
          </div>

          <div className={s.backupList}>
            {(backups.data?.backups ?? []).map((backup) => (
              <div className={s.backupRow} key={backup.name}>
                <div>
                  <strong>{backup.name}</strong>
                  <span>{backup.path}</span>
                  <small>{new Date(backup.modified_at * 1000).toLocaleString('zh-CN', { hour12: false })} · {(backup.bytes / 1024).toFixed(1)} KB</small>
                  {verification[backup.name] && (
                    <small className={verification[backup.name].ok ? s.statusOk : s.statusErr}>
                      integrity={verification[backup.name].integrity} · {verification[backup.name].table_count} 张表
                    </small>
                  )}
                </div>
                <div className={s.backupActions}>
                  <Button
                    size="sm"
                    variant="secondary"
                    loading={backupBusy === `verify:${backup.name}`}
                    disabled={backupBusy !== null}
                    onClick={() => void runBackupAction(`verify:${backup.name}`, async () => {
                      const result = await api.verifyBackup(backup.name)
                      setVerification((current) => ({ ...current, [backup.name]: result.verification }))
                      setBackupMessage(`完整性验证完成：${backup.path}`)
                    })}
                  >验证</Button>
                  <input
                    aria-label={`确认恢复 ${backup.name}`}
                    value={restoreConfirm[backup.name] ?? ''}
                    placeholder={`输入 ${backup.name}`}
                    disabled={backupBusy !== null}
                    onChange={(event) => setRestoreConfirm((current) => ({
                      ...current,
                      [backup.name]: event.target.value,
                    }))}
                  />
                  <Button
                    size="sm"
                    variant="danger"
                    loading={backupBusy === `restore:${backup.name}`}
                    disabled={backupBusy !== null || restoreConfirm[backup.name] !== backup.name}
                    onClick={() => void runBackupAction(`restore:${backup.name}`, async () => {
                      const result = await api.restoreBackup(backup.name, restoreConfirm[backup.name])
                      setRestoreConfirm((current) => ({ ...current, [backup.name]: '' }))
                      setBackupMessage(`恢复完成；恢复前备份：${result.safety_backup.path}`)
                    })}
                  >恢复</Button>
                </div>
              </div>
            ))}
            {!backups.loading && (backups.data?.backups.length ?? 0) === 0 && (
              <p className="muted">{backupStatus.data?.supported === false ? 'PostgreSQL 备份由部署环境管理。' : '暂无备份。创建后会在此显示精确文件路径。'}</p>
            )}
          </div>

          <div className={s.retentionBand}>
            <label>
              保留最新备份数
              <input
                type="number"
                min={1}
                max={365}
                value={retentionKeep}
                disabled={backupBusy !== null || backupStatus.data?.supported === false}
                onChange={(event) => setRetentionKeep(Number(event.target.value))}
              />
            </label>
            <Button
              size="sm"
              variant="secondary"
              disabled={backupBusy !== null || retentionKeep < 1 || backupStatus.data?.supported === false}
              loading={backupBusy === 'retention-preview'}
              onClick={() => void runBackupAction('retention-preview', async () => {
                const preview = await api.previewBackupRetention(retentionKeep)
                setRetentionPreview(preview)
                setBackupMessage(`保留策略预览完成：${preview.candidates.length} 个待删除文件`)
              })}
            >预览清理</Button>
          </div>
          {retentionPreview && (
            <div className={s.retentionPreview}>
              <strong>待删除文件（{retentionPreview.candidates.length}）</strong>
              {retentionPreview.candidates.length > 0 ? (
                <>
                  <ul>{retentionPreview.candidates.map((path) => <li key={path}>{path}</li>)}</ul>
                  <Button
                    size="sm"
                    variant="danger"
                    disabled={backupBusy !== null}
                    loading={backupBusy === 'retention-apply'}
                    onClick={() => void runBackupAction('retention-apply', async () => {
                      const result = await api.applyBackupRetention(
                        retentionPreview.keep,
                        retentionPreview.candidates,
                      )
                      setRetentionPreview(null)
                      setBackupMessage(`已删除 ${result.deleted} 个旧备份`)
                    })}
                  >确认删除上述文件</Button>
                </>
              ) : <span>当前无需删除。</span>}
            </div>
          )}
          </div>
        </AsyncStateBoundary>
      </div>

      <div className="card">
        <div className="card-head">
          <div className="card-title">
            运行管理
            <span className="sub">标的数据、账户、实验与作业</span>
          </div>
        </div>
        <div className={s.linkGrid}>
          <a href="/instruments"><b>标的与数据</b><span>Instrument 搜索与登记</span></a>
          <a href="/ledger"><b>账户账本</b><span>现金、成交、持仓与绩效</span></a>
          <a href="/strategy-lab"><b>策略实验</b><span>版本、实验、回测与对比</span></a>
          <a href="/automation"><b>作业调度</b><span>调度配置、运行与告警</span></a>
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <div className="card-title">
            配置
            <span className="sub">本地运行参数</span>
          </div>
        </div>
        <form onSubmit={saveBase} className={s.form}>
          <div className={s.fieldGroup}>
            <label className={s.fieldLabel}>网关地址</label>
            <Input
              type="text"
              variant="mono"
              value={base}
              onChange={(e) => setBase(e.target.value)}
              placeholder="/api 或 http://localhost:8001"
            />
          </div>

          {base.trim() !== getBase() && <div className={s.impactNotice}>影响范围：保存后的全部前端 API 请求；不修改后端配置。当前生效：<b>{getBase()}</b></div>}

          <div className={s.submitRow}>
            <Button type="submit" variant="primary" size="sm">
              保存
            </Button>
            {baseSaved && <span className={s.statusOk}>{baseSaved}</span>}
            {baseError && <span className={s.statusErr}>{baseError}</span>}
          </div>
        </form>
      </div>

      <div className="card">
        <LLMProviderSettings onChanged={systemStatus.refetch} />
      </div>

      <div className="card">
        <div className="card-head">
          <div className="card-title">
            数据源状态
            <span className="sub">运行时质量与缓存</span>
          </div>
          <RefreshControl onRefresh={dataStatus.refetch} refreshing={dataStatus.loading || dataStatus.reconnecting} updatedAt={dataStatus.updatedAt} />
        </div>
        <AsyncStateBoundary
          loading={dataStatus.loading}
          error={dataStatus.error}
          reconnecting={dataStatus.reconnecting}
          hasData={dataStatus.data !== null}
          isEmpty={false}
          onRetry={dataStatus.refetch}
          loadingTitle="正在读取数据源状态…"
          emptyTitle="暂无数据源状态"
        >
          <div className="data-source-status">
            <div className="data-source-configured">
              {dataStatus.data?.configured.map((item) => (
                <span key={item.market}>
                  <b>{item.market === 'a_shares' ? 'A股' : '加密'}</b>
                  {item.primary || '未配置'}
                  {item.fallbacks.length > 0 ? ` → ${item.fallbacks.join(' → ')}` : ''}
                </span>
              ))}
            </div>
              <div className="data-source-cache">
                <span>缓存命中率 <b>{((dataStatus.data?.cache.hit_rate ?? 0) * 100).toFixed(1)}%</b></span>
                <span>K线缓存 <b>{dataStatus.data?.cache.kline_entries ?? 0}</b></span>
                <span>文档缓存 <b>{dataStatus.data?.cache.document_entries ?? 0}</b></span>
              </div>
              <div className={s.sourceCheckForm}>
                <label>检查市场<select value={sourceCheckForm.market} onChange={(event) => setSourceCheckForm((current) => ({ ...current, market: event.target.value }))}><option value="">请选择</option>{dataStatus.data?.configured.map((item) => <option key={item.market} value={item.market}>{item.market}</option>)}</select></label>
                <label>标的<Input value={sourceCheckForm.symbol} onChange={(event) => setSourceCheckForm((current) => ({ ...current, symbol: event.target.value }))} /></label>
                <label>周期<Input value={sourceCheckForm.interval} onChange={(event) => setSourceCheckForm((current) => ({ ...current, interval: event.target.value }))} /></label>
              </div>
              {sourceCheckError && <div className={s.statusErr} role="alert">{sourceCheckError}</div>}
              <div className="data-source-table" role="table" aria-label="数据源运行状态">
                <div className="data-source-row head" role="row">
                  <span>来源 / 操作</span><span>调用</span><span>错误率</span><span>最近成功</span><span>最近错误</span><span>检查</span>
                </div>
                {dataStatus.data?.sources.length ? dataStatus.data.sources.map((source) => (
                  <div className="data-source-row" role="row" key={`${source.source}-${source.operation}`}>
                    <span><b>{source.source}</b><small>{source.operation}</small></span>
                    <span className="mono-num">{source.calls}</span>
                    <span className={source.error_rate > 0 ? 'warn' : 'ok'}>{(source.error_rate * 100).toFixed(1)}%</span>
                    <span>{source.last_success_at ? new Date(source.last_success_at * 1000).toLocaleString('zh-CN', { hour12: false }) : '—'}</span>
                    <span title={source.last_error || undefined}>{source.last_error || '—'}</span>
                    <span><Button size="sm" variant="link" disabled={!sourceCheckForm.market || !sourceCheckForm.symbol.trim() || !sourceCheckForm.interval.trim()} loading={sourceChecking === `${source.source}:${source.operation}`} onClick={() => void checkSource(source.source, source.operation)}>检查</Button>{sourceCheckResults[`${source.source}:${source.operation}`] && <small className={sourceCheckResults[`${source.source}:${source.operation}`].ok ? s.statusOk : s.statusErr}>{sourceCheckResults[`${source.source}:${source.operation}`].ok ? `${sourceCheckResults[`${source.source}:${source.operation}`].count} 条 · ${sourceCheckResults[`${source.source}:${source.operation}`].latency_ms} ms` : sourceCheckResults[`${source.source}:${source.operation}`].error}</small>}</span>
                  </div>
                )) : (
                  <p className="muted">暂无调用记录，读取行情或新闻后会显示。</p>
                )}
              </div>
          </div>
        </AsyncStateBoundary>
      </div>

      <div className="card">
        <div className="card-head">
          <div className="card-title">
            本地数据
            <span className="sub">持仓与关注列表</span>
          </div>
        </div>
        <div className={s.localBody}>
          <div>
            <div className={s.localTitle}>重置为后端种子</div>
            <p className={`muted ${s.localHint}`}>本地缓存：持仓、关注列表、组合现金</p>
          </div>
          <div className={s.submitRow}>
            <ConfirmActionButton
              label={resetting ? '重置中…' : '重置本地数据'}
              title="确认重置本地数据"
              description="将清除浏览器中的持仓、关注列表和本地组合现金缓存，页面刷新后重新从后端数据播种。"
              confirmLabel="确认重置"
              disabled={resetting}
              onConfirm={resetLocalData}
            />
            {resetting && (
              <span className={s.resettingHint}>
                已清除，正在刷新…
              </span>
            )}
          </div>
        </div>
      </div>

      </section>

    </div>
  )
}
