/**
 * Реестр вкладок рабочей области: pathname → метаданные вкладки.
 *
 * Статические пути берутся из `config/navigation.ts`; динамика (`/channels/:id`)
 * матчится через `matchPath`. `workspace` — нужен ли полноэкранный режим без
 * скролла страницы (как раньше решала `MainLayout.isWorkspace`).
 */
import { matchPath } from 'react-router-dom'
import { Plug, HardHat, Gauge, BarChart3, Wallet, Database, LayoutDashboard, Building2, ShoppingCart, Megaphone, Activity, ListChecks } from 'lucide-react'
import { SPACE_PRODUCTS, SPACE_PAGES, productLabel } from './spaceProducts'
import type { ComponentType } from 'react'
import {
  mainNavItems, dataItems, oneCItems, settingsItems,
  type NavItemDef,
} from './navigation'
import { isCoreMode, workspaceTitle } from './workspaceViews'

// Иконки продуктов пространства для вкладок (плитки берут свою из реестра Ядра).
const PRODUCT_ICONS: Record<string, ComponentType<{ className?: string }>> = {
  projects: HardHat, ops: Gauge, sales: BarChart3, corp: Building2, shop: ShoppingCart,
  marketing: Megaphone, finance: Wallet, data: Database,
}

// Пути с фиксированной высотой (h-full, без скролла страницы): рабочая область Учёта,
// маршруты продуктов пространства и полноэкранные страницы.
const WORKSPACE_PATHS = new Set<string>([
  '/workspace', '/files', '/reconciliation', '/normalization',
  // «Пульс» — такое же рабочее место, как продукты разреза: своя вторая колонка и
  // свой скролл внутри. Без этих путей внешняя обёртка добавляла ему второй паддинг
  // и второй `overflow-y-auto` поверх собственных — на 320 px до первой буквы
  // уходило 56 px, а колонка пунктов не прилегала к рельсе, как в «Продажах».
  '/pulse', '/pulse/business', '/pulse/team', '/pulse/week',
  // «Задачи» — приложение Ядра со своей второй колонкой и своим скроллом внутри
  // (docs/TASKS.md). В `SPACE_PRODUCTS` их нет — это продукты разреза, — поэтому
  // пути перечислены руками. Без них `KeepAliveOutlet` кладёт поверх собственной
  // раскладки второй паддинг и второй `overflow-y-auto`.
  '/tasks', '/tasks/company', '/tasks/overview', '/tasks/setup',
  // «Аудитор» — две колонки со своим скроллом внутри: разговор и каталог навыков.
  '/auditor',
  ...SPACE_PRODUCTS.map((p) => p.route),
  // Та же страница под адресом продукта (`/finance/files`) — и раскладка та же.
  ...SPACE_PRODUCTS.map((p) => `${p.route}/files`),
])

// Fuel-only разделы (для energy-профиля скрыты; RequireFuel редиректит на `/workspace`).
const FUEL_ONLY = new Set<string>(oneCItems.map((i) => i.to))

// Плоская карта статических путей → пункт меню.
const STATIC: Record<string, NavItemDef> = {}
for (const it of [...mainNavItems, ...dataItems, ...oneCItems, ...settingsItems]) {
  STATIC[it.to] = it
}
// «Пульс» — рабочее место руководителя: его разделы табуются как обычные экраны,
// чтобы директор мог закрепить «Экран дня» и возвращаться к нему одним кликом.
for (const [to, label] of [['/pulse', 'Пульс'], ['/pulse/business', 'Бизнес'],
  ['/pulse/team', 'Команда'], ['/pulse/week', 'Неделя']] as const) {
  STATIC[to] = { to, icon: Activity, label }
}

// «Трек» — документооборот и работа компании: вкладка нужна, чтобы реестр и свою
// работу можно было закрепить и возвращаться одним кликом. Разделы табуются как
// обычные экраны — человек закрепляет «Реестры» и «Поручения» рядом.
for (const [to, label] of [['/docs', 'Трек'], ['/docs/company', 'Компания'],
  ['/docs/work', 'На мне'], ['/docs/setup', 'Настройка «Трека»']] as const) {
  STATIC[to] = { to, icon: ListChecks, label }
}

// Продукты пространства: в меню Учёта их нет (открываются плиткой со стола), но вкладка
// и полноэкранная раскладка нужны такие же, как рабочей области.
for (const p of SPACE_PRODUCTS) {
  STATIC[p.route] = { to: p.route, icon: PRODUCT_ICONS[p.code] ?? LayoutDashboard, label: p.label }
  // Страницы Ядра живут под адресом продукта — вкладка нужна и им, иначе экран,
  // открытый из «Финансов», не попадёт ни в закладки, ни в keep-alive.
  for (const path of SPACE_PAGES) {
    const item = STATIC[path]
    if (item) STATIC[`${p.route}${path}`] = { ...item, to: `${p.route}${path}` }
  }
}

export interface ResolvedTab {
  key: string            // = pathname
  title: string
  icon: ComponentType<{ className?: string }>
  workspace: boolean
  fuelOnly: boolean
  closable: boolean      // «Рабочий стол» (/) незакрываем
}

/**
 * Метаданные вкладки для пути, либо null если путь не табуется (напр. 404).
 *
 * `profileId` нужен только имени продукта: у розницы нефтепродуктов «Продажи» зовутся
 * «Топливо», и вкладка обязана называться так же, как шапка и плитка на столе.
 */
export function resolveTab(pathname: string, profileId?: string | null): ResolvedTab | null {
  const stat = STATIC[pathname]
  if (stat) {
    const product = SPACE_PRODUCTS.find((p) => p.route === pathname)
    return {
      key: pathname,
      title: product ? productLabel(product, profileId) : stat.label,
      icon: stat.icon,
      workspace: WORKSPACE_PATHS.has(pathname),
      fuelOnly: FUEL_ONLY.has(pathname),
      closable: pathname !== '/workspace',
    }
  }
  // Динамика: детальная страница коннектора.
  const ch = matchPath('/connectors/:id', pathname)
  if (ch) {
    return {
      key: pathname,
      title: `Коннектор #${ch.params.id}`,
      icon: Plug,
      workspace: false,
      fuelOnly: false,
      closable: true,
    }
  }
  return null
}

/** Нужен ли полноэкранный режим (h-full) для пути. Используется мобильной веткой MainLayout. */
export function isWorkspacePath(pathname: string): boolean {
  return WORKSPACE_PATHS.has(pathname)
}

export interface ViewDescriptor {
  key: string        // полный URL (pathname + search) — идентификатор закладки
  pathname: string   // ключ keep-alive инстанса (одна страница на pathname)
  title: string
}

/**
 * Описать ТЕКУЩИЙ вид для закрепления во вкладку. Для «Рабочего стола» берёт
 * короткое имя активного пункта меню («Операции», «Карта», «Дебиторка»).
 * null — вид не закрепляется (напр. 404).
 */
export function describeView(
  pathname: string, search: string, profileId?: string | null,
): ViewDescriptor | null {
  if (pathname === '/') {
    const sp = new URLSearchParams(search)
    const modeRaw = sp.get('mode')
    const sub = sp.get('sub')
    // Плоский рабочий стол без режима — просто «Рабочий стол».
    const title = modeRaw || sub
      ? workspaceTitle(isCoreMode(modeRaw) ? modeRaw : 'management', sub)
      : 'Рабочий стол'
    return { key: pathname + search, pathname, title }
  }
  const resolved = resolveTab(pathname, profileId)
  if (!resolved) return null
  return { key: pathname + search, pathname, title: resolved.title }
}
