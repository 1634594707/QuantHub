import { useNavigate, useRouteError, isRouteErrorResponse, useLocation } from 'react-router-dom'

function useErrorInfo() {
  const error = useRouteError()
  const location = useLocation()

  if (isRouteErrorResponse(error)) {
    return {
      status: error.status,
      statusText: error.statusText,
      message: error.data?.message || error.statusText || '页面不存在或已被迁移',
      pathname: location.pathname,
    }
  }

  const msg =
    error instanceof Error ? error.message : typeof error === 'string' ? error : '发生未知错误'
  return { status: 500, statusText: 'Application Error', message: msg, pathname: location.pathname }
}

export default function NotFoundPage() {
  const { status, message, pathname } = useErrorInfo()
  const navigate = useNavigate()
  const is404 = status === 404

  // 旧路由迁移提示
  const migrated: Record<string, { label: string; to: string }> = {
    '/backtest': { label: '回测工作台', to: '/strategies/supertrend?tab=backtest' },
    '/sentiment': { label: '情感分析策略', to: '/strategies/sentiment' },
  }
  const redirect = migrated[pathname]

  return (
    <div className="not-found">
      <div className="not-found-card">
        <div className="not-found-code">{is404 ? '404' : status}</div>
        <h1 className="not-found-title">
          {redirect ? '页面已迁移' : is404 ? '找不到页面' : '出错了'}
        </h1>
        <p className="not-found-message">
          {redirect ? (
            <>
              <code className="mono">{pathname}</code> 已被整合进策略模块，避免重复。
              请使用新的统一入口。
            </>
          ) : (
            message
          )}
        </p>
        <div className="not-found-actions">
          {redirect && (
            <button
              className="btn primary"
              onClick={() => navigate(redirect.to, { replace: true })}
            >
              跳转到{redirect.label}
            </button>
          )}
          <button className="btn" onClick={() => navigate('/', { replace: true })}>
            返回首页
          </button>
          <button className="btn ghost" onClick={() => navigate('/strategies', { replace: true })}>
            策略工作台
          </button>
        </div>
      </div>
    </div>
  )
}
