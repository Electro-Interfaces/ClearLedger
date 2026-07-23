/**
 * Состав поставки компании из серверного реестра Ядра (eco_company_apps / eco_company_app_modules).
 *
 * Два разных измерения, которые нельзя путать:
 *   • RBAC (`companyModules` из /me) — ПРАВА человека: что ему можно;
 *   • реестр (этот хук)             — СОСТАВ продукта компании: что ей вообще подключено.
 * Видимость раздела = пересечение. Раньше состав жил в localStorage (демо-гейт
 * `moduleConnectionService`) и терялся при смене браузера — теперь это серверная настройка.
 *
 * Коды модулей приложения `ledger` совпадают с ключами доступа (`config/accessModules.ts`),
 * поэтому пересечение делается напрямую, без таблицы соответствий.
 */
import { useQuery } from '@tanstack/react-query'
import { isApiEnabled } from '@/services/apiClient'
import { listCompanyApps } from '@/services/registryService'

/** Приложение-носитель разделов рабочей области. */
const HOST_APP = 'ledger'

/**
 * Коды модулей Ledger, подключённых компании. `null` = «реестр не ограничивает»:
 * офлайн-контур, старый бэкенд без реестра, ошибка запроса или пустой ответ.
 *
 * Fail-open намеренно: реестр — это состав поставки, а не защита. Молчаливое
 * закрытие разделов из-за недоступного запроса выглядело бы как пропажа продукта;
 * права при этом продолжает проверять RBAC (и бэкенд — на каждом эндпоинте).
 */
export function useRegistryModules(companyId: string): string[] | null {
  const q = useQuery({
    // Тот же ключ, что у вкладки «Приложения» (/admin) — переключение там сразу
    // перестраивает меню, и запрос остаётся один.
    queryKey: ['company-apps', companyId],
    queryFn: () => listCompanyApps(companyId),
    enabled: isApiEnabled() && !!companyId,
    staleTime: 5 * 60_000,
    retry: false,
  })

  const apps = q.data
  if (!apps) return null
  const host = apps.find((a) => a.code === HOST_APP)
  if (!host || !host.enabled) return null
  const enabled = host.modules.filter((m) => m.enabled).map((m) => m.code)
  return enabled.length > 0 ? enabled : null
}

/**
 * Итоговый набор ключей для гейтинга меню Ledger: состав поставки ∩ права роли.
 * `null` с любой стороны = «эта сторона не ограничивает».
 *
 * Возвращает плоские коды модулей Ledger (совместимо с routeAllowed через includes).
 * Права роли (`rbac`) могут быть app-namespaced (`ledger:store`, `ledger` = весь Ledger)
 * или legacy-плоскими (`store`) — фильтруем реестр по тому, что пускает роль.
 */
export function intersectAccess(
  rbac: string[] | null | undefined,
  registry: string[] | null,
): string[] | null {
  if (!registry) return rbac ?? null
  if (!rbac) return registry
  // Модуль Ledger `code` разрешён ролью, если она содержит сам код, `ledger:code`
  // или `ledger` (доступ ко всему приложению).
  return registry.filter(
    (code) => rbac.includes(code) || rbac.includes(`ledger:${code}`) || rbac.includes('ledger'),
  )
}
