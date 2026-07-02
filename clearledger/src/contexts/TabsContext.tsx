/**
 * Закреплённые вкладки-закладки рабочей области (keep-alive, «как в 1С»).
 *
 * Модель — РУЧНАЯ: переход по меню НЕ создаёт вкладку. Пользователь сам
 * закрепляет текущий вид кнопкой «Закрепить» (пин). Список = осознанные
 * закладки, к которым можно вернуться без переформатирования (keep-alive
 * в `components/layout/KeepAliveOutlet.tsx`).
 *
 * Ключ закладки = полный URL (pathname + search), поэтому под-виды рабочего
 * стола («Рабочий стол · Финансовый · Дебиторка», mode/sub в URL) — это разные
 * закладки. Активная вкладка выводится из текущего URL.
 *
 * Персист per-company в localStorage (модель `FilterContext`).
 */
import {
  createContext, useCallback, useContext, useEffect, useMemo, useState,
  type ReactNode,
} from 'react'
import { useCompany } from './CompanyContext'
import { getItem, setItem } from '@/services/storage'
import type { ViewDescriptor } from '@/config/tabRegistry'

const HOME = '/'
const storageKey = (companyId: string) => `tl-tabs-${companyId}`

export interface TabDescriptor {
  key: string        // полный URL (pathname + search)
  pathname: string   // ключ keep-alive инстанса
  title: string
  closable: boolean
}

interface TabsContextType {
  tabs: TabDescriptor[]
  /** Закрепить текущий вид во вкладку (idempotent). */
  pinTab: (view: ViewDescriptor) => void
  /** Открепить/закрыть вкладку; возвращает URL соседа для перехода. */
  closeTab: (key: string) => string
  /** Закреплён ли вид с таким ключом. */
  isPinned: (key: string) => boolean
}

const TabsContext = createContext<TabsContextType | null>(null)

function loadTabs(companyId: string): TabDescriptor[] {
  // Защита от старого/повреждённого формата (раньше хранился объект {keys:[...]}).
  const raw = getItem<unknown>(storageKey(companyId), [])
  const persisted = Array.isArray(raw) ? (raw as Partial<TabDescriptor>[]) : []
  const list: TabDescriptor[] = []
  for (const t of persisted) {
    if (!t || typeof t.key !== 'string') continue
    list.push({ key: t.key, pathname: t.pathname ?? t.key, title: t.title ?? t.key, closable: true })
  }
  return list
}

export function TabsProvider({ children }: { children: ReactNode }) {
  const { companyId } = useCompany()
  const [tabs, setTabs] = useState<TabDescriptor[]>(() => loadTabs(companyId))

  // Смена компании → загрузить её набор закладок.
  useEffect(() => { setTabs(loadTabs(companyId)) }, [companyId])

  // Персист всех закреплённых вкладок.
  useEffect(() => {
    setItem(storageKey(companyId), tabs)
  }, [companyId, tabs])

  const pinTab = useCallback((view: ViewDescriptor) => {
    setTabs((prev) => {
      if (prev.some((t) => t.key === view.key)) return prev
      return [...prev, { key: view.key, pathname: view.pathname, title: view.title, closable: true }]
    })
  }, [])

  const closeTab = useCallback((key: string): string => {
    const idx = tabs.findIndex((t) => t.key === key)
    if (idx < 0) return HOME
    const next = tabs.filter((t) => t.key !== key)
    setTabs(next)
    // Сосед справа/слева, иначе — на рабочий стол.
    return (next[idx] ?? next[idx - 1] ?? { key: HOME }).key
  }, [tabs])

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
