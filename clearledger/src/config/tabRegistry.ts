/**
 * Реестр вкладок рабочей области: pathname → метаданные вкладки.
 *
 * Статические пути берутся из `config/navigation.ts`; динамика (`/channels/:id`)
 * матчится через `matchPath`. `workspace` — нужен ли полноэкранный режим без
 * скролла страницы (как раньше решала `MainLayout.isWorkspace`).
 */
import { matchPath } from 'react-router-dom'
import { Radio } from 'lucide-react'
import type { ComponentType } from 'react'
import {
  mainNavItems, dataItems, oneCItems, settingsItems, adminItem,
  type NavItemDef,
} from './navigation'
import { isCoreMode, workspaceTitle } from './workspaceViews'

// Пути с фиксированной высотой (h-full, без скролла страницы).
const WORKSPACE_PATHS = new Set(['/', '/files', '/reconciliation', '/normalization'])

// Fuel-only разделы (для energy-профиля скрыты; RequireFuel редиректит на `/`).
const FUEL_ONLY = new Set<string>(oneCItems.map((i) => i.to))

// Плоская карта статических путей → пункт меню.
const STATIC: Record<string, NavItemDef> = {}
for (const it of [...mainNavItems, ...dataItems, ...oneCItems, ...settingsItems, adminItem]) {
  STATIC[it.to] = it
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
      closable: pathname !== '/',
    }
  }
  // Динамика: детальная страница канала.
  const ch = matchPath('/channels/:id', pathname)
  if (ch) {
    return {
      key: pathname,
      title: `Канал #${ch.params.id}`,
      icon: Radio,
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
 * Описать ТЕКУЩИЙ вид для закрепления во вкладку. Для «Рабочего стола» включает
 * режим/под-раздел из URL («Рабочий стол · Финансовый · Дебиторка»).
 * null — вид не закрепляется (напр. 404).
 */
export function describeView(pathname: string, search: string): ViewDescriptor | null {
  if (pathname === '/') {
    const sp = new URLSearchParams(search)
    const modeRaw = sp.get('mode')
    // Плоский рабочий стол без режима — просто «Рабочий стол».
    const title = modeRaw
      ? workspaceTitle(isCoreMode(modeRaw) ? modeRaw : 'management', sp.get('sub'))
      : 'Рабочий стол'
    return { key: pathname + search, pathname, title }
  }
  const resolved = resolveTab(pathname)
  if (!resolved) return null
  return { key: pathname + search, pathname, title: resolved.title }
}
