// 新闻分析页组件 barrel：统一导出 6 个组件 + 共享 utils。
// NewsCard 内联了 SentimentBadge/TopicBadge/EntityChips，不单独导出。

export { NewsCard } from './NewsCard'
export type { NewsCardProps } from './NewsCard'
export { NewsCardList } from './NewsCardList'
export type { NewsCardListProps } from './NewsCardList'
export { NewsSentimentBar } from './NewsSentimentBar'
export type { NewsSentimentBarProps } from './NewsSentimentBar'
export { NewsTopicFilter } from './NewsTopicFilter'
export type { NewsTopicFilterProps } from './NewsTopicFilter'
export { NewsEntityCloud } from './NewsEntityCloud'
export type { NewsEntityCloudProps } from './NewsEntityCloud'
export { NewsKpiRow } from './NewsKpiRow'
export type { NewsKpiRowProps } from './NewsKpiRow'
export { NewsToolbar } from './NewsToolbar'
export type { NewsToolbarProps } from './NewsToolbar'
export {
  hexToRgba,
  topicMeta,
  sentimentMeta,
  entityMeta,
  fmtNewsTime,
  sentimentPct,
} from './news-utils'
