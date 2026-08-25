import React from 'react'
import ReactDOM from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import { ThemeProvider } from './theme/ThemeContext'
import { InterfaceModeProvider } from './hooks/useInterfaceMode'
import App from './App'
import NotFoundPage from './pages/NotFoundPage'
import './styles/tokens.css'
import './styles/base.css'
import './styles/board.css'
import './styles/app.css'
import './styles/research-matrix.css'

// UI 组件库演示页（仅 dev 环境可访问 /__ui）
// Vite 静态替换 import.meta.env.DEV：生产构建时此分支为 false，路由不注册，import 被剔除。
const devRoutes = import.meta.env.DEV
  ? [{ path: '__ui', lazy: async () => ({ Component: (await import('./components/ui/_demo/UiShowcasePage')).default }) }]
  : []

const router = createBrowserRouter([
  {
    path: '/',
    element: <App />,
    // 未匹配路径 / 路由内抛错统一走 NotFoundPage（内部用 useRouteError 区分 404 与 500），
    // 并对 /backtest、/sentiment 等旧路由给出迁移提示。
    errorElement: <NotFoundPage />,
    children: [
      { index: true, lazy: async () => ({ Component: (await import('./pages/OverviewPage')).default }) },
      { path: 'evaluate', lazy: async () => ({ Component: (await import('./pages/StockEvaluationStartPage')).default }) },
      { path: 'research/:symbol', lazy: async () => ({ Component: (await import('./pages/ResearchWorkspacePage')).default }) },
      { path: 'ensemble', lazy: async () => ({ Component: (await import('./pages/EnsemblePage')).default }) },
      { path: 'radar', lazy: async () => ({ Component: (await import('./pages/RadarPage')).default }) },
      { path: 'signals', lazy: async () => ({ Component: (await import('./pages/SignalsPage')).default }) },
      // 交易域（M2-05）：浏览器唯一的 OKX 通路，经 /api/trading/* 访问 Runner。
      { path: 'trading', lazy: async () => ({ Component: (await import('./pages/TradingWorkspacePage')).default }) },
      // 账户与风控（M2-06）
      { path: 'account-risk', lazy: async () => ({ Component: (await import('./pages/AccountRiskPage')).default }) },
      { path: 'tasks', lazy: async () => ({ Component: (await import('./pages/AnalysisTasksPage')).default }) },
      { path: 'alerts', lazy: async () => ({ Component: (await import('./pages/AlertsPage')).default }) },
      { path: 'simulation', lazy: async () => ({ Component: (await import('./pages/SimulationOrdersPage')).default }) },
      // 模拟实验室兼容入口：仅回读历史 Demo 记录；新研究/模拟由职责页面发起
      { path: 'demo-lab', lazy: async () => ({ Component: (await import('./pages/DemoLabPage')).default }) },
      { path: 'ledger', lazy: async () => ({ Component: (await import('./pages/LedgerPage')).default }) },
      { path: 'instruments', lazy: async () => ({ Component: (await import('./pages/InstrumentCenterPage')).default }) },
      // 因子工厂：候选挖掘、研究门禁、模拟验证和因子档案的统一入口。
      { path: 'factor-research', lazy: async () => ({ Component: (await import('./pages/FactorResearchPage')).default }) },
      { path: 'automation', lazy: async () => ({ Component: (await import('./pages/AutomationPage')).default }) },
      { path: 'incidents', lazy: async () => ({ Component: (await import('./pages/IncidentsPage')).default }) },
      // 成员权限（/governance）已按路线图 3.F 移出一级导航。
      // M2-07 已完成：API 凭据设置入口迁至「设置 / 系统设置 · 接入凭据」（ConfigPage）。
      // 本页保留直链路由，因为它仍是「成员 / 角色 / 访问令牌签发 / 审计日志」的唯一界面；
      // 是否整体下线需用户裁决（下线将失去上述管理能力，非纯粹的重复入口清理）。
      { path: 'governance', lazy: async () => ({ Component: (await import('./pages/GovernancePage')).default }) },
      { path: 'news', lazy: async () => ({ Component: (await import('./pages/NewsPage')).default }) },
      // 回测 / 情感分析 已整合进策略工作台（G6 / 重叠清理），不再独立路由
      { path: 'strategies', lazy: async () => ({ Component: (await import('./pages/StrategiesPage')).default }) },
      { path: 'strategies/:name', lazy: async () => ({ Component: (await import('./pages/StrategyDetailPage')).default }) },
      // 策略实验（/strategy-lab）已按 M2-01 移出一级导航，但**不能删除**：
      // 它是 /strategy-lab/* 后端接口（定义 / 版本 / 实验 / 回测 / 对比）的唯一前端界面，
      // 且被命令面板、系统设置高级入口、因子研究页共 6 处入站链接引用。
      { path: 'strategy-lab', lazy: async () => ({ Component: (await import('./pages/StrategyLabPage')).default }) },
      { path: 'pa', lazy: async () => ({ Component: (await import('./pages/PaAnalysisPage')).default }) },
      { path: 'portfolio', lazy: async () => ({ Component: (await import('./pages/PortfolioPage')).default }) },
      { path: 'config', lazy: async () => ({ Component: (await import('./pages/ConfigPage')).default }) },
      ...devRoutes,
    ],
  },
])

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ThemeProvider>
      <InterfaceModeProvider>
        <RouterProvider router={router} />
      </InterfaceModeProvider>
    </ThemeProvider>
  </React.StrictMode>,
)
