// QuantHub 概览屏 Mock 数据 — UI Designer 骨架用
// 真实接入时，将 KPI / 持仓 / 决策 替换为 view_models 与行情服务输出即可。

export interface Candle {
  t: string
  o: number
  h: number
  l: number
  c: number
  v: number
}

export interface Kpi {
  label: string
  value: string
  unit?: string
  deltaAbs: string
  deltaPct: number // 正为涨，负为跌
  spark: number[]
}

export interface Holding {
  code: string
  name: string
  price: number
  chgPct: number
  shares: number
  pnl: number
  winRate: number
}

export interface Breadth {
  up: number
  flat: number
  down: number
}

export interface Watch {
  sym: string
  name: string
  price: number
  chgPct: number
  /** 兼容 WatchlistItem：mock 数据默认可用。 */
  available?: boolean
}

export type Direction = 'long' | 'short' | 'hold'

export interface Decision {
  direction: Direction
  trend: string
  cycle: string
  phase: string
  confidence: number
  dualConfidence: { stage1: number; stage2: number }
  nextBar: { predictable: boolean; top3: { label: string; prob: number }[]; remainder?: number }
  nextCycle: { predictable: boolean; top3: { label: string; prob: number }[]; remainder?: number }
  stop: number
  target: number
  riskReward: number
  winRate: number
  reason: string
  gateTrace: { gate: string; result: string }[]
}

export interface Sector {
  name: string
  chgPct: number
}

// ---------- 确定性随机（保证每次刷新图形一致） ----------
function lcg(seed: number) {
  let s = seed % 2147483647
  if (s <= 0) s += 2147483646
  return () => {
    s = (s * 16807) % 2147483647
    return (s - 1) / 2147483646
  }
}

export function genCandles(n = 240, seed = 42): Candle[] {
  const rnd = lcg(seed)
  const out: Candle[] = []
  let prev = 3210
  for (let i = 0; i < n; i++) {
    const o = prev
    const drift = (rnd() - 0.46) * 26
    const c = Math.max(3000, o + drift)
    const h = Math.max(o, c) + rnd() * 12
    const l = Math.min(o, c) - rnd() * 12
    const v = Math.round(4200 + rnd() * 9200)
    out.push({ t: `${String(i + 1).padStart(3, '0')}`, o, h, l, c, v })
    prev = c
  }
  return out
}

export const KPIS: Kpi[] = [
  {
    label: '账户净值',
    value: '1,284,560',
    unit: '¥',
    deltaAbs: '+38,210',
    deltaPct: 3.06,
    spark: [12, 18, 14, 22, 19, 26, 24, 30, 28, 34, 31, 38],
  },
  {
    label: '今日盈亏',
    value: '+12,840',
    unit: '¥',
    deltaAbs: '+1.01%',
    deltaPct: 1.01,
    spark: [4, 6, 5, 9, 7, 11, 10, 13, 12, 15, 14, 16],
  },
  {
    label: '持仓胜率',
    value: '68.4',
    unit: '%',
    deltaAbs: '+2.3pt',
    deltaPct: 2.3,
    spark: [60, 61, 59, 63, 64, 62, 65, 66, 64, 67, 68, 68],
  },
  {
    label: '可用资金',
    value: '426,300',
    unit: '¥',
    deltaAbs: '-9,200',
    deltaPct: -2.11,
    spark: [50, 48, 49, 47, 46, 45, 44, 45, 43, 44, 43, 42],
  },
]

export const HOLDINGS: Holding[] = [
  { code: '600519', name: '贵州茅台', price: 1685.0, chgPct: 1.82, shares: 100, pnl: 12400, winRate: 72 },
  { code: '300750', name: '宁德时代', price: 198.6, chgPct: -0.94, shares: 800, pnl: -3200, winRate: 61 },
  { code: '000858', name: '五粮液', price: 142.3, chgPct: 0.56, shares: 500, pnl: 5600, winRate: 65 },
  { code: '002594', name: '比亚迪', price: 256.8, chgPct: 2.31, shares: 300, pnl: 9800, winRate: 70 },
  { code: '601318', name: '中国平安', price: 48.2, chgPct: -0.41, shares: 1200, pnl: -1500, winRate: 58 },
]

export const BREADTH: Breadth = { up: 1842, flat: 213, down: 1396 }

export const SECTORS: Sector[] = [
  { name: '半导体', chgPct: 3.84 },
  { name: '汽车整车', chgPct: 2.61 },
  { name: '通信设备', chgPct: 1.92 },
  { name: '白酒', chgPct: -1.15 },
  { name: '银行', chgPct: -0.68 },
]

export const WATCH: Watch[] = [
  { sym: 'NVDA', name: '英伟达', price: 131.26, chgPct: 3.42 },
  { sym: 'AVGO', name: '博通', price: 168.4, chgPct: 1.18 },
  { sym: '600036', name: '招商银行', price: 37.8, chgPct: -0.52 },
  { sym: 'BTC', name: '比特币', price: 64210, chgPct: 2.07 },
]

export const DECISION: Decision = {
  direction: 'long',
  trend: '多头趋势',
  cycle: '日线上升段',
  phase: '主升浪初期',
  confidence: 78,
  dualConfidence: { stage1: 82, stage2: 78 },
  nextBar: {
    predictable: true,
    top3: [
      { label: '继续上涨', prob: 0.48 },
      { label: '横盘整理', prob: 0.31 },
      { label: '小幅回调', prob: 0.14 },
    ],
    remainder: 0.07,
  },
  nextCycle: {
    predictable: false,
    top3: [
      { label: '主升浪延续', prob: 0.38 },
      { label: '高位震荡', prob: 0.29 },
      { label: '阶段见顶', prob: 0.22 },
    ],
    remainder: 0.11,
  },
  stop: 3160,
  target: 3380,
  riskReward: 2.4,
  winRate: 71,
  reason:
    '量价配合健康，突破 20 日均线后回踩确认；MACD 水上金叉，资金净流入居板块前列。建议逢低布局，止损设于前低下方。',
  gateTrace: [
    { gate: 'G1 趋势过滤', result: '通过' },
    { gate: 'G2 结构确认', result: '通过' },
    { gate: 'G3 量能校验', result: '通过' },
    { gate: 'G4 波动率边界', result: '边缘' },
    { gate: 'G5 方向投票', result: '做多' },
  ],
}
