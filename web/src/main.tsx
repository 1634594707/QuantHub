import React from 'react'
import ReactDOM from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import { ThemeProvider } from './theme/ThemeContext'
import App from './App'
import OverviewPage from './pages/OverviewPage'
import SignalsPage from './pages/SignalsPage'
import BacktestPage from './pages/BacktestPage'
import StrategiesPage from './pages/StrategiesPage'
import PaAnalysisPage from './pages/PaAnalysisPage'
import SentimentPage from './pages/SentimentPage'
import StrategyDetailPage from './pages/StrategyDetailPage'
import ConfigPage from './pages/ConfigPage'
import './styles/tokens.css'
import './styles/app.css'
import './styles/strategy-module.css'

const router = createBrowserRouter([
  {
    path: '/',
    element: <App />,
    children: [
      { index: true, element: <OverviewPage /> },
      { path: 'signals', element: <SignalsPage /> },
      { path: 'backtest', element: <BacktestPage /> },
      { path: 'strategies', element: <StrategiesPage /> },
      { path: 'strategies/:name', element: <StrategyDetailPage /> },
      { path: 'pa', element: <PaAnalysisPage /> },
      { path: 'sentiment', element: <SentimentPage /> },
      { path: 'config', element: <ConfigPage /> },
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
