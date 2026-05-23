/**
 * Глобальные фильтры менеджера в шапке.
 *
 * Селекторы (мульти-выбор через чекбоксы): компания (информационно,
 * пока одна), точки обслуживания, типы документов. Изменения сразу
 * пишутся в FilterContext и сохраняются в localStorage.
 *
 * UX: каждый селектор — кнопка в шапке, открывает popover с чекбоксами.
 * Видна сводка «N выбрано» / «Все».
 */

import { useMemo } from 'react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Popover, PopoverContent, PopoverTrigger,
} from '@/components/ui/popover'
import { Building2, MapPin, FileText, Filter, X } from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import { useFilters } from '@/contexts/FilterContext'
import { getLocations } from '@/services/locationService'
import {
  LOCATION_TYPE_META, type LocationType, type ServiceLocation,
} from '@/types/location'

const ALL_DOC_TYPES: { id: string; label: string }[] = [
  { id: 'shift_report', label: 'Сменные отчёты' },
  { id: 'receipt', label: 'Поступления (ТТН)' },
  { id: 'price', label: 'Цены' },
  { id: 'sts_transactions', label: 'Операции отпуска' },
  { id: 'sts_coupons', label: 'Купоны и талоны' },
  { id: 'sts_tanks', label: 'Остатки резервуаров' },
  { id: 'msto_transactions', label: 'MSTO транзакции' },
  { id: 'corp_transactions', label: 'TradeCorp транзакции' },
]

