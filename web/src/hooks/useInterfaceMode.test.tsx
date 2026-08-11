import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { ThemeProvider } from '../theme/ThemeContext'
import Topbar from '../components/Topbar'
import { InterfaceModeSetup } from '../components/InterfaceModeSetup/InterfaceModeSetup'
import {
  INTERFACE_MODE_STORAGE_KEY,
  InterfaceModeProvider,
  useInterfaceMode,
} from './useInterfaceMode'

function ModeHarness() {
  const [mode, setMode] = useInterfaceMode()
  if (!mode) return <InterfaceModeSetup onSelect={setMode} />
  return (
    <>
      <output aria-label="当前界面范围">{mode}</output>
      <Topbar
        onMenu={() => undefined}
        health={null}
        connectionState="online"
        signalCount={0}
        onOpenCmdk={() => undefined}
        workspaceLabel="总览"
        pageLabel="总览"
        interfaceMode={mode}
        onInterfaceModeChange={setMode}
      />
    </>
  )
}

function renderHarness() {
  return render(
    <MemoryRouter>
      <ThemeProvider>
        <InterfaceModeProvider>
          <ModeHarness />
        </InterfaceModeProvider>
      </ThemeProvider>
    </MemoryRouter>,
  )
}

afterEach(() => {
  cleanup()
  localStorage.clear()
})

describe('interface mode selection', () => {
  it('requires an explicit first selection and restores the persisted choice', () => {
    const first = renderHarness()

    expect(screen.getByRole('heading', { name: '选择界面范围' })).not.toBeNull()
    fireEvent.click(screen.getByRole('button', { name: /精简界面/ }))
    expect(screen.getByLabelText('当前界面范围').textContent).toBe('beginner')
    expect(localStorage.getItem(INTERFACE_MODE_STORAGE_KEY)).toBe('beginner')

    first.unmount()
    renderHarness()
    expect(screen.queryByRole('heading', { name: '选择界面范围' })).toBeNull()
    expect(screen.getByLabelText('当前界面范围').textContent).toBe('beginner')
  })

  it('switches the active mode immediately from the topbar menu', () => {
    localStorage.setItem(INTERFACE_MODE_STORAGE_KEY, 'beginner')
    renderHarness()

    fireEvent.click(screen.getByRole('button', { name: '打开界面与个人偏好' }))
    fireEvent.click(screen.getByRole('menuitemradio', { name: '完整界面' }))

    expect(screen.getByLabelText('当前界面范围').textContent).toBe('advanced')
    expect(localStorage.getItem(INTERFACE_MODE_STORAGE_KEY)).toBe('advanced')
  })
})
