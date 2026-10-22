import { useCallback, useLayoutEffect, useState, type Dispatch, type SetStateAction } from 'react'
import { useLocation } from 'react-router-dom'
import { useNavigationHistory } from '@/contexts/navigationHistoryContextValue'
import { useTabs } from '@/contexts/TabsContext'
import { viewKey } from '@/config/tabRegistry'
import { navigationEntryId } from '@/lib/navigationHistory'

/** Поиск и отборы посещения страницы. Без localStorage и переноса между компаниями. */
export function useHistoryViewState<T>(name: string, initial: T): [T, Dispatch<SetStateAction<T>>] {
  const location = useLocation()
  const { history, views } = useNavigationHistory()
  const { isPinned } = useTabs()
  const [fallback] = useState(() => initial)
  // useLocation берётся из снимка закреплённой вкладки, если она сейчас скрыта.
  const entryKey = `${navigationEntryId(history, location.key)}:${location.pathname}:${name}`
  const url = viewKey(location.pathname, location.search)
  const pinned = isPinned(url)
  const key = pinned ? `pinned:${url}:${name}` : entryKey
  const [saved, setSaved] = useState(() => ({ key, url, value: views.get(key, views.get(entryKey, fallback)) }))
  let current = saved
  if (saved.key !== key || saved.url !== url) {
    current = { key, url, value: pinned && saved.key === entryKey && saved.url === url
      ? saved.value : views.get(key, views.get(entryKey, fallback)) }
    setSaved(current)
  }
  // У закреплённых экземпляров собственное локальное состояние. Кэш читается
  // при возврате размонтированной страницы, а не связывает скрытые вкладки.
  useLayoutEffect(() => {
    views.set(key, current.value)
    if (key !== entryKey) views.set(entryKey, current.value)
  }, [views, key, entryKey, current.value])
  const setValue = useCallback<Dispatch<SetStateAction<T>>>((next) => {
    setSaved((previous) => {
      const value = previous.key === key ? previous.value : views.get(key, fallback)
      return { key, url, value: typeof next === 'function' ? (next as (old: T) => T)(value) : next }
    })
  }, [views, key, url, fallback])
  return [current.value, setValue]
}
