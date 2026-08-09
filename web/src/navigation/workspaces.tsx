import type { ComponentType } from 'react'
import type { InterfaceMode } from '../hooks/useInterfaceMode'
import {
  IconActivity,
  IconBeaker,
  IconBell,
  IconChart,
  IconCog,
  IconCrosshair,
  IconGrid,
  IconLayers,
  IconSearch,
  IconSignal,
  IconWallet,
} from '../components/icons'

type WorkspaceIcon = ComponentType<{ size?: number; className?: string }>

/**
 * 一级导航固定为六类（路线图 3. 功能边界与导航重构 / M2-01）：
 * 总览 / 市场研究 / 策略 / 交易 / 账户风控 / 设置。
 * 每个功能只允许一个主入口，详情走二级页或抽屉，禁止重复菜单。
 */
export type WorkspaceKey = 'overview' | 'market' | 'strategy' | 'trading' | 'risk' | 'settings'

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
    key: 'overview',
    label: '总览',
    shortLabel: '总览',
    to: '/',
    icon: IconGrid,
    items: [
      { key: 'overview', label: '总览', to: '/', icon: IconGrid, end: true, searchKeywords: '概览 驾驶舱 权益 盈亏 行动队列' },
    ],
  },
  {
    key: 'market',
    label: '市场研究',
    shortLabel: '研究',
    to: '/evaluate',
    icon: IconChart,
    items: [
      {
        key: 'evaluation',
        label: '标的研究',
        to: '/evaluate',
        icon: IconChart,
        // 新闻 / 价格结构 / 模型共识 只作为标的研究页内模块，不再有独立一级入口。
        matchPrefixes: ['/evaluate', '/research', '/news', '/pa', '/ensemble'],
        searchKeywords: '股票 标的 研究 评估 新闻 K线 行情 价格行为 模型共识 AI',
      },
      { key: 'radar', label: '信号雷达', to: '/radar', icon: IconCrosshair, searchKeywords: '雷达 标的 信号 多标的 自选 收藏' },
      { key: 'tasks', label: '研究任务', to: '/tasks', icon: IconActivity, searchKeywords: '研究 分析 任务 队列' },
      { key: 'instruments', label: '标的与数据', to: '/instruments', icon: IconSearch, searchKeywords: '股票 市场 标的 主数据 数据源' },
    ],
  },
  {
    key: 'strategy',
    label: '策略',
    shortLabel: '策略',
    to: '/strategies',
    icon: IconLayers,
    items: [
      { key: 'strategy', label: '策略运行', to: '/strategies', icon: IconLayers, matchPrefixes: ['/strategies'], searchKeywords: '已安装 策略 运行 版本 参数 最近信号' },
      { key: 'portfolio', label: '策略组合', to: '/portfolio', icon: IconLayers, searchKeywords: '策略 分配 组合 权重' },
    ],
  },
  {
    key: 'trading',
    label: '交易',
    shortLabel: '交易',
    to: '/trading',
    icon: IconSignal,
    items: [
      { key: 'trading', label: '交易工作台', to: '/trading', icon: IconSignal, searchKeywords: 'OKX 实盘 下单 撤单 订单 成交 限价单 永续' },
      { key: 'signal', label: '信号审核', to: '/signals', icon: IconCrosshair, searchKeywords: '信号 审核 决策 放行 驳回' },
      { key: 'simulation', label: '模拟交易', to: '/simulation', icon: IconBeaker, searchKeywords: '模拟 纸面 交易 订单 成交' },
    ],
  },
  {
    key: 'risk',
    label: '账户风控',
    shortLabel: '风控',
    to: '/account-risk',
    icon: IconWallet,
    items: [
      { key: 'account-risk', label: '账户与风控', to: '/account-risk', icon: IconWallet, searchKeywords: '余额 持仓 保证金 风险率 风险模式 停机 对账 差异' },
      { key: 'ledger', label: '账户账本', to: '/ledger', icon: IconWallet, searchKeywords: '账本 持仓 成交 现金 绩效' },
      { key: 'alerts', label: '价格提醒', to: '/alerts', icon: IconBell, searchKeywords: '提醒 价格 涨跌 波动 风险' },
    ],
  },
  {
    key: 'settings',
    label: '设置',
    shortLabel: '设置',
    to: '/config',
    icon: IconCog,
    items: [
      { key: 'config', label: '系统设置', to: '/config', icon: IconCog, searchKeywords: '数据源 模型 OKX 交易开关 账户映射 通知 备份' },
      { key: 'automation', label: '作业调度', to: '/automation', icon: IconActivity, searchKeywords: '自动化 调度 作业 运行' },
      { key: 'incidents', label: '运行故障', to: '/incidents', icon: IconBell, searchKeywords: '故障 状态 异常 恢复' },
    ],
  },
]

