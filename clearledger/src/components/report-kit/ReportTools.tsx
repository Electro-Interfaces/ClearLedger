import {
  ArrowDown, ArrowLeftRight, ArrowUp, Calculator, ChevronDown, ChevronUp, CircleHelp, ClipboardList, Columns3, Delete,
  Plus, SquareFunction, TextSearch, X,
} from 'lucide-react'
import { useRef, useState, type ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { addPin, calcValue, checkCalc, dropPin, evaluate, feedNumber, refsOf, setExpr, useTools, type CalcCol, type CalcTotal } from './calc'
import { isMoney, num2, qty, type Cell } from './format'
import type { Panel } from './rail'
import type { Cols, Picked } from './SheetTable'

const TITLE: Record<Panel, { title: string; icon: typeof Calculator }> = {
  help: { title: 'Помощь по экрану', icon: CircleHelp },
  calc: { title: 'Калькулятор', icon: Calculator },
  formula: { title: 'Свои столбцы', icon: SquareFunction },
  search: { title: 'Поиск по таблице', icon: TextSearch },
  columns: { title: 'Столбцы', icon: Columns3 },
  compare: { title: 'Сравнение', icon: ArrowLeftRight },
  pins: { title: 'Отложенные цифры', icon: ClipboardList },
}

const num = (v: number, money = false) => (money ? num2(v) : qty(Math.round(v * 100) / 100))
const KEYS = ['7', '8', '9', '÷', '4', '5', '6', '×', '1', '2', '3', '−', '0', ',', '(', ')']
const field = 'w-full rounded-lg border border-di-outline-variant bg-di-surface-lowest px-3 text-sm text-foreground outline-none focus:border-primary'

function Shell({ panel, report, onClose, children }: { panel: Panel; report: string; onClose: () => void; children: ReactNode }) {
  const Icon = TITLE[panel].icon
  return (
    <aside aria-label={TITLE[panel].title} className="flex flex-col gap-4 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-2.5">
          <Icon className="mt-0.5 size-5 shrink-0 text-primary" aria-hidden />
          <div className="min-w-0">
            <div className="truncate text-xs text-muted-foreground">{report}</div>
            <h2 className="font-headline text-base font-bold text-foreground">{TITLE[panel].title}</h2>
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Закрыть панель"
          title="Закрыть — или клавишей Esc"
          className="-mr-2 -mt-1 grid size-9 place-items-center rounded-lg text-muted-foreground hover:bg-di-surface-high hover:text-foreground"
        >
          <X className="size-4" aria-hidden />
        </button>
      </div>
      {children}
    </aside>
  )
}

function Selection({ sel, onClear, report }: { sel: Picked[]; onClear: () => void; report: string }) {
  const picked = sel.filter((x) => typeof x.value === 'number')
  const nums = picked.map((x) => x.value as number)
  const money = !!picked.length && picked.every((x) => isMoney(x.label))
  const sum = nums.reduce((a, b) => a + b, 0)
  const stat = (label: string, value: string) => (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-[15px] font-bold tabular-nums text-foreground">{value}</dd>
    </div>
  )
  return (
    <section aria-label="Выделение" className="rounded-lg bg-di-surface-low p-3">
      {!sel.length ? (
        <p className="text-xs leading-relaxed text-muted-foreground">
          Щёлкайте по ячейкам таблицы: здесь появятся сумма, среднее и количество по выделенному. Пока панель открыта, щелчок выделяет
          ячейку, а не открывает карточку строки.
        </p>
      ) : (
        <>
          <dl className="grid grid-cols-3 gap-x-3 gap-y-2">
            {stat('Сумма', nums.length ? num(sum, money) : '0')}
            {stat('Среднее', nums.length ? num(sum / nums.length, money) : '0')}
            {stat('Ячеек', `${sel.length}${nums.length < sel.length ? `, чисел ${nums.length}` : ''}`)}
            {nums.length > 1 && stat('Минимум', num(Math.min(...nums), money))}
            {nums.length > 1 && stat('Максимум', num(Math.max(...nums), money))}
          </dl>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button variant="outline" size="sm" disabled={!nums.length} onClick={() => setExpr(String(Math.round(sum * 100) / 100).replace('.', ','))}>
              Сумму в калькулятор
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={!nums.length}
              onClick={() => addPin(`${report}: сумма ${nums.length} ячеек${picked[0] ? `, ${picked[0].label}` : ''}`, sum, money)}
            >
              <ClipboardList className="size-3.5" aria-hidden /> Отложить
            </Button>
            <Button variant="ghost" size="sm" onClick={onClear}>
              Снять выделение
            </Button>
          </div>
        </>
      )}
    </section>
  )
}

function Calc({ report }: { report: string }) {
  const { expr } = useTools()
  const value = evaluate(expr)
  const press = (k: string) => setExpr(/[÷×−+]/.test(k) ? `${expr.trimEnd()} ${k} ` : `${expr}${k}`)
  const key = 'h-10 rounded-lg text-lg font-semibold transition-colors'
  const op = 'bg-di-surface-high text-primary hover:bg-di-surface-highest'
  return (
    <section aria-label="Калькулятор" className="flex flex-col gap-2.5">
      <input
        value={expr}
        onChange={(e) => setExpr(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && value !== null && setExpr(String(Math.round(value * 100) / 100).replace('.', ','))}
        placeholder="0"
        aria-label="Выражение"
        inputMode="decimal"
        className={cn(field, 'h-11 text-right text-lg')}
      />
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-xs text-muted-foreground">{expr.trim() && value === null ? 'Выражение не закончено' : 'Результат'}</span>
        <output className="font-headline text-2xl font-extrabold tabular-nums text-foreground">{value === null ? '0' : num(value)}</output>
      </div>
      <div className="grid grid-cols-4 gap-1.5">
        {KEYS.map((k) => (
          <button
            key={k}
            type="button"
            onClick={() => press(k)}
            className={cn(key, /\d|,/.test(k) ? 'bg-di-surface-lowest text-foreground hover:bg-di-surface-high' : op)}
          >
            {k}
          </button>
        ))}
        <button type="button" onClick={() => setExpr('')} className={cn(key, 'bg-di-surface-high text-di-on-surface-variant hover:bg-di-surface-highest')}>
          C
        </button>
        <button
          type="button"
          onClick={() => setExpr(expr.trimEnd().slice(0, -1).trimEnd())}
          aria-label="Стереть символ"
          className={cn(key, 'grid place-items-center bg-di-surface-high text-di-on-surface-variant hover:bg-di-surface-highest')}
        >
          <Delete className="size-5" aria-hidden />
        </button>
        <button type="button" onClick={() => press('+')} className={cn(key, op)}>
          +
        </button>
        <button
          type="button"
          onClick={() => value !== null && setExpr(String(Math.round(value * 100) / 100).replace('.', ','))}
          disabled={value === null}
          className={cn(key, 'bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-40')}
        >
          =
        </button>
      </div>
      <Button variant="outline" size="sm" disabled={value === null} onClick={() => value !== null && addPin(`${report}: расчёт ${expr.trim()}`, value)}>
        <ClipboardList className="size-3.5" aria-hidden /> Отложить результат
      </Button>
    </section>
  )
}

function Pins() {
  const { pins } = useTools()
  if (!pins.length)
    return (
      <p className="text-sm leading-relaxed text-muted-foreground">
        Здесь будут цифры, отложенные для сверки: сумма по выделению или результат калькулятора. Список общий для всех экранов с
        инструментами и живёт до перезагрузки страницы.
      </p>
    )
  return (
    <ul className="flex flex-col divide-y divide-di-outline-variant/50">
      {pins.map((p) => (
        <li key={p.id} className="flex items-start gap-2 py-2.5 first:pt-0">
          <div className="min-w-0 flex-1">
            <div className="text-lg font-bold tabular-nums text-foreground">{num(p.value, p.money)}</div>
            <div className="text-xs leading-snug text-di-on-surface-variant">{p.label}</div>
          </div>
          <Button variant="outline" size="sm" onClick={() => feedNumber(p.value)} title="Подставить в калькулятор">
            <Calculator className="size-3.5" aria-hidden />
          </Button>
          <button
            type="button"
            onClick={() => dropPin(p.id)}
            aria-label={`Убрать ${num(p.value, p.money)}`}
            className="grid size-9 place-items-center rounded-lg text-muted-foreground hover:bg-di-surface-high hover:text-foreground"
          >
            <X className="size-4" aria-hidden />
          </button>
        </li>
      ))}
    </ul>
  )
}

const TOTAL: [CalcTotal, string][] = [
  ['sum', 'Сумма по строкам'],
  ['formula', 'Формула по итогам'],
  ['none', 'Без итога'],
]

function Formulas({ head, rows, calcs, onCalcs, example }: { head: string[]; rows: Cell[][]; calcs: CalcCol[]; onCalcs: (c: CalcCol[]) => void; example: string }) {
  const [edit, setEdit] = useState<CalcCol | null>(null)
  const [tried, setTried] = useState(false)
  const area = useRef<HTMLTextAreaElement>(null)
  const base = head.length - calcs.length
  const at = edit ? calcs.findIndex((c) => c.id === edit.id) : -1
  const avail = head.slice(0, base + (at < 0 ? calcs.length : at))
  const nums = avail.filter((_, i) => rows.some((r) => typeof r[i] === 'number'))
  const err = edit ? checkCalc(edit, avail) : ''
  const sample = rows.find((r) => edit && !err && typeof calcValue(edit.expr, head, r) === 'number')
  const used = (c: CalcCol) => calcs.find((x) => x.id !== c.id && refsOf(x.expr).includes(c.name))

  const put = (s: string) => {
    if (!edit) return
    const el = area.current
    const a = el?.selectionStart ?? edit.expr.length
    const b = el?.selectionEnd ?? edit.expr.length
    const pad = /[+−×÷]/.test(s) ? ` ${s} ` : s
    const expr = edit.expr.slice(0, a) + pad + edit.expr.slice(b)
    setEdit({ ...edit, expr })
    requestAnimationFrame(() => {
      el?.focus()
      el?.setSelectionRange(a + pad.length, a + pad.length)
    })
  }
  const save = () => {
    setTried(true)
    if (!edit || err) return
    const name = edit.name.trim()
    const old = calcs[at]?.name
    const fix = (x: CalcCol) => (old && old !== name ? { ...x, expr: x.expr.split(`[${old}]`).join(`[${name}]`) } : x)
    const next = { ...edit, name }
    onCalcs(at < 0 ? [...calcs, next] : calcs.map((x) => (x.id === edit.id ? next : fix(x))))
    setEdit(null)
    setTried(false)
  }

  if (!edit)
    return (
      <>
        <p className="text-xs leading-relaxed text-muted-foreground">
          Свой столбец считается в каждой строке из других столбцов: сложить, вычесть, умножить, разделить. Дальше он ведёт себя как
          обычный: сортировка, фильтр, итог, выгрузка в Excel. Столбцы запоминаются для этого экрана в вашем браузере.
        </p>
        {!!calcs.length && (
          <ul className="flex flex-col divide-y divide-di-outline-variant/50">
            {calcs.map((c) => {
              const by = used(c)
              return (
                <li key={c.id} className="flex items-start gap-2 py-2.5 first:pt-0">
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-bold text-foreground">{c.name}</div>
                    <div className="break-words text-xs leading-snug text-di-on-surface-variant">{c.expr}</div>
                  </div>
                  <Button variant="outline" size="sm" onClick={() => setEdit(c)}>
                    Изменить
                  </Button>
                  <button
                    type="button"
                    onClick={() => onCalcs(calcs.filter((x) => x.id !== c.id))}
                    disabled={!!by}
                    aria-label={`Удалить столбец «${c.name}»`}
                    title={by ? `Сначала уберите его из формулы «${by.name}»` : 'Удалить столбец'}
                    className="grid size-9 place-items-center rounded-lg text-muted-foreground hover:bg-di-surface-high hover:text-foreground disabled:opacity-30"
                  >
                    <X className="size-4" aria-hidden />
                  </button>
                </li>
              )
            })}
          </ul>
        )}
        <Button onClick={() => setEdit({ id: Date.now(), name: '', expr: '', total: 'sum' })}>
          <Plus className="size-4" aria-hidden /> Новый столбец
        </Button>
      </>
    )

  const op = 'h-10 rounded-lg bg-di-surface-high text-lg font-semibold text-primary hover:bg-di-surface-highest'
  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(e) => {
        e.preventDefault()
        save()
      }}
    >
      <label className="flex flex-col gap-1.5">
        <span className="text-sm font-medium text-foreground">Название столбца</span>
        <input autoFocus value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} placeholder={example} className={cn(field, 'h-10')} />
      </label>
      <label className="flex flex-col gap-1.5">
        <span className="text-sm font-medium text-foreground">Формула</span>
        <textarea
          ref={area}
          rows={3}
          value={edit.expr}
          onChange={(e) => setEdit({ ...edit, expr: e.target.value })}
          placeholder="Щёлкните столбец ниже, затем знак, затем следующий столбец или число"
          className={cn(field, 'resize-none py-2 leading-snug')}
        />
      </label>
      <div className="grid grid-cols-6 gap-1.5">
        {['+', '−', '×', '÷', '(', ')'].map((k) => (
          <button key={k} type="button" onClick={() => put(k)} className={op} aria-label={`Знак ${k}`}>
            {k}
          </button>
        ))}
      </div>
      <div>
        <div className="mb-1.5 text-xs text-muted-foreground">Числовые столбцы</div>
        <div className="flex flex-wrap gap-1.5">
          {nums.map((h) => (
            <button
              key={h}
              type="button"
              onClick={() => put(`[${h}]`)}
              className="rounded-full border border-di-outline-variant bg-di-surface-lowest px-3 py-1.5 text-xs font-medium text-foreground hover:border-primary hover:text-primary"
            >
              {h}
            </button>
          ))}
        </div>
      </div>
      <label className="flex flex-col gap-1.5">
        <span className="text-sm font-medium text-foreground">Итог внизу таблицы</span>
        <select value={edit.total} onChange={(e) => setEdit({ ...edit, total: e.target.value as CalcTotal })} className={cn(field, 'h-10')}>
          {TOTAL.map(([k, t]) => (
            <option key={k} value={k}>
              {t}
            </option>
          ))}
        </select>
        <span className="text-xs leading-snug text-muted-foreground">
          Для деления берите «Формула по итогам»: итог посчитается из итогов столбцов, а не сложением частных.
        </span>
      </label>
      <div role="status" className="rounded-lg bg-di-surface-low p-3 text-xs">
        {err ? (
          <span className={tried ? 'font-medium text-red-700 dark:text-red-400' : 'text-muted-foreground'}>{err}</span>
        ) : sample ? (
          <span className="text-di-on-surface-variant">
            В первой подходящей строке: <span className="text-sm font-bold text-foreground">{num(calcValue(edit.expr, head, sample) as number)}</span>
          </span>
        ) : (
          <span className="text-muted-foreground">В строках нет чисел для этой формулы, столбец будет пустым.</span>
        )}
      </div>
      <div className="flex gap-2">
        <Button type="submit">{at < 0 ? 'Добавить столбец' : 'Сохранить'}</Button>
        <Button
          type="button"
          variant="ghost"
          onClick={() => {
            setEdit(null)
            setTried(false)
          }}
        >
          Отмена
        </Button>
      </div>
    </form>
  )
}

