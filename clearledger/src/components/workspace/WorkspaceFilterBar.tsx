import { useMemo, useState } from 'react'
import { ru } from 'date-fns/locale'
import { useQueryClient } from '@tanstack/react-query'
import {
  CalendarDays, ChevronDown, Database, RefreshCw, RotateCcw,
  SlidersHorizontal, type LucideIcon,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Calendar } from '@/components/ui/calendar'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { useFilters } from '@/contexts/FilterContext'
import { todayISO, daysAgoISO, monthFirstISO, prevMonthBounds, isoLocal } from './analytics/periodPresets'
import { activeFilterCount } from '@/contexts/filterState'
import { useCompany } from '@/contexts/CompanyContext'
import { useShifts } from '@/hooks/useFuel'
import { getStsStationsFromLocations } from '@/services/locationService'
import { WorkspaceFilterModal } from './WorkspaceFilterModal'
import { WorkspaceScopeControl } from './WorkspaceScopePopover'
import { FuelKindControl } from './FuelKindControl'
import { ViewHistoryMenu } from './ViewHistoryMenu'
import { ActiveFilterChips } from '@/components/common/ActiveFilterChips'
import { AdvancedOnly } from '@/components/common/AdvancedOnly'
import { formatPeriod as fmtPeriod } from '@/lib/formatDate'
import { cn } from '@/lib/utils'

/** Границы квартала со сдвигом: 0 — текущий, -1 — прошлый. */
function quarterBounds(offset: number): { from: string; to: string } {
  const d = new Date()
  const startMonth = (Math.floor(d.getMonth() / 3) + offset) * 3
  return {
    from: isoLocal(new Date(d.getFullYear(), startMonth, 1)),
    to: isoLocal(new Date(d.getFullYear(), startMonth + 3, 0)),
  }
}

/** ISO (YYYY-MM-DD) → локальная Date без сдвига TZ. */
function parseLocal(iso: string): Date {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y || 2000, (m || 1) - 1, d || 1)
}

/** Быстрые пресеты периода — понятные подписи для поповера. */
/** Заливка дней внутри интервала — одинаковая в обоих календарях периода. */
const RANGE_CLASSNAMES = { inRange: 'bg-primary/10 rounded-none' }

const PERIOD_QUICK: { label: string; value: () => { from: string; to: string } }[] = [
  { label: 'Текущий месяц', value: () => ({ from: monthFirstISO(), to: todayISO() }) },
  { label: 'Прошлый месяц', value: prevMonthBounds },
  { label: 'Текущий квартал', value: () => quarterBounds(0) },
  { label: 'Прошлый квартал', value: () => quarterBounds(-1) },
  { label: 'Последние 30 дней', value: () => ({ from: daysAgoISO(30), to: todayISO() }) },
  { label: 'Последние 90 дней', value: () => ({ from: daysAgoISO(90), to: todayISO() }) },
  { label: 'С начала года', value: () => ({ from: `${new Date().getFullYear()}-01-01`, to: todayISO() }) },
  { label: 'Весь год', value: () => ({ from: `${new Date().getFullYear()}-01-01`, to: `${new Date().getFullYear()}-12-31` }) },
]

/**
 * Чип «Период» — поповер только с функциями периода.
 *
 * Работает по модели диалога «Настройка периода» в 1С: пользователь набирает
 * период в ЧЕРНОВИКЕ и подтверждает кнопкой. До подтверждения контур не
 * меняется, поэтому таблицы под окном не перезапрашиваются на каждый клик, а
 * «Отмена» действительно отменяет.
 *
 * Раньше период применялся на каждое действие, и в режиме диапазона это давало
 * эффект «выбор слетает»: первый клик по дате отдаёт {from, to: undefined},
 * старый код записывал его как {from: X, to: X} — интервал схлопывался в один
 * день, а следующий клик начинал новый диапазон.
 */
