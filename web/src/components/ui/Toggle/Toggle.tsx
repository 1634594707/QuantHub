// 开关：替代 .toggle / .live-toggle，支持 size / label / disabled。
import type { ReactNode } from 'react'
import s from './Toggle.module.css'

type Size = 'sm' | 'md'

interface ToggleProps {
  checked: boolean
  onChange: (checked: boolean) => void
  size?: Size
  label?: ReactNode
  disabled?: boolean
  className?: string
}

const SIZE_CLASS: Record<Size, string> = {
  sm: s.sm,
  md: s.md,
}

export function Toggle({
  checked,
  onChange,
  size = 'md',
  label,
  disabled = false,
  className,
}: ToggleProps) {
  const toggle = (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      className={[s.toggle, SIZE_CLASS[size], checked ? s.checked : '', className ?? '']
        .filter(Boolean)
        .join(' ')}
      onClick={() => !disabled && onChange(!checked)}
    />
  )

  if (!label) return toggle

  return (
    <label className={s.wrapper}>
      {toggle}
      {label && <span className={s.label}>{label}</span>}
    </label>
  )
}
