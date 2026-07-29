export type ConnectionState = 'online' | 'unauthorized' | 'forbidden' | 'degraded' | 'offline'

export const CONNECTION_LABELS: Record<ConnectionState, { short: string; detail: string }> = {
  online: { short: '实时', detail: '网关、访问权限和核心业务接口正常' },
  unauthorized: { short: '需令牌', detail: '网关在线，需要有效的访问令牌' },
  forbidden: { short: '权限不足', detail: '网关在线，当前身份缺少访问权限' },
  degraded: { short: '业务异常', detail: '网关在线，部分业务数据暂不可用' },
  offline: { short: '离线', detail: '无法连接网关' },
}