function PeriodControl() {
  const { period, setPeriod } = useFilters()
  const [open, setOpen] = useState(false)
  // Черновик: undefined-конец = «начало выбрано, ждём вторую дату».
  const [draft, setDraft] = useState<{ from?: Date; to?: Date }>(() => ({
    from: parseLocal(period.from),
    to: parseLocal(period.to),
  }))
  /**
   * Два независимых календаря: левый задаёт начало, правый — конец.
   *
   * Единый range-календарь на два месяца показывал их подряд (май + июнь), и
   * при периоде «4 июня – 18 июля» конец не попадал на экран вообще. Теперь у
   * каждой границы свой календарь со своим месяцем — обе границы видно всегда,
   * листать можно порознь.
   */
  const [viewFrom, setViewFrom] = useState<Date>(() => parseLocal(period.from))
  const [viewTo, setViewTo] = useState<Date>(() => parseLocal(period.to))

  function setBoth(next: { from?: Date; to?: Date }) {
    setDraft(next)
    if (next.from) setViewFrom(next.from)
    if (next.to) setViewTo(next.to)
  }

  function openChange(next: boolean) {
    // При каждом открытии черновик берётся из текущего контура: незавершённый
    // выбор прошлого раза не должен «залипать».
    if (next) {
      const f = parseLocal(period.from)
      const t = parseLocal(period.to)
      setDraft({ from: f, to: t })
      setViewFrom(f)
      setViewTo(t)
    }
    setOpen(next)
  }

  const complete = !!draft.from && !!draft.to
  const changed = complete
    && (isoLocal(draft.from!) !== period.from || isoLocal(draft.to!) !== period.to)

  // Дни внутри выбранного интервала — подсвечиваем в ОБОИХ календарях, иначе
  // при границах в разных месяцах не видно, что именно охвачено.
  const inRange = useMemo(
    () => ({ inRange: draft.from && draft.to ? { from: draft.from, to: draft.to } : [] }),
    [draft.from, draft.to],
  )

  function apply() {
    if (!complete) return
    setPeriod({ from: isoLocal(draft.from!), to: isoLocal(draft.to!) })
    setOpen(false)
  }

  return (
    <Popover open={open} onOpenChange={openChange}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={`Период: ${fmtPeriod(period.from, period.to)}. Открыть выбор периода`}
          className="group flex h-11 shrink-0 items-center gap-2.5 rounded-lg border border-primary/40 bg-primary/10 px-3.5 text-left text-primary transition-colors hover:bg-primary/15"
        >
          <CalendarDays className="size-[18px] shrink-0 opacity-80" aria-hidden="true" />
          <span className="min-w-0">
            <span className="block text-[11px] uppercase tracking-wide leading-tight text-muted-foreground">Период</span>
            <span className="block max-w-64 truncate text-sm font-semibold leading-tight">{fmtPeriod(period.from, period.to)}</span>
          </span>
          <ChevronDown className="size-4 shrink-0 opacity-60 transition-transform group-data-[state=open]:rotate-180" aria-hidden="true" />
        </button>
      </PopoverTrigger>
      {/* Потолок по высоте + внутренний скролл: на телефоне (844 px) окно
          разворачивалось на 1059 px, и подвал с «Применить» уезжал за экран —
          период было невозможно сменить вообще. Ширину на мобиле сажаем на
          вьюпорт, иначе календари распирают попап.
          ⚠ Потолок = доступная под триггером высота (radix-переменная), а не
          жёсткие 85dvh: попап открывается от top≈142 px, вниз остаётся ~702 px,
          и 85dvh (717 px) уводил подвал «Готово» на самый край за экран. */}
      <PopoverContent
        align="start"
        sideOffset={6}
        className="max-h-[min(85dvh,var(--radix-popover-content-available-height,85dvh))] w-[calc(100vw-2rem)] overflow-hidden p-0 sm:w-auto"
      >
        <div className="flex max-h-[min(85dvh,var(--radix-popover-content-available-height,85dvh))] max-sm:flex-col">
          {/* Быстрые пресеты — столбцом слева на десктопе, а на телефоне
              горизонтальной лентой сверху (высота ~48 px вместо блока 160 px),
              чтобы не съедать вертикаль у календарей и не выглядеть обрезанными. */}
          <div className="flex shrink-0 gap-0.5 border-border p-2 max-sm:flex-row max-sm:overflow-x-auto max-sm:border-b sm:w-44 sm:flex-col sm:border-r">
            {/* Пресет заполняет черновик и НЕ закрывает окно: часто нужно взять
                «прошлый месяц» и подвинуть одну границу. Подсветка — по
                черновику, чтобы было видно, что именно набрано. */}
            {PERIOD_QUICK.map((preset) => {
              const val = preset.value()
              const isActive = complete
                && val.from === isoLocal(draft.from!) && val.to === isoLocal(draft.to!)
              return (
                <Button
                  key={preset.label}
                  variant={isActive ? 'default' : 'ghost'}
                  size="sm"
                  className="h-8 w-full justify-start text-xs font-medium max-sm:w-auto max-sm:shrink-0 max-sm:justify-center max-sm:whitespace-nowrap"
                  onClick={() => setBoth({ from: parseLocal(val.from), to: parseLocal(val.to) })}
                >
                  {preset.label}
                </Button>
              )
            })}
          </div>

          {/* Прямой ввод дат + календарь диапазоном + итог интервала.
              min-h-0 обязателен: без него flex-ребёнок не даёт вложенному
              блоку скроллиться и высота снова уходит за экран. */}
          <div className="flex min-h-0 flex-1 flex-col">
            {/* Быстрый ввод любой даты без листания — для длинных диапазонов */}
            <div className="flex shrink-0 items-end gap-2 border-b border-border p-3">
              <label className="flex flex-1 flex-col gap-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                Начало
                <Input
                  type="date"
                  value={draft.from ? isoLocal(draft.from) : ''}
                  max={draft.to ? isoLocal(draft.to) : undefined}
                  onChange={(e) => {
                    if (!e.target.value) return
                    const d = parseLocal(e.target.value)
                    setDraft((prev) => ({ ...prev, from: d }))
                    setViewFrom(d)  // перемотать левый календарь к введённой дате
                  }}
                  className="h-9 text-sm font-medium text-foreground"
                />
              </label>
              <span className="pb-2 text-muted-foreground">–</span>
              <label className="flex flex-1 flex-col gap-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                Конец
                <Input
                  type="date"
                  value={draft.to ? isoLocal(draft.to) : ''}
                  min={draft.from ? isoLocal(draft.from) : undefined}
                  onChange={(e) => {
                    if (!e.target.value) return
                    const d = parseLocal(e.target.value)
                    setDraft((prev) => ({ ...prev, to: d }))
                    setViewTo(d)
                  }}
                  className="h-9 text-sm font-medium text-foreground"
                />
              </label>
            </div>

            {/* Два независимых календаря: слева начало, справа конец.
                Диапазон между ними подсвечен в обоих — видно, что именно
                охвачено, даже когда границы в разных месяцах. */}
            {/* Календари скроллятся, подвал с кнопками остаётся на месте */}
            <div className="flex min-h-0 flex-1 overflow-y-auto max-sm:flex-col">
              <div className="sm:border-r sm:border-border">
                <div className="px-3 pt-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  Начало периода
                </div>
                <Calendar
                  mode="single"
                  locale={ru}          // дни недели по-русски, неделя с понедельника
                  captionLayout="dropdown"
                  startMonth={new Date(2023, 0)}
                  endMonth={new Date(new Date().getFullYear() + 1, 11)}
                  month={viewFrom}
                  onMonthChange={setViewFrom}
                  // ui/calendar.tsx форматирует месяц через toLocaleString('default'),
                  // то есть локалью браузера мимо locale — в шапке получался «Jul».
                  // Компоненты ui/ правим не руками, поэтому переопределяем пропом.
                  formatters={{
                    formatMonthDropdown: (date) => date.toLocaleString('ru-RU', { month: 'long' }),
                  }}
                  selected={draft.from}
                  onSelect={(d) => {
                    if (!d) return
                    // Начало позже конца — сдвигаем конец, иначе период пустой.
                    setDraft((prev) => (prev.to && d > prev.to ? { from: d, to: d } : { ...prev, from: d }))
                  }}
                  modifiers={inRange}
                  modifiersClassNames={RANGE_CLASSNAMES}
                />
              </div>
              <div>
                <div className="px-3 pt-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  Конец периода
                </div>
                <Calendar
                  mode="single"
                  locale={ru}
                  captionLayout="dropdown"
                  startMonth={new Date(2023, 0)}
                  endMonth={new Date(new Date().getFullYear() + 1, 11)}
                  month={viewTo}
                  onMonthChange={setViewTo}
                  formatters={{
                    formatMonthDropdown: (date) => date.toLocaleString('ru-RU', { month: 'long' }),
                  }}
                  selected={draft.to}
                  onSelect={(d) => {
                    if (!d) return
                    // Конец раньше начала — сдвигаем начало.
                    setDraft((prev) => (prev.from && d < prev.from ? { from: d, to: d } : { ...prev, to: d }))
                  }}
                  modifiers={inRange}
                  modifiersClassNames={RANGE_CLASSNAMES}
                />
              </div>
            </div>

            <div className="flex shrink-0 items-center justify-between gap-3 border-t border-border bg-popover px-3 py-2.5">
              <div className="min-w-0">
                <div className="text-[11px] uppercase tracking-wide text-muted-foreground">Выбрано</div>
                <div className="truncate text-sm font-semibold text-foreground">
                  {complete
                    ? fmtPeriod(isoLocal(draft.from!), isoLocal(draft.to!))
                    : draft.from
                      ? 'Укажите конец периода'
                      : 'Период не выбран'}
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-1.5">
                <Button variant="ghost" size="sm" className="h-8 text-xs" onClick={() => setOpen(false)}>
                  Отмена
                </Button>
                <Button
                  size="sm"
                  className="h-8 text-xs"
                  disabled={!complete}
                  onClick={apply}
                  title={complete ? undefined : 'Выберите обе границы периода'}
                >
                  {changed ? 'Применить' : 'Готово'}
                </Button>
              </div>
            </div>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  )
}

