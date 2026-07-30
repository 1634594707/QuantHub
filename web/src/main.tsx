import React from 'react'
import ReactDOM from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import { ThemeProvider } from './theme/ThemeContext'
import App from './App'
import NotFoundPage from './pages/NotFoundPage'
import './styles/tokens.css'
import './styles/base.css'
import './styles/board.css'
import './styles/app.css'

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
      { path: 'example', lazy: async () => ({ Component: (await import('./pages/ExampleWorkspacePage')).default }) },
      { path: 'research/:symbol', lazy: async () => ({ Component: (await import('./pages/ResearchWorkspacePage')).default }) },
      { path: 'ensemble', lazy: async () => ({ Component: (await import('./pages/EnsemblePage')).default }) },
      { path: 'signals', lazy: async () => ({ Component: (await import('./pages/SignalsPage')).default }) },
      { path: 'tasks', lazy: async () => ({ Component: (await import('./pages/AnalysisTasksPage')).default }) },
      { path: 'alerts', lazy: async () => ({ Component: (await import('./pages/AlertsPage')).default }) },
      { path: 'simulation', lazy: async () => ({ Component: (await import('./pages/SimulationOrdersPage')).default }) },
      { path: 'ledger', lazy: async () => ({ Component: (await import('./pages/LedgerPage')).default }) },
      { path: 'instruments', lazy: async () => ({ Component: (await import('./pages/InstrumentCenterPage')).default }) },
      { path: 'strategy-lab', lazy: async () => ({ Component: (await import('./pages/StrategyLabPage')).default }) },
      { path: 'factor-research', lazy: async () => ({ Component: (await import('./pages/FactorResearchPage')).default }) },
      { path: 'automation', lazy: async () => ({ Component: (await import('./pages/AutomationPage')).default }) },
      { path: 'incidents', lazy: async () => ({ Component: (await import('./pages/IncidentsPage')).default }) },
      { path: 'governance', lazy: async () => ({ Component: (await import('./pages/GovernancePage')).default }) },
      { path: 'news', lazy: async () => ({ Component: (await import('./pages/NewsPage')).default }) },
      // 回测 / 情感分析 已整合进策略工作台（G6 / 重叠清理），不再独立路由
      { path: 'strategies', lazy: async () => ({ Component: (await import('./pages/StrategiesPage')).default }) },
      { path: 'strategies/:name', lazy: async () => ({ Component: (await import('./pages/StrategyDetailPage')).default }) },
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
      <RouterProvider router={router} />
    </ThemeProvider>
  </React.StrictMode>,
)
