import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, getApiToken } from '../api/client'
import type { ApiTokenRecord, GovernanceAuditLog } from '../api/types'
import { useApi } from '../api/useApi'
import { AsyncStateBoundary } from '../components/ui/AsyncStateBoundary/AsyncStateBoundary'
import { Button } from '../components/ui/Button/Button'
import { ConfirmActionButton } from '../components/ui/ConfirmActionButton/ConfirmActionButton'
import { SegmentedControl } from '../components/ui/SegmentedControl/SegmentedControl'
import { Table, type Column } from '../components/ui/Table/Table'
import { WorkspaceHeader } from '../components/WorkspaceHeader/WorkspaceHeader'
import { scrollElementWithinMainContent } from '../lib/scroll'
import common from './OperationsPages.module.css'
import s from './GovernancePage.module.css'

type GovernanceView = 'members' | 'tokens' | 'roles' | 'audit'

const ROLE_META: Record<string, { label: string; summary: string }> = {
  admin: { label: '管理员', summary: '管理成员、权限和全部系统设置' },
  operator: { label: '操作员', summary: '运行策略、自动化与日常运营任务' },
  reviewer: { label: '审核员', summary: '研究市场并审核信号，不改系统设置' },
  viewer: { label: '只读成员', summary: '只查看数据，适合作为新成员起点' },
}

const PERMISSION_LABELS: Record<string, string> = {
  'automation.manage': '管理自动化',
  'backups.manage': '管理备份',
  'config.manage': '修改系统设置',
  'ledger.write': '维护账本',
  'portfolio.write': '维护组合',
  read: '查看数据',
  'research.write': '发起研究',
  'signals.write': '审核信号',
  'simulation.write': '模拟交易',
  'strategy.write': '运行策略',
  'users.manage': '管理成员',
}

const DOMAIN_LABELS: Record<string, string> = {
  auth: '成员权限',
  automation: '自动化',
  backups: '备份',
  config: '系统设置',
  ledger: '账本',
  market: '行情',
  'market-data': '数据源',
  news: '新闻 AI',
  portfolio: '投资组合',
  research: '研究',
  signals: '信号',
  simulation: '模拟交易',
  strategies: '策略',
}

function roleMeta(role: string) {
  return ROLE_META[role] ?? { label: role, summary: '自定义职责' }
}

function formatTime(value: number | null) {
  if (value === null) return '从未'
  return new Date(value * 1000).toLocaleString('zh-CN', { hour12: false })
}

function formatAuditAction(action: string) {
  const [method = '', path = ''] = action.split(' ', 2)
  if (path.includes('/strategies/') && path.endsWith('/run')) return '运行策略'
  if (path === '/news/analyze') return '分析新闻'
  if (path === '/research/runs') return '创建研究任务'
  if (path === '/market/watchlist') return method === 'DELETE' ? '移除自选标的' : '添加自选标的'
  if (path === '/portfolio/holdings') return method === 'DELETE' ? '移除持仓' : '添加持仓'
  if (path.includes('/roles')) return '修改成员角色'
  if (path.includes('/auth/tokens')) return method === 'DELETE' ? '撤销访问令牌' : '创建访问令牌'
  if (path === '/auth/users') return '添加成员'
  return ({ POST: '提交变更', PUT: '更新内容', PATCH: '更新设置', DELETE: '删除内容' } as Record<string, string>)[method] ?? action
}

function formatAuditError(error: string | null) {
  if (!error) return '—'
  if (error.includes('422')) return '填写内容不完整'
  if (error.includes('404')) return '目标不存在'
  if (error.includes('401') || error.includes('403')) return '没有操作权限'
  return error
}

