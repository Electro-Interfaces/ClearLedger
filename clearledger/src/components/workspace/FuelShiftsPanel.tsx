/**
 * «Сменные отчёты» — журнал смен сети с раскрытием каждой смены (fuel, ГИГ).
 *
 * Смена — первичный документ топливного учёта: всё остальное в разделе (книга
 * резервуаров, расхождения, инвентаризация) считается ИЗ неё. До этого экрана
 * журнал смен был доступен только внутри «Бухгалтерского» — то есть человек,
 * который ведёт товародвижение, не мог посмотреть первичку, не уходя в чужой
 * продукт.
 *
 * Экран сознательно тонкий: список + фильтры, а разбор одной смены — уже готовый
 * `ShiftDetailsDialog` (состав смены с показаниями счётчиков, резервуары,
 * поступления, расшифровка реализации, движение наличных, корректировка). Второй
 * такой карточки в продукте быть не должно.
 *
 * Период берётся из контура рабочей области, поэтому в локальных фильтрах его нет —
 * только то, чего в контуре не бывает: статус, номер смены и станция.
 */

import { Fragment, useMemo, useRef, useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import {
  Loader2, ClipboardList, CircleCheck, CircleDot, AlertTriangle, Search,
  ArrowUp, ArrowDown, ChevronsUpDown,
} from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { ShiftDetailsDialog } from '@/components/fuel/ShiftDetailsDialog'
import { PanelViewTabs } from './PanelViewTabs'
import { ShiftCoverageView } from './ShiftCoverageView'
import { ExportButton } from './analytics/ExportButton'
import { ViewParamsBar } from './ViewParamsBar'
import { useTabParams } from '@/hooks/useTabParams'
import { cn } from '@/lib/utils'
import { fmtLiters, fmtMoney } from '@/services/analyticsService'
import { getLoadedShifts, type LoadedShift } from '@/services/fuel/fuelMappingService'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const dtm = (iso: string | null) =>
  (iso ? new Date(iso).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' }) : '—')
/** В строке — только время: дату несёт заголовок дня, иначе она повторяется в каждой. */
const hm = (iso: string | null) =>
  (iso ? new Date(iso).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }) : '—')
const dayKey = (iso: string | null) => (iso ? iso.slice(0, 10) : '—')
const dayTitle = (key: string) => (key === '—' ? 'Без даты открытия' : new Date(`${key}T00:00:00`)
  .toLocaleDateString('ru-RU', { day: '2-digit', month: 'long', weekday: 'short' }))
/** Закрытие на следующие сутки — норма для суточной смены, но это надо показать. */
const closedMark = (s: LoadedShift) =>
  (s.closed_at && dayKey(s.closed_at) !== dayKey(s.opened_at) ? '+1' : '')

/** Смена без сумм — это не нулевая выручка, а неполученная детализация. */
function statusOf(s: LoadedShift): { label: string; cls: string; icon: typeof CircleCheck } {
  if (!s.closed_at) return { label: 'Открыта', cls: 'text-sky-600 dark:text-sky-400', icon: CircleDot }
  if (s.total_amount === 0) return { label: 'Без данных', cls: 'text-amber-600 dark:text-amber-400', icon: AlertTriangle }
  return { label: 'Закрыта', cls: 'text-muted-foreground', icon: CircleCheck }
}

/** Карточка сводки — тот же вид, что `Metric` в сетевых экранах «Топлива». */
function Stat({ label, value, sub, tone }: {
  label: string; value: string; sub?: string; tone?: 'warn' | 'ok' | 'info'
}) {
  return (
    <div className="min-w-0 border-r border-border/70 px-4 py-3 last:border-r-0">
      <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className={cn('mt-1 truncate text-lg font-semibold tabular-nums',
        tone === 'warn' && 'text-amber-600 dark:text-amber-400',
        tone === 'ok' && 'text-emerald-600 dark:text-emerald-400',
        tone === 'info' && 'text-sky-600 dark:text-sky-400')}>{value}</div>
      {sub && <div className="mt-0.5 truncate text-[11px] text-muted-foreground">{sub}</div>}
    </div>
  )
}

