import { ArrowDown, ArrowUp, BarChart3, Check, ExternalLink, EyeOff, MoveHorizontal, Pin, PinOff, Search, Sigma, X } from 'lucide-react'
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { cn } from '@/lib/utils'
import { qty, showNum } from './format'

export type Filt = { in?: string[]; min?: number | null; max?: number | null }

type Stat = 'sum' | 'avg' | 'min' | 'max' | 'count'
const STATS: { key: Stat; label: string; hint: string }[] = [
  { key: 'sum', label: 'Сумма', hint: 'Сумма по столбцу' },
  { key: 'avg', label: 'Среднее', hint: 'Среднее значение' },
  { key: 'min', label: 'Мин.', hint: 'Наименьшее значение' },
  { key: 'max', label: 'Макс.', hint: 'Наибольшее значение' },
  { key: 'count', label: 'Кол-во', hint: 'Сколько строк со значением' },
]

function useFloating(anchor: HTMLElement, width: number, onClose: () => void) {
  const box = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState({ top: 0, left: 0, max: 400 })
  const close = useRef(onClose)
  useLayoutEffect(() => {
    close.current = onClose
  })
  useLayoutEffect(() => {
    const r = anchor.getBoundingClientRect()
    const top = r.bottom + 6
    setPos({ top, left: Math.min(Math.max(8, r.right - width), window.innerWidth - width - 8), max: window.innerHeight - top - 12 })
  }, [anchor, width])
  useEffect(() => {
    box.current?.querySelector<HTMLElement>('button, input')?.focus()
    const down = (e: PointerEvent) => {
      const t = e.target as Node
      if (!box.current?.contains(t) && !anchor.contains(t)) close.current()
    }
    const key = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      e.stopPropagation()
      close.current()
      anchor.focus()
    }
    const scroll = (e: Event) => !box.current?.contains(e.target as Node) && close.current()
    const resize = () => close.current()
    document.addEventListener('pointerdown', down)
    document.addEventListener('keydown', key, true)
    window.addEventListener('scroll', scroll, true)
    window.addEventListener('resize', resize)
    return () => {
      document.removeEventListener('pointerdown', down)
      document.removeEventListener('keydown', key, true)
      window.removeEventListener('scroll', scroll, true)
      window.removeEventListener('resize', resize)
    }
  }, [anchor])
  return { box, style: { top: pos.top, left: pos.left, maxHeight: pos.max, width } }
}

const panel =
  'fixed z-50 flex flex-col overflow-y-auto rounded-xl border border-di-outline-variant bg-di-surface-lowest p-1.5 text-foreground shadow-lg'
const caps = 'text-xs font-semibold text-muted-foreground'

export function ColumnStats({
  anchor,
  title,
  values,
  all,
  onOpenRow,
  onClose,
}: {
  anchor: HTMLElement
  title: string
  values: { v: number; pos: number }[]
  all: number
  onOpenRow?: (pos: number) => void
  onClose: () => void
}) {
  const { box, style } = useFloating(anchor, 320, onClose)
  const [stat, setStat] = useState<Stat>('sum')
  const r = useMemo(() => {
    if (!values.length) return null
    let min = values[0]
    let max = values[0]
    let sum = 0
    for (const x of values) {
      sum += x.v
      if (x.v < min.v) min = x
      if (x.v > max.v) max = x
    }
    return { sum, avg: sum / values.length, min, max }
  }, [values])
  const value =
    !r ? null : stat === 'sum' ? r.sum : stat === 'avg' ? r.avg : stat === 'min' ? r.min.v : stat === 'max' ? r.max.v : values.length
  const row = r && (stat === 'min' ? r.min.pos : stat === 'max' ? r.max.pos : null)
  const hint = STATS.find((s) => s.key === stat)!.hint

  return createPortal(
    <div ref={box} role="dialog" aria-label={`Итоги по столбцу «${title}»`} style={style} className={panel}>
      <p className={cn('flex items-center gap-1.5 px-2.5 pb-2 pt-1.5', caps)}>
        <Sigma className="size-3.5" aria-hidden /> {title}
      </p>
      <div role="radiogroup" aria-label="Показатель" className="mx-1 grid grid-cols-5 gap-1 rounded-lg bg-di-surface p-1">
        {STATS.map((s) => (
          <button
            key={s.key}
            type="button"
            role="radio"
            aria-checked={stat === s.key}
            onClick={() => setStat(s.key)}
            className={cn(
              'h-8 rounded-md px-1 text-xs font-semibold transition-colors',
              stat === s.key ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground',
            )}
          >
            {s.label}
          </button>
        ))}
      </div>
      <div className="px-2.5 pb-3 pt-4" aria-live="polite">
        <p className="text-xs text-muted-foreground">{hint}</p>
        <p className="mt-1 font-headline text-xl font-bold leading-tight tabular-nums text-foreground">
          {value === null ? '—' : stat === 'count' ? qty(value) : showNum(value, title)}
        </p>
        <p className="mt-1.5 text-xs text-muted-foreground">
          {values.length === all ? `По всем ${qty(all)} строкам` : `По ${qty(values.length)} строкам со значением из ${qty(all)}`}
        </p>
      </div>
      {row !== null && onOpenRow && (
        <button type="button" onClick={() => onOpenRow(row)} className={item}>
          <span className="text-muted-foreground" aria-hidden>
            <ExternalLink className="size-4" />
          </span>
          <span className="flex-1">Открыть эту строку</span>
        </button>
      )}
    </div>,
    document.body,
  )
}

