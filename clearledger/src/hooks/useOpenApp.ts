/**
 * Открытие приложения экосистемы — общая механика лаунчера и рельса (Ядро).
 *
 * **Продукт открывается в новой вкладке** (решение МАГа 27.07.2026): рабочие места
 * держат открытыми параллельно — эксплуатация в одной вкладке, финансы в другой, — и
 * вызов продукта не должен выбрасывать из того, где человек уже работает.
 *
 * Исключение — сервисы со своей кнопкой рядом (Чат · Заявки · Конференция): они и так
 * под рукой, их вызов ведёт себя как раньше.
 */
import { useCallback, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { authorizeApp, hasSideButton, type SsoApp } from '@/services/ssoService'
import { startMeeting } from '@/services/conferenceService'
import { useCompany } from '@/contexts/CompanyContext'
import { useMaxWidth } from '@/hooks/use-mobile'

/** Маршрут SPA → абсолютный адрес с учётом базы сборки (по умолчанию корень).
 *  Без неё новая вкладка открыла бы `/finance` мимо приложения — на 404 кромки. */
function routeUrl(route: string): string {
  const base = import.meta.env.BASE_URL.replace(/\/$/, '')
  return `${window.location.origin}${base}${route}`
}

function isSameOrigin(url: string) {
  try {
    return new URL(url, window.location.href).origin === window.location.origin
  } catch {
    return false
  }
}

export function useOpenApp() {
  const { companyId } = useCompany()
  const navigate = useNavigate()
  // Тот же порог, что у раскладок: ниже него продукт открывается в текущей вкладке.
  const narrow = useMaxWidth(1024)
  const [busy, setBusy] = useState<string | null>(null)

  const open = useCallback(async (code: string, newTab = false) => {
    if (busy) return
    setBusy(code)
    try {
      // «Конференции» — не адрес, а действие: у сервиса нет своей страницы пространства,
      // и переход на голый meet.dataworker.ru приводил человека к чужой форме «создать
      // конференцию» — без имени комнаты, без организатора и без ссылки для приглашения.
      // Поэтому здесь комната создаётся сразу: организатор входит по своей ссылке, а
      // гостевая ложится в буфер, чтобы было чем позвать участников.
      if (code === 'conf') {
        const m = await startMeeting()
        try { await navigator.clipboard.writeText(m.guest_url) } catch { /* буфер недоступен */ }
        toast.success('Конференция создана — ссылка для участников скопирована', { description: m.guest_url })
        return
      }
      const url = await authorizeApp(code, companyId)
      // Чужой домен (мост) всегда уходит в новую вкладку: там своя сессия и свой «назад».
      if (newTab || !isSameOrigin(url)) window.open(url, '_blank', 'noopener,noreferrer')
      else window.location.assign(url)
    } catch (e) {
      const msg = (e as Error).message || ''
      toast.error(/503|не настроен/i.test(msg) ? 'Единый вход не настроен' : 'Не удалось открыть приложение')
    } finally {
      setBusy(null)
    }
  }, [busy, companyId])

  /**
   * Внутренний продукт живёт в этом же SPA, но на десктопе открывается новой вкладкой —
   * как и всякий другой: рабочие места держат рядом, а не вместо друг друга. Токен ему
   * не нужен, сессия уже своя. Сервисы с кнопкой рядом (Чат) остаются навигацией: они
   * часть текущего экрана, а не отдельное рабочее место.
   *
   * На узком экране — всегда в текущей вкладке. Держать рабочие места параллельно в
   * телефоне не выходит: переключение стоит двух жестов через меню браузера, вкладки
   * копятся и теряются, «назад» перестаёт возвращать на стол. Плюс новая вкладка
   * открывается со своими настройками — в режиме эмуляции устройства она приходит
   * сразу в десктопном виде.
   */
  const openApp = useCallback(async (app: SsoApp) => {
    const sameTab = narrow || hasSideButton(app.code)
    if (app.mode === 'internal' && app.route) {
      if (sameTab) navigate(app.route)
      else window.open(routeUrl(app.route), '_blank', 'noopener,noreferrer')
      return
    }
    await open(app.code, !sameTab)
  }, [narrow, navigate, open])

  return { open, openApp, busy }
}
