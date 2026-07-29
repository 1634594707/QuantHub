import { useState } from 'react'
import DecisionPanel from '../components/DecisionPanel'
import { Field } from '../components/ui/Field/Field'
import { Input } from '../components/ui/Input/Input'
import { SegmentedControl } from '../components/ui/SegmentedControl/SegmentedControl'
import { Button } from '../components/ui/Button/Button'
import { Select } from '../components/ui/Select/Select'
import { WorkspaceHeader } from '../components/WorkspaceHeader/WorkspaceHeader'
import s from './PaAnalysisPage.module.css'

const TIMEFRAMES = [
  { value: '5m', label: '5m' },
  { value: '15m', label: '15m' },
  { value: '1h', label: '1h' },
  { value: '1d', label: '1d' },
]

export default function PaAnalysisPage() {
  const [symbol, setSymbol] = useState('600519')
  const [timeframe, setTimeframe] = useState('1h')
  const [market, setMarket] = useState('a_shares')
  const [active, setActive] = useState({ symbol: '600519', timeframe: '1h', market: 'a_shares' })
  const [requestKey, setRequestKey] = useState(0)
  const [symbolError, setSymbolError] = useState('')
  const [researchRunId, setResearchRunId] = useState<string | null>(null)

  function run() {
    const normalized = symbol.trim().toUpperCase()
    if (!normalized) {
      setSymbolError('请输入标的代码')
      return
    }
    setSymbolError('')
    setActive({ symbol: normalized, timeframe, market })
    setResearchRunId(null)
    setRequestKey((key) => key + 1)
  }

  return (
    <div className="stack-4">
      <WorkspaceHeader
        context="研究 / PA 分析"
        title="价格行为分析"
        metrics={[
          { label: '当前标的', value: active.symbol },
          { label: '周期', value: active.timeframe },
          { label: '市场', value: active.market },
        ]}
      />
      <div className="card">
        <div className="card-head">
          <div className="card-title">
            PA 分析工作台
            <span className="sub">价格行为两阶段分析</span>
          </div>
        </div>
        <div className={s.formArea}>
          <Field label="标的代码" error={symbolError || undefined}>
            <Input
              value={symbol}
              onChange={(e) => {
                setSymbol(e.target.value)
                if (e.target.value.trim()) setSymbolError('')
              }}
              onKeyDown={(e) => e.key === 'Enter' && run()}
              placeholder="如 600519"
              invalid={Boolean(symbolError)}
              className={s.symbolInput}
            />
          </Field>

          <Field label="周期">
            <SegmentedControl
              value={timeframe}
              onChange={setTimeframe}
              options={TIMEFRAMES}
            />
          </Field>

          <Field label="市场">
            <Select
              value={market}
              onChange={(event) => setMarket(event.target.value)}
              options={[
                { value: 'a_shares', label: 'A股' },
                { value: 'crypto', label: '加密' },
              ]}
            />
          </Field>

          <Button variant="primary" className={s.runBtn} onClick={run}>
            运行分析
          </Button>
        </div>
      </div>

      <DecisionPanel
        symbol={active.symbol}
        timeframe={active.timeframe}
        market={active.market}
        requestKey={requestKey}
        researchRunId={researchRunId}
        onResearchRunId={setResearchRunId}
      />
      {researchRunId && (
        <div className={s.researchLink}>
          <span>研究记录 <b className="mono-num">{researchRunId.slice(0, 12)}</b></span>
          <a href={`/research/${encodeURIComponent(active.symbol)}?market=${encodeURIComponent(active.market)}&tf=${encodeURIComponent(active.timeframe)}&view=history`}>打开研究历史</a>
        </div>
      )}
    </div>
  )
}
