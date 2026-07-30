import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import type { PaAnalyzeResp } from '../api/types'
import DecisionPanel from './DecisionPanel'

const decision = {
  trend: '多头', trend_color: '#0a8', cycle: '正常通道', phase: '发展',
  diagnosis_confidence: { score: 72, color: '#0a8', reasoning: '结构清晰' },
  order_type: '限价单', direction: '做多', entry: 100, tp1: 110, tp2: 115, sl: 95,
  risk_reward: { ratio_text: '2.00 : 1', risk: 5, reward: 10, metrics_ok: true, note: '' },
  estimated_win_rate: '60%', trade_confidence: { score: 65, color: '#0a8', reasoning: '测试' },
  reasoning: '测试计划', key_factors: ['趋势'], watch_points: ['失效位'], risk_assessment: '严格止损',
}

function response(valid: boolean): PaAnalyzeResp {
  return {
    ok: true, symbol: 'AAPL', timeframe: '1h', market: 'us_stocks', decision,
    future: { next_bar: null, next_cycle: null },
    tree: { path: [], sections: [], terminal: null, gate_result: 'proceed', gate_shortcircuited: false },
    meta: {
      kline_count: 300, stage1_complete: true, stage2_complete: true, gate_shortcircuited: false, usage: {},
      validation_retries: valid ? 1 : 0,
      validation: {
        stage1: { stage: 'stage1', valid: true, error_count: 0, warning_count: 0, attempts: 1, issues: [] },
        stage2: {
          stage: 'stage2', valid, error_count: valid ? 0 : 1, warning_count: 0, attempts: valid ? 2 : 1,
          issues: valid ? [] : [{ code: 'price_geometry', field: 'decision', message: '价格几何无效', severity: 'error' }],
        },
      },
    },
  }
}

afterEach(cleanup)

describe('DecisionPanel quality gate', () => {
  it('shows retry status when validation passes', () => {
    render(<DecisionPanel initialData={response(true)} />)
    expect(screen.getByText(/质量闸门通过/)).toBeTruthy()
    expect(screen.getByText(/自动修正 1 次/)).toBeTruthy()
    expect((screen.getByRole('button', { name: '生成待审核信号' }) as HTMLButtonElement).disabled).toBe(false)
  })

  it('blocks signal publishing when validation fails', () => {
    render(<DecisionPanel initialData={response(false)} />)
    expect(screen.getByText(/质量闸门阻断/)).toBeTruthy()
    expect((screen.getByRole('button', { name: '生成待审核信号' }) as HTMLButtonElement).disabled).toBe(true)
  })
})
