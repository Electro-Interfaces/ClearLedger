import {
  ArrowDown, ArrowLeftRight, ArrowUp, Calculator, ChevronDown, ChevronUp, CircleHelp, ClipboardList, Columns3, Delete,
  Copy, Plus, SquareFunction, TextSearch, X,
} from 'lucide-react'
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import {
  addPin, calcValue, checkCalc, commitExpr, dropPin, evaluate, feedNumber, pickResult, refsOf, setExpr, setPickMode, textOf, useTools,
  type CalcCol, type CalcTotal, type PickMode,
} from './calc'
import { isMoney, num2, qty, type Cell } from './format'
import { setRail, type Panel } from './rail'
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

const MODES: { key: PickMode; label: string; sign: string; hint: string }[] = [
  { key: 'sum', label: 'Сумма', sign: '+', hint: 'Складывает выделенное' },
  { key: 'sub', label: 'Разность', sign: '−', hint: 'Из первого выделенного вычитает остальные по порядку щелчков' },
  { key: 'mul', label: 'Произв.', sign: '×', hint: 'Перемножает выделенное' },
  { key: 'div', label: 'Частное', sign: '÷', hint: 'Первое выделенное делит на остальные по порядку щелчков' },
  { key: 'avg', label: 'Среднее', sign: 'ср', hint: 'Среднее по выделенному' },
]

function copy(text: string) {
  void navigator.clipboard?.writeText(text).catch(() => undefined)
}

function Selection({ sel, miss, onRemove, onClear, report }: {
  sel: Picked[]; miss: string | null; onRemove: (key: string) => void; onClear: () => void; report: string
}) {
  const { mode } = useTools()
  const nums = sel.map((x) => x.value as number)
  const money = !!sel.length && sel.every((x) => isMoney(x.label))
  const m = MODES.find((x) => x.key === mode)!
  const result = pickResult(nums, mode)
  const shown = (v: number) => (v < 0 && mode !== 'sum' ? `(${num(v, money)})` : num(v, money))
  const formula = mode === 'avg'
    ? `(${nums.map((v) => shown(v)).join(' + ')}) ÷ ${nums.length}`
    : nums.map((v) => shown(v)).join(` ${m.sign} `)
  const stat = (label: string, value: string) => (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-sm font-semibold tabular-nums text-foreground">{value}</dd>
    </div>
  )
  const sum = nums.reduce((a, b) => a + b, 0)
  return (
    <section aria-label="Выделенное" className="flex flex-col gap-2.5 rounded-lg bg-di-surface-low p-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-foreground">Выделенное</h3>
        {!!sel.length && (
          <button type="button" onClick={onClear} className="text-xs font-semibold text-primary hover:underline">
            Снять выделение
          </button>
        )}
      </div>
      <div role="radiogroup" aria-label="Действие с выделенным" className="grid grid-cols-5 gap-1 rounded-lg bg-di-surface p-1">
        {MODES.map((x) => (
          <button
            key={x.key}
            type="button"
            role="radio"
            aria-checked={mode === x.key}
            title={x.hint}
            onClick={() => setPickMode(x.key)}
            className={cn(
              'flex h-11 flex-col items-center justify-center rounded-md text-xs font-semibold leading-none transition-colors',
              mode === x.key ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-di-surface-high hover:text-foreground',
            )}
          >
            <span className="text-base">{x.sign}</span>
            <span className="mt-0.5">{x.label}</span>
          </button>
        ))}
      </div>
      {!sel.length ? (
        <p className="text-xs leading-relaxed text-muted-foreground">
          Щёлкайте по числам в таблице — они встанут сюда по порядку, результат считается сразу: по умолчанию сумма, выше можно
          переключить на разность, произведение, частное или среднее. Повторный щелчок снимает число. Пока калькулятор открыт,
          щелчок по строке не открывает её карточку.
        </p>
      ) : (
        <>
          <ul className="flex max-h-48 flex-col gap-1 overflow-y-auto">
            {sel.map((x, k) => (
              <li key={x.key} className="flex items-center gap-2 rounded-md bg-di-surface-mid px-2 py-1 text-xs">
                <span className="w-4 shrink-0 text-center text-muted-foreground">{k === 0 ? '' : m.sign === 'ср' ? '+' : m.sign}</span>
                <span className="min-w-0 flex-1 truncate text-di-on-surface-variant" title={`${x.row ?? ''} · ${x.label}`}>
                  {x.row ? `${x.row} · ` : ''}{x.label}
                </span>
                <span className="shrink-0 font-semibold tabular-nums text-foreground">{num(x.value as number, isMoney(x.label))}</span>
                <button
                  type="button"
                  onClick={() => onRemove(x.key)}
                  aria-label={`Убрать ${num(x.value as number)}`}
                  className="grid size-6 shrink-0 place-items-center rounded text-muted-foreground hover:bg-di-surface-high hover:text-foreground"
                >
                  <X className="size-3.5" aria-hidden />
                </button>
              </li>
            ))}
          </ul>
          <div className="rounded-md border border-di-outline-variant/60 bg-di-surface-mid px-3 py-2">
            <div className="break-words text-xs tabular-nums text-muted-foreground">{formula} =</div>
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-xs text-muted-foreground">{m.label === 'Произв.' ? 'Произведение' : m.label}</span>
              <output className="font-headline text-2xl font-extrabold tabular-nums text-foreground">
                {result === null ? 'деление на 0' : num(result, money && mode !== 'mul' && mode !== 'div')}
              </output>
            </div>
          </div>
          {sel.length > 1 && (
            <dl className="grid grid-cols-4 gap-x-2">
              {stat('Сумма', num(sum, money))}
              {stat('Среднее', num(sum / nums.length, money))}
              {stat('Мин.', num(Math.min(...nums), money))}
              {stat('Макс.', num(Math.max(...nums), money))}
            </dl>
          )}
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              disabled={result === null}
              onClick={() => result !== null && addPin(`${report}: ${m.label.toLowerCase()} ${nums.length} чисел — ${formula}`, result, money)}
            >
              <ClipboardList className="size-3.5" aria-hidden /> Отложить
            </Button>
            <Button variant="outline" size="sm" disabled={result === null} onClick={() => result !== null && setExpr(textOf(result))}>
              В калькулятор
            </Button>
            <Button variant="outline" size="sm" disabled={result === null} onClick={() => result !== null && copy(textOf(result))} title="Скопировать результат">
              <Copy className="size-3.5" aria-hidden />
            </Button>
          </div>
        </>
      )}
      {miss && <p className="text-xs text-amber-700 dark:text-amber-400">«{miss}» — не число, в расчёт не взято.</p>}
    </section>
  )
}

