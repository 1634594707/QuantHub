// 文本/数字输入：支持 prefix/suffix（如图标、单位）、invalid 状态、mono 变体。
import type { InputHTMLAttributes, ReactNode } from 'react'
import s from './Input.module.css'

type Size = 'sm' | 'md'

interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'size' | 'prefix'> {
  inputSize?: Size
  variant?: 'default' | 'mono'
  invalid?: boolean
  prefix?: ReactNode
  suffix?: ReactNode
  wrapperClassName?: string
}

const SIZE_CLASS: Record<Size, string> = {
  sm: s.sm,
  md: s.md,
}

export function Input({
  inputSize = 'md',
  variant = 'default',
  invalid = false,
  prefix,
  suffix,
  wrapperClassName,
  className,
  ...rest
}: InputProps) {
  const hasAffix = Boolean(prefix || suffix)
  const input = (
    <input
      className={[
        s.input,
        variant === 'mono' ? s.mono : '',
        invalid ? s.invalid : '',
        className ?? '',
      ]
        .filter(Boolean)
        .join(' ')}
      {...rest}
    />
  )

  if (!hasAffix) return input

  return (
    <div className={[s.wrapper, SIZE_CLASS[inputSize], wrapperClassName ?? ''].filter(Boolean).join(' ')}>
      {prefix && <span className={s.prefix}>{prefix}</span>}
      {input}
      {suffix && <span className={s.suffix}>{suffix}</span>}
    </div>
  )
}
