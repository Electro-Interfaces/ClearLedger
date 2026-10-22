import { ArrowDown, ArrowUp, ChevronDown, ChevronLeft, ChevronRight, ChevronsUpDown, Filter, Pin, Rows3, Sigma } from 'lucide-react'
import {
  Fragment, useEffect, useLayoutEffect, useMemo, useRef, useState,
  type CSSProperties, type PointerEvent as ReactPointerEvent, type ReactNode,
} from 'react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { ColumnMenu, ColumnStats, type Filt } from './ColumnMenu'
import { PageSizeField, usePageSize } from './PageSize'
import { plural, qty, showCell, type Cell } from './format'

export type { Filt }
export type Cols = {
  order: number[]
  hidden: number[]
  pin?: number
  width?: Record<number, number>
  bars?: number[]
}
export type Filters = Record<number, Filt>
export type Picked = { key: string; label: string; value: Cell; row?: string }
export type Mark = {
  has: (row: number) => boolean
  set: (rows: number[], on: boolean) => void
  label: (row: number) => string
}
type Sort = { col: number; dir: 1 | -1 } | null

const DATE = /^(\d{2})\.(\d{2})\.(\d{4})$/
const key = (x: Cell) => (typeof x === 'string' ? x.replace(DATE, '$3-$2-$1') : x)
const LEAD = 40

export function compareCells(a: Cell, b: Cell) {
  const x = key(a)
  const y = key(b)
  if (x === '' || y === '') return x === y ? 0 : x === '' ? 1 : -1
  if (typeof x === 'number' && typeof y === 'number') return x - y
  return String(x).localeCompare(String(y), 'ru', { numeric: true })
}

const round2 = (n: number) => Math.round(n * 100) / 100

export const keepRow = (r: Cell[], filters?: Filters) =>
  !filters ||
  Object.entries(filters).every(([k, f]) => {
    const c = r[Number(k)]
    if (f.in && !f.in.includes(String(c))) return false
    if (f.min != null && !(typeof c === 'number' && c >= f.min)) return false
    if (f.max != null && !(typeof c === 'number' && c <= f.max)) return false
    return true
  })

export function footer(head: string[], rows: Cell[][], total: Cell[] | undefined, all: number, derive?: (t: Cell[]) => Cell[]) {
  if (!total) return undefined
  const cut = rows.length !== all
  const out = head.map((_, i): Cell => {
    const t = total[i] ?? ''
    if (!cut) return t
    if (typeof t === 'number') return round2(rows.reduce((s, r) => s + (typeof r[i] === 'number' ? (r[i] as number) : 0), 0))
    return /^\d/.test(String(t)) ? `${qty(rows.length)} из ${qty(all)}` : t
  })
  return cut && derive ? derive(out) : out
}

function distinct(rows: Cell[][], col: number) {
  const m = new Map<string, { value: string; count: number; raw: Cell }>()
  for (const r of rows) {
    const value = String(r[col])
    const e = m.get(value)
    if (e) e.count++
    else m.set(value, { value, count: 1, raw: r[col] })
  }
  return [...m.values()].sort((a, b) => compareCells(a.raw, b.raw)).map(({ value, count }) => ({ value, count }))
}

const sized = (w?: number): CSSProperties => (w ? { width: w, minWidth: w, maxWidth: w } : {})
const INTERACTIVE = 'a, button, input, select, textarea, label, [role="checkbox"]'

