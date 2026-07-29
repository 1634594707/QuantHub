import { useEffect, useState, type ReactNode } from 'react'

interface ResponsiveDetailsProps {
  summary: ReactNode
  children: ReactNode
  className?: string
  compactAt: number
}

function matchesCompact(compactAt: number): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return false
  }
  return window.matchMedia(`(max-width: ${compactAt}px)`).matches
}

export function ResponsiveDetails({ summary, children, className, compactAt }: ResponsiveDetailsProps) {
  const [compact, setCompact] = useState(() => matchesCompact(compactAt))
  const [open, setOpen] = useState(() => !matchesCompact(compactAt))

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return undefined
    }
    const query = window.matchMedia(`(max-width: ${compactAt}px)`)
    const update = () => {
      setCompact(query.matches)
      setOpen(!query.matches)
    }
    query.addEventListener('change', update)
    return () => query.removeEventListener('change', update)
  }, [compactAt])

  return (
    <details
      className={className}
      open={open}
      onToggle={(event) => {
        if (compact) setOpen(event.currentTarget.open)
      }}
    >
      <summary>{summary}</summary>
      {children}
    </details>
  )
}
