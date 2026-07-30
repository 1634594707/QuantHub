import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../../api/client'
import { workspacesForMode } from '../../navigation/workspaces'
import type { InterfaceMode } from '../../hooks/useInterfaceMode'
import type {
  GlobalSearchItem,
  Instrument,
  ResearchRun,
  SignalResp,
  SimulationOrder,
  StrategyDefinition,
  StrategyExperiment,
} from '../../api/types'
import { researchRunHref } from '../../lib/researchResults'
import { IconSearch } from '../icons'
import styles from './CommandPalette.module.css'

type CommandGroup =
  | 'actions'
  | 'pages'
  | 'instruments'
  | 'definitions'
  | 'experiments'
  | 'research'
  | 'signals'
  | 'orders'

interface CommandItem {
  id: string
  group: CommandGroup
  marker: string
  label: string
  detail: string
  path: string
  keywords: string
  secondaryLabel?: string
  secondaryPath?: string
}

function globalItem(item: GlobalSearchItem): CommandItem {
  return {
    id: item.id,
    group: item.group,
    marker: item.marker,
    label: item.label,
    detail: item.detail,
    path: item.path,
    keywords: '',
    secondaryLabel: item.secondary_label,
    secondaryPath: item.secondary_path,
  }
}

interface BusinessSearchState {
  query: string
  items: CommandItem[]
  loading: boolean
  errorCount: number
}

const GROUP_LABELS: Record<CommandGroup, string> = {
  actions: '快捷操作',
  pages: '页面',
  instruments: '标的',
  definitions: '策略定义',
  experiments: '策略实验',
  research: '研究记录',
  signals: '信号',
  orders: '模拟订单',
}

const GROUP_ORDER: CommandGroup[] = [
  'actions',
  'pages',
  'instruments',
  'definitions',
  'experiments',
  'research',
  'signals',
  'orders',
]

const QUICK_ACTIONS: CommandItem[] = [
  {
    id: 'action:new-research',
    group: 'actions',
    marker: '+',
    label: '新建综合评估',
    detail: '量化、AI 证据与模型共识',
    path: '/evaluate',
    keywords: '新建 创建 评估 股票 研究 标的',
  },
  {
    id: 'action:create-experiment',
    group: 'actions',
    marker: '+',
    label: '创建实验',
    detail: '选择策略定义并建立实验',
    path: '/strategy-lab?action=create_experiment',
    keywords: '新建 创建 策略 实验 回测',
  },
  {
    id: 'action:review-signals',
    group: 'actions',
    marker: '!',
    label: '进入待审核信号',
    detail: '仅显示状态为 new 的信号',
    path: '/signals?status=new',
    keywords: '信号 审核 new 待处理',
  },
]

function pageCommands(mode: InterfaceMode): CommandItem[] {
  return workspacesForMode(mode).flatMap((workspace) => (
  workspace.items.map((item) => ({
    id: `page:${item.key}`,
    group: 'pages' as const,
    marker: '/',
    label: item.label,
    path: item.to,
    detail: workspace.label,
    keywords: item.searchKeywords ?? `${workspace.label} ${item.label}`,
  }))
  ))
}

function includesQuery(query: string, values: Array<string | null | undefined>): boolean {
  return values.some((value) => value?.toLocaleLowerCase().includes(query))
}

function staticMatches(item: CommandItem, query: string): boolean {
  return !query || includesQuery(query, [item.label, item.detail, item.path, item.keywords])
}

function instrumentItems(rows: Instrument[], query: string): CommandItem[] {
  return rows
    .filter((row) => includesQuery(query, [row.instrument_id, row.code, row.name, row.market, row.exchange, row.asset_class]))
    .slice(0, 6)
    .map((row) => ({
      id: `instrument:${row.instrument_id}`,
      group: 'instruments',
      marker: '标',
      label: `${row.code} ${row.name}`.trim(),
      detail: `${row.market} · ${row.exchange} · ${row.asset_class}`,
      path: `/research/${encodeURIComponent(row.code)}?market=${encodeURIComponent(row.market)}&tf=1d`,
      keywords: `${row.instrument_id} ${row.currency}`,
    }))
}

