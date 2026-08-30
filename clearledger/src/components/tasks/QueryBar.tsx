/**
 * Строка запроса к списку задач (этап 12 трекерного контура).
 *
 * «мои нерешённые в TF с высоким приоритетом» формой не выражается: полей в ней
 * восемь, а сочетаний — сколько угодно. Здесь это одна строка:
 * `проект: TF #нерешённые исполнитель: я приоритет: высокий`.
 *
 * Разбирает сервер, а не браузер. Иначе «тот же результат, что формой» держался
 * бы на честном слове: два разных кода отбирали бы по-разному, и расхождение
 * вылезло бы в сохранённом отборе, где его никто не ищет.
 *
 * Здесь только ввод и подсказки. Подсказки берутся из справочников, которые
 * экран и так загрузил: второй источник имён разошёлся бы с первым.
 */
import { useMemo, useRef, useState } from 'react'
import { Search, X } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { ParsedQuery } from '@/services/tasksService'

/** Поля языка. Русские имена — язык пространства русский, и `assignee` в строке
 *  поиска читается хуже, чем `исполнитель`. Порядок — по частоте, а не по алфавиту. */
const FIELDS: { key: string; hint: string }[] = [
  { key: 'исполнитель', hint: 'фамилия или «я»' },
  { key: 'проект', hint: 'код проекта: TF' },
  { key: 'приоритет', hint: 'низкая · обычная · срочная · критичная' },
  { key: 'метка', hint: 'имя метки' },
  { key: 'спринт', hint: 'имя отрезка' },
  { key: 'версия', hint: 'в какой исправлено' },
  { key: 'автор', hint: 'кто поставил' },
  { key: 'тип', hint: 'тип задачи' },
  { key: 'стадия', hint: 'шаг маршрута' },
  { key: 'объект', hint: 'объект пространства' },
  { key: 'срок', hint: 'сегодня · неделя · просрочен · 12.09.2026' },
]

const FLAGS: { key: string; hint: string }[] = [
  { key: '#нерешённые', hint: 'живая работа' },
  { key: '#решённые', hint: 'закрытые' },
  { key: '#мои', hint: 'я исполнитель' },
  { key: '#поручил', hint: 'я автор, делает другой' },
  { key: '#наблюдаю', hint: 'где я наблюдатель' },
  { key: '#просроченные', hint: 'срок прошёл' },
  { key: '#сегодня', hint: 'что горит' },
  { key: '#ждём', hint: 'мяч у внешней стороны' },
  { key: '#бэклог', hint: 'без спринта' },
  { key: '#все', hint: 'без разреза' },
]

const PRIORITIES = ['низкая', 'обычная', 'срочная', 'критичная']
const DUES = ['сегодня', 'завтра', 'неделя', 'просрочен']

export interface QuerySuggestions {
  проект?: string[]
  исполнитель?: string[]
  автор?: string[]
  метка?: string[]
  спринт?: string[]
  версия?: string[]
  тип?: string[]
  стадия?: string[]
}

