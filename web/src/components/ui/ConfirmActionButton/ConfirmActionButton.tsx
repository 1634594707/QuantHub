import { useState } from 'react'
import { Button } from '../Button/Button'
import { Modal } from '../Modal/Modal'
import s from './ConfirmActionButton.module.css'

interface ConfirmActionButtonProps {
  label: string
  title: string
  description: string
  confirmLabel?: string
  onConfirm: () => void | Promise<void>
  disabled?: boolean
  variant?: 'danger' | 'link' | 'secondary'
  size?: 'sm' | 'md'
}

export function ConfirmActionButton({
  label,
  title,
  description,
  confirmLabel = '确认执行',
  onConfirm,
  disabled = false,
  variant = 'danger',
  size = 'sm',
}: ConfirmActionButtonProps) {
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function confirm() {
    setLoading(true)
    setError('')
    try {
      await onConfirm()
      setOpen(false)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <Button variant={variant} size={size} disabled={disabled} onClick={() => setOpen(true)}>
        {label}
      </Button>
      <Modal
        open={open}
        onClose={() => { if (!loading) setOpen(false) }}
        title={title}
        size="sm"
        closeOnOverlay={!loading}
        closeOnEscape={!loading}
        footer={(
          <>
            <Button variant="ghost" onClick={() => setOpen(false)} disabled={loading}>返回</Button>
            <Button variant="danger" onClick={() => void confirm()} loading={loading}>{confirmLabel}</Button>
          </>
        )}
      >
        <p className={s.description}>{description}</p>
        {error && <div className={s.error} role="alert">{error}</div>}
      </Modal>
    </>
  )
}
