/**
 * Продукты пространства, собранные из разделов Учёта.
 *
 * Решение МАГа (26.07.2026): режем по РАБОЧИМ МЕСТАМ, а не по видам учёта. Вид учёта —
 * разрез данных (бухгалтеру нужны и проводки, и документы, и контрагенты), рабочим местом
 * он не является. Продукт — то, в чём человек проводит день: у него свои люди, свой цикл
 * и свой ритм. Для сети ЭЗС разрез ложится на жизнь объекта:
 *
 *   строим (Проекты) → эксплуатируем (Эксплуатация) → продаём (Сеть) →
 *   чиним (Координатор) → считаем (Финансы);  Данные — служебная кухня сбора.
 *
 * Один источник для трёх вещей: маршрут продукта (App.tsx), его левое меню (AppSidebar)
 * и то, какие разделы ушли из Учёта (workspaceSections). Коды совпадают с реестром Ядра
 * (`eco_apps`), поэтому доступ выдаётся ролью на продукт целиком.
 *
 * Разрез включён только у профиля `energy` (сеть ЭЗС). У топливного профиля (ГИГ) состав
 * другой — там «Учёт» остаётся единым продуктом со всеми разделами, как раньше.
 */
import type { CoreMode } from '@/contexts/WorkspaceContext'
import { navByPath, type NavItemDef } from './navigation'

export interface SpaceProduct {
  /** Код в реестре Ядра = ключ доступа роли. */
  code: string
  /** Корневой маршрут продукта (совпадает с `INTERNAL_ROUTES` на бэкенде). */
  route: string
  label: string
  /** Разделы рабочей области, которые живут в этом продукте. */
  modes: CoreMode[]
  /** Страницы продукта (пути из `config/navigation.ts`) — его левое меню. */
  paths: string[]
}

export const SPACE_PRODUCTS: SpaceProduct[] = [
  {
    code: 'projects', route: '/projects', label: 'Проекты',
    modes: ['projects'], paths: [],
  },
  {
    // Эксплуатация — железо и его состояние: мониторинг сети, парк, склады, ЗИП.
    // Объект живёт здесь: его эксплуатируют. Реестр объектов остаётся в «Управлении».
    code: 'ops', route: '/operations', label: 'Эксплуатация',
    modes: ['operations'], paths: ['/objects'],
  },
  {
    // Сеть — коммерция: сессии, тарифы, ЮЛ/ФЛ, ABC-XYZ. Метрика тоже сюда: это
    // маркетинг сети, а не кухня данных.
    code: 'network', route: '/network', label: 'Сеть',
    modes: ['management', 'store'], paths: ['/metrika'],
  },
  {
    // Финансы — счётная сторона целиком: проводки, налоги, выгрузка, первичка,
    // контрагенты, 1С.
    // NB: «Хозяйство» площадок (энергозакупка, аренда) по смыслу денежное, но живёт
    // под-разделами режима `operations` и рисуется его панелью — переезд сюда требует
    // правки самих панелей, поэтому пока остаётся в Эксплуатации (см. docs/SPACE.md).
    code: 'finance', route: '/finance', label: 'Финансы',
    modes: ['accounting', 'financial', 'tax', 'export'],
    paths: ['/files', '/contractors', '/1c/connection', '/1c/sync', '/1c/references',
      '/1c/documents', '/1c/periods', '/1c/policy', '/1c/posting-templates', '/1c/prices',
      '/1c/batches', '/1c/fuel-mappings', '/1c/mappings', '/1c/export'],
  },
  {
    // Данные — служебная кухня: откуда берутся цифры и как приводятся к общему виду.
    // Ошибка здесь ломает все продукты сразу, поэтому доступ отдельный и узкий.
    code: 'data', route: '/data', label: 'Данные',
    modes: ['normalize', 'reconcile'],
    paths: ['/intake', '/connectors', '/sources', '/normalization', '/reconciliation', '/settings'],
  },
]

/** Профиль компании, для которого разрез включён. */
const CARVED_PROFILE = 'energy'

export function isCarvedProfile(profileId: string | null | undefined): boolean {
  return profileId === CARVED_PROFILE
}

/** Продукт по маршруту или странице (`/finance`, `/files`, `/1c/export`). */
export function productForPath(pathname: string): SpaceProduct | null {
  for (const p of SPACE_PRODUCTS) {
    if (pathname === p.route || pathname.startsWith(`${p.route}/`)) return p
    if (p.paths.some((path) => pathname === path || pathname.startsWith(`${path}/`))) return p
  }
  return null
}

/** Пункты левого меню продукта (в порядке `paths`). */
export function productNav(product: SpaceProduct): NavItemDef[] {
  return product.paths.map((path) => navByPath[path]).filter(Boolean)
}

/** Разделы, ушедшие из Учёта в отдельные продукты (при выключенном разрезе — пусто). */
export function carvedModes(profileId: string | null | undefined): Set<CoreMode> {
  if (!isCarvedProfile(profileId)) return new Set()
  return new Set(SPACE_PRODUCTS.flatMap((p) => p.modes))
}

/**
 * Пускать ли на путь. Страница продукта проверяется доступом к ПРОДУКТУ, а не к модулям
 * Учёта: у того, кому роль дала «Финансы», ключа `ledger:documents` нет, и старая проверка
 * закрыла бы ему собственные «Документы». Всё остальное — по-прежнему модулями Учёта.
 */
export function pathAllowed(
  pathname: string,
  profileId: string | null | undefined,
  canApp: (code: string) => boolean,
  fallback: (pathname: string) => boolean,
): boolean {
  if (isCarvedProfile(profileId)) {
    const product = productForPath(pathname)
    if (product) return canApp(product.code)
  }
  return fallback(pathname)
}

/** Куда возвращать при отказе: у разрезанного профиля рабочий стол пространства. */
export function homePath(profileId: string | null | undefined): string {
  return isCarvedProfile(profileId) ? '/' : '/workspace'
}
