// 新闻卡片：单条结构化分析结果的展示单元。
// 内联 SentimentBadge / TopicBadge / EntityChips 三个子组件 —— 它们仅在 NewsCard 内复用，
// 不单独导出，保持文件聚合度。卡片支持摘要展开、标题跳转、降级角标。

import { useState } from 'react'
import type { NewsAnalysisItem, NewsEntity } from '../../api/types'
import { entityMeta, fmtNewsTime, hexToRgba, sentimentMeta, topicMeta } from './news-utils'

interface SentimentBadgeProps {
  label: string
}
function SentimentBadge({ label }: SentimentBadgeProps) {
  const m = sentimentMeta(label)
  return <span className={`sent-badge ${m.cls}`}>{m.label}</span>
}

const IMPACT_LABELS: Record<string, string> = {
  positive: '正面事件',
  negative: '负面事件',
  neutral: '事件已否定',
  uncertain: '影响不确定',
}

function EventSemantics({ item }: { item: NewsAnalysisItem }) {
  const impact = item.event_impact ?? {
    label: 'uncertain',
    confidence: 0,
    reason: '当前结果未提供独立事件影响判断',
    rule_id: null,
  }
  const direction = item.price_direction ?? {
    label: 'uncertain',
    confidence: 0,
    reason: '单条新闻标题不足以推断未来价格方向',
  }
  return (
    <div className="news-semantics" aria-label="新闻语义分层">
      <span className="semantic-item">
        <span className="semantic-key">事件影响</span>
        <span className={`impact-value ${impact.label}`}>{IMPACT_LABELS[impact.label] ?? '影响不确定'}</span>
      </span>
      <span className="semantic-item" title={direction.reason}>
        <span className="semantic-key">价格方向</span>
        <span className="direction-value">不确定</span>
      </span>
      <span className="semantic-reason" title={impact.reason}>{impact.reason}</span>
    </div>
  )
}

interface TopicBadgeProps {
  value: string
}
function TopicBadge({ value }: TopicBadgeProps) {
  const m = topicMeta(value)
  return (
    <span
      className="topic-badge"
      style={{ background: hexToRgba(m.color, 0.14), color: m.color }}
    >
      {m.label}
    </span>
  )
}

interface EntityChipsProps {
  entities: NewsEntity[]
  max?: number
}
function EntityChips({ entities, max = 5 }: EntityChipsProps) {
  if (!entities || entities.length === 0) {
    return <span className="empty">无实体</span>
  }
  const shown = entities.slice(0, max)
  const overflow = entities.length - shown.length
  return (
    <span className="entity-chips">
      {shown.map((e, i) => {
        const m = entityMeta(e.type)
        return (
          <span key={`${e.text}-${i}`} className={`entity-chip ${m.cls}`}>
            {e.text}
            <span className="ent-type">{m.label}</span>
          </span>
        )
      })}
      {overflow > 0 && <span className="entity-chip more">+{overflow}</span>}
    </span>
  )
}

export interface NewsCardProps {
  item: NewsAnalysisItem
  /** 响应级降级标志：true 时卡片 foot 显示降级角标 */
  degraded: boolean
}

export function NewsCard({ item, degraded }: NewsCardProps) {
  const [expanded, setExpanded] = useState(false)

  const engineWarn = item.engine !== 'semantic+api'
  const showDegrade = degraded || engineWarn
  const summaryEmpty = !item.summary || item.summary.trim().length === 0

  const titleEl = (
    <>
      <span className="news-title">{item.title}</span>
      {item.symbols.length > 0 && (
        <span className="news-symbols">
          {item.symbols.map((s) => (
            <span key={s} className="news-symbol">
              {s}
            </span>
          ))}
        </span>
      )}
    </>
  )

  return (
    <article className="news-card">
      <div className="news-card-header">
        <SentimentBadge label={item.sentiment.label} />
        <TopicBadge value={item.topic} />
        <span className="news-meta">
          <span className="src">{item.source || '未知来源'}</span>
          <span> · </span>
          <span>{fmtNewsTime(item.ts)}</span>
        </span>
      </div>

      {item.url ? (
        <a
          className="news-title-link"
          href={item.url}
          target="_blank"
          rel="noopener noreferrer"
          title="在新标签打开原文"
        >
          {titleEl}
        </a>
      ) : (
        <div>{titleEl}</div>
      )}

      <p
        className={`news-summary ${expanded ? 'expanded' : ''} ${summaryEmpty ? 'muted' : ''}`}
        onClick={() => {
          if (!summaryEmpty) setExpanded((v) => !v)
        }}
        title={summaryEmpty ? undefined : expanded ? '点击收起' : '点击展开全文'}
      >
        {summaryEmpty ? '（无摘要，请参考标题）' : item.summary}
      </p>

      <EventSemantics item={item} />

      <EntityChips entities={item.entities} />

      <div className="news-foot">
        <span className={`foot-engine ${engineWarn ? 'warn' : ''}`}>
          {item.engine}
        </span>
        {item.model && <span className="foot-model">· {item.model}</span>}
        {showDegrade && <span className="degrade-badge">降级</span>}
        <span className="foot-latency">{item.latency_ms}ms</span>
      </div>
    </article>
  )
}
