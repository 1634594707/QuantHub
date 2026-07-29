// 统一图标包装：基于现有 components/icons.tsx，提供 <Icon name="search" /> 注册表 API。
// 所有图标 stroke 跟随 currentColor，size 默认 18，可通过 className 覆盖颜色。
import type { ReactNode } from 'react'
import {
  IconMenu,
  IconSearch,
  IconSun,
  IconMoon,
  IconBell,
  IconGrid,
  IconNetwork,
  IconSignal,
  IconChart,
  IconBeaker,
  IconWallet,
  IconFlask,
  IconCog,
  IconLayers,
  IconActivity,
  IconHeart,
  IconChevron,
  IconNews,
} from '../../icons'

/** 所有已注册图标 — 新增图标时在此追加 */
const registry = {
  menu: IconMenu,
  search: IconSearch,
  sun: IconSun,
  moon: IconMoon,
  bell: IconBell,
  grid: IconGrid,
  network: IconNetwork,
  signal: IconSignal,
  chart: IconChart,
  beaker: IconBeaker,
  wallet: IconWallet,
  flask: IconFlask,
  cog: IconCog,
  layers: IconLayers,
  activity: IconActivity,
  heart: IconHeart,
  chevron: IconChevron,
  news: IconNews,
} as const

export type IconName = keyof typeof registry

interface IconProps {
  /** 图标名（注册表 key） */
  name: IconName
  /** 尺寸 px，默认 18 */
  size?: number
  /** 附加类名（可用于 CSS Module 覆盖颜色） */
  className?: string
}

/** 统一图标组件 — 通过 name 查注册表，透传 size/className */
export function Icon({ name, size, className }: IconProps): ReactNode {
  const Cmp = registry[name]
  if (!Cmp) return null
  return <Cmp size={size} className={className} />
}
