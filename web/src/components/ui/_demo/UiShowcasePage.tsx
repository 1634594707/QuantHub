// UI 组件库演示页 — 路由 /__ui，仅 dev 环境可访问。
// 覆盖全部 20 个组件的所有变体，作为视觉验证 + 活体风格指南。
import { useState, type ReactNode } from 'react'
import { Button } from '../Button/Button'
import { IconButton } from '../IconButton/IconButton'
import { Input } from '../Input/Input'
import { Select } from '../Select/Select'
import { Textarea } from '../Textarea/Textarea'
import { Badge } from '../Badge/Badge'
import { Tag } from '../Tag/Tag'
import { Tooltip } from '../Tooltip/Tooltip'
import { Spinner } from '../Spinner/Spinner'
import { Skeleton } from '../Skeleton/Skeleton'
import { Icon } from '../Icon/Icon'
import { Card } from '../Card/Card'
import { Panel } from '../Panel/Panel'
import { Modal } from '../Modal/Modal'
import { Table, type Column } from '../Table/Table'
import { SegmentedControl } from '../SegmentedControl/SegmentedControl'
import { Field } from '../Field/Field'
import { EmptyState } from '../EmptyState/EmptyState'
import { KpiCard } from '../KpiCard/KpiCard'
import { Toggle } from '../Toggle/Toggle'
import { WorkspaceHeader } from '../../WorkspaceHeader/WorkspaceHeader'
import s from './UiShowcasePage.module.css'

function Section({ title, desc, children }: { title: string; desc?: string; children: ReactNode }) {
  return (
    <section className={s.section}>
      <h2 className={s.sectionTitle}>{title}</h2>
      {desc && <p className={s.sectionDesc}>{desc}</p>}
      <div className={s.sectionBody}>{children}</div>
    </section>
  )
}

function Row({ label, children }: { label?: string; children: ReactNode }) {
  return (
    <div className={s.demoRow}>
      {label && <span className={s.demoLabel}>{label}</span>}
      <div className={s.demoContent}>{children}</div>
    </div>
  )
}