/**
 * Колонки журнала: подпись, выравнивание и КЛЮЧ СОРТИРОВКИ.
 *
 * Ключ обязателен для каждой — «найти ту или иную смену» это в первую очередь
 * упорядочить: самая крупная выручка, самая длинная смена, конкретная АЗС.
 * `num` отделяет числовые колонки от текстовых: у первых сортировка по величине,
 * у вторых — по алфавиту с учётом русской раскладки.
 */
type SortKey = 'station' | 'shift' | 'opened' | 'closed' | 'liters' | 'amount' | 'cash' | 'card' | 'status'

const COLS: { key: SortKey; label: string; right?: boolean; num?: boolean }[] = [
  { key: 'station', label: 'АЗС' },
  { key: 'shift', label: 'Смена №', num: true },
  { key: 'opened', label: 'Открыта', right: true, num: true },
  { key: 'closed', label: 'Закрыта', right: true, num: true },
  { key: 'liters', label: 'Объём, л', right: true, num: true },
  { key: 'amount', label: 'Выручка, ₽', right: true, num: true },
  { key: 'cash', label: 'Наличные, ₽', right: true, num: true },
  { key: 'card', label: 'Карты, ₽', right: true, num: true },
  { key: 'status', label: 'Статус' },
]

const sortVal = (s: LoadedShift, k: SortKey): number | string => {
  switch (k) {
    case 'station': return s.station_name ?? `АЗС ${s.station_code}`
    case 'shift': return s.shift_number
    case 'opened': return s.opened_at ?? ''
    case 'closed': return s.closed_at ?? ''
    case 'liters': return s.total_liters
    case 'amount': return s.total_amount
    case 'cash': return s.cash
    case 'card': return s.card
    case 'status': return statusOf(s).label
  }
}

/** Заголовок-кнопка: направление показано иконкой, состояние — `aria-sort`. */
function SortTh({ col, sort, dir, onSort }: {
  col: { key: SortKey; label: string; right?: boolean }
  sort: SortKey; dir: 'asc' | 'desc'; onSort: (k: SortKey) => void
}) {
  const on = sort === col.key
  const Ico = on ? (dir === 'asc' ? ArrowUp : ArrowDown) : ChevronsUpDown
  return (
    <th aria-sort={on ? (dir === 'asc' ? 'ascending' : 'descending') : 'none'}
      className={cn('p-2 font-medium whitespace-nowrap', col.right ? 'text-right' : 'text-left')}>
      <button type="button" onClick={() => onSort(col.key)} title={`Сортировать по «${col.label}»`}
        className={cn('group inline-flex cursor-pointer items-center gap-1 transition-colors hover:text-foreground',
          col.right && 'flex-row-reverse', on && 'text-foreground')}>
        <span>{col.label}</span>
        <Ico className={cn('h-3 w-3 shrink-0', on ? 'text-primary' : 'opacity-30 group-hover:opacity-70')} />
      </button>
    </th>
  )
}

/**
 * Строка смены. `showDate` — режим плоского списка: когда группировки по суткам нет,
 * дату несёт сама строка, иначе она уже стоит в заголовке дня.
 */
