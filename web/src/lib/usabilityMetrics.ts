export type UsabilityEventName =
  | 'research_started'
  | 'research_completed'
  | 'research_abandoned'
  | 'research_error'

export interface UsabilityEvent {
  name: UsabilityEventName
  page: 'factor_research'
  step: 'setup' | 'statistical_research' | 'result_reading' | 'ai_review'
  at: number
  duration_ms?: number
  error_type?: 'validation' | 'data_source' | 'persistence' | 'ai_provider' | 'unknown'
}

const STORAGE_KEY = 'quanthub.usability.v1'
const MAX_EVENTS = 100
const EVENT_NAMES = new Set<UsabilityEventName>([
  'research_started',
  'research_completed',
  'research_abandoned',
  'research_error',
])
const STEPS = new Set<UsabilityEvent['step']>([
  'setup',
  'statistical_research',
  'result_reading',
  'ai_review',
])
const ERROR_TYPES = new Set<NonNullable<UsabilityEvent['error_type']>>([
  'validation',
  'data_source',
  'persistence',
  'ai_provider',
  'unknown',
])

export function sanitizeUsabilityEvent(input: Record<string, unknown>): UsabilityEvent | null {
  if (!EVENT_NAMES.has(input.name as UsabilityEventName)) return null
  if (!STEPS.has(input.step as UsabilityEvent['step'])) return null
  const event: UsabilityEvent = {
    name: input.name as UsabilityEventName,
    page: 'factor_research',
    step: input.step as UsabilityEvent['step'],
    at: typeof input.at === 'number' && Number.isFinite(input.at) ? input.at : Date.now(),
  }
  if (typeof input.duration_ms === 'number' && Number.isFinite(input.duration_ms)) {
    event.duration_ms = Math.max(0, Math.round(input.duration_ms))
  }
  if (ERROR_TYPES.has(input.error_type as NonNullable<UsabilityEvent['error_type']>)) {
    event.error_type = input.error_type as NonNullable<UsabilityEvent['error_type']>
  }
  return event
}

export function recordUsabilityEvent(input: Record<string, unknown>): void {
  if (typeof localStorage === 'undefined') return
  const event = sanitizeUsabilityEvent(input)
  if (!event) return
  try {
    const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]')
    const events = Array.isArray(parsed)
      ? parsed.flatMap((item) => {
        const sanitized = item && typeof item === 'object'
          ? sanitizeUsabilityEvent(item as Record<string, unknown>)
          : null
        return sanitized ? [sanitized] : []
      })
      : []
    localStorage.setItem(STORAGE_KEY, JSON.stringify([...events, event].slice(-MAX_EVENTS)))
  } catch {
    localStorage.setItem(STORAGE_KEY, JSON.stringify([event]))
  }
}

export function classifyResearchError(message: string): NonNullable<UsabilityEvent['error_type']> {
  const normalized = message.toLowerCase()
  if (/模型|ai|provider|gateway|token/.test(normalized)) return 'ai_provider'
  if (/行情|数据|k线|source|timeout|超时/.test(normalized)) return 'data_source'
  if (/保存|存储|sqlite|database/.test(normalized)) return 'persistence'
  if (/参数|标的|输入|validation/.test(normalized)) return 'validation'
  return 'unknown'
}

export const USABILITY_METRICS_STORAGE_KEY = STORAGE_KEY