export default function UiShowcasePage() {
  const [segValue, setSegValue] = useState('1d')
  const [toggleOn, setToggleOn] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)
  const [inputVal, setInputVal] = useState('')

  interface DemoRow {
    id: string
    name: string
    price: number
    change: number
    status: string
  }
  const columns: Column<DemoRow>[] = [
    { key: 'id', header: 'ID', width: '60px' },
    { key: 'name', header: '名称', render: (r) => <strong>{r.name}</strong> },
    { key: 'price', header: '价格', align: 'right', render: (r) => <span className="mono">{r.price.toFixed(2)}</span> },
    { key: 'change', header: '涨跌', align: 'right', render: (r) => <span className={r.change >= 0 ? 'up' : 'down'}>{r.change >= 0 ? '+' : ''}{r.change.toFixed(2)}%</span> },
    { key: 'status', header: '状态', render: (r) => <Badge variant={r.status === '活跃' ? 'up' : 'neutral'} dot>{r.status}</Badge> },
  ]
  const rows: DemoRow[] = [
    { id: '001', name: '贵州茅台', price: 1689.50, change: 2.34, status: '活跃' },
    { id: '002', name: '宁德时代', price: 198.20, change: -1.12, status: '观察' },
    { id: '003', name: '比亚迪', price: 245.80, change: 0.89, status: '活跃' },
  ]

  return (
    <div className={s.page}>
      <header className={s.header}>
        <h1 className={s.title}>QuantHub UI 组件库</h1>
        <p className={s.subtitle}>21 个自建组件 · 双主题适配 · CSS Modules 隔离</p>
      </header>

      <Section title="WorkspaceHeader" desc="紧凑工作区页头，桌面高度不超过 72px">
        <WorkspaceHeader
          context="执行 / 信号中心"
          title="实时信号中心"
          description="审核、证据与执行影响保持在同一工作区。"
          metrics={[
            { label: '信号总数', value: '128' },
            { label: '待审核', value: '6' },
            { label: '看多占比', value: '62%' },
          ]}
          action={<Button variant="primary" size="sm">发布信号</Button>}
        />
      </Section>

      <Section title="Button" desc="5 变体 × 3 尺寸，支持 loading / icon / fullWidth">
        <Row label="primary">
          <Button size="sm" variant="primary">小</Button>
          <Button size="md" variant="primary">中等</Button>
          <Button size="lg" variant="primary">大按钮</Button>
        </Row>
        <Row label="secondary">
          <Button variant="secondary">默认</Button>
          <Button variant="secondary" icon={<Icon name="search" />}>搜索</Button>
          <Button variant="secondary" iconRight={<Icon name="chevron" />}>下一步</Button>
        </Row>
        <Row label="ghost / danger / link">
          <Button variant="ghost">幽灵</Button>
          <Button variant="danger">删除</Button>
          <Button variant="link">文字链接</Button>
        </Row>
        <Row label="loading / disabled / fullWidth">
          <Button variant="primary" loading>保存中</Button>
          <Button variant="primary" disabled>禁用</Button>
          <Button variant="primary" fullWidth onClick={() => alert('hi')}>全宽按钮</Button>
        </Row>
      </Section>

      <Section title="IconButton" desc="仅图标，必填 label（aria）">
        <Row>
          <IconButton label="菜单" variant="default"><Icon name="menu" /></IconButton>
          <IconButton label="搜索" variant="ghost" size="sm"><Icon name="search" /></IconButton>
          <IconButton label="设置" variant="accent"><Icon name="cog" /></IconButton>
        </Row>
      </Section>

      <Section title="Input" desc="支持 prefix/suffix / mono / invalid">
        <Row label="默认">
          <Input placeholder="请输入股票代码" value={inputVal} onChange={(e) => setInputVal(e.target.value)} />
        </Row>
        <Row label="带前缀">
          <Input prefix={<Icon name="search" />} placeholder="搜索..." />
        </Row>
        <Row label="带后缀">
          <Input suffix="%" defaultValue="12.5" variant="mono" />
        </Row>
        <Row label="invalid">
          <Input invalid defaultValue="错误值" />
        </Row>
      </Section>

      <Section title="Select & Textarea">
        <Row label="select">
          <Select
            options={[
              { value: '1', label: '日线' },
              { value: '2', label: '周线' },
              { value: '3', label: '月线' },
            ]}
            defaultValue="1"
          />
        </Row>
        <Row label="textarea">
          <Textarea placeholder="多行文本输入..." rows={3} />
        </Row>
      </Section>

      <Section title="Badge" desc="7 种变体 + dot">
        <Row>
          <Badge variant="neutral">默认</Badge>
          <Badge variant="accent">强调</Badge>
          <Badge variant="up">涨</Badge>
          <Badge variant="down">跌</Badge>
          <Badge variant="warn">警告</Badge>
          <Badge variant="info">信息</Badge>
          <Badge variant="live" dot>实时</Badge>
        </Row>
      </Section>

      <Section title="Tag" desc="可关闭">
        <Row>
          <Tag variant="neutral">科技</Tag>
          <Tag variant="accent" closable onClose={() => {}}>新能源</Tag>
          <Tag variant="up" closable onClose={() => {}}>涨停</Tag>
          <Tag variant="down" closable onClose={() => {}}>跌停</Tag>
        </Row>
      </Section>

      <Section title="Tooltip" desc="纯 CSS hover，4 方向">
        <Row>
          <Tooltip content="顶部提示" side="top"><Button variant="secondary">上</Button></Tooltip>
          <Tooltip content="右侧提示" side="right"><Button variant="secondary">右</Button></Tooltip>
          <Tooltip content="底部提示" side="bottom"><Button variant="secondary">下</Button></Tooltip>
          <Tooltip content="左侧提示" side="left"><Button variant="secondary">左</Button></Tooltip>
        </Row>
      </Section>

      <Section title="Spinner & Skeleton">
        <Row label="spinner">
          <Spinner size="sm" />
          <Spinner size="md" />
          <Spinner size="lg" />
        </Row>
        <Row label="skeleton">
          <Skeleton variant="text" width={200} />
          <Skeleton variant="block" width={120} height={80} />
          <Skeleton variant="circle" />
        </Row>
      </Section>

      <Section title="Card" desc="替代 4 套卡片实现">
        <div className={s.cardGrid}>
          <Card padding="md" elevation="card">elevation: card</Card>
          <Card padding="md" elevation="flat">elevation: flat</Card>
          <Card padding="md" elevation="pop">elevation: pop</Card>
          <Card padding="md" hoverable accentRail>hoverable + accentRail</Card>
        </div>
      </Section>

      <Section title="Panel" desc="带 head/body/actions，可折叠">
        <Panel
          title="策略详情"
          subtitle="RSI 反转"
          actions={<Button size="sm" variant="primary">运行</Button>}
          collapsible
        >
          <p>面板内容：可折叠、带标题、副标题和操作区。</p>
        </Panel>
      </Section>

      <Section title="KpiCard" desc="替代 5 套 KPI 实现">
        <div className={s.kpiGrid}>
          <KpiCard label="总收益" value="12,345" unit="¥" delta="+234.5" deltaPct={2.34} spark={[10, 12, 9, 15, 13, 18, 20]} />
          <KpiCard label="回撤" value="-8.2" unit="%" delta="-1.2" deltaPct={-1.2} spark={[20, 18, 15, 16, 12, 10, 8]} />
          <KpiCard label="胜率" value="68" unit="%" deltaPct={5.2} spark={[50, 55, 60, 58, 65, 68]} />
        </div>
      </Section>

      <Section title="SegmentedControl" desc="替代 4 套分段控制">
        <Row label="默认">
          <SegmentedControl
            value={segValue}
            onChange={setSegValue}
            options={[
              { value: '1d', label: '1日' },
              { value: '1w', label: '1周' },
              { value: '1m', label: '1月' },
              { value: '1y', label: '1年' },
            ]}
          />
        </Row>
        <Row label="fullWidth + sm">
          <SegmentedControl
            value={segValue}
            onChange={setSegValue}
            size="sm"
            fullWidth
            options={[
              { value: '1d', label: '日K' },
              { value: '1w', label: '周K' },
              { value: '1m', label: '月K' },
            ]}
          />
        </Row>
      </Section>

      <Section title="Toggle">
        <Row>
          <Toggle checked={toggleOn} onChange={setToggleOn} label={`状态：${toggleOn ? '开启' : '关闭'}`} />
          <Toggle checked={false} onChange={() => {}} size="sm" label="小尺寸" />
          <Toggle checked={true} onChange={() => {}} disabled label="禁用" />
        </Row>
      </Section>

      <Section title="Field" desc="表单字段包装">
        <div className={s.fieldGrid}>
          <Field label="策略名称" required>
            <Input placeholder="输入策略名称" />
          </Field>
          <Field label="止损比例" hint="建议 5%-10%">
            <Input variant="mono" defaultValue="5%" />
          </Field>
          <Field label="无效字段" error="不能为空">
            <Input invalid defaultValue="" />
          </Field>
        </div>
      </Section>

      <Section title="Table" desc="columns/rows API + render prop">
        <Table columns={columns} rows={rows} density="comfortable" />
        <Row label="compact 密度">
          <Table columns={columns} rows={rows} density="compact" />
        </Row>
        <Row label="空数据">
          <Table columns={columns} rows={[]} />
        </Row>
      </Section>

      <Section title="Modal" desc="React Portal 实现">
        <Button variant="primary" onClick={() => setModalOpen(true)}>打开模态框</Button>
        <Modal
          open={modalOpen}
          onClose={() => setModalOpen(false)}
          title="确认操作"
          size="md"
          footer={
            <>
              <Button variant="ghost" onClick={() => setModalOpen(false)}>取消</Button>
              <Button variant="primary" onClick={() => setModalOpen(false)}>确定</Button>
            </>
          }
        >
          <p>这是一个模态对话框，支持 Escape 关闭、遮罩点击关闭、body 滚动锁。</p>
        </Modal>
      </Section>

      <Section title="EmptyState" desc="4 种变体">
        <div className={s.emptyGrid}>
          <EmptyState variant="default" title="暂无信号" desc="请先配置策略参数" />
          <EmptyState variant="no-data" title="无数据" />
          <EmptyState variant="error" title="请求失败" desc="网络超时，请重试" action={{ label: '重试', onClick: () => {} }} />
          <EmptyState variant="loading" title="加载中..." />
        </div>
      </Section>
    </div>
  )
}
