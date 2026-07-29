// KPI 行：4 张统计卡（总条数 / 正面占比 / 负面占比 / Top 主题）。
// 复用 .news-kpi-row 响应式栅格；每张卡片用 --kpi-color CSS 变量驱动左侧色条。

import { useMemo } from 'react'
import type { CSSProperties } from 'react'
import type { NewsAnalyzeResp } from '../../api/types'
import { sentimentPct, topicMeta } from './news-utils'
import s from './NewsKpiRow.module.css'

export interface NewsKpiRowProps {
  data: NewsAnalyzeResp
}

export function NewsKpiRow({ data }: NewsKpiRowProps) {
  const { total, sentiment_dist, topic_dist } = data

  const posPct = sentimentPct(sentiment_dist.positive ?? 0, total)
  const negPct = sentimentPct(sentiment_dist.negative ?? 0, total)

  const topTopic = useMemo(() => {
    const entries = Object.entries(topic_dist)
    if (entries.length === 0) return null
    const [maxKey, maxCount] = entries.reduce(
      (acc, cur) => (cur[1] > acc[1] ? cur : acc),
      entries[0],
    )
    return { meta: topicMeta(maxKey), count: maxCount }
  }, [topic_dist])

  return (
    <div className="news-kpi-row">
      <div className="news-kpi" style={{ '--kpi-color': 'var(--accent)' } as CSSProperties}>
        <span className="kpi-key">总条数</span>
        <span className="kpi-val">{total}</span>
        <span className="kpi-sub">条结构化分析</span>
      </div>
      <div className="news-kpi" style={{ '--kpi-color': 'var(--up)' } as CSSProperties}>
        <span className="kpi-key">正面占比</span>
        <span className="kpi-val">{posPct.toFixed(1)}%</span>
        <span className="kpi-sub">{sentiment_dist.positive ?? 0} 条正面</span>
      </div>
      <div className="news-kpi" style={{ '--kpi-color': 'var(--down)' } as CSSProperties}>
        <span className="kpi-key">负面占比</span>
        <span className="kpi-val">{negPct.toFixed(1)}%</span>
        <span className="kpi-sub">{sentiment_dist.negative ?? 0} 条负面</span>
      </div>
      <div
        className="news-kpi"
        style={{ '--kpi-color': topTopic ? topTopic.meta.color : 'var(--text-3)' } as CSSProperties}
      >
        <span className="kpi-key">Top 主题</span>
        <span className={`kpi-val ${s.topTopicVal}`}>
          {topTopic ? topTopic.meta.label : '—'}
        </span>
        <span className="kpi-sub">{topTopic ? `${topTopic.count} 条` : '无数据'}</span>
      </div>
    </div>
  )
}
