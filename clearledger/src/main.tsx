import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { seedIfNeeded } from '@/services/dataEntryService'
import { migrateEntries } from '@/services/storage'
import { migrateLocalStorageToIDB } from '@/services/idbStorage'
import './index.css'

// Синхронные миграции (localStorage → localStorage)
migrateEntries()

// Async init: миграция localStorage → IndexedDB, затем seed
async function init() {
  await migrateLocalStorageToIDB()
  await seedIfNeeded()
}

init().then(() => {
  if (import.meta.env.DEV) {
    import('./services/devConsole')
  }
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
