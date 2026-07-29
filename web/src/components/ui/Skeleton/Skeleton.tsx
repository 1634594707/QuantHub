// 骨架屏：占位元素，支持 text/block/circle 三种形态 + 闪烁动画。
import s from './Skeleton.module.css'

interface SkeletonProps {
  variant?: 'text' | 'block' | 'circle'
  width?: string | number
  height?: string | number
  animated?: boolean
  className?: string
}

/** 骨架屏占位 — 默认 animated=true */
export function Skeleton({
  variant = 'block',
  width,
  height,
  animated = true,
  className,
}: SkeletonProps) {
  const style = { width, height } as { width?: string | number; height?: string | number }
  return (
    <div
      className={[
        s.skeleton,
        s[variant],
        animated ? s.animated : '',
        className ?? '',
      ]
        .filter(Boolean)
        .join(' ')}
      style={style}
      aria-hidden="true"
    />
  )
}
