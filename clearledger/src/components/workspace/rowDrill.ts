/**
 * Кликабельная строка таблицы — один приём на весь «Магазин».
 *
 * Строка, за которой стоит сущность (товар, документ, смена), открывает её расшифровку.
 * Раньше это делалось голым `onClick` на `<tr>`: мышью работало, с клавиатуры — нет,
 * а строка без сущности молча гасла прозрачностью, и человек не понимал, кликабельна она
 * или он промахнулся.
 *
 * `role="button"` на `<tr>` НЕ ставим: он ломает семантику таблицы для скринридера.
 * `tabIndex` + `onKeyDown` + `aria-haspopup` достаточно; кольцо фокуса рисует общий стиль
 * `[tabindex]:focus-visible` из index.css.
 */
import type { KeyboardEvent } from 'react'

export function rowDrill(open: (() => void) | null, label?: string, base = '') {
  if (!open) {
    // Нечего раскрывать (документ без строк, агрегат) — состояние видно и ассистивно.
    return { 'aria-disabled': true as const, className: `${base} opacity-60`.trim() }
  }
  return {
    tabIndex: 0,
    'aria-haspopup': 'dialog' as const,
    'aria-label': label,
    className: `${base} cursor-pointer hover:bg-accent/20`.trim(),
    onClick: open,
    onKeyDown: (e: KeyboardEvent) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault()
        open()
      }
    },
  }
}
