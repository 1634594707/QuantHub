// 面板：Card 强化版，带 head/title/subtitle/actions/body，可折叠。
// 替代 .panel / .panel-head / .panel-body / .panel-actions。
import { useState, type ReactNode } from 'react'
import s from './Panel.module.css'
import { useLanguage } from '../../../i18n'

interface PanelProps {
  title?: ReactNode
  subtitle?: ReactNode
  actions?: ReactNode
  collapsible?: boolean
  defaultOpen?: boolean
  className?: string
  bodyClassName?: string
  children: ReactNode
}

export function Panel({
  title,
  subtitle,
  actions,
  collapsible = false,
  defaultOpen = true,
  className,
  bodyClassName,
  children,
}: PanelProps) {
  const { t } = useLanguage()
  const translateNode = (value: ReactNode) => typeof value === 'string' ? t(value) : value
  const [open, setOpen] = useState(defaultOpen)

  return (
    <section className={[s.panel, className ?? ''].filter(Boolean).join(' ')}>
      {(title || actions || collapsible) && (
        <header className={s.head}>
          {collapsible && (
            <button
              type="button"
              className={s.caret}
              onClick={() => setOpen((p) => !p)}
              aria-expanded={open}
              aria-label={t(open ? '收起' : '展开')}
              title={t(open ? '收起' : '展开')}
            >
              <svg
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                className={open ? s.caretOpen : ''}
              >
                <path d="m9 18 6-6-6-6" />
              </svg>
            </button>
          )}
          {title && (
            <h3 className={s.title}>
              {translateNode(title)}
              {subtitle && <span className={s.subtitle}>{translateNode(subtitle)}</span>}
            </h3>
          )}
          {actions && <div className={s.actions}>{actions}</div>}
        </header>
      )}
      {open && <div className={[s.body, bodyClassName ?? ''].filter(Boolean).join(' ')}>{children}</div>}
    </section>
  )
}
