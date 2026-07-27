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
import { useCompany } from '@/contexts/CompanyContext'

/** Маршрут SPA → абсолютный адрес с учётом базы сборки (`/ClearLedger/`).
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
  const [busy, setBusy] = useState<string | null>(null)

  const open = useCallback(async (code: string, newTab = false) => {
    if (busy) return
    setBusy(code)
    try {
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
   * Внутренний продукт живёт в этом же SPA, но открывается новой вкладкой — как и
   * всякий другой: рабочие места держат рядом, а не вместо друг друга. Токен ему не
   * нужен, сессия уже своя. Сервисы с кнопкой рядом (Чат) остаются навигацией: они
   * часть текущего экрана, а не отдельное рабочее место.
   */
  const openApp = useCallback(async (app: SsoApp) => {
    const sameTab = hasSideButton(app.code)
    if (app.mode === 'internal' && app.route) {
      if (sameTab) navigate(app.route)
      else window.open(routeUrl(app.route), '_blank', 'noopener,noreferrer')
      return
    }
    await open(app.code, !sameTab)
  }, [navigate, open])

  return { open, openApp, busy }
}