const item =
  'flex h-9 w-full items-center gap-2.5 rounded-lg px-2.5 text-left text-sm text-foreground outline-none hover:bg-di-surface-high focus-visible:bg-di-surface-high'

export function ColumnMenu({
  anchor,
  title,
  numeric,
  values,
  filter,
  onFilter,
  sort,
  onSort,
  pinned,
  onPin,
  onHide,
  bars,
  onBars,
  sized,
  onAutoWidth,
  onClose,
}: {
  anchor: HTMLElement
  title: string
  numeric: boolean
  values: { value: string; count: number }[]
  filter?: Filt
  onFilter?: (f: Filt | undefined) => void
  sort: 1 | -1 | null
  onSort: (dir: 1 | -1 | null) => void
  pinned: boolean
  onPin: () => void
  onHide: () => void
  bars: boolean
  onBars: () => void
  sized: boolean
  onAutoWidth: () => void
  onClose: () => void
}) {
  const { box, style } = useFloating(anchor, 304, onClose)
  const [find, setFind] = useState('')

  const needle = find.trim().toLowerCase()
  const shown = useMemo(
    () => (needle ? values.filter((v) => (v.value || '(пусто)').toLowerCase().includes(needle)) : values).slice(0, 300),
    [values, needle],
  )
  const chosen = filter?.in ? new Set(filter.in) : null
  const isOn = (v: string) => !chosen || chosen.has(v)
  const setIn = (next: Set<string>) =>
    onFilter?.(next.size === values.length ? strip({ ...filter, in: undefined }) : { ...filter, in: [...next] })
  const toggle = (v: string) => {
    const next = new Set(chosen ?? values.map((x) => x.value))
    if (next.has(v)) next.delete(v)
    else next.add(v)
    setIn(next)
  }
  const onlyShown = () => setIn(new Set(shown.map((x) => x.value)))
  const num = (k: 'min' | 'max', raw: string) => {
    const n = raw.trim() === '' ? null : Number(raw.replace(',', '.').replace(/\s/g, ''))
    if (n !== null && !Number.isFinite(n)) return
    onFilter?.(strip({ ...filter, [k]: n }))
  }
  const input = 'h-9 rounded-lg border border-di-outline-variant bg-di-surface-lowest px-2.5 text-sm text-foreground outline-none focus:border-primary'

  return createPortal(
    <div ref={box} role="dialog" aria-label={`Столбец «${title}»`} style={style} className={panel}>
      <p className={cn('px-2.5 pb-1 pt-1.5', caps)}>{title}</p>
      <MenuButton on={sort === 1} onClick={() => onSort(sort === 1 ? null : 1)} icon={<ArrowUp className="size-4" />}>
        {numeric ? 'По возрастанию' : 'От А до Я'}
      </MenuButton>
      <MenuButton on={sort === -1} onClick={() => onSort(sort === -1 ? null : -1)} icon={<ArrowDown className="size-4" />}>
        {numeric ? 'По убыванию' : 'От Я до А'}
      </MenuButton>
      <hr className="my-1.5 border-di-outline-variant/70" />
      <MenuButton onClick={onPin} icon={pinned ? <PinOff className="size-4" /> : <Pin className="size-4" />}>
        {pinned ? 'Открепить столбцы' : 'Закрепить по этот столбец'}
      </MenuButton>
      <MenuButton onClick={onHide} icon={<EyeOff className="size-4" />}>
        Скрыть столбец
      </MenuButton>
      {sized && (
        <MenuButton onClick={onAutoWidth} icon={<MoveHorizontal className="size-4" />}>
          Ширина по содержимому
        </MenuButton>
      )}
      {numeric && (
        <>
          <hr className="my-1.5 border-di-outline-variant/70" />
          <MenuButton on={bars} onClick={onBars} icon={<BarChart3 className="size-4 -rotate-90" />}>
            Полоски величины
          </MenuButton>
        </>
      )}
      {onFilter && (
        <>
          <hr className="my-1.5 border-di-outline-variant/70" />
          <div className="flex items-center justify-between px-2.5 pb-1.5">
            <p className="text-xs text-muted-foreground">Фильтр</p>
            {!!filter && (
              <button
                type="button"
                onClick={() => onFilter(undefined)}
                className="inline-flex h-7 items-center gap-1 rounded-md px-1.5 text-xs font-semibold text-primary hover:bg-di-surface-high"
              >
                <X className="size-3.5" aria-hidden /> Снять
              </button>
            )}
          </div>
          {numeric ? (
            <div className="grid grid-cols-2 gap-2 px-2.5 pb-2">
              {(['min', 'max'] as const).map((k) => (
                <label key={k} className="flex flex-col gap-1 text-xs text-muted-foreground">
                  {k === 'min' ? 'От' : 'До'}
                  <input
                    inputMode="decimal"
                    defaultValue={filter?.[k] ?? ''}
                    onKeyDown={(e) => e.key === 'Enter' && num(k, e.currentTarget.value)}
                    onBlur={(e) => num(k, e.currentTarget.value)}
                    className={input}
                  />
                </label>
              ))}
            </div>
          ) : (
            <div className="px-1 pb-1">
              <label className="relative mx-1.5 mb-1.5 flex">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
                <input
                  value={find}
                  onChange={(e) => setFind(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && needle && onlyShown()}
                  placeholder="Найти значение"
                  aria-label="Найти значение"
                  className={cn(input, 'w-full pl-8')}
                />
              </label>
              <div className="flex gap-1 px-1.5 pb-1">
                <button
                  type="button"
                  onClick={() => (needle ? onlyShown() : onFilter(strip({ ...filter, in: undefined })))}
                  className="h-7 rounded-md px-2 text-xs font-semibold text-primary hover:bg-di-surface-high"
                >
                  {needle ? 'Только найденные' : 'Выбрать все'}
                </button>
                <button
                  type="button"
                  onClick={() => onFilter({ ...filter, in: [] })}
                  className="h-7 rounded-md px-2 text-xs font-semibold text-muted-foreground hover:bg-di-surface-high hover:text-foreground"
                >
                  Снять все
                </button>
              </div>
              <ul className="max-h-56 overflow-y-auto">
                {shown.map((v) => (
                  <li key={v.value}>
                    <label className="flex min-h-9 cursor-pointer items-center gap-2.5 rounded-lg px-2.5 text-sm hover:bg-di-surface-high">
                      <input type="checkbox" className="size-4 shrink-0 accent-primary" checked={isOn(v.value)} onChange={() => toggle(v.value)} />
                      <span className={cn('min-w-0 flex-1 truncate', !v.value && 'text-muted-foreground')}>{v.value || '(пусто)'}</span>
                      <span className="text-xs tabular-nums text-muted-foreground">{qty(v.count)}</span>
                    </label>
                  </li>
                ))}
                {!shown.length && <li className="px-2.5 py-2 text-sm text-muted-foreground">Ничего не найдено</li>}
              </ul>
            </div>
          )}
        </>
      )}
    </div>,
    document.body,
  )
}

function strip(f: Filt): Filt | undefined {
  const out: Filt = {}
  if (f.in) out.in = f.in
  if (f.min != null) out.min = f.min
  if (f.max != null) out.max = f.max
  return Object.keys(out).length ? out : undefined
}

function MenuButton({ on, onClick, icon, children }: { on?: boolean; onClick: () => void; icon: ReactNode; children: ReactNode }) {
  return (
    <button type="button" onClick={onClick} className={item} aria-pressed={on}>
      <span className="text-muted-foreground" aria-hidden>
        {icon}
      </span>
      <span className="flex-1">{children}</span>
      {on && <Check className="size-4 text-primary" aria-hidden />}
    </button>
  )
}
