import type { FactorResearchResp } from '../api/types'

export type FactorResearchExportFormat = 'json' | 'csv' | 'md'

export interface FactorResearchExportArtifact {
  filename: string
  mimeType: string
  content: string
}

function csvCell(value: unknown): string {
  const text = value === null || value === undefined ? '' : String(value)
  return `"${text.replace(/"/g, '""')}"`
}

function exportStem(result: FactorResearchResp): string {
  const identity = result.run_id ?? result.summary.data_fingerprint?.slice(0, 12) ?? 'unsaved'
  const symbol = result.symbol.replace(/[^A-Za-z0-9._-]/g, '_')
  return `${symbol}_${result.interval}_${identity}`
}

function factorCsv(result: FactorResearchResp): string {
  const columns = [
    'key',
    'label',
    'category',
    'status',
    'direction',
    'score',
    'train_ic',
    'median_window_ic',
    'worst_window_ic',
    'window_pass_rate',
    'adjusted_p_value',
    'p_value',
    'icir',
    'positive_ic_ratio',
    'hit_rate',
    'exploratory_candidate',
    'weight',
  ] as const
  const rows = result.factors.map((factor) => columns.map((column) => csvCell(factor[column])).join(','))
  return [columns.map(csvCell).join(','), ...rows].join('\r\n')
}

function readableReport(result: FactorResearchResp): string {
  const summary = result.summary
  const exploratory = (summary.exploratory_candidates ?? summary.selected_factors).join(', ') || '无'
  const factors = result.factors.map((factor) => (
    `| ${factor.label} | ${factor.status} | ${factor.median_window_ic ?? factor.test_ic} | ${factor.passed_windows ?? '—'}/${factor.window_count ?? '—'} | ${factor.adjusted_p_value ?? factor.p_value} |`
  ))
  const methods = result.methods.map((method) => (
    `| ${method.label} | ${method.total_return} | ${method.max_drawdown} | ${method.closed_trades ?? method.trades} | ${method.win_rate} | ${method.profit_factor} | ${method.deflated_sharpe_ratio ?? '—'} |`
  ))
  return [
    `# ${result.symbol} 因子研究报告`,
    '',
    `- 市场：${result.market}`,
    `- 周期：${result.interval}`,
    `- 数据源：${result.source}`,
    `- 研究区间：${summary.research_period ? `${summary.research_period.start} / ${summary.research_period.end}` : '旧记录未保存'}`,
    `- 数据指纹：${summary.data_fingerprint ?? '旧记录未保存'}`,
    `- 引擎版本：${summary.engine_version ?? '旧记录未保存'}`,
    `- 兼容口径：${result.compatibility?.legacy_engine_record ? '旧引擎只读记录' : result.compatibility ? '当前引擎' : '旧记录未保存'}`,
    `- 公式版本：${summary.factor_formula_version ?? '旧记录未保存'}`,
    `- 探索候选：${exploratory}`,
    `- 多因子组合：${summary.multifactor_constructed === false ? '未发现合格因子，未构建' : '已构建或旧记录未保存状态'}`,
    `- Reality Check：${result.reality_check?.available ? `p=${result.reality_check.p_value}，候选 ${result.reality_check.candidate_count}` : result.reality_check?.reason ?? '旧记录未保存'}`,
    '',
    '## 因子结果',
    '',
    '| 因子 | 状态 | 窗口 IC 中位数 | 通过窗口 | 校正显著性 |',
    '| --- | --- | ---: | ---: | ---: |',
    ...factors,
    '',
    '## 方法结果',
    '',
    '| 方法 | 总收益 | 最大回撤 | 闭合交易 | 胜率 | 利润因子 | DSR |',
    '| --- | ---: | ---: | ---: | ---: | ---: | ---: |',
    ...methods,
    '',
    '## 方法说明',
    '',
    `${result.methodology.split}；${result.methodology.execution}。`,
    '',
    result.methodology.usable_rule,
    '',
    result.methodology.warning,
    '',
  ].join('\n')
}

export function buildFactorResearchExport(
  result: FactorResearchResp,
  format: FactorResearchExportFormat,
): FactorResearchExportArtifact {
  const stem = exportStem(result)
  if (format === 'csv') {
    return { filename: `${stem}.csv`, mimeType: 'text/csv;charset=utf-8', content: factorCsv(result) }
  }
  if (format === 'md') {
    return { filename: `${stem}.md`, mimeType: 'text/markdown;charset=utf-8', content: readableReport(result) }
  }
  return {
    filename: `${stem}.json`,
    mimeType: 'application/json;charset=utf-8',
    content: JSON.stringify(result, null, 2),
  }
}
