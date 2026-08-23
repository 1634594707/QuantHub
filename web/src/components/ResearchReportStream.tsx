import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import type { ResearchReport, ResearchReportEvent } from '../api/types'

const LABELS: Record<ResearchReport['mode'], string> = {
  quick: '简明', investor: '投资研究', professional: '专业验证', quant: '量化实验',
}

export function ResearchReportStream({ runId, mode, reportId }: { runId: string; mode: ResearchReport['mode']; reportId?: string }) {
  const [report, setReport] = useState<ResearchReport | null>(null)
  const [events, setEvents] = useState<ResearchReportEvent[]>([])
  const [stopped, setStopped] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    setReport(null); setEvents([]); setStopped(false); setError('')
    const request = reportId ? api.researchReport(reportId) : api.createResearchReport(runId, mode)
    request.then((result) => {
      if (active) setReport(result.report)
    }).catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : String(cause)) })
    return () => { active = false }
  }, [runId, mode, reportId])

  useEffect(() => {
    if (!report || stopped) return
    let active = true
    const load = async () => {
      try {
        const next = await api.researchReportEvents(report.id, events.length ? events[events.length - 1].sequence : 0)
        if (active && next.events.length) setEvents((current) => [...current, ...next.events.filter((item) => !current.some((known) => known.sequence === item.sequence))])
      } catch (cause) {
        if (active) setError(cause instanceof Error ? cause.message : String(cause))
      }
    }
    void load()
    return () => { active = false }
  }, [report, stopped, events])

  const sections = useMemo(() => {
    const output = new Map<string, string>()
    for (const event of events) {
      const key = String(event.payload.section_key ?? event.section_id ?? '')
      if (event.event_type === 'delta') output.set(key, `${output.get(key) ?? ''}${String(event.payload.delta ?? '')}`)
    }
    return [...output.entries()]
  }, [events])
  if (!runId) return null
  return <section className="research-report-stream" aria-label="AI 分析报告流式输出">
    <header><div><span>章节级报告</span><h2>{LABELS[mode]} · {report?.status === 'completed' ? '已完成' : stopped ? '已停止' : '生成中'}</h2></div>
      {report && report.status !== 'completed' && <button type="button" onClick={() => { setStopped(true); void api.cancelResearchReport(report.id) }}>停止生成</button>}</header>
    <p className="research-report-disclaimer">研究参考，不是收益承诺 · 数据截止时间：{report?.data_cutoff ?? '计算中'}</p>
    {error ? <div role="alert">{error}</div> : null}
    {sections.map(([key, body]) => <article key={key}><h3>{key}</h3><p>{body}</p></article>)}
  </section>
}
