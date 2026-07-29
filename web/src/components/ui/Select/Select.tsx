// 原生 select 美化：保留原生行为（键盘 / 移动端），仅视觉包装。
import type { SelectHTMLAttributes } from 'react'
import s from './Select.module.css'

type Size = 'sm' | 'md'

interface SelectOption {
  value: string
  label: string
}

interface SelectProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'size'> {
  selectSize?: Size
  options: SelectOption[]
  placeholder?: string
}

const SIZE_CLASS: Record<Size, string> = {
  sm: s.sm,
  md: s.md,
}

export function Select({
  selectSize = 'md',
  options,
  placeholder,
  className,
  ...rest
}: SelectProps) {
  return (
    <div className={[s.wrapper, SIZE_CLASS[selectSize], className ?? ''].filter(Boolean).join(' ')}>
      <select className={s.select} {...rest}>
        {placeholder && (
          <option value="" disabled>
            {placeholder}
          </option>
        )}
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
      <svg
        className={s.chevron}
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d="m6 9 6 6 6-6" />
      </svg>
    </div>
  )
}
