import { useMemo, useState } from 'react'
import {
  Bookmark, CalendarDays, Check, ChevronLeft, ChevronRight, Database, History,
  MapPinned, Plus, RotateCcw, X, type LucideIcon,
} from 'lucide-react'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import {
  Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/checkbox'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { useFilters, type FilterState } from '@/contexts/FilterContext'
import { activeFilterCount, clearFilterSelections, sameFilterState } from '@/contexts/filterState'
import { useCompany } from '@/contexts/CompanyContext'
import { AdvancedOnly, AdvancedHint } from '@/components/common/AdvancedOnly'
import { cn } from '@/lib/utils'
import { useUiLevel } from '@/hooks/useUiLevel'
import { useWorkspace } from '@/contexts/WorkspaceContext'
import { STORE_MODES } from '@/config/storeCatalog'
import { useQuery } from '@tanstack/react-query'
import { useLocations } from '@/hooks/useLocations'
import { getStsStationsFromLocations } from '@/services/locationService'
import { getChargeDimensions } from '@/services/analyticsService'
import { StationScopePicker } from './StationScopePicker'
import { todayISO, daysAgoISO, monthFirstISO, prevMonthBounds } from './analytics/periodPresets'

const PERIOD_PRESETS = [
  { label: 'Вчера', value: () => ({ from: daysAgoISO(1), to: daysAgoISO(1) }) },
  { label: '7 дней', value: () => ({ from: daysAgoISO(7), to: todayISO() }) },
  { label: '30 дней', value: () => ({ from: daysAgoISO(30), to: todayISO() }) },
  { label: 'Текущий месяц', value: () => ({ from: monthFirstISO(), to: todayISO() }) },
  { label: 'Прошлый месяц', value: prevMonthBounds },
  { label: 'Квартал', value: () => ({ from: daysAgoISO(90), to: todayISO() }) },
  { label: 'С начала года', value: () => ({ from: `${new Date().getFullYear()}-01-01`, to: todayISO() }) },
  {
    label: 'Прошлый год',
    value: () => {
      const year = new Date().getFullYear() - 1
      return { from: `${year}-01-01`, to: `${year}-12-31` }
    },
  },
]

/** Длина периода в днях включительно: «62 дня» отвечает на «а сколько взяли». */
function periodDays(period: { from: string; to: string }): number {
  const from = Date.parse(period.from)
  const to = Date.parse(period.to)
  if (Number.isNaN(from) || Number.isNaN(to) || to < from) return 0
  return Math.round((to - from) / 86_400_000) + 1
}

/** Сдвиг периода на его собственную длину — соседний интервал без счёта в уме. */
function shiftPeriod(period: { from: string; to: string }, direction: -1 | 1) {
  const days = periodDays(period)
  if (days === 0) return period
  const move = (iso: string) => {
    const date = new Date(`${iso}T00:00:00Z`)
    date.setUTCDate(date.getUTCDate() + direction * days)
    return date.toISOString().slice(0, 10)
  }
  return { from: move(period.from), to: move(period.to) }
}

function plural(count: number, one: string, few: string, many: string): string {
  const mod10 = count % 10
  const mod100 = count % 100
  if (mod10 === 1 && mod100 !== 11) return one
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few
  return many
}

type ArrayFilterKey = 'locationIds' | 'regionIds' | 'stationCodes'

function cloneState(state: FilterState): FilterState {
  return {
    ...state,
    period: { ...state.period },
    locationIds: [...state.locationIds],
    regionIds: [...state.regionIds],
    stationCodes: [...state.stationCodes],
  }
}

function fmtShort(iso: string): string {
  const [, m, d] = iso.split('-')
  return d && m ? `${d}.${m}` : iso
}

function describeState(state: FilterState): string {
  const scopeCount = state.locationIds.length + state.regionIds.length + state.stationCodes.length
  const parts = [`${fmtShort(state.period.from)}–${fmtShort(state.period.to)}`]
  if (scopeCount > 0) parts.push(`область: ${scopeCount}`)
  if (state.stationCode !== 'all') parts.push(`STS: ${state.stationCode}`)
  return parts.join(' · ')
}

function locationRegion(location: ReturnType<typeof useLocations>[number]): string {
  return String((location.metadata as Record<string, unknown> | undefined)?.federalSubject ?? '').trim()
}

function FilterSection({
  icon: Icon,
  title,
  description,
  action,
  children,
}: {
  icon: LucideIcon
  title: string
  description: string
  action?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-2.5">
          <div className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
            <Icon className="size-4" aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <h3 className="text-sm font-semibold leading-5">{title}</h3>
            <p className="text-xs leading-4 text-muted-foreground">{description}</p>
          </div>
        </div>
        {action}
      </div>
      {children}
    </section>
  )
}

export function WorkspaceFilterModal({ open, onOpenChange }: { open: boolean; onOpenChange: (value: boolean) => void }) {
  const {
    state, applyState, commitToHistory,
    history, presets, savePreset, deletePreset,
  } = useFilters()
  const { company, companyId } = useCompany()
  const isEnergy = company.profileId === 'energy'
  const locations = useLocations()
  const stations = getStsStationsFromLocations()
  const [draft, setDraft] = useState<FilterState>(() => cloneState(state))
  const [locationQuery, setLocationQuery] = useState('')
  const [savingPreset, setSavingPreset] = useState(false)
  const [presetName, setPresetName] = useState('')
  /**
   * Раздел слева — один экран справа.
   *
   * Раньше все секции лежали в одном скролле, а внутри «Области учёта» были ещё
   * два своих (регионы и станции): три уровня прокрутки на одном окне, и глазу
   * не за что зацепиться. Теперь раздел выбирается слева, справа только он —
   * прокрутка одна.
   */
  const [section, setSection] = useState<'period' | 'scope' | 'source'>('period')
  const { isAdvanced } = useUiLevel()

  const { data: dimensions } = useQuery({
    queryKey: ['charge-dimensions', companyId],
    queryFn: () => getChargeDimensions(companyId),
    enabled: isEnergy && open,
  })

  const locationSet = useMemo(() => new Set(draft.locationIds), [draft.locationIds])
  const regionSet = useMemo(() => new Set(draft.regionIds), [draft.regionIds])
  const days = periodDays(draft.period)
  const locationRegions = useMemo(
    () => new Map(locations.map((location) => [location.id, locationRegion(location)])),
    [locations],
  )

  // Регионы топливного профиля — из справочника точек. В энергетическом профиле
  // регион стал фасетом подборщика станций (StationScopePicker): он считается по
  // тем же станциям, что в списке, и потому всегда с ними согласован.
  const regions = useMemo(() => {
    // Отсекаем записи без букв («12» и подобные) — это не регион, а мусор в
    // справочнике. Тот же фильтр стоит в WorkspaceScopePopover; здесь его не
    // было, и «12» висел первым пунктом списка.
    const clean = (list: string[]) => list.filter((r) => /[а-яёa-z]/i.test(r)).sort((a, b) => a.localeCompare(b, 'ru'))
    return clean(Array.from(new Set(locations.map(locationRegion).filter(Boolean))))
  }, [locations])

  const filteredLocations = useMemo(() => {
    const query = locationQuery.trim().toLowerCase()
    return locations
      .filter((location) => draft.regionIds.length === 0 || regionSet.has(locationRegion(location)))
      .filter((location) => !query || location.name.toLowerCase().includes(query))
      .sort((a, b) => a.name.localeCompare(b.name, 'ru'))
  }, [draft.regionIds.length, locationQuery, locations, regionSet])

  const count = activeFilterCount(draft)
  const dirty = !sameFilterState(draft, state)

  // Подписи разделов в левой колонке: видно текущее значение, не заходя внутрь.
  const scopePicked = draft.regionIds.length + draft.locationIds.length + draft.stationCodes.length
  const scopeSummary = scopePicked === 0
    ? 'Вся сеть'
    : [
        draft.regionIds.length ? `регионов: ${draft.regionIds.length}` : null,
        draft.locationIds.length ? `точек: ${draft.locationIds.length}` : null,
        draft.stationCodes.length ? `станций: ${draft.stationCodes.length}` : null,
      ].filter(Boolean).join(' · ')
  const periodSummary = `${fmtShort(draft.period.from)} – ${fmtShort(draft.period.to)}`
  const sourceSummary = draft.stationCode === 'all'
    ? 'Все станции STS'
    : stations.find((s) => String(s.code) === draft.stationCode)?.name ?? draft.stationCode

  // «Типы данных» здесь нет намеренно: секцию сняли вместе с заглушками
  // (613d26b), и пункт меню вёл бы в пустой экран.
  // «Источник STS» — только в расширенном режиме: в простом его содержимое
  // скрыто, и пункт меню вёл бы туда же, в пустоту.
  // «Источник STS» — про загрузку топливных смен: в «Магазине» он ни на что не
  // влияет, и раздел вёл бы к настройке, которая не меняет ни одной цифры на
  // экране (замечание МАГа 25.08.2026). Период и область учёта работают везде.
  const { coreMode } = useWorkspace()
  const showSource = !isEnergy && isAdvanced && !STORE_MODES.includes(coreMode)
  const SECTIONS = [
    { key: 'period' as const, label: 'Период', value: periodSummary, icon: CalendarDays },
    { key: 'scope' as const, label: 'Область учёта', value: scopeSummary, icon: MapPinned },
    ...(showSource ? [{ key: 'source' as const, label: 'Источник STS', value: sourceSummary, icon: Database }] : []),
  ]

  // Раздел исчез при переключении в простой режим — возвращаемся к периоду.
  if (section === 'source' && !showSource) setSection('period')

  function toggleValue(key: ArrayFilterKey, value: string) {
    setDraft((current) => {
      const next = new Set(current[key])
      if (next.has(value)) next.delete(value)
      else next.add(value)
      return { ...current, [key]: [...next] }
    })
  }

  function toggleRegion(region: string) {
    setDraft((current) => {
      const next = new Set(current.regionIds)
      if (next.has(region)) next.delete(region)
      else next.add(region)
      const regionIds = [...next]
      const locationIds = regionIds.length === 0
        ? current.locationIds
        : current.locationIds.filter((id) => next.has(locationRegions.get(id) ?? ''))
      return { ...current, regionIds, locationIds }
    })
  }

  function applyDraft(next: FilterState) {
    setDraft(cloneState(next))
  }

  function handleApply() {
    applyState(draft)
    commitToHistory(draft)
    onOpenChange(false)
  }

  function handleSavePreset() {
    const name = presetName.trim()
    if (!name) return
    savePreset(name, draft)
    setPresetName('')
    setSavingPreset(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        /* Окно, в котором работают со списком, не делают уже рабочего экрана
           (DESIGN.md → Layout): 96vw до 1600px и 92dvh, как у «Чата» и «Трека».
           Прежние 896px держали шестьсот станций в колонке шириной с телефон —
           адрес обрезался на «63 км тр…», а полэкрана рядом пустовало. */
        className="flex h-[calc(100vh-1rem)] w-[calc(100vw-1rem)] max-w-[1600px] flex-col gap-0 overflow-hidden rounded-xl p-0 sm:h-[92dvh] sm:w-[96vw]"
      >
        <DialogHeader className="shrink-0 border-b px-4 py-4 text-left sm:px-5">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <DialogTitle>Фильтры рабочей области</DialogTitle>
                <Badge variant={count > 0 ? 'default' : 'secondary'}>
                  {count > 0 ? `Ограничений: ${count}` : 'Вся сеть'}
                </Badge>
              </div>
              <DialogDescription className="mt-1">
                Соберите выборку и примените её ко всем разделам рабочего стола.
              </DialogDescription>
            </div>
            <Button
              variant="ghost"
              size="icon-sm"
              className="size-8 rounded-lg"
              onClick={() => onOpenChange(false)}
              aria-label="Закрыть без применения"
            >
              <X />
            </Button>
          </div>
        </DialogHeader>

        <div className="grid min-h-0 flex-1 md:grid-cols-[260px_minmax(0,1fr)]">
          <aside className="flex max-h-56 flex-col gap-4 overflow-y-auto border-b bg-muted/20 p-3 md:max-h-none md:border-r md:border-b-0 md:p-4">
            {/* Разделы контура с текущими значениями — можно окинуть взглядом
                всю выборку, не открывая каждый. */}
            <nav className="flex flex-col gap-0.5" aria-label="Разделы фильтра">
              {SECTIONS.map((s) => {
                const Icon = s.icon
                const active = section === s.key
                return (
                  <button
                    key={s.key}
                    type="button"
                    aria-current={active ? 'true' : undefined}
                    onClick={() => setSection(s.key)}
                    className={cn(
                      'flex items-start gap-2 rounded-lg px-2.5 py-2 text-left transition-colors',
                      active ? 'bg-primary/10 text-primary' : 'hover:bg-background/70',
                    )}
                  >
                    <Icon className={cn('mt-0.5 size-4 shrink-0', active ? 'text-primary' : 'text-muted-foreground')} />
                    <span className="min-w-0">
                      <span className="block truncate text-xs font-semibold">{s.label}</span>
                      <span className={cn('block truncate text-xs', active ? 'text-primary/80' : 'text-muted-foreground')}>
                        {s.value}
                      </span>
                    </span>
                  </button>
                )
              })}
              {/* Скрытый раздел обозначен прямо в навигации — «тихо пропало»
                  недопустимо (см. useUiLevel, правило 2). */}
              {!isEnergy && !isAdvanced ? (
                <div className="px-2.5 pt-1">
                  <AdvancedHint count={1} what="раздел — источник онлайн-данных STS" />
                </div>
              ) : null}
            </nav>

            <Separator />

            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between gap-2">
                <h3
                  className="flex items-center gap-1.5 text-xs font-semibold"
                  title="Применяются к черновику — можно донастроить перед «Применить». Полные виды (раздел + пункт + параметры) сохраняются в меню «Виды»."
                >
                  <Bookmark className="size-3.5" aria-hidden="true" />
                  Быстрые наборы
                </h3>
              </div>

              {/* Кнопка со словом, а не «+»: набранную фасетами выборку хотят
                  сохранить, и значок в углу для этого не находят глазом. */}
              {!savingPreset ? (
                <Button
                  variant="outline"
                  size="xs"
                  className="h-8 w-full justify-start"
                  onClick={() => setSavingPreset(true)}
                >
                  <Plus data-icon="inline-start" />
                  Сохранить текущую выборку
                </Button>
              ) : null}

              {savingPreset ? (
                <div className="flex items-center gap-1">
                  <Input
                    autoFocus
                    value={presetName}
                    onChange={(event) => setPresetName(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter') handleSavePreset()
                      if (event.key === 'Escape') { setSavingPreset(false); setPresetName('') }
                    }}
                    placeholder={describeState(draft)}
                    className="h-8 text-xs"
                    aria-label="Название набора"
                  />
                  <Button variant="ghost" size="icon-xs" onClick={handleSavePreset} disabled={!presetName.trim()} aria-label="Сохранить набор">
                    <Check />
                  </Button>
                </div>
              ) : null}

              {presets.length === 0 && !savingPreset ? (
                <p className="text-xs leading-4 text-muted-foreground">Сохраните часто используемую выборку.</p>
              ) : null}

              <div className="flex flex-col gap-1">
                {presets.map((preset) => (
                  <div key={preset.id} className="group flex items-center gap-1 rounded-md hover:bg-background/70">
                    <button
                      type="button"
                      className="min-w-0 flex-1 px-2 py-1.5 text-left"
                      onClick={() => applyDraft(preset.state)}
                      title={describeState(preset.state)}
                    >
                      <span className="block truncate text-xs font-medium">{preset.name}</span>
                      <span className="block truncate text-xs text-muted-foreground">{describeState(preset.state)}</span>
                    </button>
                    <Button
                      variant="ghost"
                      size="icon-xs"
                      className="mr-1 opacity-60 group-hover:opacity-100"
                      onClick={() => deletePreset(preset.id)}
                      aria-label={`Удалить набор ${preset.name}`}
                    >
                      <X />
                    </Button>
                  </div>
                ))}
              </div>
            </div>

            {history.length > 0 ? (
              <>
                <Separator />
                <div className="flex flex-col gap-2">
                  <h3 className="flex items-center gap-1.5 text-xs font-semibold">
                    <History className="size-3.5" aria-hidden="true" />
                    Недавние выборки
                  </h3>
                  <div className="flex flex-col gap-1">
                    {history.slice(0, 6).map((entry, index) => (
                      <button
                        key={`${entry.period.from}-${entry.period.to}-${index}`}
                        type="button"
                        className="rounded-md px-2 py-1.5 text-left text-xs text-muted-foreground hover:bg-background/70 hover:text-foreground"
                        onClick={() => applyDraft(entry)}
                      >
                        {describeState(entry)}
                      </button>
                    ))}
                  </div>
                </div>
              </>
            ) : null}
          </aside>

          <div className="flex min-h-0 flex-col overflow-hidden">
          <ScrollArea className={cn('min-h-0 flex-1', section === 'scope' && isEnergy ? 'hidden' : null)}>
            <div className="flex flex-col gap-6 p-4 sm:p-5">
              {section === 'period' && (
              <FilterSection
                icon={CalendarDays}
                title="Период"
                description="Единый интервал для отчётов, сверок и документов."
                action={(
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {days > 0
                      ? `${days} ${plural(days, 'день', 'дня', 'дней')}`
                      : 'Даты заданы наоборот'}
                  </span>
                )}
              >
                <div className="flex flex-wrap items-end gap-2">
                  <label className="flex flex-col gap-1 text-xs text-muted-foreground">
                    С даты
                    <Input
                      type="date"
                      value={draft.period.from}
                      max={draft.period.to}
                      onChange={(event) => setDraft((current) => ({ ...current, period: { ...current.period, from: event.target.value } }))}
                      className="h-9 w-[150px] text-xs text-foreground"
                    />
                  </label>
                  <label className="flex flex-col gap-1 text-xs text-muted-foreground">
                    По дату
                    <Input
                      type="date"
                      value={draft.period.to}
                      min={draft.period.from}
                      onChange={(event) => setDraft((current) => ({ ...current, period: { ...current.period, to: event.target.value } }))}
                      className="h-9 w-[150px] text-xs text-foreground"
                    />
                  </label>
                  {/* Сдвиг на длину периода: «тот же месяц назад» — самый частый
                      следующий шаг после выбора интервала, и считать даты руками
                      для этого не нужно. */}
                  <div className="flex items-center gap-1">
                    <Button
                      variant="outline" size="xs" className="h-8"
                      onClick={() => setDraft((current) => ({ ...current, period: shiftPeriod(current.period, -1) }))}
                      disabled={days === 0}
                      aria-label="Сдвинуть период назад на его длину"
                    >
                      <ChevronLeft />
                    </Button>
                    <Button
                      variant="outline" size="xs" className="h-8"
                      onClick={() => setDraft((current) => ({ ...current, period: shiftPeriod(current.period, 1) }))}
                      disabled={days === 0}
                      aria-label="Сдвинуть период вперёд на его длину"
                    >
                      <ChevronRight />
                    </Button>
                  </div>
                </div>
                <div className="flex flex-wrap gap-1">
                  {PERIOD_PRESETS.map((preset) => {
                    const value = preset.value()
                    const active = value.from === draft.period.from && value.to === draft.period.to
                    return (
                      <Button
                        key={preset.label}
                        variant={active ? 'default' : 'outline'}
                        size="xs"
                        className="h-8"
                        aria-pressed={active}
                        onClick={() => setDraft((current) => ({ ...current, period: preset.value() }))}
                      >
                        {preset.label}
                      </Button>
                    )
                  })}
                </div>
              </FilterSection>
              )}

              {section === 'scope' && !isEnergy && (
              <FilterSection
                icon={MapPinned}
                title="Область учёта"
                description="Регион сужает список точек; выбранные точки задают рабочий контур."
                action={draft.locationIds.length + draft.regionIds.length + draft.stationCodes.length > 0 ? (
                  <Button
                    variant="ghost"
                    size="xs"
                    onClick={() => setDraft((current) => ({ ...current, locationIds: [], regionIds: [], stationCodes: [] }))}
                  >
                    Очистить
                  </Button>
                ) : undefined}
              >
                {regions.length > 0 ? (
                  <fieldset className="flex flex-col gap-2">
                    <legend className="mb-1 text-xs font-medium">Регионы</legend>
                    <div className="grid max-h-32 grid-cols-1 gap-0.5 overflow-y-auto rounded-md border p-1.5 sm:grid-cols-2">
                      {regions.map((region) => (
                        <label key={region} className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-xs hover:bg-muted/70">
                          <Checkbox checked={regionSet.has(region)} onCheckedChange={() => toggleRegion(region)} />
                          <span className="truncate">{region}</span>
                        </label>
                      ))}
                    </div>
                  </fieldset>
                ) : null}

                <fieldset className="flex flex-col gap-2">
                  <div className="flex items-center justify-between gap-2">
                    <legend className="text-xs font-medium">Точки обслуживания</legend>
                    <span className="text-xs text-muted-foreground">Выбрано: {draft.locationIds.length}</span>
                  </div>
                  <Input
                    placeholder="Найти точку"
                    value={locationQuery}
                    onChange={(event) => setLocationQuery(event.target.value)}
                    className="h-9 text-xs"
                  />
                  <div className="max-h-44 overflow-y-auto rounded-md border p-1.5">
                    {filteredLocations.length === 0 ? (
                      <p className="px-2 py-5 text-center text-xs text-muted-foreground">Точки не найдены</p>
                    ) : filteredLocations.map((location) => (
                      <label key={location.id} className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-xs hover:bg-muted/70">
                        <Checkbox checked={locationSet.has(location.id)} onCheckedChange={() => toggleValue('locationIds', location.id)} />
                        <span className="min-w-0 flex-1 truncate">{location.name}</span>
                        {locationRegion(location) ? (
                          <span className="hidden shrink-0 text-xs text-muted-foreground sm:inline">{locationRegion(location)}</span>
                        ) : null}
                      </label>
                    ))}
                  </div>
                </fieldset>
              </FilterSection>
              )}

              {/* Технический источник загрузки смен — нужен редко. В простом
                  режиме раздела нет ни в меню, ни здесь; подсказка о нём стоит
                  в навигации слева. Период и область учёта не прячем никогда:
                  это ежедневный контур. */}
              {section === 'source' && showSource ? (
                <>
                  <AdvancedOnly>
                  <FilterSection
                    icon={Database}
                    title="Источник онлайн-данных STS"
                    description="Отдельный источник загрузки смен. Он не заменяет область учёта выше."
                    action={draft.stationCode !== 'all' ? (
                      <Button variant="ghost" size="xs" onClick={() => setDraft((current) => ({ ...current, stationCode: 'all' }))}>
                        Сбросить
                      </Button>
                    ) : undefined}
                  >
                    <Select value={draft.stationCode} onValueChange={(stationCode) => setDraft((current) => ({ ...current, stationCode }))}>
                      <SelectTrigger size="sm" className="w-full max-w-sm">
                        <SelectValue placeholder="Все станции STS" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectGroup>
                          <SelectItem value="all">Все станции STS</SelectItem>
                          {stations.map((station) => (
                            <SelectItem key={station.code} value={String(station.code)}>{station.name}</SelectItem>
                          ))}
                        </SelectGroup>
                      </SelectContent>
                    </Select>
                  </FilterSection>
                  </AdvancedOnly>
                </>
              ) : null}

            </div>
          </ScrollArea>

          {/* Подбор станций живёт вне общего скролла: список должен занимать всю
              высоту окна, а не ютиться в полосе на 176 пикселей, под которой
              пустует полэкрана. */}
          {section === 'scope' && isEnergy ? (
            <div className="flex min-h-0 flex-1 flex-col gap-3 p-4 sm:p-5">
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 items-start gap-2.5">
                  <div className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
                    <MapPinned className="size-4" aria-hidden="true" />
                  </div>
                  <div className="min-w-0">
                    <h3 className="text-sm font-semibold leading-5">Область учёта</h3>
                    <p className="text-xs leading-4 text-muted-foreground">
                      Условия слева сужают сеть; отмеченные станции задают рабочий контур.
                    </p>
                  </div>
                </div>
                {draft.stationCodes.length + draft.regionIds.length > 0 ? (
                  <Button
                    variant="ghost"
                    size="xs"
                    onClick={() => setDraft((current) => ({ ...current, locationIds: [], regionIds: [], stationCodes: [] }))}
                  >
                    Очистить
                  </Button>
                ) : null}
              </div>
              <StationScopePicker
                stations={dimensions?.stations ?? []}
                selected={draft.stationCodes}
                onChange={(codes) => setDraft((current) => ({ ...current, stationCodes: codes }))}
                regionIds={draft.regionIds}
                onRegionsChange={(regionIds) => setDraft((current) => ({ ...current, regionIds }))}
              />
            </div>
          ) : null}
          </div>
        </div>

        <DialogFooter className="shrink-0 flex-row items-center justify-between border-t px-3 py-3 sm:px-5">
          <Button
            variant="ghost"
            size="sm"
            className="h-9 rounded-lg text-muted-foreground"
            onClick={() => setDraft(clearFilterSelections(draft))}
            disabled={count === 0}
          >
            <RotateCcw data-icon="inline-start" />
            <span className="hidden sm:inline">Сбросить ограничения</span>
            <span className="sm:hidden">Сбросить</span>
          </Button>
          <div className="flex min-w-0 items-center gap-3">
            {/* Итог набранного — чтобы применять, не проверяя каждый раздел. */}
            <span className="hidden min-w-0 truncate text-xs text-muted-foreground sm:block">
              Выбрано: <span className="font-medium text-foreground">{periodSummary}</span>
              {' · '}
              <span className="font-medium text-foreground">{scopeSummary}</span>
            </span>
            <Button
              variant="outline"
              size="sm"
              className="h-9 rounded-lg"
              onClick={() => setSavingPreset(true)}
              disabled={savingPreset}
              title="Сохранить набранную выборку в быстрые наборы"
            >
              <Bookmark data-icon="inline-start" />
              <span className="hidden sm:inline">В быстрые наборы</span>
              <span className="sm:hidden">В наборы</span>
            </Button>
            <Button variant="outline" size="sm" className="h-9 rounded-lg" onClick={() => onOpenChange(false)}>
              Отмена
            </Button>
            <Button size="sm" className="h-9 rounded-lg" onClick={handleApply} disabled={!dirty}>
              <Check data-icon="inline-start" />
              Применить
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
