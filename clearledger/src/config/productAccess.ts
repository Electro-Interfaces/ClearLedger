/**
 * Карта прав внутри продуктов пространства: что можно выдать ролью НИЖЕ уровня продукта.
 *
 * Раньше доступ был двухуровневым: продукт целиком (`sales`) или ничего. Для рабочего
 * места это грубо: подрядчику нужен «Реестр сессий», но не «Тарифы»; бухгалтеру —
 * «Документы», но не «Коннекторы». Здесь описано, из каких пунктов состоит каждый
 * продукт, и эти же коды становятся ключами прав `<продукт>:<пункт>`.
 *
 * **Коды берутся из тех же списков, которыми рисуется меню** (`config/workspaceMenus.ts`,
 * `config/navigation.ts`) — карта прав не может разъехаться с интерфейсом, потому что
 * это один массив, а не его копия.
 *
 * Гранулярность — пункт меню продукта, не глубже: внутренние вкладки панели («Сессии»
 * с табами разрезов) закрывать нечем и незачем, право на них = право на пункт.
 *
 * ⚠ Гейт клиентский, как и вход в продукт (`RequireApp`): серверные ручки ключами
 * продуктов не проверяются. Это защита от «увидел лишнее», а не от целенаправленного
 * запроса к API — тот же уровень, что был у разделов Учёта.
 */
import { navByPath } from './navigation'
import {
  ENERGY_MGMT, EQUIPMENT_MENU, OPS_MONITOR_MENU, SITES_MENU,
  SALES_NETWORK_MENU, SALES_SESSIONS_MENU, SALES_COMMERCE_MENU, MARKET_MENU,
} from './workspaceMenus'
import { STORE_MENU } from './storeCatalog'
import { SPACE_PAGES, SPACE_PRODUCTS, pageCode } from './spaceProducts'

export interface ProductModuleDef {
  /** Код права: ключ роли — `<продукт>:<код>`. */
  code: string
  label: string
  /** Группа в матрице доступа (заголовок над строками). */
  group: string
}

/** Страницы продукта как модули доступа: код = сегмент пути (`/files` → `files`). */
export const pageModuleCode = pageCode

function pages(paths: string[]): ProductModuleDef[] {
  return paths
    .filter((p) => navByPath[p])
    .map((p) => ({ code: pageModuleCode(p), label: navByPath[p].label, group: 'Страницы' }))
}

/** Пункты меню раздела → модули доступа (группа из самого пункта или общая). */
function items(list: { key: string; label: string; group?: string }[], group?: string): ProductModuleDef[] {
  return list.map((i) => ({ code: i.key, label: i.label, group: group ?? i.group ?? 'Разделы' }))
}

/**
 * Состав продуктов в правах. Ключ — код продукта в реестре Ядра (`eco_apps.code`).
 *
 * «Продажи» описаны без топливного меню (MGMT_MENU): разрез включён только профилю
 * `energy`, у которого этих разделов нет. Появится топливный разрез — состав дополнится
 * здесь же.
 */
export const PRODUCT_MODULES: Record<string, ProductModuleDef[]> = {
  projects: items(SITES_MENU),
  // Группы матрицы = разделы продукта: строка права стоит там же, где пункт в меню.
  ops: [
    ...items(OPS_MONITOR_MENU, 'Мониторинг'),
    ...items(EQUIPMENT_MENU, 'Оборудование'),
    ...items(ENERGY_MGMT, 'Хозяйство'),
  ],
  // Коммерция (тарифы, ЮЛ, ФЛ), сегментация и веб-аналитика вернулись в «Продажи»
  // (28.07.2026). «Корпоративного процессинга» и «Маркетинга» в карте прав нет: пока
  // это заставка «в подключении», право выдаётся на продукт целиком.
  // Группы матрицы = разделы продукта: строка права стоит там же, где пункт в меню.
  sales: [
    ...items(SALES_NETWORK_MENU, 'Сеть'),
    ...items(SALES_SESSIONS_MENU, 'Сессии'),
    ...items(SALES_COMMERCE_MENU, 'Коммерция'),
    ...pages(['/metrika']),
  ],
  shop: items(STORE_MENU),
  marketing: items(MARKET_MENU, 'Рынок'),
  finance: [
    // «Финансовый» и «Налоговый» сняты с витрины (workspaceSections) — прав на них нет:
    // роль не должна раздавать доступ к разделу, которого в интерфейсе не существует.
    { code: 'accounting', label: 'Бухгалтерский', group: 'Разделы' },
    { code: 'export', label: 'Выгрузка', group: 'Разделы' },
    ...pages(['/organization']),
  ],
  data: [
    { code: 'normalize', label: 'Нормализация', group: 'Разделы' },
    { code: 'reconcile', label: 'Сверка', group: 'Разделы' },
    ...pages(['/connectors', '/catalog']),
  ],
}

/**
 * Функции Ядра есть в каждом рабочем месте, поэтому и право на них — у каждого продукта
 * (`sales:files`): один и тот же экран, но роль может закрыть его продавцу и оставить
 * бухгалтеру. Перечислять их в составе каждого продукта руками не нужно — блок общий,
 * как и сам пункт меню (`spaceProducts.SPACE_PAGES`).
 */
const SPACE_MODULES: ProductModuleDef[] = pages(SPACE_PAGES).map(
  (m) => ({ ...m, group: 'Пространство' }))

/** Модули продукта для матрицы доступа (пусто — продукт даётся целиком). */
export function productModules(code: string): ProductModuleDef[] {
  const own = PRODUCT_MODULES[code]
  return own ? [...own, ...SPACE_MODULES] : []
}

/** Есть ли у продукта разбиение на модули (иначе право = продукт целиком). */
export const hasProductModules = (code: string) => (PRODUCT_MODULES[code]?.length ?? 0) > 0

/**
 * Есть ли у продукта такой модуль в карте прав.
 *
 * Разделы рабочей области (`mode`) модулями бывают НЕ всегда: у «Финансов» и «Данных»
 * пункт меню и есть раздел (`accounting`, `normalize`), а у «Продаж» и «Проектов»
 * правами гейтятся пункты ВНУТРИ разделов, а сами разделы кода в карте не имеют.
 * Спрашивать право на такой раздел бессмысленно — ответ всегда «нет», и рельс прятал
 * разделы у всех, кому роль дала не весь продукт, а его пункты.
 */
export const productHasModule = (appCode: string, moduleCode: string) =>
  (PRODUCT_MODULES[appCode] ?? []).some((m) => m.code === moduleCode)

/**
 * Пускать ли на пункт `moduleCode` продукта `appCode`.
 *
 * Правило «отсутствие ограничения = полный доступ»: если роль дала продукт целиком
 * (`sales`) или перечислила только пункты ДРУГИХ продуктов, внутри продукта видно всё.
 * Ограничение включается ровно тогда, когда роль перечислила пункты ЭТОГО продукта —
 * иначе выдача роли `sales` закрыла бы человеку весь продукт, который ему и дали.
 */
export function productModuleAllowed(
  appCode: string,
  moduleCode: string,
  canModule: (app: string, module: string) => boolean,
): boolean {
  if (!hasProductModules(appCode)) return true
  return canModule(appCode, moduleCode)
}

/** Продукт, которому принадлежит раздел рабочей области (`mode`), если он выделен. */
export function productForMode(mode: string): string | null {
  return SPACE_PRODUCTS.find((p) => (p.modes as string[]).includes(mode))?.code ?? null
}
