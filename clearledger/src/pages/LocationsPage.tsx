/**
 * Точки обслуживания клиента.
 *
 * Справочник мест: АЗС, магазины, офисы, склады. Используется
 * системой для привязки документов к местам и фильтрации каналов.
 */

import { useState, useEffect, useMemo } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogTrigger,
} from '@/components/ui/dialog'
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader,
  AlertDialogTitle, AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import {
  Plus, Trash2, Fuel, Store, Building2, Warehouse, MapPin, Pencil,
  Zap, Utensils, Flame, SlidersHorizontal,
  LayoutGrid, Table2, List, LayoutDashboard, Download,
} from 'lucide-react'
import { toast } from 'sonner'
import {
  getLocations, createLocation, updateLocation, deleteLocation,
  loadLocations,
} from '@/services/locationService'
import { getSources, loadSources } from '@/services/sourceService'
import { useCompany } from '@/contexts/CompanyContext'
import { useLocationTypes } from '@/hooks/useLocationTypes'
import { MetadataFieldsRenderer } from '@/components/manual/MetadataFieldsRenderer'
import { LocationTypesManager } from '@/components/locationTypes/LocationTypesManager'
import { LocationsTable } from '@/components/locations/LocationsTable'
import { LocationCockpitModal } from '@/components/locations/LocationCockpitModal'
import type { CockpitVariant } from '@/components/locations/cockpit/tabsConfig'
import { LocationContractsPopover } from '@/components/reference/LocationContractsPopover'
import { FleetKpiBar } from '@/components/locations/fleet/FleetKpiBar'
import { FleetFilters } from '@/components/locations/fleet/FleetFilters'
import { FleetDashboard } from '@/components/locations/fleet/FleetDashboard'
import { LocationExportDialog } from '@/components/locations/fleet/LocationExportDialog'
import {
  applyLocationFilters, computeFleetStats, collectFilterOptions,
  EMPTY_LOCATION_FILTERS, ATTENTION_PATCH,
  type LocationFilters, type AttentionKey,
} from '@/components/locations/fleet/locationFleetService'
import {
  LOCATION_TYPE_META, LOCATION_STATUS_META,
  type LocationStatus, type LocationType, type ServiceLocation,
} from '@/types/location'
import type { LocationTypeDef } from '@/types/locationType'

// Реестр иконок по ИМЕНИ (icon из каталога типов), резолв с фолбэком на MapPin.
const ICON_REGISTRY: Record<string, React.ComponentType<{ className?: string }>> = {
  Fuel, Zap, Store, Building2, Warehouse, MapPin, Utensils, Flame,
}
function resolveIcon(name?: string): React.ComponentType<{ className?: string }> {
  return (name && ICON_REGISTRY[name]) || MapPin
}

const STATUS_BADGE_COLOR: Record<LocationStatus, string> = {
  active: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400',
  closed: 'bg-muted text-muted-foreground',
  planned: 'bg-blue-500/15 text-blue-600 dark:text-blue-400',
}


