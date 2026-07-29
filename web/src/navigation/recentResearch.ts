export const RECENT_RESEARCH_PATH_KEY = 'quanthub.research.recent-path'

export function getRecentResearchPath(): string {
  if (typeof localStorage === 'undefined') return '/evaluate'
  const stored = localStorage.getItem(RECENT_RESEARCH_PATH_KEY)
  return stored?.startsWith('/research/') ? stored : '/evaluate'
}

export function setRecentResearchPath(path: string): void {
  if (typeof localStorage === 'undefined' || !path.startsWith('/research/')) return
  localStorage.setItem(RECENT_RESEARCH_PATH_KEY, path)
}
