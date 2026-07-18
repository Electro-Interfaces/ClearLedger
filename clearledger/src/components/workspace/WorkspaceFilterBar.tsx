import { useMemo, useState } from 'react'
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
import { ViewHistoryMenu } from './ViewHistoryMenu'
import { ActiveFilterChips } from '@/components/common/ActiveFilterChips'
import { AdvancedOnly } from '@/components/common/AdvancedOnly'
import { cn } from '@/lib/utils'

const MONTHS_SHORT = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']

/** «30 июн – 17 июл 2026» — месяц словом, год один раз (или у каждой даты, если разные). */
function fmtPeriod(fromIso: string, toIso: string): string {
  const [fy, fm, fd] = fromIso.split('-').map(Number)
  const [ty, tm, td] = toIso.split('-').map(Number)
  if (!fd || !td) return `${fromIso} – ${toIso}`
  const from = `${fd} ${MONTHS_SHORT[fm - 1]}`
  const to = `${td} ${MONTHS_SHORT[tm - 1]}`
  return fy === ty ? `${from} – ${to} ${ty}` : `${from} ${fy} – ${to} ${ty}`
}

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

  function openChange(next: boolean) {
    // При каждом открытии черновик берётся из текущего контура: незавершённый
    // выбор прошлого раза не должен «залипать».
    if (next) setDraft({ from: parseLocal(period.from), to: parseLocal(period.to) })
    setOpen(next)
  }

  const complete = !!draft.from && !!draft.to
  const changed = complete
    && (isoLocal(draft.from!) !== period.from || isoLocal(draft.to!) !== period.to)

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
      <PopoverContent align="start" sideOffset={6} className="w-auto p-0">
        <div className="flex max-sm:flex-col">
          {/* Быстрые пресеты — столбцом слева */}
          <div className="flex flex-col gap-0.5 border-border p-2 max-sm:border-b sm:w-44 sm:border-r">
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
                  className="h-8 w-full justify-start text-xs font-medium"
                  onClick={() => setDraft({ from: parseLocal(val.from), to: parseLocal(val.to) })}
                >
                  {preset.label}
                </Button>
              )
            })}
          </div>

          {/* Прямой ввод дат + календарь диапазоном + итог интервала */}
          <div className="flex flex-col">
            {/* Быстрый ввод любой даты без листания — для длинных диапазонов */}
            <div className="flex items-end gap-2 border-b border-border p-3">
              <label className="flex flex-1 flex-col gap-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                Начало
                <Input
                  type="date"
                  value={draft.from ? isoLocal(draft.from) : ''}
                  max={draft.to ? isoLocal(draft.to) : undefined}
                  onChange={(e) => { if (e.target.value) setDraft((d) => ({ ...d, from: parseLocal(e.target.value) })) }}
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
                  onChange={(e) => { if (e.target.value) setDraft((d) => ({ ...d, to: parseLocal(e.target.value) })) }}
                  className="h-9 text-sm font-medium text-foreground"
                />
              </label>
            </div>

            {/* Диапазон отдаётся календарю как есть, включая незавершённый
                («выбрано начало»). Ничего не достраиваем за пользователя —
                именно это раньше схлопывало интервал в один день. */}
            <Calendar
              mode="range"
              captionLayout="dropdown"
              startMonth={new Date(2023, 0)}
              endMonth={new Date(new Date().getFullYear() + 1, 11)}
              defaultMonth={draft.from ?? parseLocal(period.from)}
              selected={{ from: draft.from, to: draft.to }}
              onSelect={(range) => setDraft({ from: range?.from, to: range?.to })}
              numberOfMonths={2}
            />

            <div className="flex items-center justify-between gap-3 border-t border-border px-3 py-2.5">
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
  const isEnergy = company.profileId === 'energy'
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
        <WorkspaceScopeControl />
        {/* Технический источник загрузки смен: в простом режиме убран — как и
            одноимённая секция внутри модалки фильтра. Период и область учёта
            рядом остаются всегда: это ежедневный контур.
            Исключение: если источник СУЖЕН (выбрана конкретная станция), чип
            виден в любом режиме — иначе цифры на экране молча считались бы по
            одной станции, а признака этого не было бы. */}
        {!isEnergy ? (
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
        {!isEnergy ? (
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