function LocationCard({
  location,
  typeDef,
  onChange,
  onOpen,
}: {
  location: ServiceLocation
  typeDef?: LocationTypeDef
  onChange: () => void
  /** Клик по карточке → открыть окно станции (cockpit). */
  onOpen?: () => void
}) {
  const fallbackMeta = LOCATION_TYPE_META[location.type]
  const Icon = resolveIcon(typeDef?.icon ?? fallbackMeta?.icon)
  const typeLabel = typeDef?.name ?? fallbackMeta?.label ?? location.type
  const statusMeta = LOCATION_STATUS_META[location.status]

  function handleDelete() {
    if (deleteLocation(location.id)) {
      toast.success(`Удалена точка «${location.name}»`)
      onChange()
    }
  }

  return (
    <Card
      className={onOpen ? 'cursor-pointer transition-colors hover:bg-secondary/30' : undefined}
      onClick={onOpen}
      role={onOpen ? 'button' : undefined}
    >
      <CardContent className="p-4">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-md bg-muted shrink-0">
            <Icon className="h-5 w-5 text-muted-foreground" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs text-muted-foreground font-mono">
                {location.code}
              </span>
              <span className="font-medium">{location.name}</span>
              <Badge className={STATUS_BADGE_COLOR[location.status]} variant="secondary">
                {statusMeta.label}
              </Badge>
            </div>
            <div className="text-xs text-muted-foreground mt-1">
              {typeLabel}
              {location.address && <span> · {location.address}</span>}
            </div>
            {location.sourceBindings.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mt-2">
                {location.sourceBindings.map((b, i) => (
                  <Badge key={i} variant="outline" className="text-[10px]">
                    {b.label ?? `Источник ${b.sourceId.slice(0, 6)}`}
                  </Badge>
                ))}
              </div>
            )}
            {location.description && (
              <div className="text-xs text-muted-foreground mt-1.5 italic">
                {location.description}
              </div>
            )}
            <div className="mt-1.5 -ml-2" onClick={(e) => e.stopPropagation()}>
              <LocationContractsPopover locationId={location.id} />
            </div>
          </div>
          <div className="flex gap-1 shrink-0" onClick={(e) => e.stopPropagation()}>
            <LocationEditDialog location={location} onSaved={onChange}>
              <Button variant="ghost" size="icon" className="h-7 w-7">
                <Pencil className="h-3.5 w-3.5" />
              </Button>
            </LocationEditDialog>
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground hover:text-destructive">
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Удалить точку обслуживания?</AlertDialogTitle>
                  <AlertDialogDescription>
                    Точка «{location.name}» будет удалена из справочника.
                    Это не повлияет на ранее загруженные документы.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Отмена</AlertDialogCancel>
                  <AlertDialogAction onClick={handleDelete}>Удалить</AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}


