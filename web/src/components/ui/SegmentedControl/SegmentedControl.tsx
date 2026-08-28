// 分段控制：替代 .seg / .period-tabs / .d-tabs / .research-timeframes 4 套实现。
import type { ReactNode } from 'react'
import s from './SegmentedControl.module.css'

type Size = 'sm' | 'md'

interface SegOption {
  value: string
  label: ReactNode
}

interface SegmentedControlProps {
  value: string
  onChange: (value: string) => void
  options: SegOption[]
  size?: Size
  fullWidth?: boolean
  className?: string
  ariaLabel?: string
}

const SIZE_CLASS: Record<Size, string> = {
  sm: s.sm,
  md: s.md,
}

export function SegmentedControl({
  value,
  onChange,
  options,
  size = 'md',
  fullWidth = false,
  className,
  ariaLabel,
}: SegmentedControlProps) {
  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className={[
        s.seg,
        SIZE_CLASS[size],
        fullWidth ? s.fullWidth : '',
        className ?? '',
      ]
        .filter(Boolean)
        .join(' ')}
    >
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          role="tab"
          aria-selected={value === opt.value}
          className={[s.btn, value === opt.value ? s.active : ''].filter(Boolean).join(' ')}
          onClick={() => onChange(opt.value)}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}
