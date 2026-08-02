/**
 * Web Push чата: регистрация service worker и подписка браузера.
 * Ключ VAPID отдаёт бэкенд (/api/chat/push/vapid), подписка хранится там же.
 */
import * as chat from '@/services/chatService'

function b64ToU8(base64: string): Uint8Array {
  const pad = '='.repeat((4 - (base64.length % 4)) % 4)
  const raw = atob((base64 + pad).replace(/-/g, '+').replace(/_/g, '/'))
  return Uint8Array.from(raw, (c) => c.charCodeAt(0))
}

export const pushSupported = (): boolean =>
  'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window

/** Тихо восстановить подписку (permission уже granted). Возвращает успех. */
export async function ensurePushSubscription(): Promise<boolean> {
  if (!pushSupported() || Notification.permission !== 'granted') return false
  const reg = await navigator.serviceWorker.register('/sw.js')
  let sub = await reg.pushManager.getSubscription()
  if (!sub) {
    const { key } = await chat.getVapidKey()
    sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: b64ToU8(key) as BufferSource,
    })
  }
  const j = sub.toJSON()
  if (!j.keys?.p256dh || !j.keys?.auth) return false
  await chat.subscribePush({
    endpoint: sub.endpoint, keys: { p256dh: j.keys.p256dh, auth: j.keys.auth },
  })
  return true
}

/** Спросить разрешение и подписаться — по явному клику человека. */
export async function requestPushPermission(): Promise<'ok' | 'denied' | 'unsupported'> {
  if (!pushSupported()) return 'unsupported'
  const p = await Notification.requestPermission()
  if (p !== 'granted') return 'denied'
  return (await ensurePushSubscription()) ? 'ok' : 'unsupported'
}