function LocationEditDialog({
  location,
  children,
  onSaved,
}: {
  location?: ServiceLocation
  children: React.ReactNode
  onSaved: () => void
}) {
  const isEdit = !!location
  const [open, setOpen] = useState(false)
  const types = useLocationTypes()
  const { company } = useCompany()
  const isEnergy = company.profileId === 'energy'

  // Тип по умолчанию для новой точки зависит от профиля: энергетика — ЭЗС
  // (ev_charging), иначе — АЗС (fuel_station). Фолбэк — первый тип каталога.
  const defaultType: LocationType = isEnergy
    ? ((types.find((t) => t.code === 'ev_charging')?.code
        ?? types[0]?.code ?? 'ev_charging') as LocationType)
    : 'fuel_station'

  // Плейсхолдеры формы — нейтральные примеры под профиль.
  const ph = isEnergy
    ? { code: 'EVRH-0142', name: 'ЭЗС Пушкин', address: 'г. Пушкин, Привокзальная пл., 1' }
    : { code: '208', name: 'АКЗС Выборг (208)', address: 'г. Выборг, Ленинградское ш., 14' }

  const [code, setCode] = useState(location?.code ?? '')
  const [name, setName] = useState(location?.name ?? '')
  const [type, setType] = useState<LocationType>(location?.type ?? defaultType)
  const [status, setStatus] = useState<LocationStatus>(location?.status ?? 'active')
  const [address, setAddress] = useState(location?.address ?? '')
  const [description, setDescription] = useState(location?.description ?? '')
  const [service, setService] = useState(() => {
    const v = String(((location?.metadata ?? {}) as Record<string, unknown>).service ?? '').toLowerCase()
    return ['true', '1', 'yes', 'да', 'служебная', 'service'].includes(v)
  })
  // Значения полей выбранного типа точки (динамические) → в location.metadata.
  const [metadata, setMetadata] = useState<Record<string, string>>(() => {
    const m: Record<string, string> = {}
    const src = (location?.metadata ?? {}) as Record<string, unknown>
    for (const [k, v] of Object.entries(src)) {
      if (v !== null && v !== undefined && typeof v !== 'object') m[k] = String(v)
    }
    return m
  })
  const selectedType = types.find((t) => t.code === type)

  function handleSave() {
    if (!code.trim() || !name.trim()) {
      toast.error('Код и название обязательны')
      return
    }
    const missing = (selectedType?.fields ?? []).filter(
      (f) => f.required && !(metadata[f.key] ?? '').trim(),
    )
    if (missing.length > 0) {
      toast.error(`Заполните поля типа: ${missing.map((f) => f.label).join(', ')}`)
      return
    }
    const cleanMeta: Record<string, string> = {}
    for (const [k, v] of Object.entries(metadata)) if (v.trim()) cleanMeta[k] = v
    if (service) cleanMeta.service = 'true'
    else delete cleanMeta.service
    const meta = Object.keys(cleanMeta).length ? cleanMeta : undefined
    if (isEdit && location) {
      updateLocation(location.id, {
        code: code.trim(), name: name.trim(),
        type, status, address: address.trim() || undefined,
        description: description.trim() || undefined,
        metadata: meta,
      })
      toast.success(`Сохранена точка «${name}»`)
    } else {
      createLocation({
        code: code.trim(), name: name.trim(),
        type, status,
        address: address.trim() || undefined,
        description: description.trim() || undefined,
        metadata: meta,
      })
      toast.success(`Создана точка «${name}»`)
    }
    setOpen(false)
    onSaved()
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{children}</DialogTrigger>
      <DialogContent className="sm:max-w-lg max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {isEdit ? 'Редактировать точку обслуживания' : 'Новая точка обслуживания'}
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3 pt-2">
          <div className="grid grid-cols-3 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="loc-code">Код</Label>
              <Input id="loc-code" value={code} onChange={(e) => setCode(e.target.value)}
                placeholder={ph.code} />
            </div>
            <div className="space-y-1.5 col-span-2">
              <Label htmlFor="loc-name">Название</Label>
              <Input id="loc-name" value={name} onChange={(e) => setName(e.target.value)}
                placeholder={ph.name} />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="loc-type">Тип</Label>
              <Select value={type} onValueChange={(v) => setType(v)}>
                <SelectTrigger id="loc-type"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {types.map((t) => (
                    <SelectItem key={t.code} value={t.code}>{t.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="loc-status">Статус</Label>
              <Select value={status} onValueChange={(v) => setStatus(v as LocationStatus)}>
                <SelectTrigger id="loc-status"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {(Object.keys(LOCATION_STATUS_META) as LocationStatus[]).map((k) => (
                    <SelectItem key={k} value={k}>{LOCATION_STATUS_META[k].label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="loc-address">Адрес</Label>
            <Input id="loc-address" value={address} onChange={(e) => setAddress(e.target.value)}
              placeholder={ph.address} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="loc-desc">Описание</Label>
            <Textarea id="loc-desc" value={description} onChange={(e) => setDescription(e.target.value)}
              placeholder="Доп. примечания" rows={2} />
          </div>

          {/* Признак служебной/тестовой станции (наш слой) */}
          <label className="flex cursor-pointer items-center gap-2.5 rounded-md border border-border/50 px-3 py-2 hover:bg-accent/30">
            <input type="checkbox" checked={service} onChange={(e) => setService(e.target.checked)} className="size-4 accent-primary" />
            <div>
              <div className="text-sm font-medium">Служебная станция</div>
              <div className="text-xs text-muted-foreground">Тестовая/служебная — исключается из рабочих витрин по фильтру «Назначение»</div>
            </div>
          </label>

          {/* Свойства, специфичные для выбранного типа точки */}
          {selectedType && selectedType.fields.length > 0 && (
            <div className="space-y-3 border-t border-border/50 pt-3">
              <div className="text-xs font-medium text-muted-foreground">
                Свойства типа «{selectedType.name}»
                {selectedType.unit && <span> · единица: {selectedType.unit}</span>}
              </div>
              <MetadataFieldsRenderer
                fields={selectedType.fields}
                values={metadata}
                onChange={(k, v) => setMetadata((m) => ({ ...m, [k]: v }))}
              />
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>Отмена</Button>
          <Button onClick={handleSave}>{isEdit ? 'Сохранить' : 'Создать'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}




export function LocationsPage({ cockpitVariant = 'full' }: { cockpitVariant?: CockpitVariant } = {}) {
  const [_tick, setTick] = useState(0)
  const refresh = () => setTick((t) => t + 1)
  const { companyId, isCompanyAdmin, company } = useCompany()
  const isEnergy = company.profileId === 'energy'
  const types = useLocationTypes()

  // Гидрация источников (для STS-импорта) + точек обслуживания (из бэкенда)
  useEffect(() => {
    void Promise.all([loadSources(companyId), loadLocations(companyId)])
      .then(refresh).catch(() => { /* офлайн → localStorage */ })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId])

  const locations = getLocations()
  const sourcesCount = getSources().length
  const typeByCode = useMemo(() => new Map(types.map((t) => [t.code, t])), [types])

  // Единый отбор парка (поднят со страницы — общий для таблицы/карточек/дашборда/экспорта).
  const [filters, setFilters] = useState<LocationFilters>(EMPTY_LOCATION_FILTERS)
  const [fleetMode, setFleetMode] = useState<'list' | 'dashboard'>('list')
  const [exportOpen, setExportOpen] = useState(false)

  const filtered = useMemo(() => applyLocationFilters(locations, filters), [locations, filters])
  const stats = useMemo(() => computeFleetStats(filtered, typeByCode), [filtered, typeByCode])
  const options = useMemo(() => collectFilterOptions(locations, typeByCode), [locations, typeByCode])

  // Режим отображения списка: единый вид по умолчанию — таблица (как у РусГидро/
  // энергетики). Карточки доступны вручную через переключатель вида.
  const [viewOverride, setViewOverride] = useState<'cards' | 'table' | null>(null)
  const view: 'cards' | 'table' = viewOverride ?? 'table'

  // Окно станции (cockpit) — открывается кликом по строке/карточке.
  const [cockpit, setCockpit] = useState<ServiceLocation | null>(null)

  // Срез (replace): patch=null → сброс. drill-down дополнительно переключает в список.
  const sliceTo = (patch: Partial<LocationFilters> | null) =>
    setFilters(patch ? { ...EMPTY_LOCATION_FILTERS, ...patch } : EMPTY_LOCATION_FILTERS)
  const drillTo = (patch: Partial<LocationFilters>) => { sliceTo(patch); setFleetMode('list') }
  const onAttention = (k: AttentionKey) => drillTo(ATTENTION_PATCH[k])

  // Группировка по типам каталога (для карточного режима) — на текущей выборке.
  const groups = types
    .map((t) => ({ type: t, items: filtered.filter((l) => l.type === t.code) }))
    .filter((g) => g.items.length > 0)
  const knownCodes = new Set(types.map((t) => t.code))
  const unknownItems = filtered.filter((l) => !knownCodes.has(l.type))

  return (
    <div className="flex-1 min-w-0">
      <div className="px-6 py-6 space-y-6">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-2">
            <MapPin className="h-6 w-6 text-primary shrink-0" />
            <div>
              <h1 className="text-xl font-semibold">Точки обслуживания</h1>
              <p className="text-sm text-muted-foreground mt-1 max-w-2xl">
                {isEnergy
                  ? 'Места работы клиента: ЭЗС, объекты инфраструктуры, офисы, склады.'
                  : 'Места работы клиента: АЗС, ЭЗС, торговые точки, офисы, склады.'}
                {' '}Привязываются к источникам данных и используются системой
                для фильтрации документов и каналов.
              </p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2 shrink-0">
            {locations.length > 0 && (
              <Button variant="outline" onClick={() => setExportOpen(true)}>
                <Download className="h-4 w-4 mr-2" />
                Экспорт
              </Button>
            )}
            {isCompanyAdmin && (
              <LocationTypesManager onChanged={refresh}>
                <Button variant="outline">
                  <SlidersHorizontal className="h-4 w-4 mr-2" />
                  Типы точек
                </Button>
              </LocationTypesManager>
            )}
            <LocationEditDialog onSaved={refresh}>
              <Button>
                <Plus className="h-4 w-4 mr-2" />
                Добавить точку
              </Button>
            </LocationEditDialog>
          </div>
        </div>

        {locations.length === 0 ? (
          <Card>
            <CardContent className="py-10 text-center text-sm text-muted-foreground">
              Точки обслуживания не настроены.{' '}
              {sourcesCount > 0
                ? 'Создайте первую точку через кнопку выше — она появится во всех отчётах и каналах.'
                : 'Сначала настройте хотя бы один источник в разделе «Настройки → Источники».'}
            </CardContent>
          </Card>
        ) : (
          <>
            <FleetKpiBar
              stats={stats}
              fullTotal={locations.length}
              onSlice={(patch) => { sliceTo(patch); setFleetMode('list') }}
              onShowDashboard={() => setFleetMode('dashboard')}
            />

            {/* Режим + (вид списка только в режиме «Список») */}
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="inline-flex rounded-md border border-border/60 p-0.5">
                <Button variant={fleetMode === 'list' ? 'secondary' : 'ghost'} size="sm"
                  className="h-8" onClick={() => setFleetMode('list')}>
                  <List className="h-4 w-4 mr-1.5" /> Список
                </Button>
                <Button variant={fleetMode === 'dashboard' ? 'secondary' : 'ghost'} size="sm"
                  className="h-8" onClick={() => setFleetMode('dashboard')}>
                  <LayoutDashboard className="h-4 w-4 mr-1.5" /> Дашборд
                </Button>
              </div>
              {fleetMode === 'list' && (
                <div className="inline-flex rounded-md border border-border/60 p-0.5">
                  <Button variant={view === 'cards' ? 'secondary' : 'ghost'} size="icon"
                    className="h-8 w-8" title="Карточки" onClick={() => setViewOverride('cards')}>
                    <LayoutGrid className="h-4 w-4" />
                  </Button>
                  <Button variant={view === 'table' ? 'secondary' : 'ghost'} size="icon"
                    className="h-8 w-8" title="Таблица" onClick={() => setViewOverride('table')}>
                    <Table2 className="h-4 w-4" />
                  </Button>
                </div>
              )}
            </div>

            {fleetMode === 'dashboard' ? (
              <FleetDashboard
                stats={stats}
                locations={filtered}
                onDrillDown={drillTo}
                onOpenLocation={setCockpit}
              />
            ) : (
              <>
                <FleetFilters
                  filters={filters}
                  onChange={setFilters}
                  options={options}
                  stats={stats}
                  filteredCount={filtered.length}
                  totalCount={locations.length}
                  onAttention={onAttention}
                />

                {filtered.length === 0 ? (
                  <Card>
                    <CardContent className="py-10 text-center text-sm text-muted-foreground">
                      Ничего не найдено по заданным фильтрам.
                    </CardContent>
                  </Card>
                ) : view === 'table' ? (
                  <LocationsTable
                    locations={filtered}
                    typeByCode={typeByCode}
                    onChanged={refresh}
                    renderEdit={(l, child) => (
                      <LocationEditDialog location={l} onSaved={refresh}>{child}</LocationEditDialog>
                    )}
                    onSelectLocation={setCockpit}
                  />
                ) : (
                  <>
                    {groups.map((g) => (
                      <div key={g.type.code} className="space-y-2">
                        <div className="text-xs font-semibold text-muted-foreground/70 uppercase tracking-wide">
                          {g.type.name}{' '}
                          <span className="text-muted-foreground/50">· {g.items.length}</span>
                        </div>
                        <div className="space-y-2">
                          {g.items.map((l) => (
                            <LocationCard key={l.id} location={l} typeDef={typeByCode.get(l.type)}
                              onChange={refresh} onOpen={() => setCockpit(l)} />
                          ))}
                        </div>
                      </div>
                    ))}
                    {unknownItems.length > 0 && (
                      <div className="space-y-2">
                        <div className="text-xs font-semibold text-muted-foreground/70 uppercase tracking-wide">
                          Прочие <span className="text-muted-foreground/50">· {unknownItems.length}</span>
                        </div>
                        <div className="space-y-2">
                          {unknownItems.map((l) => (
                            <LocationCard key={l.id} location={l} onChange={refresh} onOpen={() => setCockpit(l)} />
                          ))}
                        </div>
                      </div>
                    )}
                  </>
                )}
              </>
            )}
          </>
        )}
      </div>

      <LocationCockpitModal
        location={cockpit ? (locations.find((l) => l.id === cockpit.id) ?? cockpit) : null}
        variant={cockpitVariant}
        onClose={() => setCockpit(null)}
        onChanged={refresh}
        renderEdit={(l, child) => (
          <LocationEditDialog location={l} onSaved={refresh}>{child}</LocationEditDialog>
        )}
      />

      <LocationExportDialog
        open={exportOpen}
        onOpenChange={setExportOpen}
        locations={filtered}
        typeByCode={typeByCode}
      />
    </div>
  )
}
