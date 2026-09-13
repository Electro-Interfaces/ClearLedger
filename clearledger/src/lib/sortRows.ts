/**
 * Ядро сортировки таблиц: одна реализация на все панели и на проверку.
 *
 * Правило, которое отличает полезную сортировку от вредной: **пустое значение всегда
 * внизу**, в обе стороны. «Нет данных» — это не ноль и не «самое маленькое»: если
 * пустые всплывут наверх при сортировке по возрастанию, первый экран займут строки,
 * про которые ничего не известно, и менеджер решит, что таблица сломалась.
 */
export type SortDir = 'asc' | 'desc'

export type Значение = string | number | boolean | null | undefined

/**
 * Ядро сортировки: одна реализация на хук и на проверку.
 *
 * Пустое значение уходит вниз в обе стороны — до того, как применится направление.
 */
export function sortRows<T>(
  rows: T[],
  get: (row: T) => Значение,
  dir: SortDir,
): T[] {
  const sign = dir === 'asc' ? 1 : -1
  return [...rows].sort((a, b) => {
    const va = get(a)
    const vb = get(b)
    const пустоA = va === null || va === undefined || va === ''
    const пустоB = vb === null || vb === undefined || vb === ''
    if (пустоA && пустоB) return 0
    if (пустоA) return 1
    if (пустоB) return -1
    if (typeof va === 'number' && typeof vb === 'number') return (va - vb) * sign
    if (typeof va === 'boolean' && typeof vb === 'boolean') {
      return (Number(va) - Number(vb)) * sign
    }
    return String(va).localeCompare(String(vb), 'ru') * sign
  })
}
