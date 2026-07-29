import { useState } from 'react'
import type { ResearchRun } from '../../api/types'
import s from './EvidenceRail.module.css'

function formatTime(epoch: number): string {
  return new Date(epoch * 1000).toLocaleString('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
  })
}

export function EvidenceRail({ run, integrity }: { run: ResearchRun | null; integrity: string }) {
  const [collapsed, setCollapsed] = useState(false)
  return (
    <aside className={`${s.rail} ${collapsed ? s.collapsed : ''}`} aria-label="证据轨道">
      <header>
        <div>
          <span>证据轨道</span>
          <strong>{run ? `${run.evidence_count} 条证据` : '等待研究运行'}</strong>
        </div>
        <button
          type="button"
          title={collapsed ? '展开证据轨道' : '折叠证据轨道'}
          aria-label={collapsed ? '展开证据轨道' : '折叠证据轨道'}
          aria-expanded={!collapsed}
          onClick={() => setCollapsed((value) => !value)}
        >
          <span aria-hidden="true">{collapsed ? '‹' : '›'}</span>
        </button>
      </header>
      {!collapsed && (
        <div className={s.body}>
          {run ? (
            <>
              <dl className={s.meta}>
                <div><dt>运行</dt><dd>{run.id}</dd></div>
                <div><dt>状态</dt><dd>{run.status}</dd></div>
                <div><dt>模块</dt><dd>{run.modules.join(' / ') || '—'}</dd></div>
                <div><dt>完整性</dt><dd>{integrity}</dd></div>
                <div><dt>更新时间</dt><dd>{formatTime(run.updated_at)}</dd></div>
              </dl>
              <ol className={s.timeline}>
                {(run.evidence ?? []).map((evidence) => (
                  <li key={evidence.id}>
                    <span>{evidence.kind}</span>
                    <strong>{evidence.title || '未命名证据'}</strong>
                    <small>{evidence.source} · {formatTime(evidence.captured_at)}</small>
                    {evidence.uri && <a href={evidence.uri} target="_blank" rel="noreferrer">打开来源</a>}
                  </li>
                ))}
              </ol>
              {!run.evidence?.length && <p className={s.empty}>当前运行没有证据明细。</p>}
            </>
          ) : (
            <p className={s.empty}>选择研究运行后显示来源、快照、模型版本和更新时间。</p>
          )}
        </div>
      )}
    </aside>
  )
}
