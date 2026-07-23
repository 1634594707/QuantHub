import React from 'react'
import ReactDOM from 'react-dom/client'
import { ThemeProvider } from './theme/ThemeContext'
import App from './App'
import './styles/tokens.css'
import './styles/app.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ThemeProvider>
      <App />
    </ThemeProvider>
  </React.StrictMode>,
)
