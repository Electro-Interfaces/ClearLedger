/**
 * Сброс локальных сужений при смене контура рабочей области.
 *
 * Контур (период · область учёта · типы данных) задаётся только верхним фильтром.
 * Когда он меняется, выборка становится другой — и локальные сужения внутри таба
 * (поиск по таблице, пагинация, выделение строк) теряют смысл: пользователь
 * остаётся на 5-й странице, которой в новой выборке уже нет, или видит пустой
 * результат из-за поискового запроса от прошлого периода.
 *
 * Слой «представление» (метрика, разрез, шаг, топ-N) при этом сохраняется —
 * он не зависит от объёма выборки. См. CLAUDE.md → «Взаимодействие верхнего
 * фильтра и параметров таба», правило 5.
 */

import { useEffect, useRef } from 'react'
import { useFilters } from '@/contexts/FilterContext'

/** Строковый отпечаток контура: меняется при любой правке верхнего фильтра. */
export function useScopeKey(): string {
  const { period, stationCode, locationIds, regionIds, stationCodes, docTypeIds } = useFilters()
  return [
    period.from,
    period.to,
    stationCode,
    locationIds.join(','),
    regionIds.join(','),
    stationCodes.join(','),
    docTypeIds.join(','),
  ].join('|')
}

/**
 * Человекочитаемое описание контура для шапки выгружаемого файла.
 *
 * Цифры из выгрузок уходят в бухгалтерию, поэтому файл обязан нести на себе
 * ответ на вопрос «за что эти суммы» — период, область учёта, типы данных
 * (CLAUDE.md, правило 7). Пример:
 * `Период: 2026-06-30 — 2026-07-18 · Регион: Москва · Типов данных: 2`
 */
export function useScopeSubtitle(): string {
  const { period, stationCode, locationIds, regionIds, stationCodes, docTypeIds } = useFilters()

  const parts = [`Период: ${period.from} — ${period.to}`]

  if (stationCodes.length > 0) parts.push(`ЭЗС: ${stationCodes.length}`)
  else if (locationIds.length > 0) parts.push(`Точек: ${locationIds.length}`)
  else if (regionIds.length === 1) parts.push(`Регион: ${regionIds[0]}`)
  else if (regionIds.length > 1) parts.push(`Регионов: ${regionIds.length}`)
  else parts.push('Вся сеть')

  if (docTypeIds.length > 0) parts.push(`Типов данных: ${docTypeIds.length}`)
  if (stationCode !== 'all') parts.push(`Источник STS: ${stationCode}`)

  return parts.join(' · ')
}

/**
 * Вызывает `reset` при каждой смене контура (кроме первого рендера).
 *
 * ```tsx
 * useResetOnScopeChange(() => { setSearch(''); setSearchInput(''); setPage(0) })
 * ```
 */
export function useResetOnScopeChange(reset: () => void): void {
  const key = useScopeKey()
  const resetRef = useRef(reset)
  resetRef.current = reset
  const prevKey = useRef<string | null>(null)

  useEffect(() => {
    if (prevKey.current === null) {
      prevKey.current = key
      return
    }
    if (prevKey.current !== key) {
      prevKey.current = key
      resetRef.current()
    }
  }, [key])
}
