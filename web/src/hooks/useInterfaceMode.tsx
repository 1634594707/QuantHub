import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

export type InterfaceMode = 'beginner' | 'advanced'

export const INTERFACE_MODE_STORAGE_KEY = 'quanthub.interface-mode'

interface InterfaceModeContextValue {
  mode: InterfaceMode | null
  setMode: (mode: InterfaceMode) => void
}

const InterfaceModeContext = createContext<InterfaceModeContextValue | null>(null)

function readMode(): InterfaceMode | null {
  const stored = localStorage.getItem(INTERFACE_MODE_STORAGE_KEY)
  return stored === 'beginner' || stored === 'advanced' ? stored : null
}

export function InterfaceModeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<InterfaceMode | null>(readMode)

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
  }), [mode])

  return <InterfaceModeContext.Provider value={value}>{children}</InterfaceModeContext.Provider>
}

export function useInterfaceMode() {
  const context = useContext(InterfaceModeContext)
  if (!context) throw new Error('useInterfaceMode 必须在 InterfaceModeProvider 内使用')
  return [context.mode, context.setMode] as const
}
