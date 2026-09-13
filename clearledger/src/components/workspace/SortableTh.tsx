/**
 * Сортировка таблицы по столбцу — один механизм на все панели.
 *
 * Разметка сортируемого заголовка уже жила тремя разными копиями (сессии, топливо,
 * реализации) и успела разойтись: где-то клик висел на всей ячейке без клавиатурного
 * пути, где-то стрелка направления не совпадала с `aria-sort`. Здесь она одна.
 *
 * Правило, которое отличает полезную сортировку от вредной: **пустое значение всегда
 * внизу**, в обе стороны. «Нет данных» — это не ноль и не «самое маленькое»: если
 * пустые всплывут наверх при сортировке по возрастанию, первый экран займут строки,
 * про которые ничего не известно, и менеджер решит, что таблица сломалась.
 */
import { ArrowDown, ArrowUp, ChevronsUpDown } from 'lucide-react'
import type { SortState } from '@/hooks/useTableSort'

/**
 * Заголовок сортируемого столбца.
 *
 * Кнопка, а не кликабельная ячейка: сортировка доступна с клавиатуры, у неё есть имя,
 * а `aria-sort` совпадает с нарисованной стрелкой. Столбец без ключа остаётся обычным
 * заголовком — сортировать «Действие» или «Что продают» нечего.
 */
export function SortTh({ children, sortKey, sort, onSort, align = 'left', className = '' }: {
  children: React.ReactNode
  /** Ключ столбца в карте сортировки; без него заголовок несортируемый. */
  sortKey?: string
  sort?: SortState
  onSort?: (key: string) => void
  align?: 'left' | 'right'
  className?: string
}) {
  const bare = `p-2 font-medium ${align === 'right' ? 'text-right' : 'text-left'} ${className}`
  if (!sortKey || !sort || !onSort) {
    return <th className={bare}>{children}</th>
  }
  const active = sort.key === sortKey
  const Icon = active ? (sort.dir === 'asc' ? ArrowUp : ArrowDown) : ChevronsUpDown
  return (
    <th className={bare}
      aria-sort={active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
      <button type="button" onClick={() => onSort(sortKey)}
        title={active
          ? `Сортировка по столбцу ${sort.dir === 'asc' ? 'по возрастанию' : 'по убыванию'}. Нажмите, чтобы изменить`
          : 'Сортировать по этому столбцу'}
        className={`group inline-flex min-h-8 items-center gap-1 whitespace-nowrap transition-colors hover:text-foreground ${
          align === 'right' ? 'flex-row-reverse' : ''} ${active ? 'text-foreground' : ''}`}>
        <span>{children}</span>
        <Icon aria-hidden className={`size-3 shrink-0 ${
          active ? 'text-primary' : 'opacity-30 group-hover:opacity-70'}`} />
      </button>
    </th>
  )
}
