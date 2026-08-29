import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

import App from './App'
import { GameProvider } from './hooks/useGame'
import './styles.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <GameProvider>
        <App />
      </GameProvider>
    </BrowserRouter>
  </StrictMode>,
)
