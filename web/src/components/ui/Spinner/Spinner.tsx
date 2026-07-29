// 加载指示器：纯 SVG 旋转环，stroke 跟随 currentColor。
import s from './Spinner.module.css'

interface SpinnerProps {
  size?: 'sm' | 'md' | 'lg'
  className?: string
}

const dim = { sm: 14, md: 20, lg: 32 } as const

/** 旋转加载指示器 — 用 currentColor，可被父级 color 控制 */
export function Spinner({ size = 'md', className }: SpinnerProps) {
  const d = dim[size]
  return (
    <svg
      className={`${s.spinner} ${className ?? ''}`.trim()}
      width={d}
      height={d}
      viewBox="0 0 24 24"
      fill="none"
      role="status"
      aria-label="加载中"
    >
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="3" opacity="0.2" />
      <path
        d="M21 12a9 9 0 0 0-9-9"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
      />
    </svg>
  )
}
