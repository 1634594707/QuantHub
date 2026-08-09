import { describe, expect, it } from 'vitest'
import {
  presentationForPath,
  WORKSPACES,
  workspaceForPath,
  workspacesForMode,
} from './workspaces'

describe('六类一级导航（M2-01）', () => {
  it('一级导航固定为总览/市场研究/策略/交易/账户风控/设置', () => {
    expect(WORKSPACES.map((workspace) => workspace.key)).toEqual([
      'overview', 'market', 'strategy', 'trading', 'risk', 'settings',
    ])
    expect(WORKSPACES.map((workspace) => workspace.label)).toEqual([
      '总览', '市场研究', '策略', '交易', '账户风控', '设置',
    ])
  })

  it('每个功能只有一个主入口，不存在重复菜单', () => {
    const primaryPaths = WORKSPACES.flatMap((workspace) => workspace.items.map((item) => item.to))
    expect(new Set(primaryPaths).size).toBe(primaryPaths.length)
  })

  it('新闻/价格结构/模型共识只作为标的研究页内模块，不占一级入口', () => {
    for (const path of ['/news', '/pa', '/ensemble']) {
      expect(workspaceForPath(path).key).toBe('market')
      expect(presentationForPath(path).board.startsWith('evaluation')).toBe(true)
    }

    const primaryPaths = WORKSPACES.flatMap((workspace) => workspace.items.map((item) => item.to))
    expect(primaryPaths).not.toContain('/news')
    expect(primaryPaths).not.toContain('/pa')
    expect(primaryPaths).not.toContain('/ensemble')
  })

  it('已下线入口不得回到一级导航', () => {
    const primaryPaths = WORKSPACES.flatMap((workspace) => workspace.items.map((item) => item.to))
    // 路线图 3.C/3.F/阶段 2：独立策略实验室、成员权限、只读示例页均已删除。
    for (const removed of ['/strategy-lab', '/governance', '/example', '/factor-research']) {
      expect(primaryPaths).not.toContain(removed)
    }
  })

  it('交易域把实盘、信号审核与模拟盘收在同一工作区', () => {
    const trading = WORKSPACES.find((workspace) => workspace.key === 'trading')

    expect(trading?.items.map((item) => item.to)).toEqual(['/trading', '/signals', '/simulation'])
    expect(workspaceForPath('/trading').key).toBe('trading')
    expect(presentationForPath('/trading').label).toBe('交易工作台')
  })

  it('账户与风控收口余额、账本与提醒', () => {
    const risk = WORKSPACES.find((workspace) => workspace.key === 'risk')

    expect(risk?.items.map((item) => item.to)).toEqual(['/account-risk', '/ledger', '/alerts'])
    expect(workspaceForPath('/alerts').key).toBe('risk')
    expect(presentationForPath('/account-risk').label).toBe('账户与风控')
  })

  it('设置只保留系统配置与运行面板，不含成员权限', () => {
    const settings = WORKSPACES.find((workspace) => workspace.key === 'settings')

    expect(settings?.items.map((item) => item.to)).toEqual(['/config', '/automation', '/incidents'])
  })

  it('新手模式只暴露最小闭环入口', () => {
    const labels = workspacesForMode('beginner').flatMap((workspace) => (
      workspace.items.map((item) => item.label)
    ))

    expect(labels).toEqual(['总览', '自选', '标的研究', '模拟交易', '账户账本', '系统设置'])
  })

  it('专业模式保留全部六个工作区', () => {
    expect(workspacesForMode('advanced').map((workspace) => workspace.key)).toEqual([
      'overview', 'market', 'strategy', 'trading', 'risk', 'settings',
    ])
  })

  it('每个一级导航的默认落地页都在自身工作区内', () => {
    for (const workspace of WORKSPACES) {
      expect(workspaceForPath(workspace.to).key).toBe(workspace.key)
    }
  })
})
