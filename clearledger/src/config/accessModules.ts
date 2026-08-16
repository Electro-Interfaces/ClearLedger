/**
 * Каталог модулей доступа (RBAC). Определяет, какие ключи доступа существуют,
 * как они группируются в UI и какие режимы/роуты открывают.
 *
 * Модель: у члена компании (UserCompany) есть список разрешённых ключей `modules`.
 *   null/undefined = полный доступ (admin, суперадмин, старые члены до миграции).
 *   массив = только перечисленные ключи.
 * Зеркалируется на backend: app/access_catalog.py (ACCESS_KEYS).
 */

export type AccessKey =
  | 'management' | 'store' | 'financial' | 'accounting' | 'tax'
  | 'documents' | 'reconciliation' | 'sources' | 'locations' | 'onec' | 'catalog'

export interface AccessModuleDef {
  key: AccessKey
  label: string
  group: 'Режимы учёта' | 'Данные и настройка'
  hint?: string
  routes: string[]        // nav-роуты (по префиксу), которые открывает ключ
  mode?: string           // ключ режима рабочего пространства, если это режим-модуль
}

export const ACCESS_MODULES: AccessModuleDef[] = [
  { key: 'management', label: 'Продажи', group: 'Режимы учёта', mode: 'management', routes: [], hint: 'аналитика, KPI, сессии, баланс' },
  { key: 'store', label: 'Магазин', group: 'Режимы учёта', mode: 'store', routes: [], hint: 'сопутка/общепит: коннектор 1С, аналитика ассортимента, выгрузка в БП' },
  { key: 'financial', label: 'Финансовый', group: 'Режимы учёта', mode: 'financial', routes: [], hint: 'денежные потоки, ДЗ/КЗ' },
  { key: 'accounting', label: 'Бухгалтерский', group: 'Режимы учёта', mode: 'accounting', routes: ['/forecast'], hint: 'проводки, 1С, закрытие месяца' },
  { key: 'tax', label: 'Налоговый', group: 'Режимы учёта', mode: 'tax', routes: [], hint: 'НДС, налог на прибыль' },
  { key: 'documents', label: 'Документы и загрузка', group: 'Данные и настройка', routes: ['/files', '/intake'] },
  { key: 'reconciliation', label: 'Разрезы и нормализация', group: 'Данные и настройка', routes: ['/reconciliation', '/normalization'] },
  { key: 'sources', label: 'Коннекторы', group: 'Данные и настройка', routes: ['/connectors', '/sources', '/channels'] },
  { key: 'locations', label: 'Объекты и контрагенты', group: 'Данные и настройка', routes: ['/objects', '/locations', '/contractors', '/organization'] },
  { key: 'onec', label: 'Интеграция 1С', group: 'Данные и настройка', routes: ['/1c'] },
  { key: 'catalog', label: 'Каталоги и параметры', group: 'Данные и настройка', routes: ['/settings', '/catalog'] },
]

export const ALL_ACCESS_KEYS: AccessKey[] = ACCESS_MODULES.map((m) => m.key)

/** Готовые профили доступа (пресеты) для быстрого назначения типовых ролей. */
export interface AccessPreset { label: string; keys: AccessKey[] | null; hint: string }
export const ACCESS_PRESETS: AccessPreset[] = [
  { label: 'Полный доступ', keys: null, hint: 'все модули' },
  { label: 'Финансист', keys: ['management', 'financial', 'documents', 'catalog'], hint: 'управленческий + финансовый' },
  { label: 'Бухгалтер', keys: ['accounting', 'tax', 'documents', 'onec', 'catalog'], hint: 'бухгалтерский + налоговый + 1С' },
  { label: 'Оператор данных', keys: ['documents', 'reconciliation', 'sources', 'locations'], hint: 'загрузка и настройка данных' },
  { label: 'Наблюдатель', keys: ['management'], hint: 'только управленческий' },
]

/** Имена продуктов пространства (для app-namespaced ключей ролей). Коды смысловые:
 *  `plan`/`conf`, не по движку. Имена — те же, что в реестре. */
export const APP_LABELS: Record<string, string> = {
  admin: 'Управление', ledger: 'Учёт', support: 'Поддержка',
  chat: 'Чаты', docs: 'Трек', conf: 'Конференции',
  // Ключ `plan` остаётся ради старых ролей: поручения живут в «Деле»,
  // но выданный когда-то доступ не должен молча пропасть из матрицы.
  plan: 'Поручения (старый ключ)',
  // Продукты разреза Учёта (config/spaceProducts.ts).
  projects: 'Проекты', ops: 'Эксплуатация', sales: 'Продажи',
  finance: 'Финансы', data: 'Данные',
}

/** Метки ключей роли (для чипов/сводки). Понимает app-namespaced (`app`, `app:module`)
 * и legacy-плоские ключи Ledger. */
export function moduleLabels(keys: string[]): string[] {
  return keys.map((k) => {
    if (k.includes(':')) {
      const [app, mod] = k.split(':', 2)
      const modLabel = ACCESS_MODULES.find((m) => m.key === mod)?.label ?? mod
      return app === 'ledger' ? modLabel : `${APP_LABELS[app] ?? app}: ${modLabel}`
    }
    // app-ключ (доступ к приложению целиком) или legacy-плоский модуль Ledger
    return APP_LABELS[k] ?? ACCESS_MODULES.find((m) => m.key === k)?.label ?? k
  })
}

/** Роуты, доступные всегда (не гейтятся модулями). */
const ALWAYS_ROUTES = ['/', '/workspace', '/admin', '/accept-invite', '/login']

/** Тип набора модулей: null = полный доступ. */
export type AccessSet = string[] | null | undefined

/** Разрешён ли модуль Ledger `key` при наборе `modules`. Совместимо: понимает
 * app-namespaced ключи (`ledger:store`, `ledger` = доступ ко всему Ledger) и
 * legacy-плоские (`store`). */
function ledgerKeyAllowed(key: string, modules: string[]): boolean {
  return modules.includes(key) || modules.includes(`ledger:${key}`) || modules.includes('ledger')
}

export function moduleAllowed(key: string, modules: AccessSet): boolean {
  if (!modules) return true
  return ledgerKeyAllowed(key, modules)
}

/** Разрешён ли режим рабочего пространства (management/financial/accounting/tax). */
export function modeAllowed(mode: string, modules: AccessSet): boolean {
  if (!modules) return true
  // Разделы «Магазина» (store_stock, store_catalog, …) — один ключ доступа `store`,
  // разделы «Бухгалтерии» (acc_store, acc_recon, …) — ключ `accounting`: незнакомый
  // режим здесь разрешён по умолчанию, и без этих строк роль без магазина или без
  // бухгалтерии увидела бы остальные их разделы.
  const root = mode.startsWith('store_') ? 'store'
    : mode.startsWith('acc_') ? 'accounting'
    : mode
  const def = ACCESS_MODULES.find((m) => m.mode === root)
  return def ? ledgerKeyAllowed(def.key, modules) : true
}

/** Разрешён ли роут левого меню при данном наборе модулей. */
export function routeAllowed(pathname: string, modules: AccessSet): boolean {
  if (!modules) return true
  if (ALWAYS_ROUTES.some((r) => (r === '/' ? pathname === '/' : pathname.startsWith(r)))) return true
  const def = ACCESS_MODULES.find((m) => m.routes.some((r) => pathname.startsWith(r)))
  if (!def) return true  // неизвестный/несгейченный роут — пропускаем
  return ledgerKeyAllowed(def.key, modules)
}