function LocationsFilterButton() {
  const { locationIds, toggleLocation, setLocationIds } = useFilters()
  const locations = useMemo(() => getLocations(), [])
  const selectedSet = useMemo(() => new Set(locationIds), [locationIds])

  // Группировка по типу
  const byType = useMemo(() => {
    const groups = new Map<LocationType, ServiceLocation[]>()
    for (const l of locations) {
      if (!groups.has(l.type)) groups.set(l.type, [])
      groups.get(l.type)!.push(l)
    }
    const order: LocationType[] = ['fuel_station', 'retail', 'office', 'warehouse', 'other']
    return order
      .filter((t) => groups.has(t))
      .map((t) => [t, groups.get(t)!] as const)
  }, [locations])

  const summary = locationIds.length === 0
    ? 'Все точки'
    : locationIds.length === 1
      ? locations.find((l) => l.id === locationIds[0])?.name ?? '1'
      : `Точек: ${locationIds.length}`

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="sm" className="h-8 gap-1.5 text-xs">
          <MapPin className="h-3.5 w-3.5" />
          <span className="hidden sm:inline">{summary}</span>
          {locationIds.length > 0 && (
            <Badge variant="secondary" className="h-4 text-[9px] px-1 ml-0.5">
              {locationIds.length}
            </Badge>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80 p-0">
        <div className="flex items-center justify-between p-2 border-b border-border/40">
          <span className="text-xs font-semibold">Точки обслуживания</span>
          <Button
            variant="ghost"
            size="sm"
            className="h-6 text-[10px] px-2"
            onClick={() => setLocationIds([])}
            disabled={locationIds.length === 0}
          >
            Очистить
          </Button>
        </div>
        <div className="p-2 max-h-[420px] overflow-y-auto space-y-3">
          {locations.length === 0 && (
            <p className="text-xs text-muted-foreground py-4 text-center">
              Нет точек обслуживания. Откройте «Настройки → Точки обслуживания».
            </p>
          )}
          {byType.map(([type, items]) => (
            <div key={type} className="space-y-0.5">
              <div className="text-[10px] font-semibold text-muted-foreground/70 uppercase tracking-wide px-1.5">
                {LOCATION_TYPE_META[type].label} <span className="text-muted-foreground/50">· {items.length}</span>
              </div>
              {items.map((l) => (
                <label key={l.id}
                  className="flex items-center gap-2 py-1 px-1.5 rounded text-xs hover:bg-accent/40 cursor-pointer">
                  <Checkbox
                    checked={selectedSet.has(l.id)}
                    onCheckedChange={() => toggleLocation(l.id)}
                    className="h-3.5 w-3.5"
                  />
                  <span className="font-mono w-10 shrink-0 text-muted-foreground">{l.code}</span>
                  <span className="truncate">{l.name}</span>
                </label>
              ))}
            </div>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  )
}


function DocTypesFilterButton() {
  const { docTypeIds, toggleDocType, setDocTypeIds } = useFilters()
  const selectedSet = useMemo(() => new Set(docTypeIds), [docTypeIds])

  const summary = docTypeIds.length === 0
    ? 'Все типы'
    : docTypeIds.length === 1
      ? ALL_DOC_TYPES.find((t) => t.id === docTypeIds[0])?.label ?? '1'
      : `Типов: ${docTypeIds.length}`

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="sm" className="h-8 gap-1.5 text-xs">
          <FileText className="h-3.5 w-3.5" />
          <span className="hidden md:inline">{summary}</span>
          {docTypeIds.length > 0 && (
            <Badge variant="secondary" className="h-4 text-[9px] px-1 ml-0.5">
              {docTypeIds.length}
            </Badge>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-72 p-0">
        <div className="flex items-center justify-between p-2 border-b border-border/40">
          <span className="text-xs font-semibold">Типы документов</span>
          <Button
            variant="ghost"
            size="sm"
            className="h-6 text-[10px] px-2"
            onClick={() => setDocTypeIds([])}
            disabled={docTypeIds.length === 0}
          >
            Очистить
          </Button>
        </div>
        <div className="p-2 max-h-[320px] overflow-y-auto space-y-0.5">
          {ALL_DOC_TYPES.map((t) => (
            <label key={t.id}
              className="flex items-center gap-2 py-1 px-1.5 rounded text-xs hover:bg-accent/40 cursor-pointer">
              <Checkbox
                checked={selectedSet.has(t.id)}
                onCheckedChange={() => toggleDocType(t.id)}
                className="h-3.5 w-3.5"
              />
              <span className="truncate">{t.label}</span>
              <span className="font-mono text-[10px] text-muted-foreground/60 ml-auto">{t.id}</span>
            </label>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  )
}


function CompanyButton() {
  const { company, companies } = useCompany()
  // Сейчас одна компания, дропдаун всё равно показываем — задел на будущее
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="sm" className="h-8 gap-1.5 text-xs">
          <Building2 className="h-3.5 w-3.5" />
          <span className="hidden lg:inline truncate max-w-[140px]">{company.name}</span>
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-56 p-1">
        <div className="text-[10px] font-semibold text-muted-foreground/70 uppercase tracking-wide px-2 py-1">
          Компания
        </div>
        {companies.map((c) => (
          <button
            key={c.id}
            className={`flex items-center gap-2 w-full px-2 py-1.5 rounded text-xs text-left hover:bg-accent/40 ${
              c.id === company.id ? 'bg-accent/30' : ''
            }`}
            disabled
          >
            <Building2 className="h-3.5 w-3.5 text-muted-foreground" />
            <span className="truncate">{c.name}</span>
            {c.id === company.id && <span className="ml-auto text-[10px] text-primary">●</span>}
          </button>
        ))}
        <div className="text-[10px] text-muted-foreground/60 px-2 py-1.5 border-t border-border/40 mt-1">
          Переключение пока недоступно — одна компания
        </div>
      </PopoverContent>
    </Popover>
  )
}


export function GlobalFilters() {
  const { locationIds, docTypeIds, clearAll } = useFilters()
  const total = locationIds.length + docTypeIds.length

  return (
    <div className="flex items-center gap-1">
      <CompanyButton />
      <div className="w-px h-5 bg-border/50 mx-1" />
      <LocationsFilterButton />
      <DocTypesFilterButton />
      {total > 0 && (
        <Button
          variant="ghost"
          size="sm"
          className="h-8 px-2 text-[10px] gap-1 text-muted-foreground hover:text-foreground"
          onClick={clearAll}
        >
          <X className="h-3 w-3" />
          Сброс ({total})
        </Button>
      )}
      {total === 0 && (
        <div className="hidden xl:flex items-center gap-1 ml-1 text-[10px] text-muted-foreground/60">
          <Filter className="h-3 w-3" />
          Без фильтров
        </div>
      )}
    </div>
  )
}