function definitionItems(rows: StrategyDefinition[], query: string): CommandItem[] {
  return rows
    .filter((row) => includesQuery(query, [row.id, row.name, row.strategy_key, row.market, row.description, ...row.tags]))
    .slice(0, 6)
    .map((row) => ({
      id: `definition:${row.id}`,
      group: 'definitions',
      marker: '策',
      label: row.name,
      detail: `${row.strategy_key} · ${row.market}`,
      path: `/strategy-lab?definition_id=${encodeURIComponent(row.id)}`,
      keywords: row.tags.join(' '),
      secondaryLabel: '创建实验',
      secondaryPath: `/strategy-lab?definition_id=${encodeURIComponent(row.id)}&action=create_experiment`,
    }))
}

function experimentItems(rows: StrategyExperiment[], query: string): CommandItem[] {
  return rows
    .filter((row) => includesQuery(query, [row.id, row.definition_id, row.symbol, row.market, row.timeframe, row.status, row.note]))
    .slice(0, 6)
    .map((row) => ({
      id: `experiment:${row.id}`,
      group: 'experiments',
      marker: '验',
      label: `${row.symbol} · ${row.timeframe}`,
      detail: `${row.status} · ${row.market} · ${row.id.slice(0, 12)}`,
      path: `/strategy-lab?definition_id=${encodeURIComponent(row.definition_id)}&experiment_id=${encodeURIComponent(row.id)}`,
      keywords: `${row.id} ${row.note}`,
    }))
}

function researchItems(rows: ResearchRun[], query: string): CommandItem[] {
  return rows
    .filter((row) => includesQuery(query, [row.id, row.symbol, row.market, row.timeframe, row.status, row.note, ...row.modules]))
    .slice(0, 6)
    .map((row) => ({
      id: `research:${row.id}`,
      group: 'research',
      marker: '研',
      label: `${row.symbol} · ${row.modules.join(' + ') || '空白研究'}`,
      detail: `${row.status} · ${row.timeframe} · ${row.evidence_count} 证据`,
      path: researchRunHref(row),
      keywords: `${row.id} ${row.note}`,
    }))
}

function signalItems(rows: SignalResp[], query: string): CommandItem[] {
  return rows
    .filter((row) => includesQuery(query, [row.id, row.symbol, row.market, row.timeframe, row.direction, row.source, row.status, ...row.tags]))
    .slice(0, 6)
    .map((row) => ({
      id: `signal:${row.id ?? `${row.symbol}:${row.ts ?? ''}`}`,
      group: 'signals',
      marker: '信',
      label: `${row.symbol} · ${row.direction}`,
      detail: `${row.status ?? 'new'} · ${row.source} · ${row.timeframe}`,
      path: row.id ? `/signals?signal_id=${encodeURIComponent(row.id)}` : '/signals',
      keywords: `${row.id ?? ''} ${row.tags.join(' ')}`,
    }))
}

function orderItems(rows: SimulationOrder[], query: string): CommandItem[] {
  return rows
    .filter((row) => includesQuery(query, [row.id, row.signal_id, row.symbol, row.market, row.side, row.status, row.order_type]))
    .slice(0, 6)
    .map((row) => ({
      id: `order:${row.id}`,
      group: 'orders',
      marker: '单',
      label: `${row.symbol} · ${row.side}`,
      detail: `${row.status} · ${row.filled_quantity}/${row.quantity} · ${row.id.slice(0, 12)}`,
      path: `/simulation?order_id=${encodeURIComponent(row.id)}`,
      keywords: `${row.id} ${row.signal_id ?? ''}`,
    }))
}

