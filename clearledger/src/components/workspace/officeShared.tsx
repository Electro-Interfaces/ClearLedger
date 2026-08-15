/**
 * Общие мелочи офисных продуктов: форматы чисел, подписи периодов, табы и выгрузка.
 *
 * Заведено после того, как одни и те же четыре формата и два компонента оказались
 * скопированы в трёх файлах («Бухгалтерия», «Реализация», «Экономика»). Цена копии не
 * в объёме, а в том, что правка формата доезжает до одного экрана из трёх, и рядом
 * стоящие цифры начинают выглядеть по-разному.
 *
 * Здесь только то, что действительно общее. Экранные компоненты остаются в своих
 * файлах: у продуктов разные вопросы, и общий «универсальный экран» кончился бы
 * набором флагов.
 */
import { Download, Printer } from 'lucide-react'
import { cn } from '@/lib/utils'

/** Деньги без копеек — основной формат витрин. */
export const money = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })

/** Деньги с копейками — там, где сходимость до копейки и есть предмет разговора. */
export const money2 = new Intl.NumberFormat('ru-RU', {
  minimumFractionDigits: 2, maximumFractionDigits: 2,
})

export const num = new Intl.NumberFormat('ru-RU')

/** Количество: три знака избыточны, ноль знаков врёт на дробных единицах. */
export const qty = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 })

export const MONTHS = ['', 'январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль',
  'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь']

/** «2026-03» → «март 2026». */
export const monthLabel = (m: string) => {
  const [y, mm] = m.split('-')
  return `${MONTHS[Number(mm)] ?? mm} ${y}`
}

/**
 * Полоса разрезов. Кнопки помечены `role="tab"` и `aria-selected`: без этого
 * скринридер читает их как обычные кнопки, а состояние «выбрано» передаётся только
 * цветом.
 */
export function Tabs<T extends string>({ value, onChange, items, label }: {
  value: T
  onChange: (v: T) => void
  items: { key: T; label: string; hint?: string }[]
  /** Чему посвящён набор: «разрез», «период», «отбор». Читается вслух. */
  label?: string
}) {
  return (
    <div className="flex flex-wrap gap-1 no-print" role="tablist" aria-label={label}>
      {items.map((i) => (
        <button key={i.key} role="tab" aria-selected={value === i.key}
          onClick={() => onChange(i.key)}
          className={cn('rounded-md px-2.5 py-1 text-xs',
            value === i.key ? 'bg-muted font-medium' : 'text-muted-foreground hover:bg-muted/50')}>
          {i.label}
          {i.hint && <span className="ml-1.5 tabular-nums opacity-70">{i.hint}</span>}
        </button>
      ))}
    </div>
  )
}

/**
 * Выгрузка экрана: Excel и PDF печатью браузера.
 *
 * PDF делаем печатью, а не генерацией на сервере: печать даёт правильную кириллицу
 * без шрифтовых пакетов в образе, а на выходе тот же PDF. Печатные стили прячут меню
 * и рельсы (`index.css`, `@media print`), поэтому на лист уходит рабочая область.
 */
export function ExportButton({ onClick, label = 'Excel' }: {
  onClick: () => void; label?: string
}) {
  const cls = 'inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs '
    + 'text-muted-foreground hover:bg-muted/50'
  return (
    <div className="inline-flex items-center gap-1 no-print">
      <button onClick={onClick} className={cls}>
        <Download className="h-3.5 w-3.5" />{label}
      </button>
      <button onClick={() => window.print()} className={cls}
        title="Печать или сохранение в PDF" aria-label="Печать или сохранение в PDF">
        <Printer className="h-3.5 w-3.5" />PDF
      </button>
    </div>
  )
}

/** Сегодня в том же виде, в каком даты ходят по API. */
export const today = () => new Date().toISOString().slice(0, 10)

/** «2026-08-15» → «15.08». ISO-даты в интерфейсе не показываем. */
export const dayLabel = (iso: string) => iso.slice(8, 10) + '.' + iso.slice(5, 7)

/**
 * Ячейка таблицы офисных экранов. Была скопирована в шести файлах «Периметра» —
 * одинаковая до символа, но на 4 px выше, чем строки остальных офисных таблиц.
 */
export function Td({ children, right, muted, className }: {
  children: React.ReactNode
  right?: boolean
  muted?: boolean
  className?: string
}) {
  return (
    <td className={cn('px-3 py-1.5 align-top',
      right && 'text-right tabular-nums whitespace-nowrap',
      muted && 'text-muted-foreground', className)}>{children}</td>
  )
}

/** Поле ввода в диалогах: один класс на все офисные формы. */
export const inputCls
  = 'w-full rounded-md border bg-background px-2.5 py-1.5 text-sm'

/**
 * Поле формы с подписью и пояснением. Подпись — настоящая метка (`<label>`), иначе
 * диктор читает «поле ввода, 30» без указания, что именно вводят.
 */
export function FormField({ label, hint, children }: {
  label: string; hint?: string; children: React.ReactNode
}) {
  return (
    <label className="block space-y-1">
      <span className="block text-[11px] uppercase tracking-wider text-muted-foreground">
        {label}
      </span>
      {children}
      {hint && <span className="block text-[11px] text-muted-foreground">{hint}</span>}
    </label>
  )
}

/** Поле поиска над таблицей: без метки скринридер читает только placeholder. */
export function SearchInput({ value, onChange, placeholder, label, width = 'w-56' }: {
  value: string
  onChange: (v: string) => void
  placeholder: string
  /** Что ищем — читается вслух вместо подсказки внутри поля. */
  label?: string
  width?: string
}) {
  return (
    <input value={value} onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder} aria-label={label ?? placeholder} type="search"
      className={cn('h-8 rounded-md border bg-background px-2.5 text-sm', width)} />
  )
}