const KEYS = ['C', '(', ')', '÷', '7', '8', '9', '×', '4', '5', '6', '−', '1', '2', '3', '+', '0', ',', '%', '⌫']

function Calc({ report }: { report: string }) {
  const { expr, history } = useTools()
  const value = evaluate(expr)
  const press = (k: string) => {
    if (k === 'C') return setExpr('')
    if (k === '⌫') return setExpr(expr.trimEnd().slice(0, -1).trimEnd())
    setExpr(/[÷×−+]/.test(k) ? `${expr.trimEnd()} ${k} ` : `${expr}${k}`)
  }
  const key = 'h-10 rounded-lg text-lg font-semibold transition-colors'
  return (
    <section aria-label="Калькулятор" className="flex flex-col gap-2.5">
      <h3 className="text-sm font-semibold text-foreground">Калькулятор</h3>
      <input
        value={expr}
        onChange={(e) => setExpr(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && commitExpr()}
        placeholder="0"
        aria-label="Выражение"
        inputMode="decimal"
        className={cn(field, 'h-11 text-right text-lg tabular-nums')}
      />
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-xs text-muted-foreground">{expr.trim() && value === null ? 'Выражение не закончено' : 'Результат'}</span>
        <span className="flex items-baseline gap-2">
          <output className="font-headline text-2xl font-extrabold tabular-nums text-foreground">{value === null ? '0' : num(value)}</output>
          {value !== null && (
            <button type="button" onClick={() => copy(textOf(value))} title="Скопировать результат" aria-label="Скопировать результат"
              className="grid size-7 place-items-center rounded text-muted-foreground hover:bg-di-surface-high hover:text-foreground">
              <Copy className="size-3.5" aria-hidden />
            </button>
          )}
        </span>
      </div>
      <div className="grid grid-cols-4 gap-1.5">
        {KEYS.map((k) => (
          <button
            key={k}
            type="button"
            onClick={() => press(k)}
            aria-label={k === '⌫' ? 'Стереть символ' : k === 'C' ? 'Очистить' : undefined}
            className={cn(
              key,
              /\d|,/.test(k)
                ? 'bg-di-surface-lowest text-foreground hover:bg-di-surface-high'
                : k === 'C' || k === '⌫'
                  ? 'bg-di-surface-high text-di-on-surface-variant hover:bg-di-surface-highest'
                  : 'bg-di-surface-high text-primary hover:bg-di-surface-highest',
            )}
          >
            {k === '⌫' ? <Delete className="mx-auto size-5" aria-hidden /> : k}
          </button>
        ))}
        <button
          type="button"
          onClick={commitExpr}
          disabled={value === null}
          className={cn(key, 'col-span-4 bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-40')}
        >
          =
        </button>
      </div>
      <Button variant="outline" size="sm" disabled={value === null} onClick={() => value !== null && addPin(`${report}: ${expr.trim()}`, value)}>
        <ClipboardList className="size-3.5" aria-hidden /> Отложить результат
      </Button>
      {!!history.length && (
        <div>
          <div className="mb-1 text-xs text-muted-foreground">Недавние вычисления — щелчок подставляет результат</div>
          <ul className="flex flex-col gap-0.5">
            {history.map((h) => (
              <li key={h.id}>
                <button type="button" onClick={() => feedNumber(h.value)}
                  className="flex w-full items-baseline justify-between gap-2 rounded px-1.5 py-1 text-left text-xs hover:bg-di-surface-high">
                  <span className="min-w-0 truncate text-muted-foreground">{h.expr} =</span>
                  <span className="shrink-0 font-semibold tabular-nums text-foreground">{num(h.value)}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
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
    const el = area.current
    const pad = /[+−×÷]/.test(s) ? ` ${s} ` : s
    let caret = 0
    setEdit((was) => {
      if (!was) return was
      const a = el ? el.selectionStart : was.expr.length
      const b = el ? el.selectionEnd : a
      caret = a + pad.length
      return { ...was, expr: was.expr.slice(0, a) + pad + was.expr.slice(b) }
    })
    requestAnimationFrame(() => {
      el?.focus()
      el?.setSelectionRange(caret, caret)
    })
  }
  const putRef = useRef(put)
  useLayoutEffect(() => {
    putRef.current = put
  })
  const editing = !!edit
  useEffect(() => {
    if (!editing) return
    setRail({ insert: (s: string) => putRef.current(s) })
    return () => setRail({ insert: null })
  }, [editing])
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
  onRemoveSel,
  miss,
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
  onRemoveSel: (key: string) => void
  miss: string | null
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
  help?: ReactNode
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
          <Selection sel={sel} miss={miss} onRemove={onRemoveSel} onClear={onClearSel} report={report} />
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
