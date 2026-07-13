import { useMemo, useState } from 'react'
import {
  Bookmark, CalendarDays, Check, Database, FileText, History,
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
import { useQuery } from '@tanstack/react-query'
import { useLocations } from '@/hooks/useLocations'
import { getStsStationsFromLocations } from '@/services/locationService'
import { getChargeDimensions } from '@/services/analyticsService'
import { todayISO, daysAgoISO, monthFirstISO, prevMonthBounds } from './analytics/periodPresets'

const FUEL_DOC_TYPES = [
  { id: 'shift_report', label: 'Сменные отчёты' },
  { id: 'receipt', label: 'Поступления (ТТН)' },
  { id: 'price', label: 'Цены' },
  { id: 'sts_transactions', label: 'Операции отпуска' },
  { id: 'sts_coupons', label: 'Купоны и талоны' },
  { id: 'sts_tanks', label: 'Остатки резервуаров' },
  { id: 'msto_transactions', label: 'MSTO транзакции' },
  { id: 'corp_transactions', label: 'TradeCorp транзакции' },
]

const ENERGY_DOC_TYPES = [
  { id: 'charge_sessions', label: 'Зарядные сессии' },
  { id: 'ofd_z_reports', label: 'Z-отчёты ОФД' },
  { id: 'energy_supply_invoices', label: 'Счета поставщика э/э' },
  { id: 'maintenance_acts', label: 'Акты ТО' },
  { id: 'rent_contracts', label: 'Договоры аренды' },
]

const PERIOD_PRESETS = [
  { label: '30 дней', value: () => ({ from: daysAgoISO(30), to: todayISO() }) },
  { label: 'Текущий месяц', value: () => ({ from: monthFirstISO(), to: todayISO() }) },
  { label: 'Прошлый месяц', value: prevMonthBounds },
  { label: 'С начала года', value: () => ({ from: `${new Date().getFullYear()}-01-01`, to: todayISO() }) },
]

type ArrayFilterKey = 'locationIds' | 'regionIds' | 'stationCodes' | 'docTypeIds'

function cloneState(state: FilterState): FilterState {
  return {
    ...state,
    period: { ...state.period },
    locationIds: [...state.locationIds],
    regionIds: [...state.regionIds],
    stationCodes: [...state.stationCodes],
    docTypeIds: [...state.docTypeIds],
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
  if (state.docTypeIds.length > 0) parts.push(`данные: ${state.docTypeIds.length}`)
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
  const [stationQuery, setStationQuery] = useState('')
  const [savingPreset, setSavingPreset] = useState(false)
  const [presetName, setPresetName] = useState('')

  const { data: dimensions } = useQuery({
    queryKey: ['charge-dimensions', companyId],
    queryFn: () => getChargeDimensions(companyId),
    enabled: isEnergy && open,
  })

  const docTypes = isEnergy ? ENERGY_DOC_TYPES : FUEL_DOC_TYPES
  const locationSet = useMemo(() => new Set(draft.locationIds), [draft.locationIds])
  const regionSet = useMemo(() => new Set(draft.regionIds), [draft.regionIds])
  const stationCodeSet = useMemo(() => new Set(draft.stationCodes), [draft.stationCodes])
  const docTypeSet = useMemo(() => new Set(draft.docTypeIds), [draft.docTypeIds])
  const locationRegions = useMemo(
    () => new Map(locations.map((location) => [location.id, locationRegion(location)])),
    [locations],
  )

  const regions = useMemo(() => {
    if (isEnergy) return [...(dimensions?.regions ?? [])].map((region) => region.region).sort((a, b) => a.localeCompare(b, 'ru'))
    return Array.from(new Set(locations.map(locationRegion).filter(Boolean))).sort((a, b) => a.localeCompare(b, 'ru'))
  }, [dimensions?.regions, isEnergy, locations])

  const filteredLocations = useMemo(() => {
    const query = locationQuery.trim().toLowerCase()
    return locations
      .filter((location) => draft.regionIds.length === 0 || regionSet.has(locationRegion(location)))
      .filter((location) => !query || location.name.toLowerCase().includes(query))
      .sort((a, b) => a.name.localeCompare(b.name, 'ru'))
  }, [draft.regionIds.length, locationQuery, locations, regionSet])

  const energyStations = useMemo(() => {
    const query = stationQuery.trim().toLowerCase()
    return (dimensions?.stations ?? []).filter((station) => (
      !query || `${station.name} ${station.code}`.toLowerCase().includes(query)
    ))
  }, [dimensions?.stations, stationQuery])

  const count = activeFilterCount(draft)
  const dirty = !sameFilterState(draft, state)

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
        className="flex h-[calc(100vh-1rem)] w-[calc(100vw-1rem)] max-w-4xl flex-col gap-0 overflow-hidden rounded-xl p-0 sm:h-[min(760px,calc(100vh-2rem))] sm:w-[calc(100vw-2rem)]"
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

        <div className="grid min-h-0 flex-1 md:grid-cols-[230px_minmax(0,1fr)]">
          <aside className="flex max-h-48 flex-col gap-4 overflow-y-auto border-b bg-muted/20 p-3 md:max-h-none md:border-r md:border-b-0 md:p-4">
            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between gap-2">
                <h3 className="flex items-center gap-1.5 text-xs font-semibold">
                  <Bookmark className="size-3.5" aria-hidden="true" />
                  Сохранённые наборы
                </h3>
                {!savingPreset ? (
                  <Button variant="ghost" size="icon-xs" onClick={() => setSavingPreset(true)} aria-label="Сохранить текущий набор">
                    <Plus />
                  </Button>
                ) : null}
              </div>

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
                    placeholder="Название набора"
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
                      <span className="block truncate text-[10px] text-muted-foreground">{describeState(preset.state)}</span>
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

          <ScrollArea className="min-h-0">
            <div className="flex flex-col gap-6 p-4 sm:p-5">
              <FilterSection
                icon={CalendarDays}
                title="Период"
                description="Единый интервал для отчётов, сверок и документов."
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
                  <div className="flex flex-wrap gap-1">
                    {PERIOD_PRESETS.map((preset) => (
                      <Button
                        key={preset.label}
                        variant="outline"
                        size="xs"
                        className="h-8"
                        onClick={() => setDraft((current) => ({ ...current, period: preset.value() }))}
                      >
                        {preset.label}
                      </Button>
                    ))}
                  </div>
                </div>
              </FilterSection>

              <Separator />

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

                {isEnergy ? (
                  <fieldset className="flex flex-col gap-2">
                    <div className="flex items-center justify-between gap-2">
                      <legend className="text-xs font-medium">Станции ЭЗС</legend>
                      <span className="text-[10px] text-muted-foreground">Выбрано: {draft.stationCodes.length}</span>
                    </div>
                    <Input
                      placeholder="Найти станцию по названию или коду"
                      value={stationQuery}
                      onChange={(event) => setStationQuery(event.target.value)}
                      className="h-9 text-xs"
                    />
                    <div className="max-h-44 overflow-y-auto rounded-md border p-1.5">
                      {energyStations.length === 0 ? (
                        <p className="px-2 py-5 text-center text-xs text-muted-foreground">Станции не найдены</p>
                      ) : energyStations.map((station) => (
                        <label key={station.code} className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-xs hover:bg-muted/70">
                          <Checkbox checked={stationCodeSet.has(station.code)} onCheckedChange={() => toggleValue('stationCodes', station.code)} />
                          <span className="min-w-0 flex-1 truncate">{station.name}</span>
                          <span className="shrink-0 tabular-nums text-muted-foreground">{station.code}</span>
                        </label>
                      ))}
                    </div>
                  </fieldset>
                ) : (
                  <fieldset className="flex flex-col gap-2">
                    <div className="flex items-center justify-between gap-2">
                      <legend className="text-xs font-medium">Точки обслуживания</legend>
                      <span className="text-[10px] text-muted-foreground">Выбрано: {draft.locationIds.length}</span>
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
                            <span className="hidden shrink-0 text-[10px] text-muted-foreground sm:inline">{locationRegion(location)}</span>
                          ) : null}
                        </label>
                      ))}
                    </div>
                  </fieldset>
                )}
              </FilterSection>

              {!isEnergy ? (
                <>
                  <Separator />
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
                </>
              ) : null}

              <Separator />

              <FilterSection
                icon={FileText}
                title="Типы данных"
                description="Ограничение действует только в разделах, которые поддерживают выбранные типы."
                action={draft.docTypeIds.length > 0 ? (
                  <Button variant="ghost" size="xs" onClick={() => setDraft((current) => ({ ...current, docTypeIds: [] }))}>
                    Все типы
                  </Button>
                ) : undefined}
              >
                <fieldset>
                  <legend className="sr-only">Типы данных</legend>
                  <div className="grid grid-cols-1 gap-0.5 rounded-md border p-1.5 sm:grid-cols-2">
                    {docTypes.map((docType) => (
                      <label key={docType.id} className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-xs hover:bg-muted/70">
                        <Checkbox checked={docTypeSet.has(docType.id)} onCheckedChange={() => toggleValue('docTypeIds', docType.id)} />
                        <span className="truncate">{docType.label}</span>
                      </label>
                    ))}
                  </div>
                </fieldset>
              </FilterSection>
            </div>
          </ScrollArea>
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
          <div className="flex items-center gap-2">
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
