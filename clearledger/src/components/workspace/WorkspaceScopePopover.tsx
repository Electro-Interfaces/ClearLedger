/**
 * Селектор «Область учёта» (сеть для анализа) — отдельное модальное окно.
 * Идеологически как выбор периода: только функции выбора сети, выбор
 * сразу через контекст фильтров (без общей модалки настроек).
 *
 * Три зоны: Регионы · Станции/Точки · «Выбрано» (наглядная сводка отобранного).
 * energy (РусГидро): регионы + станции ЭЗС (charge-dimensions, с числом сессий).
 * fuel: регионы + точки обслуживания (gig-locations, регион сужает список).
 */

import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Check, MapPinned, RotateCcw, Search, X } from 'lucide-react'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/checkbox'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useFilters } from '@/contexts/FilterContext'
import { useCompany } from '@/contexts/CompanyContext'
import { useLocations } from '@/hooks/useLocations'
import { getChargeDimensions } from '@/services/analyticsService'

function locationRegion(location: ReturnType<typeof useLocations>[number]): string {
  return String((location.metadata as Record<string, unknown> | undefined)?.federalSubject ?? '').trim()
}

/** Компактный чип выбранного элемента с удалением по крестику. */
function SelectedChip({ label, sub, onRemove }: { label: string; sub?: string; onRemove: () => void }) {
  return (
    <span className="group inline-flex max-w-full items-center gap-1.5 rounded-md border border-primary/30 bg-primary/10 py-1 pl-2.5 pr-1 text-primary">
      <span className="min-w-0 truncate text-xs font-medium">{label}</span>
      {sub ? <span className="shrink-0 text-[10px] tabular-nums opacity-70">{sub}</span> : null}
      <button
        type="button"
        onClick={onRemove}
        aria-label={`Убрать ${label}`}
        className="shrink-0 rounded p-0.5 text-primary/70 transition-colors hover:bg-primary/20 hover:text-primary"
      >
        <X className="size-3.5" />
      </button>
    </span>
  )
}