export default function GovernancePage() {
  const session = useApi(() => api.governanceSession(), [], { retry: false })
  const users = useApi(() => api.governanceUsers(), [], { retry: false })
  const roles = useApi(() => api.governanceRoles(), [], { retry: false })
  const tokens = useApi(() => api.governanceTokens(), [], { retry: false })
  const audit = useApi(() => api.governanceAudit(), [], { retry: false })
  const systemStatus = useApi(() => api.configSystemStatus(), [], { retry: false })
  const [view, setView] = useState<GovernanceView>('members')
  const [auditFilter, setAuditFilter] = useState('all')
  // 只读展示当前凭据配置状态；写入入口在 ConfigPage（M2-07 收口）
  const credentialToken = getApiToken()
  const credentialConfigured = credentialToken.length > 0
  const credentialTail = credentialToken.slice(-4)
  const [username, setUsername] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [newUserRoles, setNewUserRoles] = useState<string[]>(['viewer'])
  const [selectedUserId, setSelectedUserId] = useState('')
  const [selectedRoles, setSelectedRoles] = useState<string[]>([])
  const [tokenUserId, setTokenUserId] = useState('')
  const [tokenLabel, setTokenLabel] = useState('')
  const [expiryDays, setExpiryDays] = useState('30')
  const [createdSecret, setCreatedSecret] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loadingMoreAudit, setLoadingMoreAudit] = useState(false)

  const userRows = useMemo(() => users.data?.users ?? [], [users.data])
  const roleRows = useMemo(() => roles.data?.roles ?? [], [roles.data])
  const tokenRows = useMemo(() => tokens.data?.tokens ?? [], [tokens.data])
  const auditRows = useMemo(() => audit.data?.audit ?? [], [audit.data])
  const activeTokens = tokenRows.filter((item) => item.revoked_at === null)
  const failedAudit = auditRows.filter((item) => item.result !== 'succeeded')
  const visibleAudit = auditFilter === 'failed' ? failedAudit : auditRows

  function refresh() {
    void session.refetch()
    void users.refetch()
    void roles.refetch()
    void tokens.refetch()
    void audit.refetch()
    void systemStatus.refetch()
  }

  async function loadMoreAudit() {
    const cursor = audit.data?.next_cursor
    if (!cursor || loadingMoreAudit) return
    setLoadingMoreAudit(true)
    setError(null)
    try {
      const page = await api.governanceAudit(200, cursor)
      audit.setData((current) => {
        const ids = new Set(current.audit.map((item) => item.id))
        const additions = page.audit.filter((item) => !ids.has(item.id))
        return { ...current, audit: [...current.audit, ...additions], count: current.audit.length + additions.length, total: page.total, next_cursor: page.next_cursor }
      })
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '继续加载操作记录失败')
    } finally {
      setLoadingMoreAudit(false)
    }
  }

  async function act(key: string, message: string, fn: () => Promise<void>) {
    setBusy(key)
    setError(null)
    setNotice(null)
    try {
      await fn()
      setNotice(message)
      refresh()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
    } finally {
      setBusy(null)
    }
  }

  function toggleRole(role: string, current: string[], update: (roles: string[]) => void) {
    update(current.includes(role) ? current.filter((item) => item !== role) : [...current, role])
  }

  function startEditingUser(userId: string) {
    const user = userRows.find((item) => item.id === userId)
    if (!user) return
    setSelectedUserId(user.id)
    setSelectedRoles(user.roles)
    requestAnimationFrame(() => scrollElementWithinMainContent(document.getElementById('edit-member')))
  }

  const tokenColumns: Column<ApiTokenRecord>[] = [
    { key: 'label', header: '用途', render: (row) => (
      <div className={s.identity}><strong>{row.label}</strong><small>{row.username}</small></div>
    ) },
    { key: 'created_at', header: '创建时间', width: 165, render: (row) => formatTime(row.created_at) },
    { key: 'expires_at', header: '到期时间', width: 165, render: (row) => formatTime(row.expires_at) },
    { key: 'last_used_at', header: '最近使用', width: 165, render: (row) => formatTime(row.last_used_at) },
    { key: 'state', header: '状态', width: 80, render: (row) => (
      <span className={row.revoked_at === null ? s.active : s.revoked}>
        {row.revoked_at === null ? '可用' : '已撤销'}
      </span>
    ) },
    { key: 'action', header: '操作', width: 72, render: (row) => row.revoked_at === null ? (
      <ConfirmActionButton
        label="撤销"
        title="确认撤销访问令牌"
        description={`将撤销 ${row.username} 的“${row.label}”令牌。最近使用时间：${formatTime(row.last_used_at)}。撤销后，使用该令牌的设备和脚本会立即失去访问权限。`}
        confirmLabel="确认撤销"
        disabled={busy !== null}
        onConfirm={() => act(`revoke:${row.id}`, `${row.label} 已撤销`, async () => {
          await api.revokeGovernanceToken(row.id)
        })}
      />
    ) : '—' },
  ]

  const auditColumns: Column<GovernanceAuditLog>[] = [
    { key: 'created_at', header: '时间', width: 165, render: (row) => formatTime(row.created_at) },
    { key: 'action', header: '做了什么', render: (row) => (
      <div className={s.identity}>
        <strong>{formatAuditAction(row.action)}</strong>
        <small>{row.action}</small>
      </div>
    ) },
    { key: 'entity_type', header: '位置', width: 110, render: (row) => DOMAIN_LABELS[row.entity_type] ?? row.entity_type },
    { key: 'actor_id', header: '操作者', width: 130, render: (row) => row.actor_id === session.data?.user.id ? session.data.user.display_name : row.actor_id },
    { key: 'result', header: '结果', width: 80, render: (row) => (
      <span className={row.result === 'succeeded' ? s.active : s.failed}>
        {row.result === 'succeeded' ? '成功' : '失败'}
      </span>
    ) },
    { key: 'error', header: '说明', render: (row) => formatAuditError(row.error) },
  ]

  const deploymentMode = systemStatus.data?.gateway.deployment_mode
  const deploymentLabel = deploymentMode === 'local'
    ? '本机部署'
    : deploymentMode === 'lan'
      ? '局域网部署'
      : deploymentMode === 'postgresql'
        ? 'PostgreSQL 部署'
        : '部署状态读取中'
  const deploymentDescription = deploymentMode === 'local'
    ? '当前浏览器连接本机服务；是否需要令牌由服务端配置决定'
    : deploymentMode === 'lan'
      ? '当前服务面向局域网访问，成员权限和访问令牌由服务端强制校验'
      : deploymentMode === 'postgresql'
        ? '当前服务使用 PostgreSQL，并强制校验成员权限和访问令牌'
        : '正在读取系统配置中的 deployment_mode'

  return (
    <div className={common.page}>
      <WorkspaceHeader
        context="运营 / 成员权限"
        title="成员权限"
        description="添加成员，分配职责，管理外部访问"
        metrics={[
          { label: '当前身份', value: session.data?.user.display_name ?? '未连接' },
          { label: '成员', value: userRows.length },
          { label: '可用令牌', value: activeTokens.length },
          { label: '管理状态', value: '正常' },
        ]}
      />

      <section className={s.accessSummary} aria-label="当前访问状态">
        <div className={s.accessState}>
          <span className={s.statusDot} aria-hidden="true" />
          <div><strong>{deploymentLabel}</strong><span>{deploymentDescription}</span></div>
        </div>
        <div className={s.nextAction}>
          <span>建议下一步</span>
          <strong>{userRows.length <= 1 ? '添加第一位成员，并先授予只读权限' : '检查成员职责是否仍符合实际分工'}</strong>
        </div>
        <Button size="sm" variant="primary" onClick={() => {
          setView('members')
          requestAnimationFrame(() => scrollElementWithinMainContent(document.getElementById('add-member')))
        }}>添加成员</Button>
      </section>

      {error && <div className={common.error} role="alert">操作未完成：{error}</div>}
      {notice && <div className={common.success} role="status">{notice}</div>}

      <div className={s.viewBar}>
        <SegmentedControl
          value={view}
          onChange={(value) => setView(value as GovernanceView)}
          fullWidth
          options={[
            { value: 'members', label: `成员 ${userRows.length}` },
            { value: 'tokens', label: `访问令牌 ${activeTokens.length}` },
            { value: 'roles', label: '角色说明' },
            { value: 'audit', label: `操作记录 ${audit.data?.total ?? auditRows.length}` },
          ]}
        />
      </div>

      {view === 'members' && (
        <div className={s.viewContent} role="tabpanel">
          <div className={s.memberWorkspace}>
            <section className={common.section}>
              <div className={common.sectionHead}><div><h2>现有成员</h2><span>点击“修改职责”可直接调整权限</span></div></div>
              <AsyncStateBoundary loading={users.loading} error={users.error} reconnecting={users.reconnecting} hasData={users.data !== null}
                isEmpty={userRows.length === 0} onRetry={users.refetch} loadingTitle="正在读取成员…" emptyTitle="还没有成员">
                <div className={s.memberList}>
                  {userRows.map((user) => (
                    <article className={s.memberRow} key={user.id}>
                      <div className={s.avatar} aria-hidden="true">{user.display_name.slice(0, 1).toUpperCase()}</div>
                      <div className={s.memberIdentity}>
                        <strong>{user.display_name}</strong>
                        <span>@{user.username}</span>
                      </div>
                      <div className={s.memberRoles}>
                        {user.roles.map((role) => <span key={role}>{roleMeta(role).label}</span>)}
                      </div>
                      <span className={user.active ? s.active : s.revoked}>{user.active ? '已启用' : '已停用'}</span>
                      <Button size="sm" variant="secondary" onClick={() => startEditingUser(user.id)}>修改职责</Button>
                      {user.active ? (
                        <ConfirmActionButton
                          label="停用"
                          title="确认停用成员"
                          description={`停用 ${user.display_name}（@${user.username}）后，该成员现有的全部访问令牌会立即撤销。`}
                          confirmLabel="停用并撤销令牌"
                          disabled={busy !== null || user.id === session.data?.user.id}
                          onConfirm={() => act(`disable:${user.id}`, `${user.display_name} 已停用，现有令牌已撤销`, async () => {
                            await api.updateGovernanceUserStatus(user.id, false)
                          })}
                        />
                      ) : (
                        <Button size="sm" variant="secondary" disabled={busy !== null} loading={busy === `restore:${user.id}`} onClick={() => void act(`restore:${user.id}`, `${user.display_name} 已恢复`, async () => {
                          await api.updateGovernanceUserStatus(user.id, true)
                        })}>恢复</Button>
                      )}
                    </article>
                  ))}
                </div>
              </AsyncStateBoundary>
            </section>

            <div className={s.memberForms}>
              <section className={common.section} id="add-member">
                <div className={common.sectionHead}><div><h2>添加成员</h2><span>新成员建议从只读开始</span></div></div>
                <div className={s.formGrid}>
                  <label className={s.field}>登录名<input value={username} autoComplete="off" placeholder="例如 zhangsan" onChange={(event) => setUsername(event.target.value)} /></label>
                  <label className={s.field}>显示名称<input value={displayName} autoComplete="off" placeholder="例如 张三" onChange={(event) => setDisplayName(event.target.value)} /></label>
                  <div className={`${s.field} ${s.wide}`}><span>选择职责</span><div className={s.roleChoices}>
                    {roleRows.map((role) => {
                      const meta = roleMeta(role.name)
                      return <label key={role.id}><input type="checkbox" checked={newUserRoles.includes(role.name)}
                        onChange={() => toggleRole(role.name, newUserRoles, setNewUserRoles)} />
                        <span><strong>{meta.label}</strong><small>{meta.summary}</small></span></label>
                    })}
                  </div></div>
                  <Button size="md" variant="primary" fullWidth disabled={!username.trim() || !displayName.trim() || newUserRoles.length === 0}
                    loading={busy === 'create-user'} onClick={() => void act('create-user', `${displayName} 已添加`, async () => {
                      await api.createGovernanceUser({ username: username.trim(), display_name: displayName.trim(), roles: newUserRoles })
                      setUsername(''); setDisplayName(''); setNewUserRoles(['viewer'])
                    })}>添加成员</Button>
                </div>
              </section>

              <section className={common.section} id="edit-member">
                <div className={common.sectionHead}><div><h2>修改职责</h2><span>职责决定成员可以做什么</span></div></div>
                <div className={s.formGrid}>
                  <label className={s.field}>选择成员<select value={selectedUserId} onChange={(event) => {
                    const id = event.target.value; setSelectedUserId(id)
                    setSelectedRoles(userRows.find((item) => item.id === id)?.roles ?? [])
                  }}><option value="">请选择成员</option>{userRows.map((user) => <option key={user.id} value={user.id}>{user.display_name}</option>)}</select></label>
                  <div className={`${s.field} ${s.wide}`}><span>当前职责</span><div className={s.roleChoices}>
                    {roleRows.map((role) => {
                      const meta = roleMeta(role.name)
                      return <label key={role.id}><input type="checkbox" checked={selectedRoles.includes(role.name)}
                        onChange={() => toggleRole(role.name, selectedRoles, setSelectedRoles)} />
                        <span><strong>{meta.label}</strong><small>{meta.summary}</small></span></label>
                    })}
                  </div></div>
                  <Button size="md" variant="primary" fullWidth disabled={!selectedUserId || selectedRoles.length === 0}
                    loading={busy === 'update-roles'} onClick={() => void act('update-roles', '成员职责已更新', async () => {
                      await api.updateGovernanceUserRoles(selectedUserId, selectedRoles)
                    })}>保存职责</Button>
                </div>
              </section>
            </div>
          </div>
        </div>
      )}

      {view === 'tokens' && (
        <div className={s.viewContent} role="tabpanel">
          {/* M2-07：本机访问凭据的设置入口已统一收口到「设置 / 系统设置」，此处只做指引，避免双写。 */}
          <div className={s.credentialBand}>
            <span>
              本机访问凭据{credentialConfigured ? `已配置（末 4 位 ${credentialTail}）` : '未配置'}，
              统一在 <Link to="/config">设置 / 系统设置 · 接入凭据</Link> 中维护。
            </span>
          </div>

          <section className={common.section}>
            <div className={common.sectionHead}><div><h2>创建访问令牌</h2><span>用于自动化脚本或其他设备，明文只显示一次</span></div></div>
            <div className={s.tokenForm}>
              <label className={s.field}>代表谁访问<select value={tokenUserId} onChange={(event) => setTokenUserId(event.target.value)}><option value="">请选择成员</option>{userRows.map((user) => <option key={user.id} value={user.id}>{user.display_name}</option>)}</select></label>
              <label className={s.field}>用途名称<input value={tokenLabel} placeholder="例如 家中电脑" onChange={(event) => setTokenLabel(event.target.value)} /></label>
              <div className={s.field}><span>有效期</span><SegmentedControl size="sm" value={expiryDays} onChange={setExpiryDays}
                options={[{ value: '7', label: '7 天' }, { value: '30', label: '30 天' }, { value: '90', label: '90 天' }]} /></div>
              <Button size="md" variant="primary" disabled={!tokenUserId || !tokenLabel.trim()}
                loading={busy === 'create-token'} onClick={() => void act('create-token', '访问令牌已创建', async () => {
                  const response = await api.createGovernanceToken({ user_id: tokenUserId, label: tokenLabel.trim(), expires_at: Date.now() / 1000 + Number(expiryDays) * 86400 })
                  setCreatedSecret(response.token.token); setTokenLabel('')
                })}>创建令牌</Button>
            </div>
            {createdSecret && <div className={s.secret} role="status"><div><strong>新令牌已生成</strong><span>请现在保存，关闭后无法再次查看</span></div><code>{createdSecret}</code><div className={s.secretActions}>
              <Button size="sm" variant="primary" onClick={() => {
                void navigator.clipboard.writeText(createdSecret)
                setNotice('令牌已复制到剪贴板')
              }}>复制令牌</Button>
              <Button size="sm" variant="ghost" onClick={() => setCreatedSecret('')}>我已保存</Button>
            </div></div>}
          </section>

          <section className={common.section}>
            <div className={common.sectionHead}><div><h2>现有访问令牌</h2><span>{activeTokens.length} 个可用</span></div></div>
            <AsyncStateBoundary loading={tokens.loading} error={tokens.error} reconnecting={tokens.reconnecting} hasData={tokens.data !== null}
              isEmpty={tokenRows.length === 0} onRetry={tokens.refetch} loadingTitle="正在读取令牌…" emptyTitle="还没有访问令牌">
              <Table columns={tokenColumns} rows={tokenRows} rowKey={(row) => row.id} density="compact" />
            </AsyncStateBoundary>
          </section>
        </div>
      )}

      {view === 'roles' && (
        <div className={s.viewContent} role="tabpanel">
          <div className={s.roleGuideHeader}>
            <div><h2>四种职责，从最少权限开始</h2><p>同一成员可以拥有多个职责，系统会自动合并权限。</p></div>
            <span>推荐：新成员先选“只读成员”</span>
          </div>
          <AsyncStateBoundary loading={roles.loading} error={roles.error} reconnecting={roles.reconnecting} hasData={roles.data !== null}
            isEmpty={roleRows.length === 0} onRetry={roles.refetch} loadingTitle="正在读取角色…" emptyTitle="没有角色">
            <div className={s.roleGuideGrid}>
              {roleRows.map((role) => {
                const meta = roleMeta(role.name)
                return <article className={s.roleGuideCard} key={role.id}>
                  <div className={s.roleGuideTitle}><strong>{meta.label}</strong><code>{role.name}</code></div>
                  <p>{meta.summary}</p>
                  <span className={s.permissionCount}>{role.permissions.length} 项权限</span>
                  <div className={s.permissionList}>{role.permissions.map((item) => <span key={item} title={item}>{PERMISSION_LABELS[item] ?? item}</span>)}</div>
                </article>
              })}
            </div>
          </AsyncStateBoundary>
        </div>
      )}

      {view === 'audit' && (
        <div className={s.viewContent} role="tabpanel">
          <section className={common.section}>
            <div className={s.auditHead}>
              <div><h2>最近操作</h2><span>失败记录会给出更容易理解的原因</span></div>
              <SegmentedControl size="sm" value={auditFilter} onChange={setAuditFilter}
                options={[{ value: 'all', label: `全部 ${auditRows.length}` }, { value: 'failed', label: `只看失败 ${failedAudit.length}` }]} />
            </div>
            <AsyncStateBoundary loading={audit.loading} error={audit.error} reconnecting={audit.reconnecting} hasData={audit.data !== null}
              isEmpty={visibleAudit.length === 0} onRetry={audit.refetch} loadingTitle="正在读取操作记录…" emptyTitle={auditFilter === 'failed' ? '近期没有失败操作' : '还没有操作记录'}>
              <Table columns={auditColumns} rows={visibleAudit} rowKey={(row) => row.id} density="compact" />
            </AsyncStateBoundary>
            {audit.data?.next_cursor && <div className={common.formActions}><Button variant="secondary" loading={loadingMoreAudit} onClick={() => void loadMoreAudit()}>继续加载 · 已显示 {auditRows.length} / {audit.data.total}</Button></div>}
          </section>
        </div>
      )}
    </div>
  )
}
