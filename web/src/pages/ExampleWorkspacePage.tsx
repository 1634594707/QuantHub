import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button } from '../components/ui/Button/Button'
import { WorkspaceHeader } from '../components/WorkspaceHeader/WorkspaceHeader'
import s from './ExampleWorkspacePage.module.css'

export default function ExampleWorkspacePage() {
  const navigate = useNavigate()
  const [evidenceOpen, setEvidenceOpen] = useState(false)
  const [message, setMessage] = useState('')

  function resetExample() {
    setEvidenceOpen(false)
    setMessage('示例视图已重置；用户研究记录未发生变化')
  }

  return <div className={s.page}>
    <WorkspaceHeader
      context="研究 / 只读示例"
      title="贵州茅台 600519"
      description="独立示例工作区"
      metrics={[
        { label: '市场', value: 'A 股' },
        { label: '周期', value: '日线' },
        { label: '状态', value: '只读示例' },
      ]}
    />

    <section className={s.notice}>
      <div><strong>只读示例</strong><span>固定内容不读取、不创建也不修改用户研究、提醒、订单或账本记录。</span></div>
      <Button size="sm" variant="secondary" onClick={resetExample}>重置示例</Button>
    </section>

    <section className={s.report}>
      <header>
        <div><span>综合评估结论</span><h2>数据不足</h2><p>该示例不包含实时行情、新闻或模型输出，因此不生成方向性判断。</p></div>
        <b>数据不足</b>
      </header>
      <dl>
        <div><dt>股票名称</dt><dd>贵州茅台</dd></div>
        <div><dt>股票代码</dt><dd>600519</dd></div>
        <div><dt>最新价格</dt><dd>未提供</dd></div>
        <div><dt>价格时间</dt><dd>未提供</dd></div>
        <div><dt>行情来源</dt><dd>只读示例</dd></div>
        <div><dt>适用周期</dt><dd>日线</dd></div>
      </dl>
      <div className={s.reportGrid}>
        <div><h3>主要依据</h3><ul><li>没有可验证的行情快照</li><li>没有可验证的新闻快照</li><li>没有模型运行记录</li></ul></div>
        <div><h3>主要风险</h3><p>缺少实时数据时，任何方向性结论都不可验证。</p><h3>失效条件</h3><p>接入真实数据并完成一次评估后，应以真实报告替代本示例。</p></div>
      </div>
      <button type="button" className={s.evidenceToggle} aria-expanded={evidenceOpen} onClick={() => setEvidenceOpen((open) => !open)}>{evidenceOpen ? '收起依据详情' : '展开依据详情'}</button>
      {evidenceOpen && <div className={s.evidence}><strong>数据来源</strong><span>固定示例内容</span><strong>快照时间</strong><span>未提供</span><strong>模型</strong><span>未运行</span><strong>原始依据</strong><pre>{JSON.stringify({ market: null, news: null, model: null }, null, 2)}</pre></div>}
      <footer>
        <p>辅助研究，不构成投资建议。</p>
        <div><Button variant="primary" onClick={() => navigate('/evaluate')}>开始真实评估</Button>{message && <span role="status">{message}</span>}</div>
      </footer>
    </section>
  </div>
}
