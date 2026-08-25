// 新闻证据模块：FinBERT2 + 配置 LLM 结构化结果展示。
// 数据流：GET /news/health 引擎状态（自动重试） + POST /news/analyze 按需分析（手动触发）。
// 布局：WorkspaceHeader → NewsToolbar → NewsKpiRow → news-grid（概览 + 列表）。
// 不完整模型路径由 API 返回失败；不会展示为可执行新闻结论。

import { useCallback, useEffect, useMemo, useState } from 'react'
import '../styles/news.css'
import { api } from '../api/client'
import { executeAnalysisTask } from '../api/taskRunner'
import { useApi } from '../api/useApi'
import type { NewsAnalyzeResp } from '../api/types'
import { EmptyState, ErrorState } from '../components/ui/EmptyState/EmptyState'
import { Select } from '../components/ui/Select/Select'
import { WorkspaceHeader } from '../components/WorkspaceHeader/WorkspaceHeader'
import {
  NewsCardList,
  NewsEntityCloud,
  NewsKpiRow,
  NewsSentimentBar,
  NewsToolbar,
  NewsTopicFilter,
} from '../components/news'
import s from './NewsPage.module.css'

interface NewsPageProps {
  initialSymbol?: string
  market?: string
  timeframe?: string
  researchRunId?: string | null
  onResearchRunId?: (runId: string) => void
  embedded?: boolean
}

export default function NewsPage({
  initialSymbol = '',
  market: initialMarket = 'a_shares',
  timeframe = '1d',
  researchRunId,
  onResearchRunId,
  embedded = false,
}: NewsPageProps) {
  // —— 探活：useApi 自动重试；模型路径未就绪时阻断分析 ——
  const health = useApi(() => api.newsHealth(), [], { retryInterval: 15000 })

  // —— 分析：仅在输入标的并手动触发后请求，不随输入抖动或页面挂载自动运行 ——
  const [symbol, setSymbol] = useState(initialSymbol)
  const [market, setMarket] = useState(initialMarket)
  const [limit, setLimit] = useState(20)
  const [data, setData] = useState<NewsAnalyzeResp | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [symbolError, setSymbolError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const onSubmit = useCallback(() => {
    const normalizedSymbol = symbol.trim().toUpperCase()
    if (!normalizedSymbol) {
      setSymbolError('请输入标的代码后再分析')
      return
    }

    setSymbolError(null)
    setLoading(true)
    setError(null)
    setActiveTopics(new Set())
    executeAnalysisTask<NewsAnalyzeResp>({
      kind: 'news',
      symbol: normalizedSymbol,
      market,
      timeframe,
      payload: {
        limit,
        research_run_id: researchRunId ?? undefined,
      },
      timeoutSeconds: 90,
    })
      .then((d) => {
        setData(d)
        if (d.research_run_id) onResearchRunId?.(d.research_run_id)
      })
      .catch((e) => {
        setError(e instanceof Error ? e.message : String(e))
      })
      .finally(() => setLoading(false))
  }, [limit, market, onResearchRunId, researchRunId, symbol, timeframe])

  useEffect(() => {
    setSymbol(initialSymbol)
    setData(null)
    setError(null)
    setSymbolError(null)
  }, [initialSymbol, market, timeframe])

  useEffect(() => {
    setMarket(initialMarket)
  }, [initialMarket])

  // —— 主题筛选：本地纯前端过滤，不重新请求 ——
  const [activeTopics, setActiveTopics] = useState<Set<string>>(new Set())
  const toggleTopic = useCallback((value: string) => {
    setActiveTopics((cur) => {
      const next = new Set(cur)
      if (next.has(value)) next.delete(value)
      else next.add(value)
      return next
    })
  }, [])
  const clearTopics = useCallback(() => setActiveTopics(new Set()), [])

  const filteredItems = useMemo(() => {
    if (!data) return []
    if (activeTopics.size === 0) return data.items
    return data.items.filter((it) => activeTopics.has(it.topic))
  }, [data, activeTopics])

  const pipelineReady = health.data?.ok === true
  const engineLabel = health.data?.engine === 'transformers'
    ? `FinBERT2 + ${health.data.api_provider}`
    : '不可用'

  return (
    <div className={s.page}>
      {!embedded && (
        <WorkspaceHeader
          context="研究 / 综合评估 / 新闻证据"
          title="新闻语义证据"
          metrics={[
            { label: '分析路径', value: pipelineReady ? '可用' : '不可用' },
            { label: '引擎', value: engineLabel },
            { label: '模型', value: data?.model ?? '—' },
            { label: '总条数', value: data?.total ?? 0 },
          ]}
        />
      )}

      {!embedded && (
        <div className={s.contextBar}>
          <label>市场
            <Select
              value={market}
              onChange={(event) => setMarket(event.target.value)}
              options={[
                { value: 'a_shares', label: 'A股' },
                { value: 'us_stocks', label: '美股' },
                { value: 'crypto', label: '虚拟货币' },
              ]}
            />
          </label>
        </div>
      )}

      {/* 工具栏 */}
      <NewsToolbar
        symbol={symbol}
        onSymbolChange={(value) => {
          setSymbol(value)
          if (value.trim()) setSymbolError(null)
        }}
        symbolError={symbolError}
        onSubmit={onSubmit}
        limit={limit}
        onLimitChange={setLimit}
        loading={loading}
        health={health.data}
        healthLoading={health.loading}
        onRefreshHealth={health.refetch}
      />

      {/* 错误态（探活或分析失败） */}
      {error ? (
        <ErrorState
          message={error}
          onRetry={onSubmit}
          retrying={loading}
        />
      ) : loading && !data ? (
        // 首次加载：骨架屏占位（NewsCardList 内置骨架）
        <NewsCardList items={[]} degraded={false} loading={true} />
      ) : !data ? (
        <EmptyState
          title="输入标的代码开始分析"
          desc="新闻证据不会在页面打开时自动生成。选择市场并输入标的代码后手动开始。"
        />
      ) : data.items.length === 0 ? (
        <EmptyState
          title="暂无新闻数据"
          desc="当前标的未获取到可分析的新闻，请检查代码或稍后重试。"
          action={{ label: '重新分析', onClick: onSubmit, loading }}
        />
      ) : (
        <>
          {/* KPI 行 */}
          <NewsKpiRow data={data} />

          {/* 双栏：概览 + 列表 */}
          <div className="news-grid">
            <NewsCardList
              items={filteredItems}
              degraded={data.degraded}
              loading={false}
            />

            <aside className="news-overview">
              <NewsSentimentBar dist={data.sentiment_dist} total={data.total} />
              <NewsTopicFilter
                activeTopics={activeTopics}
                topicDist={data.topic_dist}
                onToggle={toggleTopic}
                onClear={clearTopics}
              />
              <NewsEntityCloud entities={data.top_entities} />
            </aside>
          </div>
        </>
      )}
    </div>
  )
}
