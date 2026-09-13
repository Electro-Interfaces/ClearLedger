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
 * Возвращает отсортированные строки, текущее состояние и переключатель: первый клик
 * по столбцу сортирует по убыванию (менеджеру нужен верх списка — где больше всего),
 * второй разворачивает, третий возвращает исходный порядок панели.
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
    setSort((prev) => {
      if (prev.key !== key) return { key, dir: 'desc' }
      if (prev.dir === 'desc') return { key, dir: 'asc' }
      return { key: null, dir: 'desc' }
    })
  }

  return { rows: sorted, sort, toggle }
}