function ShiftRow({ s, onOpen, showDate }: {
  s: LoadedShift; onOpen: (id: string) => void; showDate?: boolean
}) {
  const st = statusOf(s)
  const Ico = st.icon
  const noData = st.label === 'Без данных'
  const isOpen = !s.closed_at
  const time = (iso: string | null) => (showDate ? dtm(iso) : hm(iso))
  return (
    <tr onClick={() => onOpen(s.id)} title="Раскрыть смену"
      className={cn('cursor-pointer border-b border-border/40 hover:bg-muted/25',
        noData && 'bg-amber-500/[0.06]')}>
      <td className="p-2 whitespace-nowrap">{s.station_name ?? `АЗС ${s.station_code}`}</td>
      <td className="p-2 font-medium tabular-nums">#{s.shift_number}</td>
      <td className="p-2 text-right tabular-nums whitespace-nowrap text-muted-foreground">{time(s.opened_at)}</td>
      <td className="p-2 text-right tabular-nums whitespace-nowrap text-muted-foreground">
        {time(s.closed_at)}
        {!showDate && closedMark(s) && (
          <span className="ml-1 text-[10px] opacity-60" title="закрыта на следующие сутки">
            {closedMark(s)}
          </span>
        )}
      </td>
      {/* У открытой смены сумм ещё нет — прочерк, а не «0 л»: ноль читается как
          «ничего не продали». */}
      <td className={cn('p-2 text-right tabular-nums', isOpen && 'text-muted-foreground/40')}>
        {isOpen ? '—' : nf0.format(s.total_liters)}
      </td>
      <td className={cn('p-2 text-right font-medium tabular-nums',
        isOpen && 'font-normal text-muted-foreground/40')}>
        {isOpen ? '—' : nf0.format(s.total_amount)}
      </td>
      <td className="p-2 text-right tabular-nums text-muted-foreground">
        {isOpen ? '—' : nf0.format(s.cash)}
      </td>
      <td className="p-2 text-right tabular-nums text-muted-foreground">
        {isOpen ? '—' : nf0.format(s.card)}
      </td>
      <td className={cn('p-2 whitespace-nowrap', st.cls)}>
        <Ico className="mr-1 inline h-3 w-3 align-[-1px]" />{st.label}
        {s.has_corrections && (
          <span className="ml-1.5 rounded border border-current/40 px-1 text-[9px] uppercase"
            title="В смену внесена корректировка перед выгрузкой в 1С">правка</span>
        )}
      </td>
    </tr>
  )
}

