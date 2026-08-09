import { ROUTE_PRESENTATIONS, WORKSPACES } from './workspaces'

/**
 * 关键流程可达性契约（M2-08）。
 *
 * 验收条件（路线图「阶段 2」+ 工作安排 M2-08）：桌面 / 移动均可完成
 * 「查标的、看策略、审信号、下单、撤单、停机、对账」，且核心操作在两次点击内到达。
 *
 * 本模块把这条口头标准变成可执行数据：
 *   - `KEY_FLOWS` 声明六个关键流程及其落地路由与页面上的实际动作；
 *   - 点击深度由真实导航数据（`WORKSPACES`）与页面真实使用的快捷入口数据推导，
 *     不是另写一份平行定义，避免与界面漂移；
 *   - `keyFlows.test.ts` 对深度做断言，任何导航改动破坏两次点击都会让测试变红。
 */

export interface KeyFlow {
  /** 流程 ID，用于验收台账引用。 */
  id: string
  /** 流程名称，对应工作安排 M2-08 的六项。 */
  label: string
  /** 该流程的落地路由。 */
  target: string
  /** 落地页上真实存在的操作，验收时按此项在界面复核。 */
  action: string
}

export const KEY_FLOWS: KeyFlow[] = [
  { id: 'find-symbol', label: '查标的', target: '/evaluate', action: '选择市场与标的，进入标的研究上下文' },
  { id: 'view-strategy', label: '看策略', target: '/strategies', action: '查看已注册策略、版本与最近信号' },
  { id: 'review-signal', label: '审信号', target: '/signals', action: '查看待审信号并放行或驳回' },
  { id: 'place-order', label: '下单', target: '/trading', action: '提交限价永续订单（二次确认）' },
  { id: 'cancel-order', label: '撤单', target: '/trading', action: '按订单号撤单（二次确认）' },
  { id: 'halt', label: '停机', target: '/account-risk', action: '切换 normal / cancel_only / halted' },
  { id: 'reconcile', label: '对账', target: '/account-risk', action: '发起对账并查看差异明细' },
]

/**
 * 移动端底部导航（`MobileNavigation` 高级模式）的直达目标。
 * 「研究」在无历史研究上下文时落到 `/evaluate`；「更多」不是终点，只打开抽屉。
 */
export const MOBILE_PRIMARY_TARGETS: readonly string[] = ['/', '/evaluate', '/trading']

export interface QuickLink {
  to: string
  label: string
}

/**
 * 页内快捷入口。key 是提供入口的页面路由，value 是该页真实渲染的兄弟页链接。
 * 页面直接消费本数据渲染，因此测试断言等价于对界面的断言。
 */
export const WORKSPACE_QUICK_LINKS: Record<string, QuickLink[]> = {
  '/trading': [
    { to: '/signals', label: '信号审核' },
    { to: '/simulation', label: '模拟交易' },
    { to: '/account-risk', label: '账户与风控（停机 / 对账）' },
  ],
}

/** 桌面侧栏点击深度：一级工作区 1 次，工作区内二级入口 2 次；不可达返回 null。 */
export function desktopClickDepth(target: string): number | null {
  if (WORKSPACES.some((workspace) => workspace.to === target)) return 1
  if (WORKSPACES.some((workspace) => workspace.items.some((item) => item.to === target))) return 2
  return null
}

/**
 * 移动端点击深度：
 *   1 次 —— 底部导航直达；
 *   2 次 —— 底部导航直达页上的页内快捷入口，或「更多」抽屉里的一级工作区；
 *   3 次 —— 需要「更多」→ 一级工作区 → 二级入口。
 */
export function mobileClickDepth(target: string): number {
  if (MOBILE_PRIMARY_TARGETS.includes(target)) return 1
  for (const from of MOBILE_PRIMARY_TARGETS) {
    if (WORKSPACE_QUICK_LINKS[from]?.some((link) => link.to === target)) return 2
  }
  if (WORKSPACES.some((workspace) => workspace.to === target)) return 2
  return 3
}

/** 路由是否已在导航展示表登记，用于拦截「能打开但导航上无归属」的孤立页面。 */
export function hasRoutePresentation(target: string): boolean {
  return ROUTE_PRESENTATIONS.some((route) => (
    route.exact ? route.exact === target : Boolean(route.prefix && target.startsWith(route.prefix))
  ))
}
