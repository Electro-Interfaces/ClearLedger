import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { seedIfNeeded } from '@/services/dataEntryService'
import './index.css'

seedIfNeeded()

if (import.meta.env.DEV) {
  import('./services/devConsole')
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
