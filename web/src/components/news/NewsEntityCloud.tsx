// 高频实体云：Top 10 命名实体按频次渲染，字号随频次递减。
// 点击某实体 → 高亮同类型实体（其他类型 dim）。再次点击同类型 → 取消高亮。

import { useMemo, useState } from 'react'
import { ENTITY_META } from '../../api/types'

export interface NewsEntityCloudProps {
  entities: { text: string; type: string; count: number }[]
  /** 最大展示数量，默认 10 */
  max?: number
}

export function NewsEntityCloud({ entities, max = 10 }: NewsEntityCloudProps) {
  const [highlightType, setHighlightType] = useState<string | null>(null)

  // 按频次倒序，取前 max 个
  const top = useMemo(() => {
    return [...entities]
      .sort((a, b) => b.count - a.count)
      .slice(0, max)
  }, [entities, max])

  // 字号映射：max count → 18px，min count → 13px，线性插值
  const fontFor = (count: number, maxCount: number, minCount: number): number => {
    if (maxCount === minCount) return 16
    const ratio = (count - minCount) / (maxCount - minCount)
    return Math.round(13 + ratio * 5) // 13px ~ 18px
  }

  const counts = top.map((e) => e.count)
  const maxCount = counts.length > 0 ? Math.max(...counts) : 0
  const minCount = counts.length > 0 ? Math.min(...counts) : 0

  const toggleType = (type: string) => {
    setHighlightType((cur) => (cur === type ? null : type))
  }

  return (
    <div className="overview-section">
      <div className="section-title">高频实体</div>
      {top.length === 0 ? (
        <div className="entity-cloud-empty">无实体数据</div>
      ) : (
        <div className="entity-cloud">
          {top.map((e, i) => {
            const meta = ENTITY_META[e.type] ?? ENTITY_META.location
            const dim =
              highlightType !== null && e.type !== highlightType
            return (
              <button
                key={`${e.text}-${i}`}
                className={`entity-cloud-item ${meta.cls} ${dim ? 'dim' : ''}`}
                onClick={() => toggleType(e.type)}
                style={{ fontSize: `${fontFor(e.count, maxCount, minCount)}px` }}
                title={`${meta.label} · 出现 ${e.count} 次`}
              >
                {e.text}
                <span className="ec-count">({e.count})</span>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
