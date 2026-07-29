import type { ComponentType } from 'react'
import type { InterfaceMode } from '../hooks/useInterfaceMode'
import {
  IconActivity,
  IconBeaker,
  IconBell,
  IconChart,
  IconCog,
  IconCrosshair,
  IconFlask,
  IconGrid,
  IconLayers,
  IconNetwork,
  IconNews,
  IconSearch,
  IconSignal,
  IconWallet,
} from '../components/icons'

type WorkspaceIcon = ComponentType<{ size?: number; className?: string }>

export type WorkspaceKey = 'cockpit' | 'research' | 'strategy' | 'execution' | 'operations'

export interface WorkspaceNavItem {
  key: string
  label: string
  to: string
  icon: WorkspaceIcon
  end?: boolean
  matchPrefixes?: string[]
  searchKeywords?: string
}

export interface WorkspaceDefinition {
  key: WorkspaceKey
  label: string
  shortLabel: string
  to: string
  icon: WorkspaceIcon
  items: WorkspaceNavItem[]
}

export interface RoutePresentation {
  workspaceKey: WorkspaceKey
  board: string
  label: string
  exact?: string
  prefix?: string
}

export const WORKSPACES: WorkspaceDefinition[] = [
  {
    key: 'cockpit',
    label: '驾驶舱',
    shortLabel: '驾驶舱',
    to: '/',
    icon: IconGrid,
    items: [
      { key: 'overview', label: '总览', to: '/', icon: IconGrid, end: true, searchKeywords: '概览 驾驶舱' },
    ],
  },
  {
    key: 'research',
    label: '研究',
    shortLabel: '研究',
    to: '/evaluate',
    icon: IconChart,
    items: [
      { key: 'research', label: '股票评估', to: '/evaluate', icon: IconChart, matchPrefixes: ['/evaluate', '/research'], searchKeywords: '股票 标的 研究 评估' },
      { key: 'news', label: '新闻分析', to: '/news', icon: IconNews, searchKeywords: '新闻 分析' },
      { key: 'pa', label: '价格行为', to: '/pa', icon: IconCrosshair, searchKeywords: 'PA 价格 行为 分析' },
      { key: 'tasks', label: '分析任务', to: '/tasks', icon: IconActivity, searchKeywords: '分析 任务' },
      { key: 'alerts', label: '提醒中心', to: '/alerts', icon: IconBell, searchKeywords: '提醒 价格 涨跌 波动 信号 风险' },
    ],
  },
  {
    key: 'strategy',
    label: '策略',
    shortLabel: '策略',
    to: '/strategies',
    icon: IconLayers,
    items: [
      { key: 'strategy', label: '策略库', to: '/strategies', icon: IconLayers, matchPrefixes: ['/strategies'], searchKeywords: '策略 库' },
      { key: 'strategy-lab', label: '策略实验室', to: '/strategy-lab', icon: IconFlask, searchKeywords: '策略 实验室 回测' },
      { key: 'ensemble', label: '多模型判断', to: '/ensemble', icon: IconNetwork, searchKeywords: '多模型 协同 预测 判断' },
      { key: 'portfolio', label: '策略分配', to: '/portfolio', icon: IconLayers, searchKeywords: '策略 分配 组合' },
    ],
  },
  {
    key: 'execution',
    label: '执行',
    shortLabel: '执行',
    to: '/signals',
    icon: IconSignal,
    items: [
      { key: 'signal', label: '信号中心', to: '/signals', icon: IconSignal, searchKeywords: '信号 中心 审核' },
      { key: 'simulation', label: '模拟执行', to: '/simulation', icon: IconBeaker, searchKeywords: '模拟 执行 订单' },
      { key: 'ledger', label: '账户与账本', to: '/ledger', icon: IconWallet, searchKeywords: '账户 账本 持仓 成交 现金' },
    ],
  },
  {
    key: 'operations',
    label: '运营',
    shortLabel: '运营',
    to: '/instruments',
    icon: IconCog,
    items: [
      { key: 'instrument', label: '股票与市场', to: '/instruments', icon: IconSearch, searchKeywords: '股票 市场 标的 主数据' },
      { key: 'automation', label: '自动化中心', to: '/automation', icon: IconActivity, searchKeywords: '自动化 调度 运行 告警' },
      { key: 'incidents', label: '故障状态', to: '/incidents', icon: IconBell, searchKeywords: '故障 状态 异常 恢复' },
      { key: 'governance', label: '成员与访问', to: '/governance', icon: IconNetwork, searchKeywords: '成员 访问 权限 令牌 审计' },
      { key: 'config', label: '系统配置', to: '/config', icon: IconCog, searchKeywords: '系统 配置 数据源 备份' },
    ],
  },
]

