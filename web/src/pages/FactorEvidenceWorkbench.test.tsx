import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { FactorResearchResp } from '../api/types'
import { api } from '../api/client'
import { FactorEvidenceWorkbench } from './FactorEvidenceWorkbench'

const result = {
  market: 'a_shares',
  factors: [{
    key: 'momentum_20', label: '动量', formula_version: '1.0.0', score: 0.2,
    status: 'watch', description: '趋势延续假设', direction: 'positive', hypothesis_family: 'momentum',
    window_pass_rate: 0.5, window_count: 2, worst_window_ic: -0.01, direction_flips: 1,
  }],
} as unknown as FactorResearchResp

describe('FactorEvidenceWorkbench', () => {
  it('keeps exploration, research, trading and AI review states separate', async () => {
    vi.spyOn(api, 'factorLineage').mockResolvedValue({
      ok: true,
      factor_key: 'momentum_20',
      version: '1.0.0',
      target_market: 'a_shares',
      current_state: 'draft',
      evidence_complete: false,
      historical_definition_preserved: true,
      definition: {
        definition_hash: 'a'.repeat(64), formula_hash: 'b'.repeat(64),
        ast: { op: 'field', name: 'close' }, input_fields: ['close'], rationale: '', parameters: {},
      },
      trace: {
        ai_hypothesis: [], dsl: {}, data_validation: [], experiments: [],
        statistics: [], portfolio_decisions: [], simulation: [],
      },
    })
    render(<FactorEvidenceWorkbench result={result} aiReview={null} />)
    expect(screen.getByText('因子证据工作台')).toBeTruthy()
    expect(screen.getByText('探索分数')).toBeTruthy()
    expect(screen.getByText('研究状态')).toBeTruthy()
    expect(screen.getByText('交易状态')).toBeTruthy()
    expect(screen.getByText('AI 审阅')).toBeTruthy()
    expect(await screen.findByText('该因子尚未进入模拟交易，统计结果不等于交易验证。')).toBeTruthy()
  })
})
