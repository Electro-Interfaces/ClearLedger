/**
 * Service Worker чата: показывает Web Push, когда вкладка пространства закрыта.
 * Payload шлёт бэкенд (services/web_push.py): {title, body, roomId}.
 */
self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()))

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
