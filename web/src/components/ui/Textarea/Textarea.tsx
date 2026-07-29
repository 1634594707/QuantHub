// 多行文本输入：同 Input API，支持 rows / invalid / mono。
import type { TextareaHTMLAttributes } from 'react'
import s from './Textarea.module.css'

interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  variant?: 'default' | 'mono'
  invalid?: boolean
}

export function Textarea({
  variant = 'default',
  invalid = false,
  className,
  rows = 4,
  ...rest
}: TextareaProps) {
  return (
    <textarea
      rows={rows}
      className={[
        s.textarea,
        variant === 'mono' ? s.mono : '',
        invalid ? s.invalid : '',
        className ?? '',
      ]
        .filter(Boolean)
        .join(' ')}
      {...rest}
    />
  )
}