export function WorkspaceScopeControl() {
  const [open, setOpen] = useState(false)
  const [regionQuery, setRegionQuery] = useState('')
  const [stationQuery, setStationQuery] = useState('')
  const { company, companyId } = useCompany()
  const isEnergy = company.profileId === 'energy'
  const {
    regionIds, setRegionIds,
    stationCodes, setStationCodes,
    locationIds, setLocationIds,
  } = useFilters()
  const locations = useLocations()

  /**
   * Черновик выбора (модель диалога 1С: набрал — подтвердил).
   *
   * Раньше каждый чекбокс писался прямо в контур: при 400+ станциях это
   * означало перезапрос данных на каждый клик и невозможность отменить —
   * «Готово» лишь закрывало окно, а изменения уже произошли.
   */
  const [draftRegions, setDraftRegions] = useState<string[]>(regionIds)
  const [draftStations, setDraftStations] = useState<string[]>(stationCodes)
  const [draftLocations, setDraftLocations] = useState<string[]>(locationIds)

  function openChange(next: boolean) {
    // Открытие всегда начинается от текущего контура — незавершённый выбор
    // прошлого раза не «залипает».
    if (next) {
      setDraftRegions(regionIds)
      setDraftStations(stationCodes)
      setDraftLocations(locationIds)
      setRegionQuery('')
      setStationQuery('')
    }
    setOpen(next)
  }

  function apply() {
    setRegionIds(draftRegions)
    setStationCodes(draftStations)
    setLocationIds(draftLocations)
    setOpen(false)
  }

  const draftDirty = draftRegions.length !== regionIds.length
    || draftStations.length !== stationCodes.length
    || draftLocations.length !== locationIds.length
    || draftRegions.some((r) => !regionIds.includes(r))
    || draftStations.some((s) => !stationCodes.includes(s))
    || draftLocations.some((l) => !locationIds.includes(l))

  const toggleDraftRegion = (name: string) =>
    setDraftRegions((prev) => (prev.includes(name) ? prev.filter((r) => r !== name) : [...prev, name]))
  const toggleDraftStation = (code: number | string) =>
    setDraftStations((prev) => { const k = String(code); return prev.includes(k) ? prev.filter((c) => c !== k) : [...prev, k] })
  const toggleDraftLocation = (id: string) =>
    setDraftLocations((prev) => (prev.includes(id) ? prev.filter((l) => l !== id) : [...prev, id]))

  const { data: dimensions } = useQuery({
    queryKey: ['charge-dimensions', companyId],
    queryFn: () => getChargeDimensions(companyId),
    enabled: isEnergy && open,
  })

  // Внутри окна всё считается по черновику; чип снаружи — по контуру.
  const regionSet = useMemo(() => new Set(draftRegions), [draftRegions])
  const stationCodeSet = useMemo(() => new Set(draftStations), [draftStations])
  const locationSet = useMemo(() => new Set(draftLocations), [draftLocations])

  // Регионы со счётчиком (сессии для energy; число точек для fuel).
  // Отсекаем мусорные записи без букв (напр. «12») — это не регион.
  const regions = useMemo(() => {
    const raw = isEnergy
      ? [...(dimensions?.regions ?? [])].map((r) => ({ name: r.region, count: r.sessions }))
      : (() => {
          const byRegion = new Map<string, number>()
          for (const l of locations) {
            const r = locationRegion(l)
            if (r) byRegion.set(r, (byRegion.get(r) ?? 0) + 1)
          }
          return [...byRegion.entries()].map(([name, count]) => ({ name, count }))
        })()
    return raw
      .filter((r) => /[а-яёa-z]/i.test(r.name))
      .sort((a, b) => a.name.localeCompare(b.name, 'ru'))
  }, [dimensions?.regions, isEnergy, locations])

  const filteredRegions = useMemo(() => {
    const q = regionQuery.trim().toLowerCase()
    return q ? regions.filter((r) => r.name.toLowerCase().includes(q)) : regions
  }, [regions, regionQuery])

  // Станции ЭЗС (energy) — по алфавиту; поиск по имени/коду.
  const energyStations = useMemo(() => {
    const q = stationQuery.trim().toLowerCase()
    return [...(dimensions?.stations ?? [])]
      .filter((s) => !q || `${s.name} ${s.code}`.toLowerCase().includes(q))
      .sort((a, b) => a.name.localeCompare(b.name, 'ru'))
  }, [dimensions?.stations, stationQuery])

  const stationNameByCode = useMemo(
    () => new Map((dimensions?.stations ?? []).map((s) => [s.code, s.name])),
    [dimensions?.stations],
  )

  // Точки (fuel) — регион сужает список; поиск по имени.
  const filteredLocations = useMemo(() => {
    const q = stationQuery.trim().toLowerCase()
    return locations
      .filter((l) => draftRegions.length === 0 || regionSet.has(locationRegion(l)))
      .filter((l) => !q || l.name.toLowerCase().includes(q))
      .sort((a, b) => a.name.localeCompare(b.name, 'ru'))
  }, [locations, stationQuery, draftRegions.length, regionSet])

  const selectedCount = isEnergy ? draftStations.length : draftLocations.length
  const scopeCount = draftRegions.length + selectedCount

  function describeScope(regions: string[], stations: string[], locs: string[]): string {
    if (isEnergy && stations.length > 0) return stations.length === 1 ? '1 ЭЗС' : `ЭЗС: ${stations.length}`
    if (locs.length === 1) return locations.find((l) => l.id === locs[0])?.name ?? '1 точка'
    if (locs.length > 1) return `Точек: ${locs.length}`
    if (regions.length === 1) return regions[0]
    if (regions.length > 1) return `Регионов: ${regions.length}`
    return 'Вся сеть'
  }

  // Чип снаружи — применённый контур; подвал окна — черновик.
  const scopeLabel = describeScope(regionIds, stationCodes, locationIds)
  const draftScopeLabel = describeScope(draftRegions, draftStations, draftLocations)

  function resetAll() {
    setDraftRegions([]); setDraftStations([]); setDraftLocations([])
  }
  function selectAllVisible() {
    if (isEnergy) setDraftStations([...new Set([...draftStations, ...energyStations.map((s) => s.code)])])
    else setDraftLocations([...new Set([...draftLocations, ...filteredLocations.map((l) => l.id)])])
  }
  function clearVisible() {
    if (isEnergy) {
      const visible = new Set(energyStations.map((s) => s.code))
      setDraftStations(draftStations.filter((c) => !visible.has(c)))
    } else {
      const visible = new Set(filteredLocations.map((l) => l.id))
      setDraftLocations(draftLocations.filter((id) => !visible.has(id)))
    }
  }

  const listTitle = isEnergy ? 'Станции ЭЗС' : 'Точки обслуживания'
  const listCount = isEnergy ? energyStations.length : filteredLocations.length

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={`Область учёта: ${scopeLabel}. Открыть выбор сети`}
        className={`group flex h-11 shrink-0 items-center gap-2.5 rounded-lg border px-3.5 text-left transition-colors ${
          scopeCount > 0
            ? 'border-primary/40 bg-primary/10 text-primary hover:bg-primary/15'
            : 'border-border bg-background/50 text-foreground hover:bg-muted/70'
        }`}
      >
        <MapPinned className="size-[18px] shrink-0 opacity-80" aria-hidden="true" />
        <span className="min-w-0">
          <span className="block text-[11px] uppercase tracking-wide leading-tight text-muted-foreground">Область учёта</span>
          <span className="block max-w-64 truncate text-sm font-semibold leading-tight">{scopeLabel}</span>
        </span>
      </button>

      <Dialog open={open} onOpenChange={openChange}>
        <DialogContent
          showCloseButton={false}
          className="flex h-[min(680px,calc(100vh-2rem))] w-[calc(100vw-2rem)] max-w-4xl flex-col gap-0 overflow-hidden rounded-xl p-0"
        >
          <DialogHeader className="shrink-0 border-b border-border px-5 py-4 text-left">
            <div className="flex items-center gap-2.5">
              <span className="flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <MapPinned className="size-[18px]" aria-hidden="true" />
              </span>
              <div>
                <DialogTitle className="text-base">Область учёта — сеть для анализа</DialogTitle>
                <DialogDescription className="text-xs">
                  Ограничьте анализ регионами и/или конкретными {isEnergy ? 'станциями ЭЗС' : 'точками'}. Выбор применяется по кнопке — до неё цифры на экране не меняются.
                </DialogDescription>
              </div>
            </div>
          </DialogHeader>

          <div className="flex min-h-0 flex-1">
            {/* ── Регионы ── */}
            <div className="flex w-60 shrink-0 flex-col border-r border-border bg-muted/20">
              <div className="flex shrink-0 items-center justify-between px-3 pb-2 pt-3">
                <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Регионы</span>
                <span className="text-[11px] tabular-nums text-muted-foreground">{regionIds.length}/{regions.length}</span>
              </div>
              <div className="px-3 pb-2">
                <div className="relative">
                  <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
                  <Input value={regionQuery} onChange={(e) => setRegionQuery(e.target.value)} placeholder="Регион" className="h-9 pl-8 text-sm" />
                </div>
              </div>
              <ScrollArea className="min-h-0 flex-1">
                <div className="p-1.5">
                  {filteredRegions.length === 0 ? (
                    <p className="px-2 py-6 text-center text-xs text-muted-foreground">{dimensions || !isEnergy ? 'Регионы не найдены' : 'Загрузка…'}</p>
                  ) : filteredRegions.map((region) => (
                    <label key={region.name} className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-2 text-sm hover:bg-muted/70">
                      <Checkbox checked={regionSet.has(region.name)} onCheckedChange={() => toggleDraftRegion(region.name)} />
                      <span className="min-w-0 flex-1 truncate">{region.name}</span>
                    </label>
                  ))}
                </div>
              </ScrollArea>
            </div>

            {/* ── Станции / Точки ── */}
            <div className="flex min-w-0 flex-1 flex-col border-r border-border">
              <div className="flex shrink-0 items-center justify-between gap-2 px-3 pb-2 pt-3">
                <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{listTitle}</span>
                <div className="flex items-center gap-1">
                  <Button variant="ghost" size="xs" className="h-7 text-muted-foreground" onClick={selectAllVisible}>Выбрать все</Button>
                  {selectedCount > 0 && <Button variant="ghost" size="xs" className="h-7 text-muted-foreground" onClick={clearVisible}>Снять</Button>}
                </div>
              </div>
              <div className="px-3 pb-2">
                <div className="relative">
                  <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
                  <Input
                    value={stationQuery}
                    onChange={(e) => setStationQuery(e.target.value)}
                    placeholder={isEnergy ? 'Найти станцию по названию или коду' : 'Найти точку'}
                    className="h-9 pl-8 text-sm"
                  />
                </div>
              </div>
              <div className="flex shrink-0 items-center justify-between px-4 pb-1 text-[11px] text-muted-foreground">
                <span>Найдено: {listCount}</span>
                <span>Выбрано: {selectedCount}</span>
              </div>
              <ScrollArea className="min-h-0 flex-1">
                <div className="p-1.5">
                  {isEnergy ? (
                    energyStations.length === 0 ? (
                      <p className="px-2 py-8 text-center text-xs text-muted-foreground">{dimensions ? 'Станции не найдены' : 'Загрузка…'}</p>
                    ) : energyStations.map((station) => (
                      <label key={station.code} className="flex cursor-pointer items-center gap-2.5 rounded-md px-2 py-2 text-sm hover:bg-muted/70">
                        <Checkbox checked={stationCodeSet.has(station.code)} onCheckedChange={() => toggleDraftStation(station.code)} />
                        <span className="min-w-0 flex-1 truncate">{station.name}</span>
                        <span className="w-16 shrink-0 text-right text-xs font-medium tabular-nums text-muted-foreground">№{station.code}</span>
                      </label>
                    ))
                  ) : (
                    filteredLocations.length === 0 ? (
                      <p className="px-2 py-8 text-center text-xs text-muted-foreground">Точки не найдены</p>
                    ) : filteredLocations.map((location) => (
                      <label key={location.id} className="flex cursor-pointer items-center gap-2.5 rounded-md px-2 py-2 text-sm hover:bg-muted/70">
                        <Checkbox checked={locationSet.has(location.id)} onCheckedChange={() => toggleDraftLocation(location.id)} />
                        <span className="min-w-0 flex-1 truncate">{location.name}</span>
                        {locationRegion(location) ? (
                          <span className="shrink-0 text-[11px] text-muted-foreground">{locationRegion(location)}</span>
                        ) : null}
                      </label>
                    ))
                  )}
                </div>
              </ScrollArea>
            </div>

            {/* ── Выбрано (наглядная сводка) ── */}
            <div className="hidden w-72 shrink-0 flex-col bg-muted/20 md:flex">
              <div className="flex shrink-0 items-center justify-between px-3 pb-2 pt-3">
                <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Выбрано</span>
                {scopeCount > 0 && (
                  <Button variant="ghost" size="xs" className="h-7 text-muted-foreground" onClick={resetAll}>Очистить</Button>
                )}
              </div>
              <ScrollArea className="min-h-0 flex-1">
                <div className="flex flex-col gap-3 p-3">
                  {scopeCount === 0 ? (
                    <div className="rounded-lg border border-dashed border-border px-3 py-8 text-center text-xs text-muted-foreground">
                      Ничего не выбрано.<br />Анализируется вся сеть.
                    </div>
                  ) : (
                    <>
                      {regionIds.length > 0 && (
                        <div className="flex flex-col gap-1.5">
                          <span className="text-[11px] uppercase tracking-wide text-muted-foreground">Регионы · {regionIds.length}</span>
                          <div className="flex flex-wrap gap-1.5">
                            {regionIds.map((r) => (
                              <SelectedChip key={r} label={r} onRemove={() => toggleDraftRegion(r)} />
                            ))}
                          </div>
                        </div>
                      )}
                      {isEnergy && stationCodes.length > 0 && (
                        <div className="flex flex-col gap-1.5">
                          <span className="text-[11px] uppercase tracking-wide text-muted-foreground">Станции · {stationCodes.length}</span>
                          <div className="flex flex-wrap gap-1.5">
                            {stationCodes.map((c) => (
                              <SelectedChip key={c} label={stationNameByCode.get(c) ?? `№${c}`} sub={`№${c}`} onRemove={() => toggleDraftStation(c)} />
                            ))}
                          </div>
                        </div>
                      )}
                      {!isEnergy && locationIds.length > 0 && (
                        <div className="flex flex-col gap-1.5">
                          <span className="text-[11px] uppercase tracking-wide text-muted-foreground">Точки · {locationIds.length}</span>
                          <div className="flex flex-wrap gap-1.5">
                            {locationIds.map((id) => (
                              <SelectedChip key={id} label={locations.find((l) => l.id === id)?.name ?? id} onRemove={() => toggleDraftLocation(id)} />
                            ))}
                          </div>
                        </div>
                      )}
                    </>
                  )}
                </div>
              </ScrollArea>
            </div>
          </div>

          <DialogFooter className="shrink-0 flex-row items-center justify-between border-t border-border px-5 py-3">
            <Button variant="ghost" size="sm" className="h-9 rounded-lg text-muted-foreground" onClick={resetAll} disabled={scopeCount === 0}>
              <RotateCcw data-icon="inline-start" />
              Сбросить всё
            </Button>
            <div className="flex items-center gap-3">
              <span className="text-sm text-muted-foreground">
                {/* Счёт по черновику: показываем то, что человек набрал сейчас,
                    а не то, что применено. */}
                Выбрано: <span className="font-semibold text-foreground">{draftScopeLabel}</span>
              </span>
              <Button variant="ghost" size="sm" className="h-9 rounded-lg" onClick={() => setOpen(false)}>
                Отмена
              </Button>
              <Button size="sm" className="h-9 rounded-lg" onClick={apply}>
                <Check data-icon="inline-start" />
                {draftDirty ? 'Применить' : 'Готово'}
              </Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
