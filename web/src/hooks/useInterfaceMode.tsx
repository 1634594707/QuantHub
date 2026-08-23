import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api } from '../api/client'
import type { WorkspaceConfigResp, WorkspaceProfile } from '../api/types'

export type InterfaceMode = 'beginner' | 'advanced'

export const INTERFACE_MODE_STORAGE_KEY = 'quanthub.interface-mode'

interface InterfaceModeContextValue {
  mode: InterfaceMode | null
  setMode: (mode: InterfaceMode) => void
  profile: WorkspaceProfile | null
  workspaceConfig: WorkspaceConfigResp | null
  setProfile: (profile: WorkspaceProfile) => Promise<void>
}

const InterfaceModeContext = createContext<InterfaceModeContextValue | null>(null)

function readMode(): InterfaceMode | null {
  const stored = localStorage.getItem(INTERFACE_MODE_STORAGE_KEY)
  return stored === 'beginner' || stored === 'advanced' ? stored : null
}

export function InterfaceModeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<InterfaceMode | null>(readMode)
  const [profile, setProfileState] = useState<WorkspaceProfile | null>(null)
  const [workspaceConfig, setWorkspaceConfig] = useState<WorkspaceConfigResp | null>(null)

  useEffect(() => {
    let active = true
    api.workspaceConfig().then((config) => {
      if (active) {
        setWorkspaceConfig(config)
        setProfileState(config.profile)
      }
    }).catch(() => undefined)
    return () => { active = false }
  }, [])

  useEffect(() => {
    const update = () => setModeState(readMode())
    window.addEventListener('storage', update)
    return () => window.removeEventListener('storage', update)
  }, [])

  const value = useMemo<InterfaceModeContextValue>(() => ({
    mode,
    setMode(nextMode) {
      localStorage.setItem(INTERFACE_MODE_STORAGE_KEY, nextMode)
      setModeState(nextMode)
    },
    profile,
    workspaceConfig,
    async setProfile(nextProfile) {
      const current = workspaceConfig?.config
      const response = await api.updateWorkspaceConfig({
        profile: nextProfile,
        hidden_workspaces: current?.hidden_workspaces ?? [],
        hidden_modules: current?.hidden_modules ?? [],
        pinned_routes: current?.pinned_routes ?? [],
        default_home: current?.default_home ?? '/',
        default_market: current?.default_market ?? 'a_shares',
        recent_routes: current?.recent_routes ?? [],
        version: current?.version || undefined,
      })
      setWorkspaceConfig(response)
      setProfileState(response.profile)
    },
  }), [mode, profile, workspaceConfig])

  return <InterfaceModeContext.Provider value={value}>{children}</InterfaceModeContext.Provider>
}

export function useInterfaceMode() {
  const context = useContext(InterfaceModeContext)
  if (!context) throw new Error('useInterfaceMode 必须在 InterfaceModeProvider 内使用')
  return [context.mode, context.setMode, context.profile, context.setProfile, context.workspaceConfig] as const
}
