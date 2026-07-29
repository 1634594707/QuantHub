// 情绪堆叠条：三段（正面/负面/中性）按 sentiment_dist 占比渲染。
// 宽度用百分比，hover 通过 title 显示精确数值。total=0 时显示空轨道。

import type { NewsAnalyzeResp } from '../../api/types'
import { sentimentPct } from './news-utils'

export interface NewsSentimentBarProps {
  dist: NewsAnalyzeResp['sentiment_dist']
  total: number
}

export function NewsSentimentBar({ dist, total }: NewsSentimentBarProps) {
  const pos = dist.positive ?? 0
  const neg = dist.negative ?? 0
  const neu = dist.neutral ?? 0
  const posPct = sentimentPct(pos, total)
  const negPct = sentimentPct(neg, total)
  const neuPct = sentimentPct(neu, total)

  return (
    <div className="overview-section">
      <div className="section-title">情绪分布</div>
      <div
        className="news-sent-bar"
        title={`正面 ${pos} · 负面 ${neg} · 中性 ${neu}`}
      >
        <span
          className="pos"
          style={{ width: `${posPct}%` }}
          title={`正面 ${pos} (${posPct.toFixed(1)}%)`}
        />
        <span
          className="neg"
          style={{ width: `${negPct}%` }}
          title={`负面 ${neg} (${negPct.toFixed(1)}%)`}
        />
        <span
          className="neu"
          style={{ width: `${neuPct}%` }}
          title={`中性 ${neu} (${neuPct.toFixed(1)}%)`}
        />
      </div>
      <div className="news-sent-legend">
        <span className="li">
          <span className="sw pos" />
          正面 <span className="v">{posPct.toFixed(1)}%</span>
        </span>
        <span className="li">
          <span className="sw neg" />
          负面 <span className="v">{negPct.toFixed(1)}%</span>
        </span>
        <span className="li">
          <span className="sw neu" />
          中性 <span className="v">{neuPct.toFixed(1)}%</span>
        </span>
      </div>
    </div>
  )
}
