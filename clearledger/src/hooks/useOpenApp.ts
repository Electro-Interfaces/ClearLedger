/**
 * Открытие приложения экосистемы — общая механика лаунчера и рельса (Ядро).
 *
 * Приложения контейнера живут на ОДНОМ домене (`<domain>/support`, docs/CORE.md §6),
 * поэтому переход к ним — обычная навигация в той же вкладке: работает «назад»,
 * не плодятся вкладки. Новую вкладку открываем только там, где это уместно:
 * мосты на чужих доменах (Plane/Jitsi) и явное намерение пользователя
 * (Ctrl/⌘/Shift + клик, средняя кнопка) — как в любой ссылке.
 */
import { useCallback, useState } from 'react'
import { toast } from 'sonner'
import { authorizeApp } from '@/services/ssoService'
import { useCompany } from '@/contexts/CompanyContext'

/** Хочет ли пользователь открыть новой вкладкой (модификаторы/средняя кнопка). */
export function wantsNewTab(e?: { metaKey?: boolean; ctrlKey?: boolean; shiftKey?: boolean; button?: number }) {
  return !!e && (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1)
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

  return { open, busy }
}