export function workspacesForMode(mode: InterfaceMode): WorkspaceDefinition[] {
  if (mode === 'advanced') return WORKSPACES
  // 新手模式只暴露读多写少的最小闭环：总览 / 自选 / 标的研究 / 模拟交易 / 设置。
  return WORKSPACES
    .filter((workspace) => workspace.key !== 'strategy')
    .map((workspace) => {
      if (workspace.key === 'overview') {
        return {
          ...workspace,
          items: [
            ...workspace.items,
            { key: 'watchlist', label: '自选', to: '/#watchlist', icon: IconSearch, searchKeywords: '自选 关注 股票' },
          ],
        }
      }
      if (workspace.key === 'market') {
        return { ...workspace, items: workspace.items.filter((item) => item.key === 'evaluation') }
      }
      if (workspace.key === 'trading') {
        // 新手模式不暴露实盘交易台与信号审核，只保留模拟盘。
        return { ...workspace, to: '/simulation', items: workspace.items.filter((item) => item.key === 'simulation') }
      }
      if (workspace.key === 'risk') {
        return { ...workspace, to: '/ledger', items: workspace.items.filter((item) => item.key === 'ledger') }
      }
      return { ...workspace, items: workspace.items.filter((item) => item.key === 'config') }
    })
}

export const ROUTE_PRESENTATIONS: RoutePresentation[] = [
  { workspaceKey: 'overview', board: 'overview', label: '总览', exact: '/' },
  { workspaceKey: 'market', board: 'evaluation', label: '标的研究', prefix: '/evaluate' },
  { workspaceKey: 'market', board: 'evaluation', label: '标的研究', prefix: '/research' },
  { workspaceKey: 'market', board: 'evaluation-news', label: '标的研究 · 新闻证据', prefix: '/news' },
  { workspaceKey: 'market', board: 'evaluation-pa', label: '标的研究 · 价格结构', prefix: '/pa' },
  { workspaceKey: 'market', board: 'evaluation-consensus', label: '标的研究 · 模型共识', prefix: '/ensemble' },
  { workspaceKey: 'market', board: 'radar', label: '信号雷达', prefix: '/radar' },
  { workspaceKey: 'market', board: 'tasks', label: '研究任务', prefix: '/tasks' },
  { workspaceKey: 'market', board: 'instruments', label: '标的与数据', prefix: '/instruments' },
  { workspaceKey: 'strategy', board: 'workbench', label: '策略运行', prefix: '/strategies/' },
  { workspaceKey: 'strategy', board: 'library', label: '策略运行', prefix: '/strategies' },
  { workspaceKey: 'strategy', board: 'portfolio', label: '策略组合', prefix: '/portfolio' },
  { workspaceKey: 'trading', board: 'trading', label: '交易工作台', prefix: '/trading' },
  { workspaceKey: 'trading', board: 'signals', label: '信号审核', prefix: '/signals' },
  { workspaceKey: 'trading', board: 'simulation', label: '模拟交易', prefix: '/simulation' },
  { workspaceKey: 'risk', board: 'account-risk', label: '账户与风控', prefix: '/account-risk' },
  { workspaceKey: 'risk', board: 'ledger', label: '账户账本', prefix: '/ledger' },
  { workspaceKey: 'risk', board: 'alerts', label: '价格提醒', prefix: '/alerts' },
  { workspaceKey: 'settings', board: 'config', label: '系统设置', prefix: '/config' },
  { workspaceKey: 'settings', board: 'automation', label: '作业调度', prefix: '/automation' },
  { workspaceKey: 'settings', board: 'incidents', label: '运行故障', prefix: '/incidents' },
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
