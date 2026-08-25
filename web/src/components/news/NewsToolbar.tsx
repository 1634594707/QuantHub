// 工具栏：标的输入 + 条数下拉 + 运行按钮 + 模型路径状态徽标。
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
  /** 完整新闻模型路径的探活结果 */
  health: NewsHealthResp | null
  /** 探活是否在加载中 */
  healthLoading: boolean
  /** 手动重探 */
  onRefreshHealth: () => void
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
}: NewsToolbarProps) {
  const pipelineReady = health?.ok === true
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

      <div className="toolbar-tail">
        <button
          className={`src-pill ${pipelineReady ? 'live' : 'warn'} ${s.healthPill}`}
          onClick={onRefreshHealth}
          title={
            healthLoading
              ? '检查中…'
              : pipelineReady
                ? `FinBERT2 + 配置 LLM${modelName ? ` · ${modelName}` : ''}`
                : 'FinBERT2 或配置 LLM 不可用'
          }
        >
          <span
            className={`${s.healthDot} ${pipelineReady ? s.healthDotOk : s.healthDotWarn}`}
          />
          {healthLoading
            ? '检查中…'
            : pipelineReady
              ? '模型可用'
              : '模型不可用'}
        </button>
      </div>
    </div>
  )
}
