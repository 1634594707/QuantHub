// 表单字段包装：统一 label / hint / error / required 布局。
import type { ReactNode } from 'react'
import s from './Field.module.css'

interface FieldProps {
  label?: ReactNode
  hint?: ReactNode
  error?: ReactNode
  required?: boolean
  children: ReactNode
  className?: string
}

export function Field({ label, hint, error, required = false, children, className }: FieldProps) {
  return (
    <div className={[s.field, className ?? ''].filter(Boolean).join(' ')}>
      {label && (
        <label className={s.label}>
          {label}
          {required && <span className={s.required} aria-hidden="true">*</span>}
        </label>
      )}
      {children}
      {error ? (
        <div className={s.error} role="alert">{error}</div>
      ) : hint ? (
        <div className={s.hint}>{hint}</div>
      ) : null}
    </div>
  )
}
