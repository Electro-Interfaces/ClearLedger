/**
 * Service Worker пространства: Web Push, когда вкладка закрыта, и установка на телефон.
 *
 * Payload пуша шлёт бэкенд (services/web_push.py): {title, body, roomId}.
 *
 * Обработчик `fetch` здесь обязателен, а не «на будущее»: без него Chrome НЕ считает
 * сайт устанавливаемым и не показывает предложение поставить приложение — из-за этого
 * «Пульс» не предлагался на домашний экран, хотя манифест был на месте.
 *
 * Кэш намеренно НЕ ведём: пространство показывает деньги и сроки, и старая цифра из
 * кэша хуже честного «нет сети». Офлайн отдаём только заглушку навигации.
 */
self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()))

self.addEventListener('fetch', (event) => {
  const req = event.request
  // Вмешиваемся только в переходы по страницам: API, ассеты и ws идут напрямую.
  if (req.mode !== 'navigate') return
  event.respondWith((async () => {
    try {
      return await fetch(req)
    } catch {
      return new Response(
        '<!doctype html><meta charset="utf-8">'
        + '<meta name="viewport" content="width=device-width,initial-scale=1">'
        + '<body style="font:16px/1.5 system-ui;margin:0;display:grid;place-items:center;'
        + 'height:100vh;background:#0b0f19;color:#e6e9ef">'
        + '<div style="text-align:center;padding:24px">'
        + '<div style="font-size:18px;font-weight:600">Нет связи</div>'
        + '<div style="margin-top:8px;opacity:.7">Пространство откроется, когда вернётся сеть.<br>'
        + 'Цифры здесь живые — из кэша их не показываем.</div></div>',
        { headers: { 'Content-Type': 'text/html; charset=utf-8' }, status: 503 })
    }
  })())
})

self.addEventListener('push', (event) => {
  let data = {}
  try { data = event.data ? event.data.json() : {} } catch { /* не наш формат — молчим */ }
  if (!data.title && !data.body) return
  event.waitUntil(self.registration.showNotification(data.title || 'Сообщение', {
    body: data.body || '',
    icon: '/favicon.svg',
    // tag схлопывает очередь уведомлений одной комнаты в одно.
    tag: data.roomId || 'chat',
    data: { roomId: data.roomId || null },
  }))
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  // Открыть пространство на «Чатах»: существующая вкладка — фокусом, иначе новая.
  event.waitUntil((async () => {
    const list = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
    const existing = list.find((c) => 'focus' in c)
    if (existing) {
      existing.focus()
      existing.postMessage({ type: 'open-chat', roomId: event.notification.data?.roomId })
    } else {
      await self.clients.openWindow('/messages')
    }
  })())
})
