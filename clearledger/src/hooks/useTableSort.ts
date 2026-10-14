/**
 * Сортировка таблицы по столбцу — состояние и порядок строк.
 *
 * Ядро сравнения живёт в `lib/sortRows`, заголовок — в `components/workspace/SortableTh`.
 * Здесь только то, что требует React: текущий столбец, направление и переключение.
 */
import { useMemo, useState } from 'react'
import { sortRows, type SortDir, type Значение } from '@/lib/sortRows'

export type SortState = { key: string | null; dir: SortDir }

/** Как достать значение столбца из строки. Пустое уходит вниз. */
export type SortMap<T> = Record<string, (row: T) => Значение>

/**
 * Сортировка списка по выбранному столбцу.
 *
 * Возвращает отсортированные строки, текущее состояние и переключатель. Первый клик
 * по числовому столбцу сортирует по убыванию (менеджеру нужен верх списка — где
 * больше всего), по текстовому — по алфавиту: «Станция» первым кликом от «Я» к «А»
 * читалась как поломка (14.10.2026). Второй клик разворачивает, третий возвращает
 * исходный порядок панели.
 */
export function useTableSort<T>(
  rows: T[],
  map: SortMap<T>,
  initial: SortState = { key: null, dir: 'desc' },
) {
  const [sort, setSort] = useState<SortState>(initial)

  const sorted = useMemo(() => {
    const get = sort.key ? map[sort.key] : null
    return get ? sortRows(rows, get, sort.dir) : rows
  }, [rows, map, sort])

  const toggle = (key: string) => {
    const get = map[key]
    const образец = get ? rows.map(get).find((v) => v !== null && v !== undefined && v !== '') : undefined
    const первое: SortDir = typeof образец === 'string' ? 'asc' : 'desc'
    const второе: SortDir = первое === 'asc' ? 'desc' : 'asc'
    setSort((prev) => {
      if (prev.key !== key) return { key, dir: первое }
      if (prev.dir === первое) return { key, dir: второе }
      return { key: null, dir: 'desc' }
    })
  }

  return { rows: sorted, sort, toggle }
}

