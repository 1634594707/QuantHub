import { useCallback, useSyncExternalStore } from 'react'
import type { WorkspaceKey } from './workspaces'

export const NAVIGATION_PREFERENCES_KEY = 'quanthub.navigation.preferences.v1'
const NAVIGATION_PREFERENCES_EVENT = 'quanthub:navigation-preferences'
const HIDEABLE_WORKSPACES = new Set<WorkspaceKey>(['market', 'strategy', 'trading', 'risk'])
const MAX_RECENT_ROUTES = 8

export interface NavigationPreferences {
  pinnedRouteIds: string[]
  hiddenWorkspaceIds: WorkspaceKey[]
  recentRouteIds: string[]
}

const EMPTY_PREFERENCES: NavigationPreferences = {
  pinnedRouteIds: [],
  hiddenWorkspaceIds: [],
  recentRouteIds: [],
}

let cachedRaw: string | null | undefined
let cachedPreferences = EMPTY_PREFERENCES

function uniqueStrings(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return [...new Set(value.filter((item): item is string => typeof item === 'string' && item.length > 0))]
}

function readPreferences(): NavigationPreferences {
  if (typeof localStorage === 'undefined') return EMPTY_PREFERENCES
  const raw = localStorage.getItem(NAVIGATION_PREFERENCES_KEY)
  if (raw === cachedRaw) return cachedPreferences
  cachedRaw = raw
  try {
    const value = raw ? JSON.parse(raw) as Partial<NavigationPreferences> : {}
    cachedPreferences = {
      pinnedRouteIds: uniqueStrings(value.pinnedRouteIds),
      hiddenWorkspaceIds: uniqueStrings(value.hiddenWorkspaceIds)
        .filter((item): item is WorkspaceKey => HIDEABLE_WORKSPACES.has(item as WorkspaceKey)),
      recentRouteIds: uniqueStrings(value.recentRouteIds).slice(0, MAX_RECENT_ROUTES),
    }
  } catch {
    cachedPreferences = EMPTY_PREFERENCES
  }
  return cachedPreferences
}

function subscribe(listener: () => void) {
  window.addEventListener('storage', listener)
  window.addEventListener(NAVIGATION_PREFERENCES_EVENT, listener)
  return () => {
    window.removeEventListener('storage', listener)
    window.removeEventListener(NAVIGATION_PREFERENCES_EVENT, listener)
  }
}

function writePreferences(next: NavigationPreferences) {
  localStorage.setItem(NAVIGATION_PREFERENCES_KEY, JSON.stringify(next))
  cachedRaw = undefined
  window.dispatchEvent(new Event(NAVIGATION_PREFERENCES_EVENT))
}

export function strategyRouteId(strategyName: string) {
  return `strategy:${strategyName}`
}

export function useNavigationPreferences() {
  const preferences = useSyncExternalStore(subscribe, readPreferences, () => EMPTY_PREFERENCES)

  const update = useCallback((fn: (current: NavigationPreferences) => NavigationPreferences) => {
    writePreferences(fn(readPreferences()))
  }, [])

  const togglePinnedRoute = useCallback((routeId: string) => {
    update((current) => ({
      ...current,
      pinnedRouteIds: current.pinnedRouteIds.includes(routeId)
        ? current.pinnedRouteIds.filter((item) => item !== routeId)
        : [...current.pinnedRouteIds, routeId],
    }))
  }, [update])

  const toggleWorkspaceHidden = useCallback((workspaceId: WorkspaceKey) => {
    if (!HIDEABLE_WORKSPACES.has(workspaceId)) return
    update((current) => ({
      ...current,
      hiddenWorkspaceIds: current.hiddenWorkspaceIds.includes(workspaceId)
        ? current.hiddenWorkspaceIds.filter((item) => item !== workspaceId)
        : [...current.hiddenWorkspaceIds, workspaceId],
    }))
  }, [update])

  const recordRecentRoute = useCallback((routeId: string) => {
    update((current) => ({
      ...current,
      recentRouteIds: [routeId, ...current.recentRouteIds.filter((item) => item !== routeId)]
        .slice(0, MAX_RECENT_ROUTES),
    }))
  }, [update])

  return {
    ...preferences,
    togglePinnedRoute,
    toggleWorkspaceHidden,
    recordRecentRoute,
  }
}
