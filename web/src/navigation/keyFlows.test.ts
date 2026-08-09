import { describe, expect, it } from 'vitest'
import {
  KEY_FLOWS,
  MOBILE_PRIMARY_TARGETS,
  WORKSPACE_QUICK_LINKS,
  desktopClickDepth,
  hasRoutePresentation,
  mobileClickDepth,
} from './keyFlows'
import { WORKSPACES } from './workspaces'

/** M2-08 关键流程响应式验收：桌面与移动均需在两次点击内到达六项核心操作。 */
describe('key flow reachability (M2-08)', () => {
  it('covers exactly the seven flows required by the roadmap', () => {
    expect(KEY_FLOWS.map((flow) => flow.label)).toEqual([
      '查标的', '看策略', '审信号', '下单', '撤单', '停机', '对账',
    ])
  })

  it.each(KEY_FLOWS)('$label reaches $target within two desktop clicks', (flow) => {
    const depth = desktopClickDepth(flow.target)
    expect(depth).not.toBeNull()
    expect(depth as number).toBeLessThanOrEqual(2)
  })

  it.each(KEY_FLOWS)('$label reaches $target within two mobile clicks', (flow) => {
    expect(mobileClickDepth(flow.target)).toBeLessThanOrEqual(2)
  })

  it.each(KEY_FLOWS)('$label lands on a route registered in the navigation table', (flow) => {
    expect(hasRoutePresentation(flow.target)).toBe(true)
  })

  it('keeps every mobile primary target inside the six-workspace navigation', () => {
    for (const target of MOBILE_PRIMARY_TARGETS) {
      const known = WORKSPACES.some(
        (workspace) => workspace.to === target || workspace.items.some((item) => item.to === target),
      )
      expect(known, `${target} 不在一级/二级导航中`).toBe(true)
    }
  })

  it('never points an in-page quick link at an unregistered route', () => {
    for (const [from, links] of Object.entries(WORKSPACE_QUICK_LINKS)) {
      expect(hasRoutePresentation(from), `${from} 未登记`).toBe(true)
      for (const link of links) {
        expect(hasRoutePresentation(link.to), `${from} → ${link.to} 未登记`).toBe(true)
        expect(link.label.length).toBeGreaterThan(0)
      }
    }
  })
})
