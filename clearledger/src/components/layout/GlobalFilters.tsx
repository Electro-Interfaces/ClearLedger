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
import { MapPin, FileText, Filter, X, ChevronDown, Map as MapIcon } from 'lucide-react'
import { useFilters } from '@/contexts/FilterContext'
import { useLocations } from '@/hooks/useLocations'
import { CompanySelector } from '@/components/company/CompanySelector'
import { StationsSelectorDialog, type StationOption } from '@/components/stations/StationsSelectorDialog'

/** Пилюля-селектор в стиле TradePoint: тёмный фон, бордер, иконка + текст + шеврон. */
const pillCls =
  'h-11 gap-2 rounded-xl px-3.5 text-sm font-medium bg-secondary dark:bg-di-surface-high ' +
  'border border-border/60 dark:border-di-outline-variant/25 text-foreground ' +
  'hover:bg-accent dark:hover:bg-di-surface-highest hover:border-primary/40 transition-all'

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
  const { locationIds, setLocationIds } = useFilters()
  const locations = useLocations()   // активная компания, рефетч при переключении

  const selectedLocations = useMemo(
    () => locations.filter((l) => locationIds.includes(l.id)),
    [locations, locationIds],
  )

  // Универсум для StationsSelectorDialog — берём станции из справочника
  // напрямую (по code+system_id из STS-привязок), но фильтр в шапке
  // оперирует location.id. Мост: ниже мы сохраняем locationIds[].
  const options: StationOption[] = useMemo(() => {
    const out: StationOption[] = []
    const seen = new Set<string>()
    for (const loc of locations) {
      if (loc.type !== 'fuel_station') continue
      for (const b of loc.sourceBindings) {
        const systemId = Number(b.config?.system_id ?? b.config?.systemId)
        const code = Number(b.config?.station ?? b.config?.code ?? loc.code)
        if (!systemId || !code) continue
        const key = `${systemId}|${code}`
        if (seen.has(key)) continue
        seen.add(key)
        out.push({ systemId, code, name: loc.name, locationId: loc.id })
      }
    }
    // Добавляем точки других типов (офисы/склады/...) без STS-привязки
    for (const loc of locations) {
      if (loc.type === 'fuel_station') continue
      const code = Number(loc.code) || 0
      const key = `0|${code}|${loc.id}`
      if (seen.has(key)) continue
      seen.add(key)
      out.push({ systemId: 0, code, name: loc.name, locationId: loc.id })
    }
    out.sort((a, b) => a.systemId - b.systemId || a.code - b.code)
    return out
  }, [locations])

  // Текущий выбор в формате StationKey[] — для диалога
  const selectedKeys = useMemo(() => {
    const set = new Set<string>(locationIds)
    return options
      .filter((o) => o.locationId && set.has(o.locationId))
      .map((o) => ({ code: o.code, systemId: o.systemId }))
  }, [options, locationIds])

  function onSave(next: StationOption[]) {
    const ids = next
      .map((o) => o.locationId)
      .filter((x): x is string => !!x)
    // Уникальные ID — точка с несколькими STS-привязками выбирается одним id
    setLocationIds(Array.from(new Set(ids)))
  }

  const summary = locationIds.length === 0
    ? 'Все точки'
    : locationIds.length === 1
      ? selectedLocations[0]?.name ?? '1'
      : `Точек: ${locationIds.length}`

  return (
    <StationsSelectorDialog
      options={options}
      selected={selectedKeys}
      onSave={onSave}
      trigger={
        <Button variant="ghost" className={pillCls}>
          <MapPin className="h-4 w-4 opacity-70" />
          <span className="hidden sm:inline truncate max-w-[180px]">{summary}</span>
          {locationIds.length > 0 && (
            <Badge variant="secondary" className="h-4 text-[9px] px-1">
              {locationIds.length}
            </Badge>
          )}
          <ChevronDown className="h-4 w-4 opacity-60" />
        </Button>
      }
    />
  )
}


function RegionFilterButton() {
  const { regionIds, toggleRegion, setRegionIds } = useFilters()
  const locations = useLocations()

  const regions = useMemo(
    () => Array.from(new Set(
      locations.map((l) => String((l.metadata as Record<string, unknown> | undefined)?.federalSubject ?? '').trim())
        .filter(Boolean),
    )).sort((a, b) => a.localeCompare(b, 'ru')),
    [locations],
  )
  const selectedSet = useMemo(() => new Set(regionIds), [regionIds])

  if (regions.length === 0) return null

  const summary = regionIds.length === 0
    ? 'Все регионы'
    : regionIds.length === 1 ? regionIds[0] : `Регионов: ${regionIds.length}`

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="ghost" className={pillCls}>
          <MapIcon className="h-4 w-4 opacity-70" />
          <span className="hidden md:inline truncate max-w-[160px]">{summary}</span>
          {regionIds.length > 0 && (
            <Badge variant="secondary" className="h-4 text-[9px] px-1">{regionIds.length}</Badge>
          )}
          <ChevronDown className="h-4 w-4 opacity-60" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-72 p-0">
        <div className="flex items-center justify-between p-2 border-b border-border/40">
          <span className="text-xs font-semibold">Регионы</span>
          <Button variant="ghost" size="sm" className="h-6 text-[10px] px-2"
            onClick={() => setRegionIds([])} disabled={regionIds.length === 0}>
            Очистить
          </Button>
        </div>
        <div className="p-2 max-h-[320px] overflow-y-auto space-y-0.5">
          {regions.map((r) => (
            <label key={r}
              className="flex items-center gap-2 py-1 px-1.5 rounded text-xs hover:bg-accent/40 cursor-pointer">
              <Checkbox checked={selectedSet.has(r)} onCheckedChange={() => toggleRegion(r)} className="h-3.5 w-3.5" />
              <span className="truncate">{r}</span>
            </label>
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
        <Button variant="ghost" className={pillCls}>
          <FileText className="h-4 w-4 opacity-70" />
          <span className="hidden md:inline">{summary}</span>
          {docTypeIds.length > 0 && (
            <Badge variant="secondary" className="h-4 text-[9px] px-1">
              {docTypeIds.length}
            </Badge>
          )}
          <ChevronDown className="h-4 w-4 opacity-60" />
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


export function GlobalFilters() {
  const { locationIds, regionIds, docTypeIds, clearAll } = useFilters()
  const total = locationIds.length + regionIds.length + docTypeIds.length

  return (
    <div className="flex items-center gap-2">
      <CompanySelector />
      <div className="w-px h-6 bg-border/50 mx-0.5" />
      <RegionFilterButton />
      <LocationsFilterButton />
      <DocTypesFilterButton />
      {total > 0 && (
        <Button
          variant="ghost"
          size="sm"
          className="h-9 px-2.5 text-xs gap-1 text-muted-foreground hover:text-foreground"
          onClick={clearAll}
        >
          <X className="h-3.5 w-3.5" />
          Сброс ({total})
        </Button>
      )}
      {total === 0 && (
        <div className="hidden xl:flex items-center gap-1.5 ml-1 text-xs text-muted-foreground/60">
          <Filter className="h-3.5 w-3.5" />
          Без фильтров
        </div>
      )}
    </div>
  )
}
