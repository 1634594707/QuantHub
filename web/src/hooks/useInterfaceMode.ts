import { useEffect, useState } from 'react'

export type InterfaceMode = 'beginner' | 'advanced'

const STORAGE_KEY = 'quanthub.interface-mode'
const CHANGE_EVENT = 'quanthub:interface-mode-change'

function readMode(): InterfaceMode {
  return localStorage.getItem(STORAGE_KEY) === 'beginner' ? 'beginner' : 'advanced'
}

export function useInterfaceMode() {
  const [mode, setModeState] = useState<InterfaceMode>(readMode)

  useEffect(() => {
    const update = () => setModeState(readMode())
    window.addEventListener('storage', update)
    window.addEventListener(CHANGE_EVENT, update)
    return () => {
      window.removeEventListener('storage', update)
      window.removeEventListener(CHANGE_EVENT, update)
    }
  }, [])

  function setMode(mode: InterfaceMode) {
    localStorage.setItem(STORAGE_KEY, mode)
    setModeState(mode)
    window.dispatchEvent(new Event(CHANGE_EVENT))
  }

  return [mode, setMode] as const
}
