import type { HoldingInput, HoldingRow } from '../hooks/useEditableHoldings'
import { Button } from './ui/Button/Button'
import { Input } from './ui/Input/Input'
import { Select } from './ui/Select/Select'
import { IconButton } from './ui/IconButton/IconButton'
import { Table } from './ui/Table'
import s from './HoldingsTable.module.css'

const fmt = (n: number) => n.toLocaleString('en-US', { maximumFractionDigits: 2 })
const fmtInt = (n: number) => n.toLocaleString('en-US', { maximumFractionDigits: 0 })

const MARKETS = [
  { value: 'a_shares', label: 'A股' },
  { value: 'us_stocks', label: '美股' },
  { value: 'crypto', label: '加密货币' },
]

function ReturnBar({ ret }: { ret: number }) {
  const pct = Math.min(98, Math.max(2, 50 + ret * 1.5))
  const up = ret >= 0
  return (
    <div className={s.winrate}>
      <span className={`${s.winrateValue} ${up ? 'up' : 'down'}`}>
        {up ? '+' : ''}
        {ret.toFixed(1)}%
      </span>
      <div className={s.winrateTrack}>
        <div
          className={s.winrateFill}
          style={{ width: `${pct}%`, background: up ? 'var(--up)' : 'var(--down)' }}
        />
      </div>
    </div>
  )
}

interface Props {
  rows: HoldingRow[]
  editing: boolean
  onAdd: () => void
  onUpdate: (id: string, patch: Partial<HoldingInput>) => void
  onResolveName: (id: string, symbol: string, market: string) => void
  onRemove: (id: string) => void
  onToggleEdit: () => void
  saving?: boolean
  saveError?: string
  resolvingIds?: ReadonlySet<string>
}

export default function HoldingsTable({
  rows,
  editing,
  onAdd,
  onUpdate,
  onResolveName,
  onRemove,
  onToggleEdit,
  saving = false,
  saveError = '',
  resolvingIds = new Set(),
}: Props) {
  return (
    <div className="card">
      <div className="card-head">
        <div className="card-title">
          研究组合持仓 <span className="sub">{rows.length} 只</span>
        </div>
        {editing ? (
          <div className={s.headActions}>
            <Button variant="link" size="sm" onClick={onAdd}>
              + 添加
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={onToggleEdit}
              loading={saving}
              disabled={saving}
            >
              {saving ? '保存中…' : '完成'}
            </Button>
          </div>
        ) : (
          <Button variant="link" size="sm" onClick={onToggleEdit}>
            编辑
          </Button>
        )}
      </div>

      {editing ? (
        <div className="edit-list">
          {rows.map((r) => (
            <div className={`edit-row ${s.editRow}`} key={r.id}>
              <Input
                className="edit-input"
                placeholder="代码"
                value={r.code}
                onChange={(e) => {
                  const code = e.target.value.toUpperCase()
                  onUpdate(r.id, { code, name: '' })
                  onResolveName(r.id, code, r.market)
                }}
              />
              <Input
                className="edit-input"
                placeholder={resolvingIds.has(r.id) ? '识别中…' : '名称'}
                value={r.name}
                aria-busy={resolvingIds.has(r.id)}
                onChange={(e) => onUpdate(r.id, { name: e.target.value })}
              />
              <Select
                className="edit-input"
                options={MARKETS}
                value={r.market}
                onChange={(e) => {
                  const market = e.target.value
                  onUpdate(r.id, { market, name: '' })
                  onResolveName(r.id, r.code, market)
                }}
              />
              <Input
                className={`edit-input num ${s.numInput}`}
                type="number"
                placeholder="股数"
                value={r.shares}
                onChange={(e) => onUpdate(r.id, { shares: Number(e.target.value) || 0 })}
              />
              <Input
                className={`edit-input num ${s.numInput}`}
                type="number"
                placeholder="成本"
                value={r.cost}
                onChange={(e) => onUpdate(r.id, { cost: Number(e.target.value) || 0 })}
              />
              <IconButton
                variant="ghost"
                size="sm"
                label="删除持仓"
                title="删除持仓"
                onClick={() => onRemove(r.id)}
              >
                ✕
              </IconButton>
            </div>
          ))}
          {rows.length === 0 && (
            <div className={`muted ${s.emptyHint}`}>
              暂无持仓
            </div>
          )}
          {saveError && <div className="edit-save-error" role="alert">{saveError}</div>}
        </div>
      ) : (
        <Table
          rows={rows}
          rowKey={(r) => r.id}
          columns={[
            {
              key: 'name',
              header: '标的',
              render: (r) => (
                <div className="sym">
                  <div className="sym-badge">{r.name.slice(0, 1)}</div>
                  <div>
                    <div className="sym-name">{r.name}</div>
                    <div className="sym-code mono">{r.code}</div>
                  </div>
                </div>
              ),
            },
            {
              key: 'price',
              header: '最新价',
              align: 'right',
              render: (r) =>
                r.available && r.price != null ? <span className="mono">{fmt(r.price)}</span> : <span className="watch-unavail">无行情</span>,
            },
            {
              key: 'chg',
              header: '涨跌幅',
              align: 'right',
              render: (r) => {
                const up = (r.chgPct ?? 0) >= 0
                return r.chgPct == null
                  ? <span className="watch-unavail">—</span>
                  : <span className={`mono ${up ? 'up' : 'down'}`}>{up ? '+' : ''}{r.chgPct.toFixed(2)}%</span>
              },
            },
            {
              key: 'shares',
              header: '持仓',
              align: 'right',
              render: (r) => <span className="mono">{fmtInt(r.shares)}</span>,
            },
            {
              key: 'marketValue',
              header: '市值',
              align: 'right',
              render: (r) =>
                r.marketValue == null ? <span className="watch-unavail">—</span> : <span className="mono">{fmtInt(r.marketValue)}</span>,
            },
            {
              key: 'pnl',
              header: '浮动盈亏',
              align: 'right',
              render: (r) => {
                const pnlUp = (r.pnl ?? 0) >= 0
                return r.pnl == null
                  ? <span className="watch-unavail">—</span>
                  : <span className={`mono ${pnlUp ? 'up' : 'down'}`}>{pnlUp ? '+' : '-'}{fmt(Math.abs(r.pnl))}</span>
              },
            },
            {
              key: 'return',
              header: '收益率',
              render: (r) => {
                const hasValuation = r.available && r.price != null && r.marketValue != null && r.pnl != null
                return hasValuation && r.price != null
                  ? <ReturnBar ret={(r.price - r.cost) / r.cost * 100} />
                  : <span className="watch-unavail">无行情</span>
              },
            },
          ]}
        />
      )}
    </div>
  )
}