export function SheetTable({
  head,
  rows,
  total,
  caption,
  lines,
  cols,
  onCols,
  groupBy,
  onGroup,
  filters,
  onFilters,
  search,
  searchAt,
  onHits,
  selected,
  onPick,
  onRow,
  onView,
  derive,
  render,
  rowClass,
  mark,
  empty,
  tableAttrs,
  rowTitle,
  onHeadPick,
  defaultWidths,
  expand,
}: {
  head: string[]
  rows: Cell[][]
  total?: Cell[]
  caption: ReactNode
  lines: string[]
  cols?: Cols
  onCols?: (c: Cols) => void
  groupBy?: Record<number, string>
  onGroup?: (col: number) => void
  filters?: Filters
  onFilters?: (f: Filters) => void
  search?: string
  searchAt?: number
  onHits?: (n: number) => void
  selected?: Set<string>
  onPick?: (cell: Picked) => void
  onRow?: (order: number[], pos: number) => void
  onView?: (order: number[]) => void
  derive?: (t: Cell[]) => Cell[]
  render?: (row: number, col: number) => ReactNode | undefined
  rowClass?: (row: number) => string | undefined
  mark?: Mark
  empty?: ReactNode
  tableAttrs?: Record<string, string>
  rowTitle?: (row: number) => string
  onHeadPick?: (col: number) => void
  defaultWidths?: Record<number, number>
  expand?: (row: number) => ReactNode
}) {
  const [sort, setSort] = useState<Sort>(null)
  const size = usePageSize() || Math.max(1, rows.length)
  const [page, setPage] = useState(0)
  const [drag, setDrag] = useState<{ from: number; over: number | null } | null>(null)
  const [menu, setMenu] = useState<{ col: number; anchor: HTMLElement } | null>(null)
  const [stats, setStats] = useState<{ col: number; anchor: HTMLElement } | null>(null)
  const [live, setLive] = useState<{ col: number; w: number } | null>(null)
  const [lefts, setLefts] = useState<number[]>([])
  const [fixedWidth, setFixedWidth] = useState(0)
  const resizing = useRef(false)
  const ths = useRef<(HTMLTableCellElement | null)[]>([])
  const tableRef = useRef<HTMLTableElement>(null)
  const box = useRef<HTMLDivElement>(null)
  const horizontal = useRef<HTMLDivElement>(null)
  const [scrollWidth, setScrollWidth] = useState(0)
  const [autoWidths, setAutoWidths] = useState<number[]>([])
  const panned = useRef(false)
  const [wide, setWide] = useState(false)
  const [panning, setPanning] = useState(false)
  const [more, setMore] = useState(false)
  const [cur, setCur] = useState<number | null>(null)
  const activeRef = useRef<HTMLTableRowElement>(null)
  const found = useRef<HTMLTableCellElement>(null)
  const lead = mark ? LEAD : 0

  useEffect(() => {
    setPage(0)
  }, [size, filters])

  const view = useMemo(() => {
    const order = cols?.order.length === head.length ? cols.order : head.map((_, i) => i)
    return order.filter((i) => !cols?.hidden.includes(i))
  }, [cols, head])
  const patch = (p: Partial<Cols>) => onCols?.({ ...(cols ?? { order: head.map((_, i) => i), hidden: [] }), ...p })
  const moveCol = (from: number, to: number) => {
    if (!onCols || from === to) return
    const order = cols?.order.length === head.length ? [...cols.order] : head.map((_, i) => i)
    const right = order.indexOf(from) < order.indexOf(to)
    order.splice(order.indexOf(from), 1)
    order.splice(order.indexOf(to) + (right ? 1 : 0), 0, from)
    patch({ order })
  }
  const widthOf = (i: number) => (live?.col === i ? live.w : cols?.width?.[i] ?? defaultWidths?.[i] ?? autoWidths[i] ?? 120)
  const tableWidth = lead + view.reduce((sum, i) => sum + widthOf(i), 0)
  const pin = Math.min(cols?.pin ?? 0, view.length)

  // Авторазмер берётся со всего набора, а не с текущей страницы. Иначе длинная
  // строка на странице 2 меняет геометрию таблицы и положение полосы прокрутки.
  useLayoutEffect(() => {
    const table = tableRef.current
    const context = document.createElement('canvas').getContext('2d')
    if (!table || !context) return
    let disposed = false
    const measure = () => {
      if (disposed) return
      const style = getComputedStyle(table)
      context.font = `${style.fontSize} ${style.fontFamily}`
      const cache = new Map<string, number>()
      const textWidth = (value: Cell, col: number) => {
        const text = String(showCell(value, head[col]) ?? '')
        let width = cache.get(text)
        if (width === undefined) {
          width = context.measureText(text).width
          cache.set(text, width)
        }
        return width
      }
      const widths = head.map((title, col) => {
        // Заголовок может переноситься; значения читаются в одну строку.
        let width = Math.min(180, context.measureText(title).width * 12 / 14 + 24)
        for (const row of rows) width = Math.max(width, textWidth(row[col] ?? '', col) + 24)
        if (total) width = Math.max(width, textWidth(total[col] ?? '', col) + 24)
        return Math.ceil(Math.max(72, Math.min(480, width)))
      })
      setAutoWidths((was) => was.length === widths.length && was.every((w, i) => w === widths[i]) ? was : widths)
    }
    measure()
    void document.fonts.ready.then(measure)
    document.fonts.addEventListener('loadingdone', measure)
    return () => {
      disposed = true
      document.fonts.removeEventListener('loadingdone', measure)
    }
  }, [head, rows, total])

  useLayoutEffect(() => {
    const measure = () => {
      let acc = lead
      const next = view.slice(0, pin).map((_, k) => {
        const at = Math.floor(acc)
        acc += ths.current[k]?.getBoundingClientRect().width ?? 0
        return at
      })
      setLefts((was) => (was.length === next.length && was.every((x, k) => x === next[k]) ? was : next))
      setFixedWidth(Math.floor(acc))
    }
    measure()
    if (!pin || !tableRef.current) return
    const ro = new ResizeObserver(measure)
    ro.observe(tableRef.current)
    return () => ro.disconnect()
  }, [view, pin, cols?.width, live, lead])

  useLayoutEffect(() => {
    const el = box.current
    if (!el) return
    const check = () => {
      setWide(el.scrollWidth > el.clientWidth + 1)
      setMore(el.scrollLeft < el.scrollWidth - el.clientWidth - 1)
      const bar = horizontal.current
      // У основной области может быть вертикальная полоса. Уравниваем именно
      // диапазоны прокрутки, чтобы верхняя полоса доходила до последнего столбца.
      setScrollWidth(el.scrollWidth + (bar?.clientWidth || el.clientWidth) - el.clientWidth)
      if (bar && Math.abs(bar.scrollLeft - el.scrollLeft) > 1) bar.scrollLeft = el.scrollLeft
    }
    check()
    const ro = new ResizeObserver(check)
    ro.observe(el)
    if (horizontal.current) ro.observe(horizontal.current)
    if (tableRef.current) ro.observe(tableRef.current)
    el.addEventListener('scroll', check, { passive: true })
    return () => {
      ro.disconnect()
      el.removeEventListener('scroll', check)
    }
  }, [])

  const step = (dir: 1 | -1) => {
    const el = box.current
    if (!el) return
    const fixed = lead + ths.current.slice(0, pin).reduce((s, th) => s + (th?.offsetWidth ?? 0), 0)
    const starts = ths.current.slice(pin, view.length).map((th) => (th ? th.offsetLeft - fixed : 0))
    const now = el.scrollLeft
    const to = dir > 0 ? starts.find((x) => x > now + 1) : [...starts].reverse().find((x) => x < now - 1)
    el.scrollTo({ left: to ?? (dir > 0 ? el.scrollWidth : 0), behavior: 'smooth' })
  }

  const startPan = (e: ReactPointerEvent<HTMLElement>) => {
    const el = box.current
    if (!el || !wide || e.pointerType !== 'mouse' || e.button !== 0) return
    if ((e.target as HTMLElement).closest('table') !== tableRef.current) return
    if ((e.target as HTMLElement).closest(`[data-pinned], ${INTERACTIVE}`)) return
    const x0 = e.clientX
    const s0 = el.scrollLeft
    panned.current = false
    const move = (ev: PointerEvent) => {
      const dx = ev.clientX - x0
      if (!panned.current && Math.abs(dx) < 6) return
      if (!panned.current) {
        panned.current = true
        setPanning(true)
        window.getSelection()?.removeAllRanges()
      }
      el.scrollLeft = s0 - dx
    }
    const up = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      setPanning(false)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  const startResize = (e: ReactPointerEvent<HTMLSpanElement>, col: number) => {
    e.preventDefault()
    e.stopPropagation()
    const el = e.currentTarget
    const x0 = e.clientX
    const w0 = (el.parentElement as HTMLElement).offsetWidth
    let w = w0
    resizing.current = true
    el.setPointerCapture(e.pointerId)
    const move = (ev: PointerEvent) => {
      w = Math.max(56, Math.round(w0 + ev.clientX - x0))
      setLive({ col, w })
    }
    const up = () => {
      el.removeEventListener('pointermove', move)
      el.removeEventListener('pointerup', up)
      resizing.current = false
      setLive(null)
      if (w !== w0) patch({ width: { ...cols?.width, [col]: w } })
    }
    el.addEventListener('pointermove', move)
    el.addEventListener('pointerup', up)
  }
  const autoWidth = (col: number) => {
    patch({ width: { ...cols?.width, [col]: autoWidths[col] ?? 120 } })
  }
  const edge = 'shadow-[6px_0_8px_-6px_rgb(0_0_0/0.25)]'
  const sticky = (k: number, base: string) =>
    k < pin
      ? { className: cn('sticky', base, k === pin - 1 && edge), style: { left: lefts[k] ?? 0 } }
      : { className: '', style: {} }
  const leadCell = (base: string) => cn('sticky left-0 w-10 min-w-10 max-w-10 px-0 text-center', base, !pin && wide && edge)

  const numeric = useMemo(() => head.map((_, i) => rows.some((r) => typeof r[i] === 'number')), [head, rows])
  const filtered = useMemo(() => rows.map((r, i) => ({ r, i })).filter((x) => keepRow(x.r, filters)), [rows, filters])
  const foot = useMemo(() => footer(head, filtered.map((x) => x.r), total, rows.length, derive), [head, filtered, total, rows.length, derive])
  const barMax = useMemo(() => {
    const out: Record<number, number> = {}
    for (const c of cols?.bars ?? []) out[c] = Math.max(0, ...filtered.map((x) => (typeof x.r[c] === 'number' ? Math.abs(x.r[c] as number) : 0)))
    return out
  }, [cols?.bars, filtered])
  const nFilters = Object.keys(filters ?? {}).length
  const sorted = useMemo(() => {
    const list = [...filtered]
    if (!sort) return list
    return list.sort((a, b) => {
      const d = compareCells(a.r[sort.col], b.r[sort.col])
      const blank = a.r[sort.col] === '' || b.r[sort.col] === ''
      return (blank ? d : d * sort.dir) || a.i - b.i
    })
  }, [filtered, sort])

  useEffect(() => {
    onView?.(sorted.map((x) => x.i))
  }, [sorted, onView])

  const needle = (search ?? '').trim().toLowerCase()
  const hits = useMemo(() => {
    if (needle.length < 2) return []
    const out: { row: number; id: string }[] = []
    sorted.forEach((x, row) =>
      view.forEach((c) => {
        if (String(showCell(x.r[c], head[c])).toLowerCase().includes(needle)) out.push({ row, id: `${x.i}:${c}` })
      }),
    )
    return out
  }, [needle, sorted, view, head])
  const hitIds = useMemo(() => new Set(hits.map((h) => h.id)), [hits])
  const current = hits.length ? hits[(((searchAt ?? 0) % hits.length) + hits.length) % hits.length] : null

  useEffect(() => {
    onHits?.(hits.length)
  }, [hits.length, onHits])
  useEffect(() => {
    if (current) setPage(Math.floor(current.row / size))
  }, [current, size])
  useEffect(() => {
    const tr = activeRef.current
    const el = box.current
    if (!tr || !el) return
    const top = tableRef.current?.tHead?.offsetHeight ?? 0
    const bottom = tableRef.current?.tFoot?.offsetHeight ?? 0
    if (tr.offsetTop - top < el.scrollTop) el.scrollTop = tr.offsetTop - top
    else if (tr.offsetTop + tr.offsetHeight > el.scrollTop + el.clientHeight - bottom)
      el.scrollTop = tr.offsetTop + tr.offsetHeight - el.clientHeight + bottom
  }, [cur, page])
  useEffect(() => {
    setCur(null)
  }, [rows, filters, sort])
  useEffect(() => {
    found.current?.scrollIntoView({ block: 'center', inline: 'center' })
  }, [current?.id, page])

  const toggle = (col: number) => {
    if (onHeadPick && numeric[col]) return onHeadPick(col)
    setPage(0)
    setSort((s) =>
      s?.col !== col ? { col, dir: numeric[col] ? -1 : 1 } : s.dir === (numeric[col] ? -1 : 1) ? { col, dir: numeric[col] ? 1 : -1 } : null,
    )
  }
  const open = (pos: number) => {
    tableRef.current?.tBodies[0]?.querySelector<HTMLTableRowElement>(':scope > tr[data-report-row="' + sorted[pos]?.i + '"]')?.focus({ preventScroll: true })
    onRow?.(
      sorted.map((x) => x.i),
      pos,
    )
  }
  const pages = Math.max(1, Math.ceil(sorted.length / size))
  const at = Math.min(page, pages - 1)
  const from = at * size
  const slice = sorted.slice(from, from + size)
  const markedAll = !!mark && !!sorted.length && sorted.every((x) => mark.has(x.i))
  const markIcon = 'size-3.5 shrink-0 text-primary'
  const headBtn = 'grid h-8 w-8 shrink-0 place-items-center rounded-md text-primary hover:bg-di-surface-highest'

  return (
    <section className="overflow-hidden rounded-lg border border-border/60 bg-di-surface-mid">
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 px-3 py-2.5">
        <p className="text-sm text-foreground">
          {caption}
          {lines.map((l) => (
            <span key={l} className="text-muted-foreground">
              {' '}
              · {l}
            </span>
          ))}
        </p>
        <p className="text-xs text-muted-foreground">
          {nFilters > 0 && (
            <>
              <Filter className="mr-1 inline size-3.5 -translate-y-px text-primary" aria-hidden />
              отобрано {qty(filtered.length)} из{' '}
            </>
          )}
          {qty(rows.length)} {plural(rows.length, 'строка', 'строки', 'строк')}
          {nFilters > 0 && onFilters && (
            <button
              type="button"
              onClick={() => onFilters({})}
              className="ml-1.5 rounded-md px-1.5 font-semibold text-primary hover:bg-di-surface-high"
            >
              снять {nFilters > 1 ? 'фильтры' : 'фильтр'}
            </button>
          )}
          {view.length < head.length && <> · скрыто столбцов: {head.length - view.length}</>}
          {sort && (
            <>
              {' '}
              · сортировка: {head[sort.col].toLowerCase()}, {sort.dir === 1 ? 'по возрастанию' : 'по убыванию'}
            </>
          )}
        </p>
      </div>

      <div
        ref={horizontal}
        role="region"
        aria-label="Горизонтальная прокрутка таблицы"
        tabIndex={wide ? 0 : -1}
        hidden={!wide}
        onKeyDown={(e) => {
          const el = box.current
          if (!el || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return
          e.preventDefault()
          e.stopPropagation()
          el.scrollLeft = e.key === 'Home' ? 0 : e.key === 'End' ? el.scrollWidth
            : el.scrollLeft + (e.key === 'ArrowRight' ? 80 : -80)
          e.currentTarget.scrollLeft = el.scrollLeft
        }}
        onScroll={(e) => {
          const el = box.current
          if (el && Math.abs(el.scrollLeft - e.currentTarget.scrollLeft) > 1) el.scrollLeft = e.currentTarget.scrollLeft
        }}
        className="h-4 overflow-x-auto overflow-y-hidden border-t border-di-outline-variant/60 outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary/40"
      >
        <div aria-hidden style={{ width: scrollWidth, height: 1 }} />
      </div>
      <div className="relative">
        <div
          ref={box}
          tabIndex={0}
          aria-label={onPick ? 'Таблица: выбирайте числовые ячейки для калькулятора, повторное нажатие снимает выделение'
            : expand ? 'Группы: щёлкните по строке или нажмите Enter, чтобы раскрыть состав группы'
              : onRow ? 'Таблица: щёлкните по строке и двигайтесь стрелками, Enter открывает карточку строки'
                : 'Таблица: щёлкните по строке и двигайтесь стрелками'}
          style={{ scrollPaddingLeft: fixedWidth }}
          onClickCapture={(e) => {
            const target = e.target as HTMLElement
            if (target.closest('table') !== tableRef.current) return
            const td = target.closest<HTMLElement>('tbody td[data-pos]')
            if (!panned.current && td) setCur(Number(td.dataset.pos))
            if (target.closest(INTERACTIVE)) return
            if (onRow && !expand && pin > 0 && td && !td.hasAttribute('data-pinned') && !onPick) {
              e.stopPropagation()
              box.current?.focus({ preventScroll: true })
              return
            }
            if (!panned.current) return
            panned.current = false
            e.stopPropagation()
            e.preventDefault()
          }}
          onKeyDown={(e) => {
            const target = e.target as HTMLElement
            const nested = target.closest('table')
            if (nested && nested !== tableRef.current) return
            if (target.closest('input, select, textarea, button, a')) return
            if (e.key === 'Escape' && cur !== null) return setCur(null)
            if (e.key === 'Enter' && cur !== null && onRow) {
              e.preventDefault()
              e.stopPropagation()
              return open(cur)
            }
            if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
              e.preventDefault()
              e.stopPropagation()
              return step(e.key === 'ArrowLeft' ? -1 : 1)
            }
            if ((e.key !== 'ArrowUp' && e.key !== 'ArrowDown') || !sorted.length) return
            e.preventDefault()
            e.stopPropagation()
            const pos = Math.min(Math.max((cur ?? from - 1) + (e.key === 'ArrowUp' ? -1 : 1), 0), sorted.length - 1)
            setCur(pos)
            if (Math.floor(pos / size) !== at) setPage(Math.floor(pos / size))
          }}
          className="max-h-[calc(100dvh-16rem)] min-h-[240px] overflow-auto border-t border-di-outline-variant/60 outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary/40"
        >
          <table ref={tableRef} {...tableAttrs} style={{ tableLayout: 'fixed', width: tableWidth, minWidth: '100%' }} className="border-separate border-spacing-0 text-sm">
            <colgroup>
              {mark && <col style={{ width: LEAD }} />}
              {view.map((i) => <col key={i} style={{ width: widthOf(i) }} />)}
              <col />
            </colgroup>
            <thead>
              <tr>
                {mark && (
                  <th scope="col" className={leadCell('top-0 z-30 border-b border-di-outline-variant bg-di-surface-low')}>
                    <input
                      type="checkbox"
                      className="size-4 align-middle accent-primary"
                      checked={markedAll}
                      onChange={(e) => mark.set(sorted.map((x) => x.i), e.target.checked)}
                      aria-label="Отметить все строки"
                    />
                  </th>
                )}
                {view.map((i, k) => {
                  const on = sort?.col === i
                  const Icon = !on ? ChevronsUpDown : sort.dir === 1 ? ArrowUp : ArrowDown
                  const w = widthOf(i)
                  const st = sticky(k, 'z-20')
                  return (
                    <th
                      key={i}
                      ref={(el) => {
                        ths.current[k] = el
                      }}
                      style={{ ...st.style, ...sized(w) }}
                      scope="col"
                      aria-sort={!on ? 'none' : sort.dir === 1 ? 'ascending' : 'descending'}
                      draggable={!!onCols}
                      onDragStart={(e) => {
                        if (resizing.current) return e.preventDefault()
                        e.dataTransfer.effectAllowed = 'move'
                        setDrag({ from: i, over: null })
                      }}
                      onDragOver={(e) => {
                        if (!drag) return
                        e.preventDefault()
                        if (drag.over !== i) setDrag({ ...drag, over: i })
                      }}
                      onDrop={(e) => {
                        e.preventDefault()
                        if (drag) moveCol(drag.from, i)
                        setDrag(null)
                      }}
                      onDragEnd={() => setDrag(null)}
                      className={cn(
                        'sticky top-0 z-10 border-b border-di-outline-variant bg-di-surface-low p-0 align-bottom',
                        st.className,
                        numeric[i] ? 'text-right' : 'text-left',
                        onCols && 'cursor-grab active:cursor-grabbing',
                        drag?.from === i && 'opacity-40',
                        drag &&
                          drag.over === i &&
                          drag.from !== i &&
                          (view.indexOf(drag.from) < view.indexOf(i) ? 'shadow-[inset_-3px_0_0_var(--color-primary)]' : 'shadow-[inset_3px_0_0_var(--color-primary)]'),
                      )}
                    >
                      <div className="group relative flex min-h-10 items-stretch transition-colors focus-within:bg-di-surface-high hover:bg-di-surface-high">
                        <button
                          type="button"
                          onClick={() => toggle(i)}
                          title={onHeadPick && numeric[i] ? `Вставить «${head[i]}» в формулу` : onCols ? `Сортировать по «${head[i]}». Чтобы переставить столбец, перетащите заголовок` : `Сортировать по «${head[i]}»`}
                          className={cn(
                            'flex min-w-0 flex-1 items-center gap-1 rounded-md px-3 py-1.5 text-xs font-medium leading-tight text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary',
                            numeric[i] ? 'flex-row-reverse text-right' : 'text-left',
                            on && 'text-foreground',
                            onHeadPick && numeric[i] && 'text-primary underline decoration-dotted underline-offset-4',
                          )}
                        >
                          <span className={cn('min-w-0 [overflow-wrap:normal] [word-break:keep-all]', (live?.col === i || cols?.width?.[i]) && 'truncate')}>{head[i]}</span>
                          {k === pin - 1 && <Pin className={markIcon} aria-label="Закреплено" />}
                          {filters?.[i] && <Filter className={markIcon} aria-label="Есть фильтр" />}
                          {on && <Icon className="size-3.5 shrink-0 text-primary" aria-hidden />}
                        </button>
                        {onCols && (
                          <div
                            className={cn(
                              'absolute inset-y-0 flex items-center gap-0.5 bg-di-surface-high px-0.5 transition-opacity',
                              numeric[i] ? 'left-0' : 'right-0',
                              menu?.col === i || stats?.col === i
                                ? 'opacity-100'
                                : 'pointer-events-none opacity-0 group-focus-within:pointer-events-auto group-focus-within:opacity-100 group-hover:pointer-events-auto group-hover:opacity-100',
                            )}
                          >
                            {!on && <Icon className="mx-0.5 size-3.5 shrink-0 text-muted-foreground" aria-hidden />}
                            {onGroup && groupBy?.[i] ? (
                              <button
                                type="button"
                                onClick={() => onGroup(i)}
                                aria-label={`Сводная по «${head[i]}»`}
                                title={`Открыть сводную: первый уровень — ${groupBy[i].toLowerCase()}`}
                                className={headBtn}
                              >
                                <Rows3 className="size-3.5" aria-hidden />
                              </button>
                            ) : numeric[i] ? (
                              <button
                                type="button"
                                onClick={(e) => {
                                  const anchor = e.currentTarget
                                  setStats((s) => (s?.col === i ? null : { col: i, anchor }))
                                }}
                                aria-label={`Итоги по столбцу «${head[i]}»`}
                                aria-haspopup="dialog"
                                aria-expanded={stats?.col === i}
                                title="Сумма, среднее, минимум, максимум, количество"
                                className={cn(headBtn, stats?.col === i && 'bg-di-surface-highest')}
                              >
                                <Sigma className="size-3.5" aria-hidden />
                              </button>
                            ) : null}
                            <button
                              type="button"
                              onClick={(e) => {
                                const anchor = e.currentTarget
                                setMenu((m) => (m?.col === i ? null : { col: i, anchor }))
                              }}
                              aria-label={`Меню столбца «${head[i]}»`}
                              aria-haspopup="dialog"
                              aria-expanded={menu?.col === i}
                              title="Сортировка, закрепить, скрыть, фильтр"
                              className={cn(
                                'grid h-8 w-7 shrink-0 place-items-center rounded-md text-muted-foreground hover:bg-di-surface-highest hover:text-foreground',
                                menu?.col === i && 'bg-di-surface-highest text-foreground',
                              )}
                            >
                              <ChevronDown className="size-4" aria-hidden />
                            </button>
                          </div>
                        )}
                      </div>
                      {onCols && (
                        <span
                          role="separator"
                          aria-orientation="vertical"
                          aria-label={`Ширина столбца «${head[i]}»`}
                          title="Потяните, чтобы изменить ширину. Двойной щелчок — по содержимому"
                          onPointerDown={(e) => startResize(e, i)}
                          onDoubleClick={() => autoWidth(i)}
                          className={cn(
                            'absolute right-0 top-0 z-10 h-full w-1.5 cursor-col-resize touch-none transition-colors hover:bg-primary/40',
                            live?.col === i && 'bg-primary/60',
                          )}
                        />
                      )}
                    </th>
                  )
                })}
                <th aria-hidden className="sticky top-0 z-10 border-b border-di-outline-variant bg-di-surface-low p-0" />
              </tr>
            </thead>
            <tbody
              onPointerDown={startPan}
              className={cn(
                wide && 'cursor-grab select-none',
                onRow && pin > 0 && !wide && 'cursor-default',
                panning && 'cursor-grabbing select-none [&_*]:cursor-grabbing',
              )}
            >
              {slice.map((x, n) => {
                const tint = rowClass?.(x.i)
                const active = cur === from + n
                const detail = expand?.(x.i)
                const rowBg = cn('bg-di-surface-mid group-hover/row:bg-di-surface-high', active && '!bg-di-surface-high')
                return (
                  <Fragment key={x.i}>
                  <tr
                    data-report-row={x.i}
                    ref={active ? activeRef : undefined}
                    aria-selected={active || undefined}
                    aria-expanded={expand ? !!detail : undefined}
                    tabIndex={onRow ? 0 : undefined}
                    onClick={
                      onRow &&
                      ((e) => {
                        if (onPick || (e.target as HTMLElement).closest(INTERACTIVE)) return
                        open(from + n)
                      })
                    }
                    onKeyDown={onRow && ((e) => {
                      if (e.key !== 'Enter' || e.target !== e.currentTarget) return
                      e.preventDefault()
                      e.stopPropagation()
                      open(from + n)
                    })}
                    className={cn('group/row outline-none hover:bg-di-surface-high/70', onRow && 'focus-visible:bg-di-surface-high', onRow && !wide && !pin && 'cursor-pointer')}
                  >
                    {mark && (
                      <td data-pinned="" className={leadCell(cn('z-[5] border-b border-di-outline-variant/40', rowBg))}>
                        <input
                          type="checkbox"
                          className="size-4 align-middle accent-primary"
                          checked={mark.has(x.i)}
                          onChange={(e) => mark.set([x.i], e.target.checked)}
                          aria-label={`Отметить ${mark.label(x.i)}`}
                        />
                      </td>
                    )}
                    {view.map((i, k) => {
                      const id = `${x.i}:${i}`
                      const picked = selected?.has(id)
                      const hit = hitIds.has(id)
                      const now = current?.id === id
                      const w = widthOf(i)
                      const pinned = k < pin
                      const st = sticky(k, cn('z-[5]', rowBg))
                      const v = x.r[i]
                      const bar = barMax[i] && typeof v === 'number' ? Math.round((Math.abs(v) / barMax[i]) * 100) : 0
                      const custom = render?.(x.i, i)
                      return (
                        <td
                          key={i}
                          ref={now ? found : undefined}
                          data-pinned={pinned ? '' : undefined}
                          data-pos={from + n}
                          data-col={i}
                          title={w || (!numeric[i] && custom === undefined) ? String(showCell(v, head[i])) || undefined : undefined}
                          style={{
                            ...st.style,
                            ...sized(w),
                            ...(bar ? { backgroundImage: `linear-gradient(to right, color-mix(in srgb, var(--color-primary) 16%, transparent) ${bar}%, transparent ${bar}%)` } : {}),
                          }}
                          onClick={onPick ? () => onPick({ key: id, label: head[i], value: v, row: rowTitle?.(x.i) }) : undefined}
                          aria-selected={onPick ? !!picked : undefined}
                          className={cn(
                            'whitespace-nowrap border-b border-di-outline-variant/40 px-3 py-2',
                            st.className,
                            !pinned && tint,
                            active && !picked && !now && '!bg-di-surface-high text-foreground',
                            pinned && onRow && !onPick && '!cursor-pointer',
                            w && 'overflow-hidden text-ellipsis',
                            numeric[i] ? 'text-right tabular-nums text-foreground' : 'text-left',
                            onPick && 'cursor-cell',
                            picked
                              ? pinned
                                ? '!bg-[color-mix(in_srgb,var(--color-primary)_15%,var(--di-surface-mid))] text-foreground shadow-[inset_0_0_0_1px_color-mix(in_srgb,var(--color-primary)_50%,transparent)]'
                                : 'bg-primary/15 text-foreground shadow-[inset_0_0_0_1px_color-mix(in_srgb,var(--color-primary)_50%,transparent)]'
                              : now
                                ? pinned
                                  ? '!bg-[color-mix(in_srgb,#f59e0b_45%,var(--di-surface-mid))] text-foreground'
                                  : 'bg-amber-400/45 text-foreground'
                                : hit
                                  ? pinned
                                    ? '!bg-[color-mix(in_srgb,#f59e0b_20%,var(--di-surface-mid))] text-foreground'
                                    : 'bg-amber-400/20 text-foreground'
                                  : sort?.col === i && !pinned
                                    ? 'bg-primary/[0.04] text-foreground'
                                    : !numeric[i] && 'text-di-on-surface-variant',
                          )}
                        >
                          {onPick && typeof v === 'number' ? (
                            <button type="button" aria-pressed={!!picked}
                              aria-label={`${head[i]}: ${showCell(v, head[i])}, ${rowTitle?.(x.i) ?? `строка ${from + n + 1}`}`}
                              className="w-full rounded-sm text-right focus-visible:outline-2 focus-visible:outline-primary">
                              {custom ?? showCell(v, head[i])}
                            </button>
                          ) : custom !== undefined ? (
                            custom
                          ) : v === '' ? (
                            <span className="text-muted-foreground/60" aria-label="нет данных">
                              —
                            </span>
                          ) : (
                            showCell(v, head[i])
                          )}
                        </td>
                      )
                    })}
                    <td aria-hidden className={cn('border-b border-di-outline-variant/40 p-0', tint, active && '!bg-di-surface-high')} />
                  </tr>
                  {detail && <tr>
                    <td colSpan={view.length + (mark ? 2 : 1)} className="max-w-0 border-b border-di-outline-variant/60 bg-background px-3 py-3">
                      {detail}
                    </td>
                  </tr>}
                  </Fragment>
                )
              })}
              {!slice.length && (
                <tr>
                  <td colSpan={view.length + (mark ? 2 : 1)} className="p-6 text-center text-sm text-muted-foreground">
                    {nFilters > 0 && rows.length ? (
                      <>
                        Фильтры столбцов не оставили ни одной строки.{' '}
                        {onFilters && (
                          <button type="button" onClick={() => onFilters({})} className="font-semibold text-primary hover:underline">
                            Снять фильтры
                          </button>
                        )}
                      </>
                    ) : (
                      empty ?? 'Строк нет'
                    )}
                  </td>
                </tr>
              )}
            </tbody>
            {foot && !!slice.length && (
              <tfoot>
                <tr>
                  {mark && <td className={leadCell('bottom-0 z-30 border-t border-di-outline-variant bg-di-surface-low')} />}
                  {view.map((i, k) => {
                    const pickable = !!onPick && typeof foot[i] === 'number'
                    const w = widthOf(i)
                    const st = sticky(k, 'z-20')
                    return (
                      <td
                        key={i}
                        style={{ ...st.style, ...sized(w) }}
                        onClick={pickable ? () => onPick({ key: `t:${i}`, label: head[i], value: foot[i], row: 'Итого' }) : undefined}
                        className={cn(
                          'sticky bottom-0 z-10 whitespace-nowrap border-t border-di-outline-variant px-3 py-2.5 font-semibold text-foreground',
                          st.className,
                          w && 'overflow-hidden text-ellipsis',
                          numeric[i] ? 'text-right tabular-nums' : 'text-left',
                          pickable && 'cursor-cell',
                          selected?.has(`t:${i}`) ? 'bg-di-surface-highest shadow-[inset_0_0_0_1px_color-mix(in_srgb,var(--color-primary)_50%,transparent)]' : 'bg-di-surface-low',
                        )}
                      >
                        {pickable ? (
                          <button type="button" aria-pressed={!!selected?.has(`t:${i}`)}
                            aria-label={`Итого, ${head[i]}: ${showCell(foot[i], head[i])}`}
                            className="w-full rounded-sm text-right focus-visible:outline-2 focus-visible:outline-primary">
                            {showCell(foot[i], head[i])}
                          </button>
                        ) : showCell(foot[i], head[i])}
                      </td>
                    )
                  })}
                  <td aria-hidden className="sticky bottom-0 z-10 border-t border-di-outline-variant bg-di-surface-low p-0" />
                </tr>
              </tfoot>
            )}
          </table>
        </div>
        <div
          aria-hidden
          className={cn(
            'pointer-events-none absolute inset-y-0 right-0 z-30 w-10 bg-gradient-to-l from-black/15 to-transparent transition-opacity duration-200',
            wide && more ? 'opacity-100' : 'opacity-0',
          )}
        />
      </div>

      {menu && onCols && (
        <ColumnMenu
          key={menu.col}
          anchor={menu.anchor}
          title={head[menu.col]}
          numeric={numeric[menu.col]}
          values={distinct(rows, menu.col)}
          filter={filters?.[menu.col]}
          onFilter={
            onFilters &&
            ((f) => {
              const rest = { ...(filters ?? {}) }
              delete rest[menu.col]
              onFilters(f ? { ...rest, [menu.col]: f } : rest)
            })
          }
          sort={sort?.col === menu.col ? sort.dir : null}
          onSort={(dir) => {
            setPage(0)
            setSort(dir ? { col: menu.col, dir } : null)
          }}
          pinned={view.indexOf(menu.col) < pin}
          onPin={() => patch({ pin: view.indexOf(menu.col) < pin ? 0 : view.indexOf(menu.col) + 1 })}
          onHide={() => {
            patch({ hidden: [...(cols?.hidden ?? []), menu.col] })
            setMenu(null)
          }}
          bars={!!cols?.bars?.includes(menu.col)}
          onBars={() =>
            patch({ bars: cols?.bars?.includes(menu.col) ? cols.bars.filter((c) => c !== menu.col) : [...(cols?.bars ?? []), menu.col] })
          }
          sized={!!cols?.width?.[menu.col]}
          onAutoWidth={() => autoWidth(menu.col)}
          onClose={() => setMenu(null)}
        />
      )}

      {stats && (
        <ColumnStats
          key={stats.col}
          anchor={stats.anchor}
          title={head[stats.col]}
          values={sorted.flatMap((x, pos) => (typeof x.r[stats.col] === 'number' ? [{ v: x.r[stats.col] as number, pos }] : []))}
          all={sorted.length}
          onOpenRow={
            onRow &&
            ((pos) => {
              setStats(null)
              open(pos)
            })
          }
          onClose={() => setStats(null)}
        />
      )}

      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 border-t border-di-outline-variant/60 px-3 py-2">
        <PageSizeField />
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span>
            Строки {qty(sorted.length ? from + 1 : 0)}–{qty(Math.min(from + size, sorted.length))} из {qty(sorted.length)}
          </span>
          <Button variant="outline" size="sm" className="h-8 w-8 p-0" disabled={at === 0} onClick={() => setPage(at - 1)} aria-label="Предыдущая страница">
            <ChevronLeft className="size-4" aria-hidden />
          </Button>
          <span className="text-foreground">
            {at + 1} из {pages}
          </span>
          <Button variant="outline" size="sm" className="h-8 w-8 p-0" disabled={at >= pages - 1} onClick={() => setPage(at + 1)} aria-label="Следующая страница">
            <ChevronRight className="size-4" aria-hidden />
          </Button>
        </div>
      </div>
    </section>
  )
}
