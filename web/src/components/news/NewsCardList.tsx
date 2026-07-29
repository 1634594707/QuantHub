// 新闻卡片列表：承载 NewsCard × N，提供排序切换、骨架屏与空态。
// 排序由本组件内部管理（time / sentiment 两种），不触发重新请求。

import { useMemo, useState } from 'react'
import type { NewsAnalysisItem } from '../../api/types'
import { NewsCard } from './NewsCard'
import { SegmentedControl } from '../ui/SegmentedControl/SegmentedControl'
import s from './NewsCardList.module.css'

type SortBy = 'time' | 'sentiment'

const SORT_OPTIONS = [
  { value: 'time', label: '时间↓' },
  { value: 'sentiment', label: '情绪强度↓' },
]

export interface NewsCardListProps {
  items: NewsAnalysisItem[]
  degraded: boolean
  loading: boolean
}

export function NewsCardList({ items, degraded, loading }: NewsCardListProps) {
  const [sortBy, setSortBy] = useState<SortBy>('time')

  const sorted = useMemo(() => {
    const arr = [...items]
    if (sortBy === 'time') {
      // 时间倒序：有 ts 的在前，无 ts 的在后
      arr.sort((a, b) => {
        const ta = a.ts ? new Date(a.ts).getTime() : 0
        const tb = b.ts ? new Date(b.ts).getTime() : 0
        return tb - ta
      })
    } else {
      // 情绪强度倒序：|score| 越大越靠前
      arr.sort((a, b) => {
        const sa = Math.abs(a.sentiment.score) * a.sentiment.confidence
        const sb = Math.abs(b.sentiment.score) * b.sentiment.confidence
        return sb - sa
      })
    }
    return arr
  }, [items, sortBy])

  return (
    <div className="news-list">
      <div className={`news-list-head ${s.listHead}`}>
        <span className={s.listTitle}>
          新闻列表 ({items.length} 条)
        </span>
        <SegmentedControl
          className={s.sortSeg}
          value={sortBy}
          onChange={(v) => setSortBy(v as SortBy)}
          options={SORT_OPTIONS}
          size="sm"
        />
      </div>

      {loading ? (
        <>
          <div className="news-skeleton-card">
            <div className="sk-line short" />
            <div className="sk-line title" />
            <div className="sk-line long" />
            <div className="sk-line mid" />
          </div>
          <div className="news-skeleton-card">
            <div className="sk-line short" />
            <div className="sk-line title" />
            <div className="sk-line long" />
            <div className="sk-line mid" />
          </div>
          <div className="news-skeleton-card">
            <div className="sk-line short" />
            <div className="sk-line title" />
            <div className="sk-line long" />
            <div className="sk-line mid" />
          </div>
        </>
      ) : sorted.length === 0 ? (
        <div className="empty-hint onboarding">暂无新闻数据，请调整标的或条数后重试</div>
      ) : (
        sorted.map((item, i) => (
          <NewsCard
            key={`${item.title}-${i}`}
            item={item}
            degraded={degraded}
          />
        ))
      )}
    </div>
  )
}
