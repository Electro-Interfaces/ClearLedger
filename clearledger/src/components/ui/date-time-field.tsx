/**
 * Дата и время: печатать цифрами ИЛИ выбрать — одновременно, а не вместо.
 *
 * 🔴 Заменяет `<input type="datetime-local">`, который на телефоне открывает нативные
 * барабаны. Претензия МАГа 16.09.2026: «можно указать только выбирая из справочника,
 * нельзя ввести цифрами; и листать вверх-вниз неудобно — легче ткнуть в дату».
 * Обе беды от одного: барабан это ЕДИНСТВЕННЫЙ способ ввода, а человек, который знает
 * ответ («семнадцатое, в девять тридцать»), вынужден крутить до него колесо.
 *
 * Так устроено везде, где встречи ставят каждый день (Google Calendar, Outlook, Notion):
 * поле — обычный текст с цифровой клавиатурой, рядом кнопка — сетка месяца и список
 * получаса. Кто помнит дату — печатает, кто выбирает — тыкает; ни один не ждёт другого.
 *
 * Форматы ввода намеренно прощающие: `1709` → 17.09 текущего года, `17092026` и
 * `17.09.26` → полная дата, `930` → 09:30, `9` → 09:00. Разделители не обязательны —
 * на телефоне точка и двоеточие живут на второй раскладке.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { CalendarDays, Clock } from 'lucide-react'
import { ru } from 'date-fns/locale'
import { Calendar } from '@/components/ui/calendar'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { cn } from '@/lib/utils'
import { dateToText, textToDate, textToTime } from '@/lib/date-input'

interface FieldProps {
  id?: string
  value: string
  onChange: (next: string) => void
  disabled?: boolean
  className?: string
  'aria-label'?: string
}

/** Поле даты: печать цифрами + сетка месяца по кнопке. Значение — `YYYY-MM-DD`. */
export function DateField({ id, value, onChange, disabled, className, ...rest }: FieldProps) {
  const [text, setText] = useState(() => dateToText(value))
  const [open, setOpen] = useState(false)
  // Значение может прийти снаружи (сдвинули начало — подтянулся конец), но пока человек
  // печатает, перебивать его нельзя: иначе «17.0» превращается в «01.01.2026» под руками.
  const typing = useRef(false)
  useEffect(() => { if (!typing.current) setText(dateToText(value)) }, [value])

  const commit = (next: string) => {
    setText(next)
    typing.current = true
    const iso = textToDate(next)
    if (iso) onChange(iso)
  }
  const selected = value ? new Date(value + 'T00:00') : undefined

  return (
    <div className={cn('relative', className)}>
      <Input
        id={id}
        value={text}
        disabled={disabled}
        inputMode="numeric"
        placeholder="дд.мм.гггг"
        aria-label={rest['aria-label'] ?? 'Дата'}
        className="pr-10 text-base sm:text-sm"
        onChange={(e) => commit(e.target.value)}
        onBlur={() => { typing.current = false; setText(dateToText(value)) }}
      />
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <button
            type="button"
            disabled={disabled}
            aria-label="Выбрать дату в календаре"
            className="absolute right-0 top-0 inline-flex size-10 items-center justify-center rounded-r-md text-muted-foreground
                       hover:text-foreground disabled:pointer-events-none disabled:opacity-50 sm:size-9"
          >
            <CalendarDays className="size-4" />
          </button>
        </PopoverTrigger>
        <PopoverContent align="end" className="w-auto p-0">
          <Calendar
            mode="single"
            locale={ru}
            captionLayout="dropdown"
            defaultMonth={selected}
            selected={selected}
            onSelect={(d) => {
              if (!d) return
              typing.current = false
              onChange(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`)
              setOpen(false)
            }}
          />
        </PopoverContent>
      </Popover>
    </div>
  )
}

/**
 * Поле времени: печать цифрами + список получаса по кнопке. Значение — `HH:mm`.
 *
 * Список, а не барабан: рабочее время попадает в него целиком, и нужный час виден
 * сразу — по нему можно ткнуть, а не прокручивать к нему. Открывается на текущем
 * значении, чтобы 18:00 не искали от полуночи.
 */
export function TimeField({ id, value, onChange, disabled, className, ...rest }: FieldProps) {
  const [text, setText] = useState(value || '')
  const [open, setOpen] = useState(false)
  const typing = useRef(false)
  const listRef = useRef<HTMLDivElement>(null)
  useEffect(() => { if (!typing.current) setText(value || '') }, [value])

  const slots = useMemo(() => Array.from({ length: 48 }, (_, i) =>
    `${String(Math.floor(i / 2)).padStart(2, '0')}:${i % 2 ? '30' : '00'}`), [])

  const commit = (next: string) => {
    setText(next)
    typing.current = true
    const hhmm = textToTime(next)
    if (hhmm) onChange(hhmm)
  }

  return (
    <div className={cn('relative', className)}>
      <Input
        id={id}
        value={text}
        disabled={disabled}
        inputMode="numeric"
        placeholder="чч:мм"
        aria-label={rest['aria-label'] ?? 'Время'}
        className="pr-10 text-base tabular-nums sm:text-sm"
        onChange={(e) => commit(e.target.value)}
        onBlur={() => { typing.current = false; setText(value || '') }}
      />
      <Popover open={open} onOpenChange={(o) => {
        setOpen(o)
        // Прокрутка к текущему значению — после отрисовки списка, иначе прокручивать нечего.
        if (o) setTimeout(() => listRef.current?.querySelector('[data-current="true"]')
          ?.scrollIntoView({ block: 'center' }), 0)
      }}>
        <PopoverTrigger asChild>
          <button
            type="button"
            disabled={disabled}
            aria-label="Выбрать время из списка"
            className="absolute right-0 top-0 inline-flex size-10 items-center justify-center rounded-r-md text-muted-foreground
                       hover:text-foreground disabled:pointer-events-none disabled:opacity-50 sm:size-9"
          >
            <Clock className="size-4" />
          </button>
        </PopoverTrigger>
        <PopoverContent align="end" className="w-28 p-1">
          <div ref={listRef} className="max-h-64 overflow-y-auto">
            {slots.map((s) => (
              <button
                key={s}
                type="button"
                data-current={s === value}
                onClick={() => { typing.current = false; onChange(s); setOpen(false) }}
                className={cn('flex w-full items-center justify-center rounded px-2 py-2 text-sm tabular-nums transition-colors sm:py-1.5',
                  s === value ? 'bg-primary/10 font-medium text-primary' : 'hover:bg-accent hover:text-foreground')}
              >
                {s}
              </button>
            ))}
          </div>
        </PopoverContent>
      </Popover>
    </div>
  )
}
