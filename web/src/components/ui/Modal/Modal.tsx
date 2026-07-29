// 模态对话框：React Portal 实现，支持 Escape 关闭 / 遮罩点击 / body 滚动锁。
import { useLayoutEffect, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { IconButton } from '../IconButton/IconButton'
import s from './Modal.module.css'

type Size = 'sm' | 'md' | 'lg' | 'xl'

interface ModalProps {
  open: boolean
  onClose: () => void
  title?: ReactNode
  size?: Size
  footer?: ReactNode
  closeOnOverlay?: boolean
  closeOnEscape?: boolean
  children: ReactNode
}

const SIZE_CLASS: Record<Size, string> = {
  sm: s.sm,
  md: s.md,
  lg: s.lg,
  xl: s.xl,
}

export function Modal({
  open,
  onClose,
  title,
  size = 'md',
  footer,
  closeOnOverlay = true,
  closeOnEscape = true,
  children,
}: ModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null)

  useLayoutEffect(() => {
    if (!open) return
    const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const focusableSelector = 'button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])'
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && closeOnEscape) {
        onClose()
        return
      }
      if (e.key !== 'Tab') return
      const focusable = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>(focusableSelector) ?? [])
      if (!focusable.length) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const first = dialogRef.current?.querySelector<HTMLElement>(focusableSelector)
    ;(first ?? dialogRef.current)?.focus()
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = prev
      trigger?.focus()
    }
  }, [open, onClose, closeOnEscape])

  if (!open) return null

  return createPortal(
    <div
      className={s.overlay}
      onClick={(e) => {
        if (closeOnOverlay && e.target === e.currentTarget) onClose()
      }}
      role="dialog"
      aria-modal="true"
      aria-label={typeof title === 'string' ? title : '对话框'}
    >
      <div ref={dialogRef} className={[s.modal, SIZE_CLASS[size]].join(' ')} tabIndex={-1}>
        {title && (
          <header className={s.head}>
            <h2 className={s.title}>{title}</h2>
            <IconButton variant="ghost" size="sm" label="关闭" onClick={onClose}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <path d="M18 6 6 18M6 6l12 12" />
              </svg>
            </IconButton>
          </header>
        )}
        <div className={s.body}>{children}</div>
        {footer && <footer className={s.footer}>{footer}</footer>}
      </div>
    </div>,
    document.body,
  )
}
