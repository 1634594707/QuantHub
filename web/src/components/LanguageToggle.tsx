import { Languages } from 'lucide-react'
import { useLanguage, type AppLocale } from '../i18n'
import { SegmentedControl } from './ui/SegmentedControl/SegmentedControl'

interface LanguageToggleProps {
  className?: string
}

export function LanguageToggle({ className }: LanguageToggleProps) {
  const { locale, setLocale, t } = useLanguage()

  return (
    <div className={['language-toggle', className ?? ''].filter(Boolean).join(' ')}>
      <Languages size={15} aria-hidden="true" />
      <SegmentedControl
        ariaLabel={t('界面语言')}
        size="sm"
        value={locale}
        onChange={(value) => setLocale(value as AppLocale)}
        options={[
          { value: 'zh-CN', label: <span lang="zh-CN">中</span> },
          { value: 'en', label: 'EN' },
        ]}
      />
    </div>
  )
}
