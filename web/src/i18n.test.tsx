import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { LanguageProvider, useLanguage } from './i18n'

function LocaleProbe() {
  const { locale, setLocale, t } = useLanguage()

  return (
    <div>
      <span data-testid="locale">{locale}</span>
      <span data-testid="overview-label">{t('总览')}</span>
      <span data-testid="evaluation-label">{t('标的评估')}</span>
      <span data-testid="strategy-lenses-label">{t('策略视角')}</span>
      <button type="button" onClick={() => setLocale('en')}>English</button>
      <button type="button" onClick={() => setLocale('zh-CN')}>Chinese</button>
    </div>
  )
}

describe('LanguageProvider', () => {
  beforeEach(() => {
    window.localStorage.clear()
    document.documentElement.lang = 'zh-CN'
  })

  it('switches visible labels, persists the preference, and updates document language', async () => {
    render(
      <LanguageProvider>
        <LocaleProbe />
      </LanguageProvider>,
    )

    expect(screen.getByTestId('locale').textContent).toBe('zh-CN')
    expect(screen.getByTestId('overview-label').textContent).toBe('总览')
    expect(screen.getByTestId('evaluation-label').textContent).toBe('标的评估')
    expect(screen.getByTestId('strategy-lenses-label').textContent).toBe('策略视角')

    fireEvent.click(screen.getByRole('button', { name: 'English' }))

    await waitFor(() => {
      expect(screen.getByTestId('locale').textContent).toBe('en')
      expect(screen.getByTestId('overview-label').textContent).toBe('Overview')
      expect(screen.getByTestId('evaluation-label').textContent).toBe('Instrument evaluation')
      expect(screen.getByTestId('strategy-lenses-label').textContent).toBe('Strategy lenses')
      expect(document.documentElement.lang).toBe('en')
      expect(window.localStorage.getItem('quanthub.locale')).toBe('en')
    })
  })
})
