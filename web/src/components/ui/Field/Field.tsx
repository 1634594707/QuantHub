// 表单字段包装：统一 label / hint / error / required 布局。
import type { ReactNode } from 'react'
import s from './Field.module.css'
import { useLanguage } from '../../../i18n'

interface FieldProps {
  label?: ReactNode
  hint?: ReactNode
  error?: ReactNode
  required?: boolean
  children: ReactNode
  className?: string
}

export function Field({ label, hint, error, required = false, children, className }: FieldProps) {
  const { t } = useLanguage()
  const translateNode = (value: ReactNode) => typeof value === 'string' ? t(value) : value

  return (
    <div className={[s.field, className ?? ''].filter(Boolean).join(' ')}>
      {label && (
        <label className={s.label}>
          {translateNode(label)}
          {required && <span className={s.required} aria-hidden="true">*</span>}
        </label>
      )}
      {children}
      {error ? (
        <div className={s.error} role="alert">{translateNode(error)}</div>
      ) : hint ? (
        <div className={s.hint}>{translateNode(hint)}</div>
      ) : null}
    </div>
  )
}
