import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

export type ThemeMode = 'dark' | 'light'

interface ThemeCtx {
  theme: ThemeMode
  toggle: () => void
  setTheme: (t: ThemeMode) => void
}

const Ctx = createContext<ThemeCtx | null>(null)
const STORAGE_KEY = 'qh-theme'

function getInitial(): ThemeMode {
  if (typeof window === 'undefined') return 'dark'
  const saved = window.localStorage.getItem(STORAGE_KEY)
  if (saved === 'light' || saved === 'dark') return saved
  return 'dark' // 默认暗色，契合盯盘场景
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<ThemeMode>(getInitial)

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    window.localStorage.setItem(STORAGE_KEY, theme)
  }, [theme])

  const setTheme = (t: ThemeMode) => setThemeState(t)
  const toggle = () => setThemeState((p) => (p === 'dark' ? 'light' : 'dark'))

  return <Ctx.Provider value={{ theme, toggle, setTheme }}>{children}</Ctx.Provider>
}

export function useTheme(): ThemeCtx {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useTheme 必须在 ThemeProvider 内使用')
  return ctx
}
