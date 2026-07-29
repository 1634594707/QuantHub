// 工具栏：标的输入 + 条数下拉 + 运行按钮 + LM Studio 状态徽标。
// 受控组件：所有状态由父组件 NewsPage 持有，本组件只负责触发回调。

import type { NewsHealthResp } from '../../api/types'
import s from './NewsToolbar.module.css'

export interface NewsToolbarProps {
  symbol: string
  onSymbolChange: (v: string) => void
  symbolError?: string | null
  /** 回车或点击「分析」时触发 */
  onSubmit: () => void
  limit: number
  onLimitChange: (v: number) => void
  /** 是否正在请求中（按钮禁用 + spinner） */
  loading: boolean
  /** LM Studio 探活结果 */
  health: NewsHealthResp | null
  /** 探活是否在加载中 */
  healthLoading: boolean
  /** 手动重探 */
  onRefreshHealth: () => void
  /** 是否启用 API 结构化增强（用户手动开关） */
  useApi: boolean
  onUseApiChange: (v: boolean) => void
}

const LIMIT_OPTIONS = [10, 20, 50, 100]

export function NewsToolbar({
  symbol,
  onSymbolChange,
  symbolError,
  onSubmit,
  limit,
  onLimitChange,
  loading,
  health,
  healthLoading,
  onRefreshHealth,
  useApi,
  onUseApiChange,
}: NewsToolbarProps) {
  const apiEnhanced = health?.api_enhancement === true
  const modelName = health?.model ?? null
  const hasSymbol = symbol.trim().length > 0

  return (
    <div className="news-toolbar">
      <div className="news-symbol-control">
        <label className="field-label" htmlFor="news-symbol">标的代码</label>
        <input
          id="news-symbol"
          className={`news-symbol-input${symbolError ? ' invalid' : ''}`}
          type="text"
          value={symbol}
          onChange={(e) => onSymbolChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') onSubmit()
          }}
          placeholder="必填，如 600519"
          autoComplete="off"
          aria-required="true"
          aria-invalid={Boolean(symbolError)}
          aria-describedby={symbolError ? 'news-symbol-error' : undefined}
        />
        {symbolError && (
          <span id="news-symbol-error" className="news-field-error" role="alert">
            {symbolError}
          </span>
        )}
      </div>

      <span className="field-label">条数</span>
      <div className={`news-sort-seg ${s.limitControl}`}>
        {LIMIT_OPTIONS.map((n) => (
          <button
            key={n}
            className={limit === n ? s.limitActive : ''}
            onClick={() => onLimitChange(n)}
            aria-pressed={limit === n}
          >
            {n}
          </button>
        ))}
      </div>

      <button
        className={`news-run-btn${loading ? ' is-loading' : ''}`}
        onClick={onSubmit}
        disabled={loading || !hasSymbol}
        aria-label="运行新闻分析"
        title={!hasSymbol ? '请先输入股票代码' : undefined}
      >
        {loading && <span className="spinner" />}
        {loading ? '分析中…' : '分析'}
      </button>

      {/* API 增强开关：即使 Key 已配置，用户也可手动关闭以节省 API 额度 */}
      <label
        className={`ub-toggle ${s.apiToggle}`}
        title={useApi ? 'API 增强已开启（结构化 NER/主题/摘要）' : 'API 增强已关闭（仅语义情绪，不消耗 API 额度）'}
      >
        <input
          type="checkbox"
          checked={useApi}
          onChange={(e) => onUseApiChange(e.target.checked)}
        />
        <span>API 增强</span>
      </label>

      <div className="toolbar-tail">
        <button
          className={`src-pill ${apiEnhanced ? 'live' : 'warn'} ${s.healthPill}`}
          onClick={onRefreshHealth}
          title={
            healthLoading
              ? '检查中…'
              : apiEnhanced
                ? `API 增强${modelName ? ` · ${modelName}` : ''}`
                : 'API 未启用 · 仅语义分析'
          }
        >
          <span
            className={`${s.healthDot} ${apiEnhanced ? s.healthDotOk : s.healthDotWarn}`}
          />
          {healthLoading
            ? '检查中…'
            : apiEnhanced
              ? 'API 增强'
              : '仅语义分析'}
        </button>
      </div>
    </div>
  )
}
