// 新闻分析页共享工具：颜色转换、主题/情绪查找、时间格式化。
// 复用 lib/time.ts 的 formatRelativeTime；这里只放 news 专属逻辑。

import { NEWS_TOPICS, SENTIMENT_META, ENTITY_META } from '../../api/types'

/** 将 #RRGGBB hex 色转为 rgba(r,g,b,alpha) 字符串，用于内联 style 注入半透明背景。 */
export function hexToRgba(hex: string, alpha: number): string {
  const m = hex.replace('#', '')
  if (m.length !== 6) return hex // 兜底：非标准 hex 原样返回
  const r = parseInt(m.slice(0, 2), 16)
  const g = parseInt(m.slice(2, 4), 16)
  const b = parseInt(m.slice(4, 6), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

/** 按主题 value 查找元信息；未命中返回 unknown 兜底项。 */
export function topicMeta(value: string): { value: string; label: string; color: string } {
  return NEWS_TOPICS.find((t) => t.value === value) ?? NEWS_TOPICS[NEWS_TOPICS.length - 1]
}

/** 按情绪 label 查找元信息；未命中返回 neutral 兜底。 */
export function sentimentMeta(label: string): { label: string; cls: string } {
  return SENTIMENT_META[label] ?? SENTIMENT_META.neutral
}

/** 按实体 type 查找元信息；未命中返回 location 兜底（颜色最暖）。 */
export function entityMeta(type: string): { label: string; cls: string } {
  return ENTITY_META[type] ?? ENTITY_META.location
}

/** ISO 时间 → MM-DD HH:mm 短格式；解析失败原样返回。 */
export function fmtNewsTime(ts: string | null): string {
  if (!ts) return '—'
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return ts
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const mi = String(d.getMinutes()).padStart(2, '0')
  return `${mm}-${dd} ${hh}:${mi}`
}

/** 计算情绪占比（0-100，保留 1 位小数）；total=0 时返回 0。 */
export function sentimentPct(count: number, total: number): number {
  if (total <= 0) return 0
  return (count / total) * 100
}
