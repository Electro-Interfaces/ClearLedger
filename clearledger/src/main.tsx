import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './index.css'

import { initDefaults } from './services/initService'
import { startScheduler } from './services/channelScheduler'

// Миграция: очистить данные старого формата при смене схемы
const SCHEMA_VERSION = '4'
if (localStorage.getItem('gig-schema') !== SCHEMA_VERSION) {
  localStorage.removeItem('gig-channels')
  localStorage.removeItem('gig-sources')
  localStorage.removeItem('gig-initialized')
  localStorage.setItem('gig-schema', SCHEMA_VERSION)
  console.log('[GIG Fuel] Schema migrated to v' + SCHEMA_VERSION)
}

// Авто-инициализация: источник STS + канал «Загрузка сменных отчётов»
initDefaults()

// Запуск планировщика автозагрузки каналов
startScheduler()

console.log('[GIG Fuel] Starting...')

try {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
  console.log('[GIG Fuel] Rendered OK')
} catch (err) {
  console.error('[GIG Fuel] RENDER ERROR:', err)
  document.getElementById('root')!.innerHTML = `<pre style="color:red;padding:2rem">${err}</pre>`
}
