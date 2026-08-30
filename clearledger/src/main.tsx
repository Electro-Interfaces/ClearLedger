import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './index.css'

import { initUiLevel } from './hooks/useUiLevel'
import { isApiEnabled, isDemoMode } from './services/apiClient'
import { initPwaInstall } from './lib/pwaInstall'

// Пропуск инженера в чужое пространство приходит в хэше — и до страницы не доживает:
// провайдер фильтра при старте пишет выборку в адрес через `replace`, а React Router
// собирает новый URL из пути и query, теряя хэш. Забираем пропуск здесь, до первого
// рендера, и сразу чистим адрес: в истории браузера ему делать нечего.
if (window.location.pathname.replace(/\/$/, '').endsWith('/space-guest')
    && window.location.hash.includes('token=')) {
  try {
    sessionStorage.setItem('eco-space-pass', window.location.hash.replace(/^#/, ''))
  } catch { /* приватный режим — останется чтение из хэша */ }
  history.replaceState(null, '', window.location.pathname)
}

// Chrome может выдать событие установки до того, как авторизация и React-обвязка
// закончат загрузку. Сохраняем его сразу: событие одноразовое и повторно не приходит.
if (!isDemoMode()) initPwaInstall()

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
  void Promise.all([
    import('./services/cacheReset'),
    import('./config/companies'),
    import('./services/initService'),
    import('./services/channelScheduler'),
  ]).then(([cache, companies, init, scheduler]) => {
    cache.setServicesCompany(companies.defaultCompanyId)
    init.initDefaults()
    scheduler.startScheduler()
  })
}

// Service worker регистрируем ЗДЕСЬ, а не при включении уведомлений: Chrome
// предлагает поставить приложение на телефон только сайту с активным SW, и
// «Пульс» не предлагался никому, кто не включил пуши в чате. Пуш-подписка
// (`lib/chatPush`) переиспользует эту же регистрацию. Не ждём window.load:
// чем раньше SW активируется и возьмёт страницу под контроль, тем раньше браузер
// выдаст настоящее beforeinstallprompt вместо сценария обычного ярлыка сайта.
if (!isDemoMode() && 'serviceWorker' in navigator) {
  navigator.serviceWorker.register(`${import.meta.env.BASE_URL}sw.js`, {
    scope: import.meta.env.BASE_URL,
    updateViaCache: 'none',
  }).catch((err) => {
    // Не повод ронять приложение: без SW работает всё, кроме установки и пушей.
    console.warn('[Пространство] service worker не зарегистрирован:', err)
  })
}

// Режим работы (простой/расширенный) — до первого рендера, иначе простой
// режим на мгновение мигнёт расширенным.
initUiLevel()

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
