// 主题筛选：9 主题多选胶囊 + 「全部」清空。
// activeTopics 由父组件持有（Set<string>），点击切换实时筛选列表（不重新请求）。

import { NEWS_TOPICS } from '../../api/types'

export interface NewsTopicFilterProps {
  /** 当前激活的主题集合；空集合 = 全部 */
  activeTopics: Set<string>
  /** 主题 → 计数映射（来自 resp.topic_dist） */
  topicDist: Record<string, number>
  /** 切换某主题：传入 value，父组件自行 toggle */
  onToggle: (value: string) => void
  /** 清空筛选（回到「全部」） */
  onClear: () => void
}

export function NewsTopicFilter({
  activeTopics,
  topicDist,
  onToggle,
  onClear,
}: NewsTopicFilterProps) {
  const allActive = activeTopics.size === 0

  return (
    <div className="overview-section">
      <div className="section-title">主题筛选</div>
      <div className="topic-filter">
        <button
          className={`topic-tab all ${allActive ? 'active' : ''}`}
          onClick={onClear}
          aria-pressed={allActive}
        >
          全部
        </button>
        {NEWS_TOPICS.map((t) => {
          const count = topicDist[t.value] ?? 0
          // 只显示有计数的主题，避免 9 个胶囊都显示 0
          if (count === 0 && !activeTopics.has(t.value)) return null
          const active = activeTopics.has(t.value)
          return (
            <button
              key={t.value}
              className={`topic-tab ${active ? 'active' : ''}`}
              onClick={() => onToggle(t.value)}
              aria-pressed={active}
              style={
                active
                  ? {
                      background: `rgba(${hexParts(t.color)}, 0.14)`,
                      color: t.color,
                      borderColor: t.color,
                    }
                  : undefined
              }
            >
              {t.label}
              <span className="count">{count}</span>
            </button>
          )
        })}
      </div>
    </div>
  )
}

/** 局部 hex → "r, g, b" 解析（仅用于内联 style，避免引入 utils 循环依赖）。 */
function hexParts(hex: string): string {
  const m = hex.replace('#', '')
  if (m.length !== 6) return '100, 116, 136'
  const r = parseInt(m.slice(0, 2), 16)
  const g = parseInt(m.slice(2, 4), 16)
  const b = parseInt(m.slice(4, 6), 16)
  return `${r}, ${g}, ${b}`
}