export function FuelShiftsPanel({ companyId, dateFrom, dateTo }: {
  companyId: string; dateFrom: string; dateTo: string
}) {
  const [p, patch] = useTabParams('fuel_shifts', {
    status: 'all', q: '', sub: 'log',
    // Порядок по умолчанию — свежие сверху: журнал открывают ради последних смен.
    sort: 'opened' as SortKey, dir: 'desc' as 'asc' | 'desc',
    station: 'all', fixed: 'all',
  })
  const [open, setOpen] = useState<string | null>(null)
  const ref = useRef<HTMLDivElement>(null)

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['fuel-shifts-journal', companyId, dateFrom, dateTo],
    // limit с запасом: 14 станций × 31 сутки ≈ 434 смены на месяц, годовой период
    // упирается в 20 000 — предел ручки.
    queryFn: () => getLoadedShifts({ dateFrom, dateTo, limit: 20000 }),
    placeholderData: keepPreviousData,
  })

  /** Станции периода — для селектора: список из данных, а не из справочника сети,
   *  иначе в фильтре висят точки, по которым в периоде нет ни одной смены. */
  const stations = useMemo(() => {
    const m = new Map<number, string>()
    ;(data ?? []).forEach((s) => m.set(s.station_code, s.station_name ?? `АЗС ${s.station_code}`))
    return [...m].sort((a, b) => a[0] - b[0])
  }, [data])

  const rows = useMemo(() => {
    const q = p.q.trim().toLowerCase()
    const filtered = (data ?? []).filter((s) => {
      const st = statusOf(s)
      if (p.status === 'open' && s.closed_at) return false
      if (p.status === 'closed' && !s.closed_at) return false
      if (p.status === 'nodata' && st.label !== 'Без данных') return false
      if (p.station !== 'all' && String(s.station_code) !== p.station) return false
      if (p.fixed === 'yes' && !s.has_corrections) return false
      if (p.fixed === 'no' && s.has_corrections) return false
      if (!q) return true
      return String(s.shift_number).includes(q)
        || (s.station_name ?? '').toLowerCase().includes(q)
        || String(s.station_code).includes(q)
    })
    // Сортировка после фильтра: строки текстом сравниваются по-русски (localeCompare),
    // числа — по величине. Смешивать нельзя: «#1000» левее «#999» только как строка.
    const mul = p.dir === 'asc' ? 1 : -1
    return [...filtered].sort((a, b) => {
      const va = sortVal(a, p.sort)
      const vb = sortVal(b, p.sort)
      if (typeof va === 'string' || typeof vb === 'string') {
        return mul * String(va).localeCompare(String(vb), 'ru')
      }
      return mul * (va - vb)
    })
  }, [data, p.status, p.q, p.station, p.fixed, p.sort, p.dir])

  /** Группы по суткам осмысленны только в порядке по времени открытия: при сортировке
   *  по выручке или объёму дневной заголовок соврал бы о порядке строк. */
  const grouped = p.sort === 'opened'
  const onSort = (k: SortKey) => patch(
    p.sort === k ? { dir: p.dir === 'desc' ? 'asc' : 'desc' } : { sort: k, dir: k === 'station' || k === 'status' ? 'asc' : 'desc' },
  )

  /** Сутки открытия → смены дня с итогом: заголовок группы и есть «день целиком». */
  const groups = useMemo(() => {
    const m = new Map<string, LoadedShift[]>()
    rows.forEach((s) => {
      const k = dayKey(s.opened_at)
      m.set(k, [...(m.get(k) ?? []), s])
    })
    return [...m.entries()]
      .sort((a, b) => b[0].localeCompare(a[0]))
      .map(([key, items]) => ({
        key,
        items,
        liters: items.reduce((a, s) => a + s.total_liters, 0),
        amount: items.reduce((a, s) => a + s.total_amount, 0),
        open: items.filter((s) => !s.closed_at).length,
        nodata: items.filter((s) => s.closed_at && s.total_amount === 0).length,
      }))
  }, [rows])

  const totals = useMemo(() => rows.reduce(
    (a, s) => ({
      liters: a.liters + s.total_liters, amount: a.amount + s.total_amount,
      nodata: a.nodata + (s.closed_at && s.total_amount === 0 ? 1 : 0),
      open: a.open + (s.closed_at ? 0 : 1),
    }),
    { liters: 0, amount: 0, nodata: 0, open: 0 },
  ), [rows])

  return (
    <div ref={ref} className="space-y-4 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-base font-semibold">
            <ClipboardList className="h-4 w-4 text-blue-600 dark:text-blue-400" />Сменные отчёты
          </h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Первичный документ учёта: показания счётчиков, резервуары, поступления, касса.
            Клик по строке раскрывает смену целиком.
          </p>
        </div>
        <ExportButton title={p.sub === 'gaps' ? 'Полнота сменных отчётов' : 'Журнал смен'} getEl={() => ref.current} />
      </div>

      {/* Два вида одного предмета: сам журнал и его полнота. Полнота — не отдельный
          пункт меню: вопрос «все ли отчёты на месте» задают, уже стоя в журнале. */}
      <PanelViewTabs
        tabs={[{ k: 'log', label: 'Журнал смен' }, { k: 'gaps', label: 'Пробелы' }]}
        value={p.sub} onChange={(k) => patch({ sub: k })} ariaLabel="Виды пункта «Сменные отчёты»" />

      {p.sub === 'gaps' ? (
        <ShiftCoverageView companyId={companyId} dateFrom={dateFrom} dateTo={dateTo} />
      ) : (
      <>

      <ViewParamsBar>
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
          Статус:
          <Select value={p.status} onValueChange={(v) => patch({ status: v })}>
            <SelectTrigger className="h-7 w-[150px] text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all" className="text-xs">Все статусы</SelectItem>
              <SelectItem value="closed" className="text-xs">Закрытые</SelectItem>
              <SelectItem value="open" className="text-xs">Открытые</SelectItem>
              <SelectItem value="nodata" className="text-xs">Без данных</SelectItem>
            </SelectContent>
          </Select>
        </label>
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
          АЗС:
          <Select value={p.station} onValueChange={(v) => patch({ station: v })}>
            <SelectTrigger className="h-7 w-[170px] text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all" className="text-xs">Вся сеть</SelectItem>
              {stations.map(([code, name]) => (
                <SelectItem key={code} value={String(code)} className="text-xs">{name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </label>
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
          Правки:
          <Select value={p.fixed} onValueChange={(v) => patch({ fixed: v })}>
            <SelectTrigger className="h-7 w-[150px] text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all" className="text-xs">Любые</SelectItem>
              <SelectItem value="yes" className="text-xs">С корректировкой</SelectItem>
              <SelectItem value="no" className="text-xs">Без корректировки</SelectItem>
            </SelectContent>
          </Select>
        </label>
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Search className="size-3.5" />
          <Input value={p.q} onChange={(e) => patch({ q: e.target.value })}
            placeholder="Номер смены или АЗС" className="h-7 w-[180px] text-xs" />
        </label>
        {(p.status !== 'all' || p.station !== 'all' || p.fixed !== 'all' || p.q) && (
          <button type="button"
            onClick={() => patch({ status: 'all', station: 'all', fixed: 'all', q: '' })}
            className="rounded-md border border-border/60 px-2 py-0.5 text-xs text-muted-foreground hover:text-foreground">
            Сбросить
          </button>
        )}
        <span className="ml-auto text-xs text-muted-foreground tabular-nums">
          показано {nf0.format(rows.length)} из {nf0.format(data?.length ?? 0)}
        </span>
      </ViewParamsBar>

      {/* Сводка периода — карточками: «10 открыто · 193 без данных» в сером тексте
          сбоку читалось как подпись к фильтру, хотя это и есть повод открыть экран. */}
      {rows.length > 0 && (
        <Card className="gap-0 py-0"><CardContent className="grid grid-cols-2 p-0 md:grid-cols-4">
          <Stat label="Смен за период" value={nf0.format(rows.length)}
            sub={`${nf0.format(new Set(rows.map((s) => dayKey(s.opened_at))).size)} суток`} />
          <Stat label="Объём" value={fmtLiters(totals.liters)}
            sub={`выручка ${fmtMoney(totals.amount)}`} />
          <Stat label="Открыты" value={nf0.format(totals.open)}
            sub={totals.open ? 'смена ещё идёт' : 'все закрыты'} tone={totals.open ? 'info' : undefined} />
          <Stat label="Без данных" value={nf0.format(totals.nodata)}
            sub={totals.nodata ? 'детализация не пришла' : 'пробелов нет'}
            tone={totals.nodata ? 'warn' : 'ok'} />
        </CardContent></Card>
      )}

      {isLoading ? (
        <div className="flex justify-center py-16"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
      ) : error ? (
        /* Сорванный запрос — не пустой период. Именно на этом экране ручка журнала
           отдавала 500 (строка вместо даты в фильтре), а человек читал «За период
           смен нет» и искал причину в загрузке данных, а не в ошибке сервера. */
        <div className="p-8 text-center text-sm">
          <div className="text-red-400/90">Журнал не загрузился</div>
          <div className="mt-1 text-xs text-muted-foreground">
            {error instanceof Error ? error.message : 'неизвестная ошибка'}
          </div>
          <button onClick={() => refetch()}
            className="mt-3 rounded-md border border-border/60 px-3 py-1.5 text-xs hover:bg-accent/20">
            Повторить
          </button>
        </div>
      ) : rows.length === 0 ? (
        <div className="p-8 text-center text-sm text-muted-foreground">
          {data?.length ? 'Под фильтр не подошла ни одна смена' : 'За период смен нет'}
        </div>
      ) : (
        <Card className="gap-0 overflow-hidden py-0"><CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[840px] text-xs"
              data-export-name="Журнал смен"
              data-export-rows={JSON.stringify({
                columns: ['АЗС', 'Смена №', 'Открыта', 'Закрыта', 'Объём, л', 'Выручка, ₽', 'Наличные, ₽', 'Карты, ₽', 'Статус'],
                rows: rows.map((s) => [
                  s.station_name ?? `АЗС ${s.station_code}`, s.shift_number,
                  dtm(s.opened_at), dtm(s.closed_at), s.total_liters, s.total_amount,
                  s.cash, s.card, statusOf(s).label,
                ]),
              })}>
              <thead>
                <tr className="border-b bg-muted/35 text-muted-foreground">
                  {COLS.map((c) => (
                    <SortTh key={c.key} col={c} sort={p.sort} dir={p.dir} onSort={onSort} />
                  ))}
                </tr>
              </thead>
              <tbody>
                {/* Смены сгруппированы по суткам открытия: дата в каждой из 2 477 строк
                    повторялась двенадцать раз подряд и не давала увидеть день целиком.
                    Заголовок дня несёт дату и итог, строка — только время. */}
                {grouped ? groups.map((g) => (
                  <Fragment key={g.key}>
                    <tr className="border-b border-border/60 bg-muted/30">
                      <td className="px-2 py-1.5 font-medium" colSpan={2}>
                        {dayTitle(g.key)}
                        <span className="ml-2 font-normal text-muted-foreground">
                          {nf0.format(g.items.length)} см.
                        </span>
                      </td>
                      <td className="px-2 py-1.5 text-right text-[11px] text-muted-foreground" colSpan={2}>
                        {g.open ? `${nf0.format(g.open)} открыто` : ''}
                        {g.nodata ? `${g.open ? ' · ' : ''}${nf0.format(g.nodata)} без данных` : ''}
                      </td>
                      <td className="px-2 py-1.5 text-right tabular-nums text-muted-foreground">{nf0.format(g.liters)}</td>
                      <td className="px-2 py-1.5 text-right font-medium tabular-nums">{nf0.format(g.amount)}</td>
                      <td colSpan={3} />
                    </tr>
                    {g.items.map((s) => (
                      <ShiftRow key={s.id} s={s} onOpen={setOpen} showDate={false} />
                    ))}
                  </Fragment>
                )) : (
                  /* Плоский список: сортировка не по времени, и дневные группы соврали бы
                     о порядке — вместо них дата возвращается в саму строку. */
                  rows.map((s) => <ShiftRow key={s.id} s={s} onOpen={setOpen} showDate />)
                )}
              </tbody>
              <tfoot>
                <tr className="border-t bg-muted/25 font-medium">
                  <td className="p-2" colSpan={4}>Итого по фильтру</td>
                  <td className="p-2 text-right tabular-nums">{nf0.format(totals.liters)}</td>
                  <td className="p-2 text-right tabular-nums">{nf0.format(totals.amount)}</td>
                  <td className="p-2" colSpan={3} />
                </tr>
              </tfoot>
            </table>
          </div>
        </CardContent></Card>
      )}

      <div className="rounded-lg border border-dashed px-4 py-3 text-xs text-muted-foreground">
        «Без данных» — смена закрыта, но источник не отдал детализацию продаж: это не
        нулевая выручка, а пробел. Такие смены добираются переигровкой канала «Топливо:
        сменный отчёт», и после неё суммы появляются задним числом.
      </div>

      </>
      )}

      <ShiftDetailsDialog shiftId={open} open={!!open} onClose={() => setOpen(null)} />
    </div>
  )
}