export function ReportTools({
  panel,
  report,
  onClose,
  sel,
  onClearSel,
  head,
  cols,
  onCols,
  defaultCols,
  rows,
  calcs,
  onCalcs,
  search,
  onSearch,
  hits,
  at,
  onAt,
  searchHint,
  formulaExample,
  compare,
  help,
}: {
  panel: Panel
  report: string
  onClose: () => void
  sel: Picked[]
  onClearSel: () => void
  head: string[]
  cols: Cols
  onCols: (c: Cols) => void
  defaultCols: Cols
  rows: Cell[][]
  calcs: CalcCol[]
  onCalcs: (c: CalcCol[]) => void
  search: string
  onSearch: (s: string) => void
  hits: number
  at: number
  onAt: (n: number) => void
  searchHint: string
  formulaExample: string
  compare: ReactNode
  help: ReactNode
}) {
  const order = cols.order.length === head.length ? cols.order : head.map((_, i) => i)
  const move = (pos: number, to: number) => {
    if (to < 0 || to >= order.length) return
    const next = [...order]
    const [x] = next.splice(pos, 1)
    next.splice(to, 0, x)
    onCols({ ...cols, order: next })
  }
  const shown = order.filter((i) => !cols.hidden.includes(i)).length
  const now = hits ? (((at % hits) + hits) % hits) + 1 : 0
  const arrow = 'grid size-8 place-items-center rounded-lg text-muted-foreground hover:bg-di-surface-high hover:text-foreground disabled:opacity-30'

  return (
    <Shell panel={panel} report={report} onClose={onClose}>
      {panel === 'help' && help}

      {panel === 'calc' && (
        <>
          <Selection sel={sel} onClear={onClearSel} report={report} />
          <Calc report={report} />
        </>
      )}

      {panel === 'pins' && <Pins />}

      {panel === 'formula' && <Formulas head={head} rows={rows} calcs={calcs} onCalcs={onCalcs} example={formulaExample} />}

      {panel === 'search' && (
        <>
          <input
            type="text"
            autoFocus
            value={search}
            onChange={(e) => {
              onSearch(e.target.value)
              onAt(0)
            }}
            onKeyDown={(e) => e.key === 'Enter' && hits > 0 && onAt(at + (e.shiftKey ? -1 : 1))}
            placeholder={searchHint}
            aria-label="Искать в таблице"
            className={cn(field, 'h-10')}
          />
          <div className="flex items-center justify-between gap-3">
            <span role="status" className="text-sm text-di-on-surface-variant">
              {search.trim().length < 2 ? 'Введите от двух символов' : hits ? `Совпадение ${now} из ${hits}` : 'Совпадений нет'}
            </span>
            <span className="flex gap-1.5">
              <Button variant="outline" size="sm" disabled={!hits} onClick={() => onAt(at - 1)} aria-label="Предыдущее совпадение">
                <ChevronUp className="size-4" aria-hidden />
              </Button>
              <Button variant="outline" size="sm" disabled={!hits} onClick={() => onAt(at + 1)} aria-label="Следующее совпадение">
                <ChevronDown className="size-4" aria-hidden />
              </Button>
            </span>
          </div>
          <p className="text-xs leading-relaxed text-muted-foreground">
            Поиск идёт по всем строкам таблицы, а не только по открытой странице: таблица сама перелистывается к совпадению. Enter
            переходит к следующему, Shift+Enter к предыдущему. Строки он не убирает — для отбора есть фильтр в меню столбца.
          </p>
        </>
      )}

      {panel === 'columns' && (
        <>
          <p className="text-xs leading-relaxed text-muted-foreground">
            Снимите флажок, чтобы скрыть столбец, стрелками поменяйте порядок. Настройка запоминается для этого экрана.
          </p>
          <ul className="flex flex-col divide-y divide-di-outline-variant/50">
            {order.map((i, pos) => {
              const on = !cols.hidden.includes(i)
              return (
                <li key={i} className="flex items-center gap-2 py-1">
                  <label className="flex min-h-9 flex-1 cursor-pointer items-center gap-2.5 text-sm text-foreground">
                    <input
                      type="checkbox"
                      className="size-4 accent-primary"
                      checked={on}
                      disabled={on && shown === 1}
                      onChange={() => onCols({ ...cols, order, hidden: on ? [...cols.hidden, i] : cols.hidden.filter((x) => x !== i) })}
                    />
                    <span className={on ? undefined : 'text-muted-foreground line-through'}>{head[i]}</span>
                  </label>
                  <button type="button" onClick={() => move(pos, pos - 1)} disabled={pos === 0} aria-label={`Поднять «${head[i]}»`} className={arrow}>
                    <ArrowUp className="size-4" aria-hidden />
                  </button>
                  <button
                    type="button"
                    onClick={() => move(pos, pos + 1)}
                    disabled={pos === order.length - 1}
                    aria-label={`Опустить «${head[i]}»`}
                    className={arrow}
                  >
                    <ArrowDown className="size-4" aria-hidden />
                  </button>
                </li>
              )
            })}
          </ul>
          <Button variant="outline" size="sm" onClick={() => onCols(defaultCols)}>
            Вернуть как было
          </Button>
        </>
      )}

      {panel === 'compare' && compare}
    </Shell>
  )
}
