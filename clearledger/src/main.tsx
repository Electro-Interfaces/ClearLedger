import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './index.css'

import { initDefaults } from './services/initService'
import { startScheduler } from './services/channelScheduler'
import { isApiEnabled } from './services/apiClient'
import { setServicesCompany } from './services/cacheReset'
import { defaultCompanyId } from './config/companies'

// После деплоя закэшированный index.html тянет чанки со старыми хэшами → Vite
// кидает vite:preloadError («Failed to fetch dynamically imported module»).
// Лечение — один автоматический reload (свежий index подтянет новые чанки);
// гард в sessionStorage защищает от цикла, если проблема не в кэше.
window.addEventListener('vite:preloadError', (e) => {
  if (sessionStorage.getItem('tl-chunk-reload') !== '1') {
    sessionStorage.setItem('tl-chunk-reload', '1')
    e.preventDefault()
    console.warn('[TradeLedger] Устаревшая сборка в кэше — перезагрузка за свежей')
    window.location.reload()
  }
})
// Флаг снимаем только после 30с стабильной работы: следующий деплой в этой же
// вкладке снова получит свой одиночный reload, а реальный сбой не зациклится.
window.addEventListener('load', () => {
  setTimeout(() => sessionStorage.removeItem('tl-chunk-reload'), 30_000)
})

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
