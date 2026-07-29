import { useCallback, type KeyboardEvent } from 'react'

interface RecordNavigationOptions {
  keys: string[]
  activeKey: string | null
  onSelect: (key: string) => void
  onOpen?: (key: string) => void
}

export function useRecordNavigation({ keys, activeKey, onSelect, onOpen }: RecordNavigationOptions) {
  return useCallback((event: KeyboardEvent<HTMLElement>) => {
    const target = event.target as HTMLElement
    if (target.closest('input, textarea, select, button, a')) return
    if (!keys.length) return

    if (event.key === 'Enter') {
      const key = activeKey && keys.includes(activeKey) ? activeKey : keys[0]
      event.preventDefault()
      onSelect(key)
      onOpen?.(key)
      return
    }

    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
    event.preventDefault()
    const currentIndex = activeKey ? keys.indexOf(activeKey) : -1
    const nextIndex = event.key === 'ArrowDown'
      ? Math.min(keys.length - 1, currentIndex < 0 ? 0 : currentIndex + 1)
      : Math.max(0, currentIndex < 0 ? keys.length - 1 : currentIndex - 1)
    onSelect(keys[nextIndex])
  }, [activeKey, keys, onOpen, onSelect])
}