export function QueryBar({ value, onChange, result, suggestions, className }: {
  value: string
  onChange: (v: string) => void
  result?: ParsedQuery
  suggestions: QuerySuggestions
  className?: string
}) {
  const [text, setText] = useState(value)
  const [open, setOpen] = useState(false)
  const [cursor, setCursor] = useState(0)
  const ref = useRef<HTMLInputElement>(null)

  // Подсказки считаем по последнему слову: до двоеточия предлагаем поля, после —
  // значения именно этого поля. Так подсказка отвечает на вопрос, который человек
  // задаёт прямо сейчас, а не показывает весь словарь разом.
  const tail = text.slice(0, ref.current?.selectionStart ?? text.length)
  const token = tail.split(/\s+/).pop() ?? ''
  const items = useMemo(() => {
    const colon = token.indexOf(':')
    if (colon > 0) {
      const field = token.slice(0, colon).toLowerCase()
      const typed = token.slice(colon + 1).toLowerCase()
      const values = field === 'приоритет' ? PRIORITIES
        : field === 'срок' ? DUES
          : field === 'исполнитель' || field === 'автор'
            ? ['я', ...(suggestions[field as 'исполнитель'] ?? [])]
            : suggestions[field as keyof QuerySuggestions] ?? []
      return values
        .filter((v) => v.toLowerCase().includes(typed))
        .slice(0, 8)
        .map((v) => ({ text: `${field}: ${v.includes(' ') ? `"${v}"` : v}`, hint: '' }))
    }
    const low = token.toLowerCase()
    if (low.startsWith('#')) {
      return FLAGS.filter((f) => f.key.toLowerCase().startsWith(low))
        .slice(0, 8).map((f) => ({ text: f.key, hint: f.hint }))
    }
    return [...FIELDS.filter((f) => !low || f.key.startsWith(low))
      .map((f) => ({ text: `${f.key}: `, hint: f.hint })),
    ...(low ? [] : FLAGS.slice(0, 4).map((f) => ({ text: f.key, hint: f.hint })))]
      .slice(0, 8)
  }, [token, suggestions])

  const apply = (piece: string) => {
    const before = text.slice(0, text.length - token.length)
    const next = `${before}${piece}${piece.endsWith(': ') ? '' : ' '}`
    setText(next)
    setCursor(0)
    ref.current?.focus()
  }

  const submit = (v: string) => { setOpen(false); onChange(v.trim()) }

  return (
    <div className={cn('relative', className)}>
      <div className="flex items-center gap-1">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input ref={ref} value={text} spellCheck={false}
            placeholder="проект: TF #нерешённые исполнитель: я"
            className="h-8 pl-7 text-xs"
            onChange={(e) => { setText(e.target.value); setOpen(true); setCursor(0) }}
            onFocus={() => setOpen(true)}
            onBlur={() => window.setTimeout(() => setOpen(false), 150)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                if (open && items[cursor]) { e.preventDefault(); apply(items[cursor].text) }
                else submit(text)
                return
              }
              if (e.key === 'Escape') { setOpen(false); return }
              if (!open || items.length === 0) return
              if (e.key === 'ArrowDown') {
                e.preventDefault(); setCursor((c) => (c + 1) % items.length)
              }
              if (e.key === 'ArrowUp') {
                e.preventDefault(); setCursor((c) => (c - 1 + items.length) % items.length)
              }
              if (e.key === 'Tab' && items[cursor]) { e.preventDefault(); apply(items[cursor].text) }
            }} />
          {text && (
            <button type="button" aria-label="Очистить запрос"
              className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              onClick={() => { setText(''); submit('') }}>
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
        <Button size="sm" variant="outline" className="h-8" onClick={() => submit(text)}>
          Найти
        </Button>
      </div>

      {open && items.length > 0 && (
        <div className="absolute z-30 mt-1 w-full overflow-hidden rounded-lg border bg-popover shadow-lg">
          {items.map((it, idx) => (
            <button key={it.text} type="button"
              onMouseDown={(e) => { e.preventDefault(); apply(it.text) }}
              onMouseEnter={() => setCursor(idx)}
              className={cn('flex w-full items-baseline gap-2 px-2.5 py-1.5 text-left text-xs',
                idx === cursor ? 'bg-accent' : 'hover:bg-accent/60')}>
              <span className="font-mono">{it.text.trim()}</span>
              <span className="truncate text-xs text-muted-foreground">{it.hint}</span>
            </button>
          ))}
        </div>
      )}

      {/* Неузнанное показываем всегда: молча проглоченная опечатка сужает список,
          а человек читает это как «работы нет». */}
      {result?.unknown && result.unknown.length > 0 && (
        <p className="mt-1 text-xs text-amber-700 dark:text-amber-400">
          Не понял: {result.unknown.join(' · ')}
        </p>
      )}
    </div>
  )
}
