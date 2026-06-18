/**
 * Точки обслуживания клиента.
 *
 * Справочник мест: АЗС, магазины, офисы, склады. Используется
 * системой для привязки документов к местам и фильтрации каналов.
 */

import { useState, useEffect } from 'react'
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
  Download, Loader2,
} from 'lucide-react'
import { toast } from 'sonner'
import {
  getLocations, createLocation, updateLocation, deleteLocation,
  getLocationByCode, loadLocations,
} from '@/services/locationService'
import { getSources, loadSources } from '@/services/sourceService'
import { useCompany } from '@/contexts/CompanyContext'
import { stsGetPoints, type StsPoint } from '@/services/fuel/stsApiClient'
import { getSettings } from '@/services/settingsService'
import { mstoGetServicePoints } from '@/services/msto/mstoApiClient'
import { tradecorpGetSummary } from '@/services/tradecorp/tradecorpApiClient'
import {
  LOCATION_TYPE_META, LOCATION_STATUS_META,
  type LocationStatus, type LocationType, type ServiceLocation,
} from '@/types/location'

const ICON_MAP: Record<LocationType, React.ComponentType<{ className?: string }>> = {
  fuel_station: Fuel,
  retail: Store,
  office: Building2,
  warehouse: Warehouse,
  other: MapPin,
}

const STATUS_BADGE_COLOR: Record<LocationStatus, string> = {
  active: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400',
  closed: 'bg-muted text-muted-foreground',
  planned: 'bg-blue-500/15 text-blue-600 dark:text-blue-400',
}