interface CommandPaletteProps {
  open: boolean
  onClose: () => void
  interfaceMode: InterfaceMode
}

export function CommandPalette({ open, onClose, interfaceMode }: CommandPaletteProps) {
  const [query, setQuery] = useState('')
  const [activeIndex, setActiveIndex] = useState(0)
  const [searchRevision, setSearchRevision] = useState(0)
  const [business, setBusiness] = useState<BusinessSearchState>({
    query: '',
    items: [],
    loading: false,
    errorCount: 0,
  })
  const inputRef = useRef<HTMLInputElement>(null)
  const paletteRef = useRef<HTMLElement>(null)
  const itemRefs = useRef(new Map<number, HTMLDivElement>())
  const requestId = useRef(0)
  const restoreFocusRef = useRef<HTMLElement | null>(null)
  const wasOpenRef = useRef(false)
  const navigate = useNavigate()
  const normalizedQuery = query.trim().toLocaleLowerCase()

  const staticItems = useMemo(
    () => [
      ...QUICK_ACTIONS.filter((item) => interfaceMode === 'advanced' || item.id === 'action:new-research'),
      ...pageCommands(interfaceMode),
    ].filter((item) => staticMatches(item, normalizedQuery)),
    [interfaceMode, normalizedQuery],
  )
  const businessItems = business.query === normalizedQuery
    ? business.items.filter((item) => interfaceMode === 'advanced' || ['instruments', 'research', 'orders'].includes(item.group))
    : []
  const items = useMemo(() => [...staticItems, ...businessItems], [businessItems, staticItems])
  const groupedItems = useMemo(
    () => GROUP_ORDER
      .map((group) => ({ group, items: items.filter((item) => item.group === group) }))
      .filter((section) => section.items.length > 0),
    [items],
  )
  const indexById = useMemo(
    () => new Map(items.map((item, index) => [item.id, index])),
    [items],
  )

  useEffect(() => {
    if (!open || !normalizedQuery) {
      requestId.current += 1
      setBusiness({ query: '', items: [], loading: false, errorCount: 0 })
      return
    }

    const currentRequest = ++requestId.current
    setBusiness({ query: normalizedQuery, items: [], loading: true, errorCount: 0 })
    const timer = window.setTimeout(async () => {
      const results = await Promise.allSettled([api.globalSearch(query.trim(), 6)])
      if (requestId.current !== currentRequest) return

      const [globalResults] = results
      const next = globalResults.status === 'fulfilled'
        ? globalResults.value.items.map(globalItem)
        : []
      setBusiness({
        query: normalizedQuery,
        items: next,
        loading: false,
        errorCount: results.filter((result) => result.status === 'rejected').length,
      })
    }, 180)

    return () => window.clearTimeout(timer)
  }, [normalizedQuery, open, query, searchRevision])

  useEffect(() => {
    if (!items.length) {
      setActiveIndex(0)
      return
    }
    setActiveIndex((index) => Math.min(index, items.length - 1))
  }, [items.length])

  useEffect(() => {
    itemRefs.current.get(activeIndex)?.scrollIntoView?.({ block: 'nearest' })
  }, [activeIndex])

  useEffect(() => {
    if (!open) return
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        onClose()
        return
      }
      if (event.key === 'Tab') {
        const focusable = Array.from(
          paletteRef.current?.querySelectorAll<HTMLElement>('input:not([disabled]), button:not([disabled])') ?? [],
        )
        if (!focusable.length) return
        const first = focusable[0]
        const last = focusable[focusable.length - 1]
        const active = document.activeElement
        if (event.shiftKey && (active === first || !paletteRef.current?.contains(active))) {
          event.preventDefault()
          last.focus()
        } else if (!event.shiftKey && active === last) {
          event.preventDefault()
          first.focus()
        }
        return
      }
      if (event.key === 'ArrowDown') {
        event.preventDefault()
        setActiveIndex((index) => Math.min(index + 1, items.length - 1))
        return
      }
      if (event.key === 'ArrowUp') {
        event.preventDefault()
        setActiveIndex((index) => Math.max(index - 1, 0))
        return
      }
      if (event.key === 'Enter') {
        if (event.target instanceof HTMLButtonElement) return
        event.preventDefault()
        const item = items[activeIndex]
        if (item) {
          navigate(item.path)
          onClose()
        }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [activeIndex, items, navigate, onClose, open])

  useEffect(() => {
    if (open && !wasOpenRef.current) {
      restoreFocusRef.current = document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null
      setQuery('')
      setActiveIndex(0)
      requestAnimationFrame(() => inputRef.current?.focus())
    } else if (!open && wasOpenRef.current) {
      const target = restoreFocusRef.current
      requestAnimationFrame(() => target?.focus())
    }
    wasOpenRef.current = open
  }, [open])

  if (!open) return null

  const go = (path: string) => {
    navigate(path)
    onClose()
  }
  const showEmpty = Boolean(normalizedQuery) && !business.loading && items.length === 0

  return (
    <div
      className={styles.backdrop}
      role="dialog"
      aria-modal="true"
      aria-label="全局检索"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <section ref={paletteRef} className={styles.palette}>
        <div className={styles.searchRow}>
          <IconSearch size={18} className={styles.searchIcon} />
          <input
            ref={inputRef}
            className={styles.input}
            placeholder="搜索页面、标的、策略、研究、信号或订单"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value)
              setActiveIndex(0)
            }}
            aria-label="全局业务搜索"
            aria-controls="global-command-results"
            aria-activedescendant={items[activeIndex] ? `command-${items[activeIndex].id}` : undefined}
            autoComplete="off"
          />
          <span className={styles.resultCount}>{business.loading ? '检索中' : `${items.length} 项`}</span>
        </div>

        <div
          id="global-command-results"
          className={styles.list}
          role="listbox"
          aria-label="检索结果"
          aria-busy={business.loading}
        >
          {groupedItems.map((section) => (
            <section className={styles.group} key={section.group} aria-label={GROUP_LABELS[section.group]}>
              <div className={styles.groupLabel}>{GROUP_LABELS[section.group]}</div>
              {section.items.map((item) => {
                const index = indexById.get(item.id) ?? 0
                const active = index === activeIndex
                return (
                  <div
                    id={`command-${item.id}`}
                    key={item.id}
                    ref={(node) => {
                      if (node) itemRefs.current.set(index, node)
                      else itemRefs.current.delete(index)
                    }}
                    className={`${styles.item} ${active ? styles.active : ''}`}
                    role="option"
                    aria-selected={active}
                    onMouseEnter={() => setActiveIndex(index)}
                  >
                    <button type="button" className={styles.itemMain} onClick={() => go(item.path)}>
                      <span className={styles.marker} aria-hidden="true">{item.marker}</span>
                      <span className={styles.itemCopy}>
                        <b>{item.label}</b>
                        <small>{item.detail}</small>
                      </span>
                    </button>
                    {item.secondaryLabel && item.secondaryPath && (
                      <button
                        type="button"
                        className={styles.secondaryAction}
                        onClick={() => go(item.secondaryPath!)}
                      >
                        {item.secondaryLabel}
                      </button>
                    )}
                  </div>
                )
              })}
            </section>
          ))}

          {business.loading && (
            <div className={styles.state} role="status">
              <span className={styles.loader} aria-hidden="true" />
              正在读取业务数据
            </div>
          )}
          {showEmpty && <div className={styles.state}>没有找到“{query.trim()}”</div>}
          {business.errorCount > 0 && !business.loading && (
            <div className={styles.errorNotice} role="status">
              <span>业务数据未载入</span>
              <button type="button" onClick={() => setSearchRevision((value) => value + 1)}>重新检索</button>
            </div>
          )}
        </div>
      </section>
    </div>
  )
}
