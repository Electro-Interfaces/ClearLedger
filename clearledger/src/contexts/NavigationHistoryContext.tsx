import { useEffect, useLayoutEffect, useState, type ReactNode } from 'react'
import { useLocation, useNavigationType } from 'react-router-dom'
import {
  advanceNavigationHistory, startNavigationHistory, NavigationViewStore,
  type NavigationHistory,
} from '@/lib/navigationHistory'
import { NavigationHistoryContext } from './navigationHistoryContextValue'

function readSession<T>(key: string | null): T | undefined {
  if (!key) return
  try {
    return JSON.parse(sessionStorage.getItem(key) ?? 'null', (_name, value) =>
      value?.navigationSet instanceof Array ? new Set(value.navigationSet) : value) ?? undefined
  } catch { return undefined }
}

function saveSession(key: string | null, value: unknown) {
  if (!key) return
  try {
    sessionStorage.setItem(key, JSON.stringify(value, (_name, item) =>
      item instanceof Set ? { navigationSet: [...item] } : item))
  } catch { /* Недоступное хранилище не мешает возврату в памяти приложения. */ }
}

/** Монтируется внутри границы компании; новая компания получает отдельную историю. */
export function NavigationHistoryProvider({ children, scope }: { children: ReactNode; scope: string }) {
  const { key } = useLocation()
  const action = useNavigationType()
  const native = window.history.state as { key?: string; idx?: number } | null
  const position = (native?.key ?? 'default') === key ? native?.idx : undefined
  const historyKey = scope ? `cl-navigation-history:${scope}` : null
  const viewsKey = scope ? `cl-navigation-views:${scope}` : null
  const [history, setHistory] = useState(() => {
    const saved = readSession<NavigationHistory>(historyKey)
    const valid = saved && Array.isArray(saved.entries) && Number.isInteger(saved.index)
      && saved.index >= 0 && saved.index < saved.entries.length
      && saved.entries.every((entry) => typeof entry.key === 'string' && typeof entry.id === 'string'
        && Array.isArray(entry.aliases) && Number.isInteger(entry.position))
    return valid ? advanceNavigationHistory(saved, key, action, position) : startNavigationHistory(key, position)
  })
  const [views] = useState(() => {
    const saved = readSession<[string, unknown][]>(viewsKey)
    const entries = Array.isArray(saved) ? saved.filter((row) => Array.isArray(row) && typeof row[0] === 'string') : []
    return new NavigationViewStore(entries, (next) => saveSession(viewsKey, next))
  })
  const current = advanceNavigationHistory(history, key, action, position)
  // Согласовать идентификатор записи до рендера страницы: REPLACE не сбрасывает
  // её поиск, а POP сразу читает сохранённое состояние нужного посещения.
  if (current !== history) setHistory(current)
  useLayoutEffect(() => { saveSession(historyKey, current) }, [historyKey, current])
  useEffect(() => () => {
    // React размонтирует границу при смене компании/пользователя. Обычный reload
    // документа сохраняет sessionStorage, поэтому браузерный возврат тоже работает.
    try {
      if (historyKey) sessionStorage.removeItem(historyKey)
      if (viewsKey) sessionStorage.removeItem(viewsKey)
    } catch { /* В памяти граница уже сброшена. */ }
  }, [historyKey, viewsKey])

  return <NavigationHistoryContext.Provider value={{ history: current, views }}>{children}</NavigationHistoryContext.Provider>
}
