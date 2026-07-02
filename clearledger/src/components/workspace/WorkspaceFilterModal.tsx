/**
 * Модальное окно настройки основного фильтра рабочей области.
 * Свёрнутая строка (`WorkspaceFilterBar`) показывает сводку, здесь — полная
 * настройка всех параметров: период, станция STS, точки, регионы, типы документов.
 *
 * Единый фильтр применяется ко всем разделам рабочего стола (management/financial/
 * accounting/tax). Период/точки/регионы/типы живут в `FilterContext`, станция STS —
 * в `WorkspaceContext` (используется онлайн-загрузкой смен).
 */

import { useMemo, useState } from 'react'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from '@/components/ui/dialog'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/checkbox'
import { Calendar, MapPin, Map as MapIcon, FileText, Fuel, X, Bookmark, History, Plus, Check } from 'lucide-react'
import { useFilters } from '@/contexts/FilterContext'
import type { FilterState } from '@/contexts/FilterContext'
import { useCompany } from '@/contexts/CompanyContext'
import { useQuery } from '@tanstack/react-query'
import { useLocations } from '@/hooks/useLocations'
import { getStsStationsFromLocations } from '@/services/locationService'
import { getChargeDimensions } from '@/services/analyticsService'
import { todayISO, daysAgoISO, monthFirstISO, prevMonthBounds } from './analytics/periodPresets'

// Наборы типов документов по профилю (перенесены из GlobalFilters — единый фильтр).
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
  { label: 'YTD', value: () => ({ from: `${new Date().getFullYear()}-01-01`, to: todayISO() }) },
]

function fmtShort(iso: string): string {
  const [, m, d] = iso.split('-')
  return d && m ? `${d}.${m}` : iso
}

/** Краткое описание набора фильтра для чипов истории. */
function describeState(s: FilterState): string {
  const parts = [`${fmtShort(s.period.from)}–${fmtShort(s.period.to)}`]
  if (s.stationCode && s.stationCode !== 'all') parts.push(`ст. ${s.stationCode}`)
  const cnt = s.locationIds.length + s.regionIds.length + (s.stationCodes?.length ?? 0) + s.docTypeIds.length
  if (cnt) parts.push(`фильтров ${cnt}`)
  return parts.join(' · ')
}

function Section({ icon: Icon, title, action, children }: {
  icon: React.ComponentType<{ className?: string }>
  title: string
  action?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <section className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          <Icon className="h-3.5 w-3.5" />
          {title}
        </div>
        {action}
      </div>
      {children}
    </section>
  )
}

