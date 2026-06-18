import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './index.css'

import { initDefaults } from './services/initService'
import { startScheduler } from './services/channelScheduler'
import { isApiEnabled } from './services/apiClient'
import { setServicesCompany } from './services/cacheReset'
import { defaultCompanyId } from './config/companies'

// Миграция схемы: per-company ключи (tl-*-${companyId}) вместо глобальных gig-*.
const SCHEMA_VERSION = '5'
if (localStorage.getItem('gig-schema') !== SCHEMA_VERSION) {
  // Старые глобальные ключи (до мультитенантности) больше не читаются.
  for (const k of ['gig-channels', 'gig-sources', 'gig-initialized']) {
    localStorage.removeItem(k)
  }
  localStorage.setItem('gig-schema', SCHEMA_VERSION)
  console.log('[TradeLedger] Schema migrated to v' + SCHEMA_VERSION)
}

// Офлайн-демо (без VITE_API_URL): инициализация дефолтов + планировщик для
// активной компании. В API-режиме это ведёт бэкенд (seed) + ручной/канальный
// запуск под авторизацией — на старте без сессии планировщик не запускаем.
if (!isApiEnabled()) {
  setServicesCompany(defaultCompanyId)
  initDefaults()
  startScheduler()
}

console.log('[TradeLedger] Starting...')

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
