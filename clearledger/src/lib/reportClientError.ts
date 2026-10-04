/**
 * Отправка сбоя интерфейса в журнал пространства.
 *
 * «Периодически возникает ошибка» — это всё, что мы знали о падениях экрана:
 * минифицированный текст React без места и без повторяемости (МАГ, 18.09.2026).
 * Теперь падение уезжает с маршрутом, версией и стеком компонентов.
 *
 * Дисциплина отправки — своя, не серверная: цикл перерисовки способен вызвать
 * границу ошибок сотни раз подряд, и без предохранителя браузер сам устроит
 * себе отказ. Не чаще одного сообщения в десять секунд и не больше пяти за
 * вкладку; сервер поверх этого сворачивает повторы по отпечатку.
 */

import { getToken } from '@/services/apiClient'
import { APP_VERSION } from '@/lib/appUpdate'

const ПАУЗА_МС = 10_000
const ПРЕДЕЛ_ЗА_ВКЛАДКУ = 5

let последняя = 0
let отправлено = 0

export interface СбойИнтерфейса {
  message: string
  stack?: string | null
  componentStack?: string | null
  /** Экран, если он известен: «Маркетинг · Компании и расклад сил». */
  screen?: string | null
}

export function reportClientError(сбой: СбойИнтерфейса): void {
  const сейчас = Date.now()
  if (отправлено >= ПРЕДЕЛ_ЗА_ВКЛАДКУ) return
  if (сейчас - последняя < ПАУЗА_МС) return
  последняя = сейчас
  отправлено += 1

  const тело = JSON.stringify({
    message: (сбой.message || '').slice(0, 2000),
    stack: сбой.stack ? сбой.stack.slice(0, 8000) : null,
    componentStack: сбой.componentStack ? сбой.componentStack.slice(0, 8000) : null,
    // Адрес без параметров: в них попадает содержимое фильтров и поиска.
    path: `${window.location.pathname}${window.location.hash}`.slice(0, 500),
    screen: сбой.screen ?? null,
    version: APP_VERSION,
  })

  const token = getToken()
  // keepalive — падение часто заканчивается уходом со страницы, и обычный fetch
  // браузер обрывает раньше, чем запрос уходит.
  fetch(`${import.meta.env.VITE_API_URL ?? ''}/api/client-errors`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: тело,
    keepalive: true,
  }).catch(() => {
    // Журнал сбоев не имеет права мешать работе: молчим.
  })
}
