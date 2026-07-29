import { describe, expect, it } from 'vitest'
import { workspacesForMode } from './workspaces'

describe('workspacesForMode', () => {
  it('limits beginner navigation to the five user-facing entries', () => {
    const labels = workspacesForMode('beginner').flatMap((workspace) => (
      workspace.items.map((item) => item.label)
    ))

    expect(labels).toEqual(['总览', '自选', '股票评估', '模拟执行', '设置'])
  })

  it('keeps every advanced workspace', () => {
    expect(workspacesForMode('advanced').map((workspace) => workspace.key)).toEqual([
      'cockpit', 'research', 'strategy', 'execution', 'operations',
    ])
  })
})