function LocationCard({
  location,
  onChange,
}: {
  location: ServiceLocation
  onChange: () => void
}) {
  const Icon = ICON_MAP[location.type]
  const typeMeta = LOCATION_TYPE_META[location.type]
  const statusMeta = LOCATION_STATUS_META[location.status]

  function handleDelete() {
    if (deleteLocation(location.id)) {
      toast.success(`Удалена точка «${location.name}»`)
      onChange()
    }
  }

  return (
    <Card>
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
              {typeMeta.label}
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
          </div>
          <div className="flex gap-1 shrink-0">
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
  const [code, setCode] = useState(location?.code ?? '')
  const [name, setName] = useState(location?.name ?? '')
  const [type, setType] = useState<LocationType>(location?.type ?? 'fuel_station')
  const [status, setStatus] = useState<LocationStatus>(location?.status ?? 'active')
  const [address, setAddress] = useState(location?.address ?? '')
  const [description, setDescription] = useState(location?.description ?? '')

  function handleSave() {
    if (!code.trim() || !name.trim()) {
      toast.error('Код и название обязательны')
      return
    }
    if (isEdit && location) {
      updateLocation(location.id, {
        code: code.trim(), name: name.trim(),
        type, status, address: address.trim() || undefined,
        description: description.trim() || undefined,
      })
      toast.success(`Сохранена точка «${name}»`)
    } else {
      createLocation({
        code: code.trim(), name: name.trim(),
        type, status,
        address: address.trim() || undefined,
        description: description.trim() || undefined,
      })
      toast.success(`Создана точка «${name}»`)
    }
    setOpen(false)
    onSaved()
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{children}</DialogTrigger>
      <DialogContent className="sm:max-w-md">
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
                placeholder="208" />
            </div>
            <div className="space-y-1.5 col-span-2">
              <Label htmlFor="loc-name">Название</Label>
              <Input id="loc-name" value={name} onChange={(e) => setName(e.target.value)}
                placeholder="АКЗС Выборг (208)" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="loc-type">Тип</Label>
              <Select value={type} onValueChange={(v) => setType(v as LocationType)}>
                <SelectTrigger id="loc-type"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {(Object.keys(LOCATION_TYPE_META) as LocationType[]).map((k) => (
                    <SelectItem key={k} value={k}>{LOCATION_TYPE_META[k].label}</SelectItem>
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
              placeholder="г. Выборг, Ленинградское ш., 14" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="loc-desc">Описание</Label>
            <Textarea id="loc-desc" value={description} onChange={(e) => setDescription(e.target.value)}
              placeholder="Доп. примечания" rows={2} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>Отмена</Button>
          <Button onClick={handleSave}>{isEdit ? 'Сохранить' : 'Создать'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}


// Пул кодов для discover в STS. Покрывает реальные коды сети ГИГ (1..10
// + 200..220) с запасом — если появится станция «11» или «215», она
// тоже найдётся при следующем импорте.
interface ImportedCode {
  code: string
  label?: string
  config: Record<string, string | number>
  bindingLabel: string
}

interface ImportSummary {
  found: number
  matched: number
  unmatched: ImportedCode[]
  sourceName: string
}

/** Привязать найденные коды к существующим ServiceLocation по code. */
function applyBindings(
  sourceId: string,
  sourceName: string,
  found: ImportedCode[],
): ImportSummary {
  const unmatched: ImportedCode[] = []
  let matched = 0
  for (const item of found) {
    const existing = getLocationByCode(item.code)
    if (!existing) {
      unmatched.push(item)
      continue
    }
    // Удаляем старую привязку с тем же sourceId и теми же config-ключами,
    // добавляем актуальную.
    const otherBindings = existing.sourceBindings.filter((b) => {
      if (b.sourceId !== sourceId) return true
      const keys = Object.keys(item.config)
      return !keys.every((k) => b.config[k] === item.config[k])
    })
    updateLocation(existing.id, {
      sourceBindings: [
        ...otherBindings,
        { sourceId, config: item.config, label: item.bindingLabel },
      ],
    })
    matched += 1
  }
  return { found: found.length, matched, unmatched, sourceName }
}

/** Авто-импорт ВСЕХ торговых точек из STS (/v1/points): создаёт недостающие
 *  ServiceLocation и привязывает к STS-источнику (system_id + station). */
function importPointsFromSts(
  sourceId: string,
  system: number,
  points: StsPoint[],
): ImportSummary {
  let matched = 0
  for (const p of points) {
    const code = String(p.id ?? p.number ?? '').trim()
    if (!code || code === 'undefined') continue
    const config = { system_id: system, station: Number(code) }
    const label = `STS sys=${system} st=${code}`
    const name = p.name || `АЗС №${code}`
    const existing = getLocationByCode(code)
    if (existing) {
      // Убираем любую старую STS-привязку этой станции (у STS-привязок есть
      // system_id) — вкл. устаревшие sourceId и прежнюю систему (sys=65),
      // чтобы не плодить дубли. MSTO/TradeCorp-привязки не трогаем.
      const other = existing.sourceBindings.filter(
        (b) => !(b.config.system_id != null && String(b.config.station) === code),
      )
      updateLocation(existing.id, {
        address: existing.address || p.address,
        sourceBindings: [...other, { sourceId, config, label }],
      })
    } else {
      createLocation({
        code, name, type: 'fuel_station', address: p.address,
        sourceBindings: [{ sourceId, config, label }],
      })
    }
    matched += 1
  }
  return { found: points.length, matched, unmatched: [], sourceName: 'STS' }
}

/** Извлечь первое целое число из строки (для имён типа «АКЗС 208»). */
function parseStationCode(name: string): string | null {
  const m = name.match(/\d+/)
  return m ? m[0] : null
}


interface ImportDialogProps {
  trigger: React.ReactNode
  title: string
  description: string
  canRun: boolean
  sourceMissingText?: string
  runImport: (setProgress: (label: string) => void) => Promise<ImportSummary>
  onDone: () => void
}

function ImportDialog({
  trigger, title, description, canRun, sourceMissingText, runImport, onDone,
}: ImportDialogProps) {
  const [open, setOpen] = useState(false)
  const [running, setRunning] = useState(false)
  const [progressLabel, setProgressLabel] = useState('')
  const [summary, setSummary] = useState<ImportSummary | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function handleRun() {
    if (!canRun) {
      toast.error(sourceMissingText ?? 'Источник не настроен')
      return
    }
    setRunning(true)
    setSummary(null)
    setError(null)
    try {
      const result = await runImport(setProgressLabel)
      setSummary(result)
      toast.success(
        `${result.sourceName}: найдено ${result.found}, сопоставлено ${result.matched}, без пары ${result.unmatched.length}`,
      )
      onDone()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      toast.error('Импорт прерван — см. ошибку в диалоге')
    } finally {
      setRunning(false)
    }
  }

  function handleClose() {
    setOpen(false)
    setSummary(null)
    setError(null)
    setProgressLabel('')
  }

  return (
    <Dialog open={open} onOpenChange={(o) => (o ? setOpen(true) : handleClose())}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 text-sm">
          <p className="text-muted-foreground">{description}</p>
          {!canRun && sourceMissingText && (
            <div className="text-destructive text-xs">{sourceMissingText}</div>
          )}
          {running && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              {progressLabel || 'Запрос…'}
            </div>
          )}
          {error && (
            <div className="text-destructive text-xs whitespace-pre-wrap">{error}</div>
          )}
          {summary && !running && (
            <div className="space-y-2 text-xs">
              <div className="font-medium">
                Найдено {summary.found} · сопоставлено {summary.matched} · без пары {summary.unmatched.length}
              </div>
              {summary.unmatched.length > 0 && (
                <div>
                  <div className="text-muted-foreground mb-1">
                    Без точки обслуживания (создайте вручную с этими кодами):
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {summary.unmatched.map((u, i) => (
                      <Badge key={i} variant="outline" className="text-[10px]">
                        {u.code}{u.label ? ` · ${u.label}` : ''}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
        <DialogFooter>
          {summary ? (
            <Button onClick={handleClose}>Готово</Button>
          ) : (
            <>
              <Button variant="outline" onClick={handleClose} disabled={running}>
                Отмена
              </Button>
              <Button onClick={handleRun} disabled={running || !canRun}>
                {running ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    Запрос…
                  </>
                ) : (
                  'Начать'
                )}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}


function StsImportButton({ onDone }: { onDone: () => void }) {
  const stsSource = getSources().find((s) => s.type === 'rest')
  return (
    <ImportDialog
      trigger={
        <Button variant="outline" size="sm">
          <Download className="h-4 w-4 mr-2" />
          Импорт из STS
        </Button>
      }
      title="Импорт точек из STS"
      description={
        'Загружает все торговые точки сети из STS (GET /v1/points) для текущей системы ' +
        'и создаёт/обновляет точки обслуживания с привязкой к STS (system_id + station).'
      }
      canRun={!!stsSource}
      sourceMissingText={
        !stsSource
          ? 'Источник «STS API ГИГ» не настроен. Сначала откройте «Настройки → Источники».'
          : undefined
      }
      runImport={async (setProgress) => {
        const sourceId = stsSource!.id
        const sys = getSettings().stsSystemCode
        setProgress(`Загрузка точек из STS (система ${sys})…`)
        const points = await stsGetPoints(sys)
        setProgress(`Получено точек: ${points.length}. Создаю/привязываю…`)
        return importPointsFromSts(sourceId, sys, points)
      }}
      onDone={onDone}
    />
  )
}


function MstoImportButton({ onDone }: { onDone: () => void }) {
  const mstoSource = getSources().find((s) => s.type === 'msto')
  return (
    <ImportDialog
      trigger={
        <Button variant="outline" size="sm">
          <Download className="h-4 w-4 mr-2" />
          Импорт из MSTO
        </Button>
      }
      title="Импорт кодов станций из MSTO"
      description={
        'Получает список servicePoints из MSTO IntegratorService. Каждый servicePointId сопоставляется ' +
        'с точкой обслуживания: сначала по числу в имени точки MSTO, затем по самому servicePointId.'
      }
      canRun={!!mstoSource}
      sourceMissingText={
        !mstoSource
          ? 'Источник «MSTO Онлайн-заказы» не настроен. Сначала откройте «Настройки → Источники».'
          : undefined
      }
      runImport={async (setProgress) => {
        const sourceId = mstoSource!.id
        setProgress('Запрос /private/servicePoints…')
        const points = await mstoGetServicePoints({
          url: mstoSource!.connection.url,
          login: mstoSource!.connection.login,
          password: mstoSource!.connection.password,
        })
        const found: ImportedCode[] = points.map((p) => {
          const code = parseStationCode(p.name) ?? String(p.id)
          return {
            code,
            label: p.name,
            config: { servicePointId: p.id, servicePointName: p.name },
            bindingLabel: `MSTO id=${p.id}${p.name ? ` (${p.name})` : ''}`,
          }
        })
        return applyBindings(sourceId, 'MSTO', found)
      }}
      onDone={onDone}
    />
  )
}


function TradecorpImportButton({ onDone }: { onDone: () => void }) {
  const tcSource = getSources().find((s) => s.type === 'tradecorp')
  return (
    <ImportDialog
      trigger={
        <Button variant="outline" size="sm">
          <Download className="h-4 w-4 mr-2" />
          Импорт из TradeCorp
        </Button>
      }
      title="Импорт кодов станций из TradeCorp"
      description={
        'Получает сводку транзакций корпоративных карт за последние 90 дней и собирает уникальные ' +
        'коды станций. Каждый stationNumber сопоставляется с точкой обслуживания по этому коду.'
      }
      canRun={!!tcSource}
      sourceMissingText={
        !tcSource
          ? 'Источник «TradeCorp Корп. карты» не настроен. Сначала откройте «Настройки → Источники».'
          : undefined
      }
      runImport={async (setProgress) => {
        const sourceId = tcSource!.id
        setProgress('Запрос transactions_get за 90 дней…')
        const now = new Date()
        const ninetyDaysAgo = new Date(now.getTime() - 90 * 24 * 60 * 60 * 1000)
        const summary = await tradecorpGetSummary(ninetyDaysAgo, now, undefined, {
          url: tcSource!.connection.url,
          login: tcSource!.connection.login,
          password: tcSource!.connection.password,
          emitentId: tcSource!.connection.emitentId,
        })
        const found: ImportedCode[] = summary.map((s) => ({
          code: String(s.stationNumber),
          label: s.stationName,
          config: { stationNumber: s.stationNumber, stationName: s.stationName },
          bindingLabel: `TradeCorp st=${s.stationNumber}${s.stationName ? ` (${s.stationName})` : ''}`,
        }))
        return applyBindings(sourceId, 'TradeCorp', found)
      }}
      onDone={onDone}
    />
  )
}




export function LocationsPage() {
  const [_tick, setTick] = useState(0)
  const refresh = () => setTick((t) => t + 1)
  const { companyId } = useCompany()

  // Гидрация источников (для STS-импорта) + точек обслуживания (из бэкенда)
  useEffect(() => {
    void Promise.all([loadSources(companyId), loadLocations(companyId)])
      .then(refresh).catch(() => { /* офлайн → localStorage */ })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId])

  const locations = getLocations()
  const sourcesCount = getSources().length

  // Группировка по типу
  const byType: Record<LocationType, ServiceLocation[]> = {
    fuel_station: [], retail: [], office: [], warehouse: [], other: [],
  }
  for (const l of locations) byType[l.type].push(l)
  const order: LocationType[] = ['fuel_station', 'retail', 'office', 'warehouse', 'other']

  return (
    <div className="flex-1 min-w-0">
      <div className="px-6 py-6 space-y-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-xl font-semibold">Точки обслуживания</h1>
            <p className="text-sm text-muted-foreground mt-1 max-w-2xl">
              Места работы клиента: АЗС, торговые точки, офисы, склады.
              Привязываются к источникам данных и используются системой
              для фильтрации документов и каналов.
            </p>
          </div>
          <div className="flex flex-wrap gap-2 shrink-0">
            <StsImportButton onDone={refresh} />
            <MstoImportButton onDone={refresh} />
            <TradecorpImportButton onDone={refresh} />
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
          order
            .filter((t) => byType[t].length > 0)
            .map((t) => (
              <div key={t} className="space-y-2">
                <div className="text-xs font-semibold text-muted-foreground/70 uppercase tracking-wide">
                  {LOCATION_TYPE_META[t].label}{' '}
                  <span className="text-muted-foreground/50">· {byType[t].length}</span>
                </div>
                <div className="space-y-2">
                  {byType[t].map((l) => (
                    <LocationCard key={l.id} location={l} onChange={refresh} />
                  ))}
                </div>
              </div>
            ))
        )}
      </div>
    </div>
  )
}
