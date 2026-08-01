import { describe, expect, it } from 'vitest'
import type { FactorResearchResp } from '../api/types'
import { buildFactorResearchExport } from './factorResearchExport'

const result = {
  run_id: 'run-123',
  symbol: 'BRK/B',
  market: 'us_stocks',
  interval: '1d',
  source: 'test_feed',
  compatibility: {
    current_engine_version: '2.2.0', record_engine_version: '2.0.0',
    legacy_engine_record: true, policy: 'historical_result_preserved_read_only',
  },
  summary: {
    selected_factors: ['trend_strength'],
    exploratory_candidates: ['trend_strength'],
    data_fingerprint: 'a'.repeat(64),
    engine_version: '2.0.0',
    factor_formula_version: '1.0.0',
    research_period: { start: '2024-01-01', end: '2025-01-01' },
  },
  factors: [{
    key: 'trend_strength', label: '趋势, "强度"', category: '趋势', status: 'usable', direction: 'positive',
    score: 80, train_ic: 0.1, test_ic: 0.08, median_window_ic: 0.08, worst_window_ic: 0.03,
    window_pass_rate: 0.6667, passed_windows: 2, window_count: 3, adjusted_p_value: 0.04,
    p_value: 0.01, icir: 1.2, positive_ic_ratio: 0.7, hit_rate: 0.55,
    exploratory_candidate: true, selected: true, weight: 1,
  }],
  methods: [{
    label: '多因子组合', total_return: 0.12, max_drawdown: -0.08, closed_trades: 6,
    trades: 6, win_rate: 0.5, profit_factor: 1.3,
  }],
  methodology: {
    split: '三窗口验证', execution: '延迟一周期执行', usable_rule: '严格多数窗口通过', warning: '历史统计不代表未来收益',
  },
} as unknown as FactorResearchResp

describe('buildFactorResearchExport', () => {
  it('builds a complete JSON snapshot with a safe deterministic filename', () => {
    const artifact = buildFactorResearchExport(result, 'json')
    expect(artifact.filename).toBe('BRK_B_1d_run-123.json')
    expect(JSON.parse(artifact.content).summary.data_fingerprint).toBe('a'.repeat(64))
  })

  it('escapes commas and quotes in factor CSV fields', () => {
    const artifact = buildFactorResearchExport(result, 'csv')
    expect(artifact.content).toContain('"趋势, ""强度"""')
    expect(artifact.content.split('\r\n')).toHaveLength(2)
  })

  it('builds a readable Markdown report with factor and method evidence', () => {
    const artifact = buildFactorResearchExport(result, 'md')
    expect(artifact.content).toContain('# BRK/B 因子研究报告')
    expect(artifact.content).toContain('## 因子结果')
    expect(artifact.content).toContain('兼容口径：旧引擎只读记录')
    expect(artifact.content).toContain('| 多因子组合 | 0.12 | -0.08 | 6 | 0.5 | 1.3 |')
  })
})
