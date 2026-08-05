/**
 * Показ длинного списка без обрезки.
 *
 * Раньше таблицы резались молча: «показано 400 из 1019, уточните поиск». Но
 * товаровед приходит смотреть весь ассортимент, а не первые четыреста строк по
 * чужой сортировке; ответ «уточните поиск» на вопрос «что вообще есть» не
 * годится. Рендерить тысячи строк разом тоже нельзя — страница встаёт.
 *
 * Отсюда середина: список показывается порциями, и рядом стоит кнопка. Данные
 * доступны все, DOM растёт по требованию человека, а не по умолчанию.
 */
import { useEffect, useState } from 'react'

/** Сколько строк показывать сразу и на сколько прирастать по кнопке. */
export const ПОРЦИЯ = 300

export function useVisible<T>(rows: T[], step = ПОРЦИЯ) {
  const [сколько, задать] = useState(step)
  // Смена набора (другой фильтр, другой период) возвращает список в начало:
  // иначе после сужения поиска остаётся раскрытый хвост от прошлой выборки.
  useEffect(() => { задать(step) }, [rows, step])
  return {
    visible: rows.length <= сколько ? rows : rows.slice(0, сколько),
    shown: Math.min(сколько, rows.length),
    total: rows.length,
    hasMore: rows.length > сколько,
    more: () => задать((c) => c + step),
    all: () => задать(rows.length),
  }
}

export function ShowMore({ shown, total, hasMore, onMore, onAll, unit = 'строк' }: {
  shown: number; total: number; hasMore: boolean
  onMore: () => void; onAll: () => void; unit?: string
}) {
  if (!hasMore) {
    return total > 0 ? (
      <div className="border-t border-border/30 px-3 py-2 text-[11px] text-muted-foreground">
        Показано всё: {new Intl.NumberFormat('ru-RU').format(total)} {unit}.
      </div>
    ) : null
  }
  const nf = new Intl.NumberFormat('ru-RU')
  return (
    <div className="flex flex-wrap items-center gap-3 border-t border-border/30 px-3 py-2 text-[11px]">
      <span className="text-muted-foreground">
        Показано {nf.format(shown)} из {nf.format(total)} {unit}
      </span>
      <button type="button" onClick={onMore} className="text-primary hover:underline">
        показать ещё {nf.format(Math.min(ПОРЦИЯ, total - shown))}
      </button>
      <button type="button" onClick={onAll} className="text-muted-foreground hover:text-foreground">
        показать все
      </button>
      {total - shown > 2000 && (
        <span className="text-muted-foreground/70">
          — при полном показе страница может подтормаживать
        </span>
      )}
    </div>
  )
}
