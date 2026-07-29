/**
 * 将 ISO 时间或时间戳转换为相对时间字符串。
 * 超过 24 小时返回具体日期（MM-DD）。
 */
export function formatRelativeTime(ts: string | number | Date): string {
  const t = new Date(ts).getTime()
  const now = Date.now()
  const diff = now - t
  if (Number.isNaN(diff)) return ''
  if (diff < 0) return '刚刚'
  if (diff < 60_000) return '刚刚'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`
  if (diff < 30 * 86_400_000) return `${Math.floor(diff / 86_400_000)} 天前`
  const d = new Date(t)
  return `${d.getMonth() + 1}-${d.getDate()}`
}
