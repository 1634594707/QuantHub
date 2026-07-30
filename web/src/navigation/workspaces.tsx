import type { ComponentType } from 'react'
import type { InterfaceMode } from '../hooks/useInterfaceMode'
import {
  IconActivity,
  IconBeaker,
  IconBell,
  IconChart,
  IconCog,
  IconFlask,
  IconGrid,
  IconLayers,
  IconNetwork,
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
      { key: 'evaluation', label: '综合评估', to: '/evaluate', icon: IconChart, matchPrefixes: ['/evaluate', '/research', '/news', '/pa', '/ensemble'], searchKeywords: '股票 标的 研究 评估 新闻 价格行为 模型共识 AI' },
      { key: 'factor-validation', label: '因子验证', to: '/factor-research', icon: IconBeaker, searchKeywords: '量化 因子 样本外 IC 回撤 动量 趋势' },
      { key: 'tasks', label: '研究任务', to: '/tasks', icon: IconActivity, searchKeywords: '研究 分析 任务 队列' },
    ],
  },
  {
    key: 'strategy',
    label: '策略',
    shortLabel: '策略',
    to: '/strategies',
    icon: IconLayers,
    items: [
      { key: 'strategy', label: '策略运行', to: '/strategies', icon: IconLayers, matchPrefixes: ['/strategies'], searchKeywords: '已安装 策略 运行 参数 回测' },
      { key: 'strategy-lab', label: '策略实验', to: '/strategy-lab', icon: IconFlask, searchKeywords: '策略 实验 版本 回测 对比' },
      { key: 'portfolio', label: '策略组合', to: '/portfolio', icon: IconLayers, searchKeywords: '策略 分配 组合 权重' },
    ],
  },
  {
    key: 'execution',
    label: '执行',
    shortLabel: '执行',
    to: '/signals',
    icon: IconSignal,
    items: [
      { key: 'signal', label: '信号审核', to: '/signals', icon: IconSignal, searchKeywords: '信号 审核 决策' },
      { key: 'simulation', label: '模拟交易', to: '/simulation', icon: IconBeaker, searchKeywords: '模拟 交易 订单 成交' },
      { key: 'ledger', label: '账户账本', to: '/ledger', icon: IconWallet, searchKeywords: '账户 账本 持仓 成交 现金 绩效' },
      { key: 'alerts', label: '价格提醒', to: '/alerts', icon: IconBell, searchKeywords: '提醒 价格 涨跌 波动 风险' },
    ],
  },
  {
    key: 'operations',
    label: '运营',
    shortLabel: '运营',
    to: '/instruments',
    icon: IconCog,
    items: [
      { key: 'instrument', label: '标的与数据', to: '/instruments', icon: IconSearch, searchKeywords: '股票 市场 标的 主数据 数据源' },
      { key: 'automation', label: '作业调度', to: '/automation', icon: IconActivity, searchKeywords: '自动化 调度 作业 运行 告警' },
      { key: 'incidents', label: '运行故障', to: '/incidents', icon: IconBell, searchKeywords: '故障 状态 异常 恢复' },
      { key: 'governance', label: '成员权限', to: '/governance', icon: IconNetwork, searchKeywords: '成员 访问 权限 令牌 审计' },
      { key: 'config', label: '系统设置', to: '/config', icon: IconCog, searchKeywords: '系统 设置 配置 数据源 备份' },
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
        return { ...workspace, items: workspace.items.filter((item) => item.key === 'evaluation') }
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
  { workspaceKey: 'research', board: 'evaluation', label: '综合评估', prefix: '/evaluate' },
  { workspaceKey: 'research', board: 'example', label: '只读示例', prefix: '/example' },
  { workspaceKey: 'research', board: 'evaluation', label: '综合评估', prefix: '/research' },
  { workspaceKey: 'research', board: 'evaluation-news', label: '综合评估 · 新闻证据', prefix: '/news' },
  { workspaceKey: 'research', board: 'evaluation-pa', label: '综合评估 · 价格结构', prefix: '/pa' },
  { workspaceKey: 'research', board: 'evaluation-consensus', label: '综合评估 · 模型共识', prefix: '/ensemble' },
  { workspaceKey: 'research', board: 'factor-validation', label: '因子验证', prefix: '/factor-research' },
  { workspaceKey: 'research', board: 'tasks', label: '研究任务', prefix: '/tasks' },
  { workspaceKey: 'strategy', board: 'strategy-lab', label: '策略实验', prefix: '/strategy-lab' },
  { workspaceKey: 'strategy', board: 'portfolio', label: '策略组合', prefix: '/portfolio' },
  { workspaceKey: 'strategy', board: 'workbench', label: '策略运行', prefix: '/strategies/' },
  { workspaceKey: 'strategy', board: 'library', label: '策略运行', prefix: '/strategies' },
  { workspaceKey: 'execution', board: 'signals', label: '信号审核', prefix: '/signals' },
  { workspaceKey: 'execution', board: 'simulation', label: '模拟交易', prefix: '/simulation' },
  { workspaceKey: 'execution', board: 'ledger', label: '账户账本', prefix: '/ledger' },
  { workspaceKey: 'execution', board: 'alerts', label: '价格提醒', prefix: '/alerts' },
  { workspaceKey: 'operations', board: 'instruments', label: '标的与数据', prefix: '/instruments' },
  { workspaceKey: 'operations', board: 'automation', label: '作业调度', prefix: '/automation' },
  { workspaceKey: 'operations', board: 'incidents', label: '运行故障', prefix: '/incidents' },
  { workspaceKey: 'operations', board: 'governance', label: '成员权限', prefix: '/governance' },
  { workspaceKey: 'operations', board: 'config', label: '系统设置', prefix: '/config' },
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