export function WorkspaceFilterModal({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const {
    period, setPeriod,
    stationCode, setStationCode,
    locationIds, setLocationIds, toggleLocation,
    regionIds, setRegionIds, toggleRegion,
    stationCodes, setStationCodes, toggleStationCode,
    docTypeIds, setDocTypeIds, toggleDocType,
    clearAll, applyState,
    history, presets, savePreset, deletePreset,
  } = useFilters()
  const { company, companyId } = useCompany()
  const isEnergy = company.profileId === 'energy'
  const locations = useLocations()
  const stations = getStsStationsFromLocations()
  const [locQuery, setLocQuery] = useState('')
  const [stQuery, setStQuery] = useState('')
  const [savingPreset, setSavingPreset] = useState(false)
  const [presetName, setPresetName] = useState('')

  // Справочник ЭЗС (energy) — станции и каноничные регионы из сессий.
  const { data: dims } = useQuery({
    queryKey: ['charge-dimensions', companyId],
    queryFn: () => getChargeDimensions(companyId),
    enabled: isEnergy && open,
  })

  const docTypes = isEnergy ? ENERGY_DOC_TYPES : FUEL_DOC_TYPES
  const docSet = useMemo(() => new Set(docTypeIds), [docTypeIds])
  const locSet = useMemo(() => new Set(locationIds), [locationIds])
  const regionSet = useMemo(() => new Set(regionIds), [regionIds])
  const stationCodeSet = useMemo(() => new Set(stationCodes), [stationCodes])

  const fuelRegions = useMemo(
    () => Array.from(new Set(
      locations.map((l) => String((l.metadata as Record<string, unknown> | undefined)?.federalSubject ?? '').trim()).filter(Boolean),
    )).sort((a, b) => a.localeCompare(b, 'ru')),
    [locations],
  )
  const regions = isEnergy ? (dims?.regions ?? []).map((r) => r.region) : fuelRegions

  const energyStations = useMemo(() => {
    const q = stQuery.trim().toLowerCase()
    const list = dims?.stations ?? []
    return q ? list.filter((s) => `${s.name} ${s.code}`.toLowerCase().includes(q)) : list
  }, [dims, stQuery])

  const filteredLocations = useMemo(() => {
    const q = locQuery.trim().toLowerCase()
    const list = q ? locations.filter((l) => l.name.toLowerCase().includes(q)) : locations
    return [...list].sort((a, b) => a.name.localeCompare(b.name, 'ru'))
  }, [locations, locQuery])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Фильтр рабочей области</DialogTitle>
        </DialogHeader>

        <div className="grid gap-5 max-h-[65vh] overflow-y-auto pr-1">
          {/* Наборы (пресеты) и история применений */}
          <div className="rounded-md border border-border/40 bg-muted/20 p-2.5 space-y-2">
            <div className="flex items-center gap-1.5 flex-wrap">
              <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground mr-1">
                <Bookmark className="h-3.5 w-3.5" /> Наборы
              </div>
              {presets.length === 0 && !savingPreset && (
                <span className="text-xs text-muted-foreground/60">нет сохранённых</span>
              )}
              {presets.map((p) => (
                <span key={p.id} className="inline-flex items-center gap-1 rounded-md border border-border/50 bg-background/60 pl-2 pr-1 py-0.5 text-xs">
                  <button className="hover:text-primary transition-colors" onClick={() => applyState(p.state)} title={describeState(p.state)}>{p.name}</button>
                  <button className="opacity-50 hover:opacity-100 hover:text-destructive transition-opacity" onClick={() => deletePreset(p.id)} title="Удалить набор">
                    <X className="h-3 w-3" />
                  </button>
                </span>
              ))}
              {savingPreset ? (
                <span className="inline-flex items-center gap-1">
                  <Input
                    autoFocus
                    value={presetName}
                    onChange={(e) => setPresetName(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') { savePreset(presetName); setPresetName(''); setSavingPreset(false) }
                      if (e.key === 'Escape') { setSavingPreset(false); setPresetName('') }
                    }}
                    placeholder="Имя набора"
                    className="h-7 w-36 text-xs"
                  />
                  <Button size="icon" variant="ghost" className="h-7 w-7"
                    onClick={() => { savePreset(presetName); setPresetName(''); setSavingPreset(false) }}>
                    <Check className="h-3.5 w-3.5" />
                  </Button>
                </span>
              ) : (
                <Button size="sm" variant="outline" className="h-7 text-xs px-2 gap-1" onClick={() => setSavingPreset(true)}>
                  <Plus className="h-3.5 w-3.5" /> Сохранить текущий
                </Button>
              )}
            </div>

            {history.length > 0 && (
              <div className="space-y-1 pt-1 border-t border-border/30">
                <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  <History className="h-3.5 w-3.5" /> Недавние
                </div>
                <div className="flex items-center gap-1 flex-wrap">
                  {history.map((h, i) => (
                    <button
                      key={i}
                      onClick={() => applyState(h)}
                      className="rounded-md border border-border/40 bg-background/40 px-2 py-0.5 text-xs text-muted-foreground hover:text-foreground hover:border-primary/40 transition-colors"
                    >
                      {describeState(h)}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Период */}
          <Section icon={Calendar} title="Период">
            <div className="flex flex-wrap items-center gap-2">
              <Input
                type="date"
                value={period.from}
                onChange={(e) => setPeriod({ ...period, from: e.target.value })}
                className="h-8 w-[150px] text-xs"
              />
              <span className="text-xs text-muted-foreground">—</span>
              <Input
                type="date"
                value={period.to}
                onChange={(e) => setPeriod({ ...period, to: e.target.value })}
                className="h-8 w-[150px] text-xs"
              />
              <div className="flex flex-wrap items-center gap-1 ml-1">
                {PERIOD_PRESETS.map((p) => (
                  <Button key={p.label} variant="outline" size="sm" className="h-8 text-xs px-2"
                    onClick={() => setPeriod(p.value())}>
                    {p.label}
                  </Button>
                ))}
              </div>
            </div>
          </Section>

          {/* Станция STS — только fuel (онлайн-загрузка смен) */}
          {!isEnergy && (
            <Section icon={Fuel} title="Станция (онлайн-данные STS)">
              <Select value={stationCode} onValueChange={setStationCode}>
                <SelectTrigger className="h-8 w-[240px] text-xs">
                  <SelectValue placeholder="Все станции" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Все станции</SelectItem>
                  {stations.map((s) => (
                    <SelectItem key={s.code} value={String(s.code)}>{s.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Section>
          )}

          {/* Станции ЭЗС — energy (сужение аналитики сессий) */}
          {isEnergy && (
            <Section
              icon={Fuel}
              title={`Станции ЭЗС${stationCodes.length ? ` · ${stationCodes.length}` : ''}`}
              action={
                <Button variant="ghost" size="sm" className="h-6 text-[10px] px-2"
                  onClick={() => setStationCodes([])} disabled={stationCodes.length === 0}>
                  Все
                </Button>
              }
            >
              <Input
                placeholder="Поиск станции…"
                value={stQuery}
                onChange={(e) => setStQuery(e.target.value)}
                className="h-8 text-xs"
              />
              <div className="max-h-40 overflow-y-auto rounded-md border border-border/40 p-1.5 space-y-0.5">
                {energyStations.length === 0 && (
                  <div className="px-2 py-3 text-center text-xs text-muted-foreground">Станции не найдены</div>
                )}
                {energyStations.map((s) => (
                  <label key={s.code}
                    className="flex items-center gap-2 py-1 px-1.5 rounded text-xs hover:bg-accent/40 cursor-pointer">
                    <Checkbox checked={stationCodeSet.has(s.code)} onCheckedChange={() => toggleStationCode(s.code)} className="h-3.5 w-3.5" />
                    <span className="truncate flex-1">{s.name}</span>
                    <span className="text-muted-foreground/60 shrink-0 tabular-nums">{s.code}</span>
                  </label>
                ))}
              </div>
            </Section>
          )}

          {/* Точки обслуживания */}
          <Section
            icon={MapPin}
            title={`Точки обслуживания${locationIds.length ? ` · ${locationIds.length}` : ''}`}
            action={
              <Button variant="ghost" size="sm" className="h-6 text-[10px] px-2"
                onClick={() => setLocationIds([])} disabled={locationIds.length === 0}>
                Все
              </Button>
            }
          >
            <Input
              placeholder="Поиск точки…"
              value={locQuery}
              onChange={(e) => setLocQuery(e.target.value)}
              className="h-8 text-xs"
            />
            <div className="max-h-40 overflow-y-auto rounded-md border border-border/40 p-1.5 space-y-0.5">
              {filteredLocations.length === 0 && (
                <div className="px-2 py-3 text-center text-xs text-muted-foreground">Точки не найдены</div>
              )}
              {filteredLocations.map((l) => (
                <label key={l.id}
                  className="flex items-center gap-2 py-1 px-1.5 rounded text-xs hover:bg-accent/40 cursor-pointer">
                  <Checkbox checked={locSet.has(l.id)} onCheckedChange={() => toggleLocation(l.id)} className="h-3.5 w-3.5" />
                  <span className="truncate">{l.name}</span>
                </label>
              ))}
            </div>
          </Section>

          {/* Регионы */}
          {regions.length > 0 && (
            <Section
              icon={MapIcon}
              title={`Регионы${regionIds.length ? ` · ${regionIds.length}` : ''}`}
              action={
                <Button variant="ghost" size="sm" className="h-6 text-[10px] px-2"
                  onClick={() => setRegionIds([])} disabled={regionIds.length === 0}>
                  Все
                </Button>
              }
            >
              <div className="max-h-36 overflow-y-auto rounded-md border border-border/40 p-1.5 grid grid-cols-2 gap-x-2 gap-y-0.5">
                {regions.map((r) => (
                  <label key={r}
                    className="flex items-center gap-2 py-1 px-1.5 rounded text-xs hover:bg-accent/40 cursor-pointer">
                    <Checkbox checked={regionSet.has(r)} onCheckedChange={() => toggleRegion(r)} className="h-3.5 w-3.5" />
                    <span className="truncate">{r}</span>
                  </label>
                ))}
              </div>
            </Section>
          )}

          {/* Типы документов */}
          <Section
            icon={FileText}
            title={`Типы документов${docTypeIds.length ? ` · ${docTypeIds.length}` : ''}`}
            action={
              <Button variant="ghost" size="sm" className="h-6 text-[10px] px-2"
                onClick={() => setDocTypeIds([])} disabled={docTypeIds.length === 0}>
                Все
              </Button>
            }
          >
            <div className="rounded-md border border-border/40 p-1.5 grid grid-cols-2 gap-x-2 gap-y-0.5">
              {docTypes.map((t) => (
                <label key={t.id}
                  className="flex items-center gap-2 py-1 px-1.5 rounded text-xs hover:bg-accent/40 cursor-pointer">
                  <Checkbox checked={docSet.has(t.id)} onCheckedChange={() => toggleDocType(t.id)} className="h-3.5 w-3.5" />
                  <span className="truncate">{t.label}</span>
                </label>
              ))}
            </div>
          </Section>
        </div>

        <DialogFooter className="gap-2 sm:gap-2">
          <Button variant="ghost" size="sm" className="gap-1.5 text-muted-foreground" onClick={clearAll}>
            <X className="h-3.5 w-3.5" />
            Сбросить выборки
          </Button>
          <Button size="sm" onClick={() => onOpenChange(false)}>Готово</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
