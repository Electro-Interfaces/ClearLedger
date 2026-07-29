/**
 * Закреплённые вкладки-закладки рабочей области (keep-alive, «как в 1С»).
 *
 * Модель — РУЧНАЯ: переход по меню НЕ создаёт вкладку. Пользователь сам
 * закрепляет текущий вид кнопкой «Закрепить» (пин). Список = осознанные
 * закладки, к которым можно вернуться без переформатирования (keep-alive
 * в `components/layout/KeepAliveOutlet.tsx`).
 *
 * Ключ закладки = полный URL (pathname + search), поэтому под-виды рабочего
 * стола («Дебиторка», «Операции», mode/sub в URL) — это разные
 * закладки. Активная вкладка выводится из текущего URL.
 *
 * Персист per-company в localStorage (модель `FilterContext`).
 */
import {
  createContext, useCallback, useContext, useMemo, useState,
  type ReactNode,
} from 'react'
import { useCompany } from './CompanyContext'
import { getItem, setItem } from '@/services/storage'
import { describeView, type ViewDescriptor } from '@/config/tabRegistry'

const HOME = '/'
const MAX_TABS = 12
const storageKey = (companyId: string) => `tl-tabs-${companyId}`
const HOME_TAB: TabDescriptor = {
  key: HOME,
  pathname: HOME,
  title: 'Рабочий стол',
  closable: false,
}

export interface TabDescriptor {
  key: string        // полный URL (pathname + search)
  pathname: string   // ключ keep-alive инстанса
  title: string
  closable: boolean
}

interface TabsContextType {
  tabs: TabDescriptor[]
  /** Закрепить текущий вид во вкладку (idempotent). */
  pinTab: (view: ViewDescriptor) => 'pinned' | 'exists' | 'limit'
  /** Открепить/закрыть вкладку; возвращает URL соседа для перехода. */
  closeTab: (key: string) => string
  /** Закреплён ли вид с таким ключом. */
  isPinned: (key: string) => boolean
}

const TabsContext = createContext<TabsContextType | null>(null)

function loadTabs(companyId: string, profileId?: string | null): TabDescriptor[] {
  if (!companyId || companyId === '_') return [HOME_TAB]
  const raw = getItem<unknown>(storageKey(companyId), [])
  const persisted = Array.isArray(raw) ? (raw as Partial<TabDescriptor>[]) : []
  const list: TabDescriptor[] = [HOME_TAB]
  const seen = new Set([HOME])
  for (const t of persisted) {
    if (!t || typeof t.key !== 'string' || t.key === HOME || seen.has(t.key)) continue
    const pathname = typeof t.pathname === 'string' ? t.pathname : t.key.split('?')[0]
    const search = t.key.startsWith(pathname) ? t.key.slice(pathname.length) : ''
    const view = describeView(pathname, search, profileId)
    if (!view) continue
    seen.add(view.key)
    list.push({ ...view, closable: true })
    if (list.length >= MAX_TABS) break
  }
  return list
}

function persistTabs(companyId: string, tabs: TabDescriptor[]) {
  if (!companyId || companyId === '_') return
  setItem(storageKey(companyId), tabs)
}

export function TabsProvider({ children }: { children: ReactNode }) {
  const { companyId, company } = useCompany()
  const [tabs, setTabs] = useState(() => loadTabs(companyId, company.profileId))

  const pinTab = useCallback((view: ViewDescriptor) => {
    if (tabs.some((tab) => tab.key === view.key)) return 'exists'
    if (tabs.length >= MAX_TABS) return 'limit'
    const next = [...tabs, { ...view, closable: view.key !== HOME }]
    setTabs(next)
    persistTabs(companyId, next)
    return 'pinned'
  }, [companyId, tabs])

  const closeTab = useCallback((key: string): string => {
    const idx = tabs.findIndex((t) => t.key === key)
    if (idx < 0 || key === HOME) return HOME
    const next = tabs.filter((t) => t.key !== key)
    setTabs(next)
    persistTabs(companyId, next)
    return (next[idx] ?? next[idx - 1] ?? { key: HOME }).key
  }, [companyId, tabs])

  const isPinned = useCallback((key: string) => tabs.some((t) => t.key === key), [tabs])

  const value = useMemo<TabsContextType>(
    () => ({ tabs, pinTab, closeTab, isPinned }),
    [tabs, pinTab, closeTab, isPinned],
  )

  return <TabsContext.Provider value={value}>{children}</TabsContext.Provider>
}

export function useTabs() {
  const ctx = useContext(TabsContext)
  if (!ctx) throw new Error('useTabs must be used within TabsProvider')
  return ctx
}