function SummaryControl({
  icon: Icon,
  label,
  value,
  active = false,
  onClick,
}: {
  icon: LucideIcon
  label: string
  value: string
  active?: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={`${label}: ${value}`}
      className={cn(
        'group flex h-11 shrink-0 items-center gap-2.5 rounded-lg border px-3.5 text-left transition-colors',
        active
          ? 'border-primary/40 bg-primary/10 text-primary hover:bg-primary/15'
          : 'border-border bg-background/50 text-foreground hover:bg-muted/70',
      )}
    >
      <Icon className="size-[18px] shrink-0 opacity-80" aria-hidden="true" />
      <span className="min-w-0">
        <span className="block text-[11px] uppercase tracking-wide leading-tight text-muted-foreground">{label}</span>
        <span className="block max-w-64 truncate text-sm font-semibold leading-tight">{value}</span>
      </span>
    </button>
  )
}

export function WorkspaceFilterBar() {
  const filters = useFilters()
  const { stationCode, clearAll } = filters
  const { company } = useCompany()
  // Контур STS (вид нефтепродукта, источник загрузки, обновление смен) есть только у
  // розницы нефтепродуктов. Раньше признаком служило «не энергетика», и компания без
  // объектов получала в фильтре вопросы про топливо и станции, которых у неё нет.
  const isFuel = company.profileId === 'fuel'
  const isOffice = company.profileId === 'office'
  const stations = getStsStationsFromLocations()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)

  const { isFetching } = useShifts(stationCode === 'all' ? undefined : Number(stationCode))
  const count = activeFilterCount(filters.state)

  const sourceLabel = useMemo(() => {
    if (stationCode === 'all') return 'Все станции STS'
    return stations.find((s) => String(s.code) === stationCode)?.name ?? `Станция ${stationCode}`
  }, [stationCode, stations])


  function handleRefresh() {
    queryClient.invalidateQueries({ queryKey: ['sts-shifts'] })
    queryClient.invalidateQueries({ queryKey: ['sts-shift-report'] })
    queryClient.invalidateQueries({ queryKey: ['sts-receipts'] })
  }

  return (
    <div className="flex min-w-0 flex-1 flex-col gap-1.5">
      <div className="flex w-full min-w-0 items-center gap-1.5">
      <Button
        variant="outline"
        size="sm"
        className="h-11 rounded-lg px-3.5"
        onClick={() => setOpen(true)}
        aria-label={count > 0 ? `Настроить фильтры, активно: ${count}` : 'Настроить фильтры'}
      >
        <SlidersHorizontal data-icon="inline-start" />
        <span className="hidden sm:inline">Фильтры</span>
        {count > 0 ? <Badge className="min-w-5 px-1.5">{count}</Badge> : null}
      </Button>

      <div className="flex min-w-0 flex-1 items-center gap-1.5 overflow-x-auto scrollbar-hide">
        <PeriodControl />
        {isOffice ? null : <WorkspaceScopeControl />}
        {/* Вид нефтепродукта — третье измерение общего контура рядом с периодом и
            областью: у топливного профиля он меняет ответ на любом экране. */}
        {isFuel ? <FuelKindControl /> : null}
        {/* Технический источник загрузки смен: в простом режиме убран — как и
            одноимённая секция внутри модалки фильтра. Период и область учёта
            рядом остаются всегда: это ежедневный контур.
            Исключение: если источник СУЖЕН (выбрана конкретная станция), чип
            виден в любом режиме — иначе цифры на экране молча считались бы по
            одной станции, а признака этого не было бы. */}
        {isFuel ? (
          stationCode !== 'all' ? (
            <SummaryControl
              icon={Database}
              label="Источник STS"
              value={sourceLabel}
              active
              onClick={() => setOpen(true)}
            />
          ) : (
            <AdvancedOnly>
              <SummaryControl
                icon={Database}
                label="Источник STS"
                value={sourceLabel}
                active={false}
                onClick={() => setOpen(true)}
              />
            </AdvancedOnly>
          )
        ) : null}
      </div>

      <div className="ml-auto flex shrink-0 items-center gap-1">
        {count > 0 ? (
          <Button
            variant="ghost"
            size="sm"
            className="h-11 rounded-lg px-2.5 text-muted-foreground"
            onClick={clearAll}
            aria-label="Сбросить все ограничения, период сохранить"
          >
            <RotateCcw data-icon="inline-start" />
            <span className="hidden xl:inline">Сбросить</span>
          </Button>
        ) : null}
        <ViewHistoryMenu />
        {isFuel ? (
          <Button
            variant="ghost"
            size="icon-sm"
            className="size-11 rounded-lg"
            onClick={handleRefresh}
            disabled={isFetching}
            aria-label="Обновить данные STS"
          >
            <RefreshCw className={cn(isFetching && 'animate-spin')} />
          </Button>
        ) : null}
      </div>

      <WorkspaceFilterModal key={open ? 'open' : 'closed'} open={open} onOpenChange={setOpen} />
      </div>
      <ActiveFilterChips />
    </div>
  )
}
