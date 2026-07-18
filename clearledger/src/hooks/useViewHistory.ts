/**
 * История видов рабочей области (единый снимок: раздел + пункт + параметры пунктов).
 * Сохранить текущий вид, вернуть сохранённый, удалить.
 */

import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { nanoid } from 'nanoid'
import { useCompany } from '@/contexts/CompanyContext'
import { useFilters } from '@/contexts/FilterContext'
import { notifyTabParamsRestored } from './useTabParams'
import {
  captureTabParams, restoreTabParams, loadViewHistory, saveViewHistory,
  VIEW_HISTORY_LIMIT, type ViewSnapshot,
} from '@/services/viewSnapshot'

export function useViewHistory() {
  const { companyId } = useCompany()
  const { state, applyState } = useFilters()
  const [sp, setSp] = useSearchParams()
  const [history, setHistory] = useState<ViewSnapshot[]>(() => loadViewHistory(companyId))

  useEffect(() => { setHistory(loadViewHistory(companyId)) }, [companyId])
  useEffect(() => { saveViewHistory(companyId, history) }, [companyId, history])

  const saveCurrentView = useCallback((name?: string) => {
    const snap: ViewSnapshot = {
      id: nanoid(), at: Date.now(),
      name: name?.trim() || undefined,
      mode: sp.get('mode') ?? 'management',
      sub: sp.get('sub') ?? '',
      section: state,
      tabParams: captureTabParams(companyId),
    }
    setHistory((prev) => [snap, ...prev].slice(0, VIEW_HISTORY_LIMIT))
  }, [companyId, sp, state])

  const applyView = useCallback((snap: ViewSnapshot) => {
    applyState(snap.section)                       // раздел
    restoreTabParams(companyId, snap.tabParams)    // параметры пунктов
    notifyTabParamsRestored()                      // перечитать открытый пункт
    setSp((prev) => {                              // активный пункт
      const n = new URLSearchParams(prev)
      n.set('mode', snap.mode)
      if (snap.sub) n.set('sub', snap.sub)
      return n
    }, { replace: true })
  }, [companyId, applyState, setSp])

  const deleteView = useCallback((id: string) => {
    setHistory((prev) => prev.filter((s) => s.id !== id))
  }, [])

  // Пометить вид «по умолчанию» (§6.4 точка входа) — снимает пометку с прочих; повторный клик снимает.
  const setDefaultView = useCallback((id: string) => {
    setHistory((prev) => prev.map((s) => ({ ...s, isDefault: s.id === id ? !s.isDefault : false })))
  }, [])

  return { history, saveCurrentView, applyView, deleteView, setDefaultView }
}
