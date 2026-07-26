/**
 * Реестр вкладок рабочей области: pathname → метаданные вкладки.
 *
 * Статические пути берутся из `config/navigation.ts`; динамика (`/channels/:id`)
 * матчится через `matchPath`. `workspace` — нужен ли полноэкранный режим без
 * скролла страницы (как раньше решала `MainLayout.isWorkspace`).
 */
import { matchPath } from 'react-router-dom'
import { Plug, HardHat, Gauge, BarChart3, Wallet, Database, LayoutDashboard } from 'lucide-react'
import { SPACE_PRODUCTS } from './spaceProducts'
import type { ComponentType } from 'react'
import {
  mainNavItems, dataItems, oneCItems, settingsItems,
  type NavItemDef,
} from './navigation'
import { isCoreMode, workspaceTitle } from './workspaceViews'

// Иконки продуктов пространства для вкладок (плитки берут свою из реестра Ядра).
const PRODUCT_ICONS: Record<string, ComponentType<{ className?: string }>> = {
  projects: HardHat, ops: Gauge, network: BarChart3, finance: Wallet, data: Database,
}

// Пути с фиксированной высотой (h-full, без скролла страницы): рабочая область Учёта,
// маршруты продуктов пространства и полноэкранные страницы.
const WORKSPACE_PATHS = new Set<string>([
  '/workspace', '/files', '/reconciliation', '/normalization',
  ...SPACE_PRODUCTS.map((p) => p.route),
])

// Fuel-only разделы (для energy-профиля скрыты; RequireFuel редиректит на `/workspace`).
const FUEL_ONLY = new Set<string>(oneCItems.map((i) => i.to))

// Плоская карта статических путей → пункт меню.
const STATIC: Record<string, NavItemDef> = {}
for (const it of [...mainNavItems, ...dataItems, ...oneCItems, ...settingsItems]) {
  STATIC[it.to] = it
}
// Продукты пространства: в меню Учёта их нет (открываются плиткой со стола), но вкладка
// и полноэкранная раскладка нужны такие же, как рабочей области.
for (const p of SPACE_PRODUCTS) {
  STATIC[p.route] = { to: p.route, icon: PRODUCT_ICONS[p.code] ?? LayoutDashboard, label: p.label }
}

export interface ResolvedTab {
  key: string            // = pathname
  title: string
  icon: ComponentType<{ className?: string }>
  workspace: boolean
  fuelOnly: boolean
  closable: boolean      // «Рабочий стол» (/) незакрываем
}

/** Метаданные вкладки для пути, либо null если путь не табуется (напр. 404). */
export function resolveTab(pathname: string): ResolvedTab | null {
  const stat = STATIC[pathname]
  if (stat) {
    return {
      key: pathname,
      title: stat.label,
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
export function describeView(pathname: string, search: string): ViewDescriptor | null {
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
  const resolved = resolveTab(pathname)
  if (!resolved) return null
  return { key: pathname + search, pathname, title: resolved.title }
}
