import { useState } from 'react'
import type { CSSProperties } from 'react'
import type { MarketBreadthResp } from '../api/types'
import s from './MarketBreadth.module.css'
import { useLanguage } from '../i18n'

const PREVIEW_COUNT = 4

export default function MarketBreadth({
  data,
}: {
  data?: MarketBreadthResp | null
}) {
  const [expanded, setExpanded] = useState(false)
  const { t } = useLanguage()
  // M3 无假数据：没有后端返回时渲染空态，不使用任何硬编码广度/行业数据
  if (!data) {
    return (
      <div className={`card ${s.card}`}>
        <div className="card-head">
          <div className="card-title">
            {t('市场广度')} <span className="sub">{t('暂无数据')}</span>
          </div>
        </div>
        <div className={s.body}>
          <div className={`muted ${s.note}`}>{t('未取到市场广度数据，稍后重试或检查数据源状态。')}</div>
        </div>
      </div>
    )
  }
  const b = data
  const sectors = data.sectors ?? []
  const total = Math.max(1, b.up + b.flat + b.down)
  const pct = (v: number) => ((v / total) * 100).toFixed(1)
  const top = [...sectors].sort((a, c) => c.chgPct - a.chgPct)
  const visible = expanded ? top : top.slice(0, PREVIEW_COUNT)
  const hidden = Math.max(0, top.length - PREVIEW_COUNT)
  const marketTone = b.up > b.down ? '上涨占优' : b.down > b.up ? '下跌占优' : '多空均衡'

  return (
    <div className={`card ${s.card}`}>
      <div className="card-head">
        <div className="card-title">
          {t('市场广度')} <span className="sub">{t(marketTone)}</span>
          {b.sample && <span className={`src-pill warn ${s.samplePill}`}>{t('样本')}</span>}
        </div>
      </div>
      <div className={s.body}>
        {b.note && <div className={s.note} title={b.note}>{b.note}</div>}
        <div
          className={s.bar}
          role="img"
          aria-label={`${t('上涨')} ${b.up} ${t('平')} ${b.flat} ${t('下跌')} ${b.down}`}
        >
          <i
            className={`${s.barSeg} ${s.barSegUp}`}
            style={{ '--w': pct(b.up) + '%' } as CSSProperties}
          />
          <i
            className={`${s.barSeg} ${s.barSegFlat}`}
            style={{ '--w': pct(b.flat) + '%' } as CSSProperties}
          />
          <i
            className={`${s.barSeg} ${s.barSegDown}`}
            style={{ '--w': pct(b.down) + '%' } as CSSProperties}
          />
        </div>
        <div className={s.legend}>
          <span className="up">
            {t('涨')} <b>{b.up}</b> ({pct(b.up)}%)
          </span>
          <span className="sec">
            {t('平')} <b>{b.flat}</b>
          </span>
          <span className="down">
            {t('跌')} <b>{b.down}</b> ({pct(b.down)}%)
          </span>
        </div>

        <div className={s.sectors}>
          {visible.length === 0 && <div className={`muted ${s.note}`}>{t('暂无行业涨跌数据')}</div>}
          {visible.map((sec) => {
            const up = sec.chgPct >= 0
            return (
              <div className={s.sector} key={sec.name}>
                <span>{sec.name}</span>
                <span className={`mono ${s.sectorChange} ${up ? 'up' : 'down'}`}>
                  {up ? '+' : ''}
                  {sec.chgPct.toFixed(2)}%
                </span>
              </div>
            )
          })}
        </div>

        {hidden > 0 && (
          <button
            type="button"
            className={s.toggle}
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? t('收起行业') : `${t('展开')} ${hidden} ${t('个行业')}`}
          </button>
        )}
      </div>
    </div>
  )
}
