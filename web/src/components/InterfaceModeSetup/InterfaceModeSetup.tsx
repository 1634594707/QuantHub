import type { InterfaceMode } from '../../hooks/useInterfaceMode'
import { IconChart, IconGrid } from '../icons'
import styles from './InterfaceModeSetup.module.css'

export function InterfaceModeSetup({ onSelect }: { onSelect: (mode: InterfaceMode) => void }) {
  return (
    <main className={styles.page}>
      <section className={styles.panel} aria-labelledby="interface-mode-title">
        <div className={styles.heading}>
          <span>QuantHub</span>
          <h1 id="interface-mode-title">选择界面范围</h1>
          <p>此选择只影响导航、首页模块和数据加载范围。</p>
        </div>
        <div className={styles.options}>
          <button type="button" onClick={() => onSelect('beginner')}>
            <IconGrid size={22} />
            <strong>精简界面</strong>
            <span>研究、模拟交易与账本</span>
          </button>
          <button type="button" onClick={() => onSelect('advanced')}>
            <IconChart size={22} />
            <strong>完整界面</strong>
            <span>全部研究、策略、交易与运营能力</span>
          </button>
        </div>
      </section>
    </main>
  )
}