export function workspacesForMode(mode: InterfaceMode): WorkspaceDefinition[] {
  if (mode === 'advanced') return WORKSPACES
  return WORKSPACES
    .filter((workspace) => workspace.key !== 'strategy')
    .map((workspace) => {
      if (workspace.key === 'cockpit') {
        return {
          ...workspace,
          items: [
            ...workspace.items,
            { key: 'watchlist', label: '自选', to: '/#watchlist', icon: IconSearch, searchKeywords: '自选 关注 股票' },
          ],
        }
      }
      if (workspace.key === 'research') {
        return { ...workspace, items: workspace.items.filter((item) => item.key === 'research') }
      }
      if (workspace.key === 'execution') {
        return { ...workspace, to: '/simulation', items: workspace.items.filter((item) => item.key === 'simulation') }
      }
      return {
        ...workspace,
        label: '设置',
        shortLabel: '设置',
        to: '/config',
        items: workspace.items.filter((item) => item.key === 'config').map((item) => ({ ...item, label: '设置' })),
      }
    })
}

export const ROUTE_PRESENTATIONS: RoutePresentation[] = [
  { workspaceKey: 'cockpit', board: 'overview', label: '总览', exact: '/' },
  { workspaceKey: 'research', board: 'evaluate', label: '股票评估', prefix: '/evaluate' },
  { workspaceKey: 'research', board: 'example', label: '只读示例', prefix: '/example' },
  { workspaceKey: 'research', board: 'research', label: '股票评估', prefix: '/research' },
  { workspaceKey: 'research', board: 'news', label: '新闻分析', prefix: '/news' },
  { workspaceKey: 'research', board: 'pa', label: '价格行为', prefix: '/pa' },
  { workspaceKey: 'research', board: 'tasks', label: '分析任务', prefix: '/tasks' },
  { workspaceKey: 'research', board: 'alerts', label: '提醒中心', prefix: '/alerts' },
  { workspaceKey: 'strategy', board: 'strategy-lab', label: '策略实验室', prefix: '/strategy-lab' },
  { workspaceKey: 'strategy', board: 'ensemble', label: '多模型判断', prefix: '/ensemble' },
  { workspaceKey: 'strategy', board: 'portfolio', label: '策略分配', prefix: '/portfolio' },
  { workspaceKey: 'strategy', board: 'workbench', label: '策略工作台', prefix: '/strategies/' },
  { workspaceKey: 'strategy', board: 'library', label: '策略库', prefix: '/strategies' },
  { workspaceKey: 'execution', board: 'signals', label: '信号中心', prefix: '/signals' },
  { workspaceKey: 'execution', board: 'simulation', label: '模拟执行', prefix: '/simulation' },
  { workspaceKey: 'execution', board: 'ledger', label: '账户与账本', prefix: '/ledger' },
  { workspaceKey: 'operations', board: 'instruments', label: '股票与市场', prefix: '/instruments' },
  { workspaceKey: 'operations', board: 'automation', label: '自动化中心', prefix: '/automation' },
  { workspaceKey: 'operations', board: 'incidents', label: '故障状态', prefix: '/incidents' },
  { workspaceKey: 'operations', board: 'governance', label: '成员与访问', prefix: '/governance' },
  { workspaceKey: 'operations', board: 'config', label: '系统配置', prefix: '/config' },
]

export function presentationForPath(pathname: string): RoutePresentation {
  return ROUTE_PRESENTATIONS.find((route) => (
    route.exact ? pathname === route.exact : Boolean(route.prefix && pathname.startsWith(route.prefix))
  )) ?? ROUTE_PRESENTATIONS[0]
}

export function workspaceForPath(pathname: string): WorkspaceDefinition {
  const presentation = presentationForPath(pathname)
  return WORKSPACES.find((workspace) => workspace.key === presentation.workspaceKey) ?? WORKSPACES[0]
}

export function isWorkspaceItemActive(item: WorkspaceNavItem, pathname: string): boolean {
  if (item.end) return pathname === item.to
  if (item.matchPrefixes) return item.matchPrefixes.some((prefix) => pathname.startsWith(prefix))
  return pathname === item.to
}
