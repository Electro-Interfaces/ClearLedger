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
 * **Объект — сквозной, а не собственность одного продукта.** «Объекты» стоят в меню
 * каждого продукта, которому они по делу нужны (эксплуатация чинит, продажи считают
 * выручку, финансы держат аренду и документы) — это один и тот же реестр пространства,
 * открытый под своим углом, а не копия справочника.
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
  /**
   * Вкладки карточки станции, которые открывает этот продукт (коды `COCKPIT_TABS`).
   * Станция — ось бизнеса: её ведут все рабочие места сразу, но каждому нужна своя
   * сторона — эксплуатации железо и связь, продажам выручка, финансам договоры и
   * снабжение, данным подключённые источники. Пусто = все вкладки (профиль без разреза).
   */
  objectTabs?: string[]
}

export const SPACE_PRODUCTS: SpaceProduct[] = [
  {
    // Проекты — стройка сети. Действующие станции здесь для СПРАВКИ: чем оснащена
    // соседняя площадка, что там с подключением, введена ли она — это ответ на вопрос
    // «как делали в прошлый раз» при подборе и проектировании новой. Договоров и
    // выручки в этом окне нет: продажами и деньгами занимаются другие рабочие места.
    code: 'projects', route: '/projects', label: 'Проекты',
    modes: ['projects'], paths: ['/objects'],
    objectTabs: ['passport', 'equipment', 'integrations'],
  },
  {
    // Эксплуатация — железо и его состояние: мониторинг сети, парк, склады, ЗИП.
    code: 'ops', route: '/operations', label: 'Эксплуатация',
    modes: ['operations'], paths: ['/objects'],
    objectTabs: ['passport', 'equipment', 'integrations', 'diagnostics'],
  },
  {
    // Продажи — коммерческая сторона: сессии, тарифы, ЮЛ/ФЛ, ABC-XYZ, маркетинг.
    // Не «Сеть»: продукт называется по тому, ЧТО здесь делают, а не чем владеют —
    // и «Сеть» уже занята группой разделов внутри (обзор, карта, динамика).
    // Не «Реализация»: это термин бухучёта, ему место в Финансах.
    code: 'sales', route: '/sales', label: 'Продажи',
    modes: ['management'], paths: ['/objects'],
    objectTabs: ['passport', 'contracts', 'sales'],
  },
  {
    // Корпоративный процессинг — работа с юрлицами: тарифные планы, договоры, лимиты,
    // разбор частных клиентов рядом. Отдельное рабочее место: этим занимаются не те,
    // кто смотрит загрузку сети (решение МАГа 27.07.2026).
    code: 'corp', route: '/corporate', label: 'Корпоративный процессинг',
    modes: ['corporate'], paths: ['/objects', '/contractors'],
    objectTabs: ['passport', 'contracts', 'sales'],
  },
  {
    // Интернет-магазин — товарный контур на объектах: витрина, номенклатура, заказы.
    code: 'shop', route: '/shop', label: 'Интернет-магазин',
    modes: ['store'], paths: ['/objects'],
    objectTabs: ['passport', 'sales'],
  },
  {
    // Маркетинг — поведение клиентов и сегментация сети: ABC-XYZ, динамика, веб-аналитика.
    code: 'marketing', route: '/marketing', label: 'Маркетинг',
    modes: ['marketing'], paths: ['/objects', '/metrika'],
    objectTabs: ['passport', 'sales'],
  },
  {
    // Финансы — счётная сторона: проводки, налоги, выгрузка, первичка, контрагенты
    // и паспорт своего юрлица («Организация»: реквизиты, счета, ответственные лица).
    // NB: «Хозяйство» площадок (энергозакупка, аренда) по смыслу денежное, но живёт
    // под-разделами режима `operations` и рисуется его панелью — переезд сюда требует
    // правки самих панелей, поэтому пока остаётся в Эксплуатации (см. docs/SPACE.md).
    // Страниц контура 1С здесь нет: разрез включён профилю `energy`, а у него 1С
    // отключён (`RequireFuel`), и пункты вели бы в редирект. Вернутся вместе с
    // разрезом для топливного профиля.
    code: 'finance', route: '/finance', label: 'Финансы',
    modes: ['accounting', 'financial', 'tax', 'export'],
    paths: ['/objects', '/files', '/contractors', '/organization'],
    objectTabs: ['passport', 'contracts', 'sales', 'supply'],
  },
  {
    // Данные — служебная кухня: откуда берутся цифры и как приводятся к общему виду.
    // Ошибка здесь ломает все продукты сразу, поэтому доступ отдельный и узкий.
    // «Каталоги» — библиотека типов источников, каналов и разрезов сверки, то есть
    // тот же входной контур; «Параметры» — его настройки.
    // Станция здесь — ключ связи каналов: к ней привязываются источники, по ней
    // сходятся сессии и сверка. Нужны паспорт и подключённые интеграции.
    code: 'data', route: '/data', label: 'Данные',
    modes: ['normalize', 'reconcile'],
    paths: ['/objects', '/intake', '/connectors', '/sources', '/normalization',
      '/reconciliation', '/catalog', '/settings'],
    objectTabs: ['passport', 'integrations', 'diagnostics'],
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

/**
 * Страницы продукта для левого меню (в порядке `paths`).
 *
 * Пункта «Рабочий стол» здесь нет: рабочий стол — уровнем выше, у пространства.
 * Верхний уровень внутри продукта — его собственные разделы («Продажи», «Магазин»);
 * их подставляет `AppSidebar` из фактических секций рабочей области, а под-разделы
 * этой области остаются в гармошке `WorkspaceModeSidebar`.
 */
export function productNav(product: SpaceProduct): NavItemDef[] {
  return product.paths.map((path) => navByPath[path]).filter(Boolean)
    .map((item) => ({ ...item, to: productPagePath(product, item.to) }))
}

/**
 * Страницы, которые открыты СРАЗУ НЕСКОЛЬКИМ продуктам. У таких адрес живёт внутри
 * продукта (`/finance/objects`), иначе по пути `/objects` не понять, из какого
 * рабочего места человек смотрит станцию — а от этого зависят и права, и состав
 * карточки, и название в шапке.
 */
export const SHARED_PATHS = ['/objects']

export function productPagePath(product: SpaceProduct, path: string): string {
  return SHARED_PATHS.includes(path) ? `${product.route}${path}` : path
}

/** Продукты, которым открыта сквозная страница (для маршрутов в `App.tsx`). */
export function productsWithPath(path: string): SpaceProduct[] {
  return SPACE_PRODUCTS.filter((p) => p.paths.includes(path))
}

/** Вкладки карточки станции для продукта; вне разреза — все (undefined). */
export function objectTabsFor(pathname: string, profileId: string | null | undefined): string[] | undefined {
  if (!isCarvedProfile(profileId)) return undefined
  return productForPath(pathname)?.objectTabs
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
