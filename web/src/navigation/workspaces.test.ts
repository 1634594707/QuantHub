import { describe, expect, it } from 'vitest'
import {
  presentationForPath,
  WORKSPACES,
  workspaceForPath,
  workspacesForMode,
} from './workspaces'

describe('workspacesForMode', () => {
  it('limits beginner navigation to the five user-facing entries', () => {
    const labels = workspacesForMode('beginner').flatMap((workspace) => (
      workspace.items.map((item) => item.label)
    ))

    expect(labels).toEqual(['总览', '自选', '综合评估', '模拟交易', '设置'])
  })

  it('keeps every advanced workspace', () => {
    expect(workspacesForMode('advanced').map((workspace) => workspace.key)).toEqual([
      'cockpit', 'research', 'strategy', 'execution', 'operations',
    ])
  })

  it('keeps one primary entry for each research capability', () => {
    const research = WORKSPACES.find((workspace) => workspace.key === 'research')

    expect(research?.items.map((item) => item.label)).toEqual([
      '综合评估', '因子验证', '研究任务',
    ])
    expect(research?.items.map((item) => item.to)).toEqual([
      '/evaluate', '/factor-research', '/tasks',
    ])
  })

  it('folds module routes into comprehensive evaluation without duplicate navigation', () => {
    for (const path of ['/news', '/pa', '/ensemble']) {
      expect(workspaceForPath(path).key).toBe('research')
      expect(presentationForPath(path).board.startsWith('evaluation')).toBe(true)
    }

    const primaryPaths = WORKSPACES.flatMap((workspace) => workspace.items.map((item) => item.to))
    expect(new Set(primaryPaths).size).toBe(primaryPaths.length)
    expect(primaryPaths).not.toContain('/news')
    expect(primaryPaths).not.toContain('/pa')
    expect(primaryPaths).not.toContain('/ensemble')
  })

  it('places market alerts in execution instead of research', () => {
    expect(workspaceForPath('/alerts').key).toBe('execution')
    expect(presentationForPath('/alerts').label).toBe('价格提醒')
  })
})
