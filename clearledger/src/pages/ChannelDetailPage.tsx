/**
 * Страница канала — pipeline обработки данных.
 * /channels/:id — вкладки: Обзор, Источники, Обработка, Сверка, Данные, Лог.
 */

import { useState, useMemo } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Progress } from '@/components/ui/progress'
import { Checkbox } from '@/components/ui/checkbox'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { getChannel, updateChannel, addSourceToChannel, removeSourceFromChannel } from '@/services/channelService'
import { getSources } from '@/services/sourceService'
import { getLocations } from '@/services/locationService'
import { syncChannel, getAllLoadedDocs } from '@/services/channelSyncService'
import { extractDeliveries } from '@/services/receiptExtractService'
import { getChannelSourceIds, getChannelStations, STAGE_TYPE_META, DUPLICATE_POLICY_META } from '@/types/channel'
import type { Channel, ChannelStage, ChannelStation, SyncResult, DuplicatePolicy } from '@/types/channel'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  ArrowLeft, Play, Loader2, Radio, Database, Download, Shuffle,
  GitCompare, ShieldCheck, ArrowRightLeft, Trash2, Plus, History,
  Settings2, FileText, AlertTriangle, CheckCircle2, XCircle, GripVertical, MapPin,
} from 'lucide-react'
import { toast } from 'sonner'
import { format } from 'date-fns'

type TabId = 'overview' | 'sources' | 'pipeline' | 'data' | 'log'

// Сверка и работа с нормализованными данными — это отдельный раздел
// продукта (Обработка → Сверка / Управленческий / ...), не часть канала.
// Канал отвечает только за получение сырых данных из внешнего источника.
const TABS: { id: TabId; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { id: 'overview', label: 'Обзор', icon: Radio },
  { id: 'sources', label: 'Источники', icon: Database },
  { id: 'pipeline', label: 'Обработка', icon: Settings2 },
  { id: 'data', label: 'Загружено', icon: FileText },
  { id: 'log', label: 'Лог', icon: History },
]

const STAGE_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  Download, Shuffle, GitCompare, ShieldCheck, ArrowRightLeft,
}

const STATUS_MAP: Record<string, { label: string; variant: 'default' | 'secondary' | 'destructive' | 'outline'; color: string }> = {
  active: { label: 'Активен', variant: 'default', color: 'text-emerald-500' },
  paused: { label: 'Пауза', variant: 'secondary', color: 'text-muted-foreground' },
  error: { label: 'Ошибка', variant: 'destructive', color: 'text-destructive' },
  draft: { label: 'Черновик', variant: 'outline', color: 'text-amber-500' },
}

// ─── Расписание и Период загрузки ────────────────────────

function getScheduleSummary(channel: Channel): { mode: string; interval: number | null; label: string } {
  const sched = channel.schedule
  if (typeof sched === 'string') {
    return { mode: sched, interval: null, label: sched === 'manual' ? 'Вручную' : sched }
  }
  if (!sched) return { mode: 'manual', interval: null, label: 'Вручную' }
  if (sched.mode === 'manual') return { mode: 'manual', interval: null, label: 'Вручную' }
  if (sched.mode === 'interval') {
    const m = sched.intervalMinutes ?? 60
    const label =
      m < 60 ? `Каждые ${m} мин` :
      m === 60 ? 'Каждый час' :
      m < 1440 ? `Каждые ${m / 60} ч` :
      m === 1440 ? 'Раз в сутки' :
      `Каждые ${m} мин`
    return { mode: 'interval', interval: m, label }
  }
  return { mode: sched.mode ?? 'manual', interval: null, label: sched.mode ?? 'manual' }
}

const SCHEDULE_PRESETS: { key: string; label: string; mode: 'manual' | 'interval'; intervalMinutes?: number }[] = [
  { key: 'manual', label: 'Вручную', mode: 'manual' },
  { key: 'i30', label: 'Каждые 30 мин', mode: 'interval', intervalMinutes: 30 },
  { key: 'i60', label: 'Каждый час', mode: 'interval', intervalMinutes: 60 },
  { key: 'i360', label: 'Каждые 6 часов', mode: 'interval', intervalMinutes: 360 },
  { key: 'i1440', label: 'Раз в сутки', mode: 'interval', intervalMinutes: 1440 },
]

function ScheduleCard({ channel, onUpdate }: { channel: Channel; onUpdate: (ch: Channel) => void }) {
  const current = getScheduleSummary(channel)
  const currentKey =
    current.mode === 'manual' ? 'manual' :
    current.interval ? `i${current.interval}` : 'manual'

  function pick(key: string) {
    const preset = SCHEDULE_PRESETS.find((p) => p.key === key)
    if (!preset) return
    const updated = updateChannel(channel.id, {
      schedule: preset.mode === 'manual'
        ? { mode: 'manual', pauseOnError: true, maxRetries: 3 }
        : { mode: 'interval', intervalMinutes: preset.intervalMinutes, pauseOnError: true, maxRetries: 3 },
    })
    if (updated) onUpdate(updated)
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center gap-1.5">
          <History className="h-3.5 w-3.5" />
          Расписание
        </CardTitle>
        <CardDescription className="text-xs">{current.label}</CardDescription>
      </CardHeader>
      <CardContent>
        <Select value={currentKey} onValueChange={pick}>
          <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            {SCHEDULE_PRESETS.map((p) => (
              <SelectItem key={p.key} value={p.key} className="text-xs">{p.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-[10px] text-muted-foreground mt-2 leading-tight">
          {current.mode === 'manual'
            ? 'Канал запускается только по кнопке «Запустить».'
            : 'Канал запускается автоматически, пока приложение открыто.'}
        </p>
      </CardContent>
    </Card>
  )
}

// Период загрузки — список конкретных месяцев (YYYY-MM).
// Канал при запуске прогоняет каждый выбранный месяц как диапазон.
// Если ничего не выбрано — фолбэк к `periodDays` как глубине.

const MONTH_NAMES_RU = [
  'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
  'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь',
]

function monthKey(year: number, month0: number): string {
  return `${year}-${String(month0 + 1).padStart(2, '0')}`
}

function monthLabel(key: string): string {
  const [y, m] = key.split('-').map(Number)
  return `${MONTH_NAMES_RU[(m ?? 1) - 1]} ${y}`
}

function lastNMonths(n: number): string[] {
  const now = new Date()
  const out: string[] = []
  for (let i = 0; i < n; i++) {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1)
    out.push(monthKey(d.getFullYear(), d.getMonth()))
  }
  return out
}

function PeriodCard({ channel, onUpdate }: { channel: Channel; onUpdate: (ch: Channel) => void }) {
  const cfgMonths: string[] = channel.config?.months ?? []
  const months = useMemo(() => lastNMonths(12), [])
  const selected = useMemo(() => new Set(cfgMonths), [cfgMonths.join(',')])

  function save(next: Set<string>) {
    const arr = months.filter((m) => next.has(m))
    const updated = updateChannel(channel.id, {
      config: { ...channel.config, months: arr },
    })
    if (updated) onUpdate(updated)
  }

  function toggle(m: string) {
    const next = new Set(selected)
    if (next.has(m)) next.delete(m)
    else next.add(m)
    save(next)
  }

  function pickPreset(kind: 'current' | 'last3' | 'last6' | 'all' | 'none') {
    const next = new Set<string>()
    if (kind === 'current') next.add(months[0])
    if (kind === 'last3') months.slice(0, 3).forEach((m) => next.add(m))
    if (kind === 'last6') months.slice(0, 6).forEach((m) => next.add(m))
    if (kind === 'all') months.forEach((m) => next.add(m))
    save(next)
  }

  const summary =
    selected.size === 0 ? 'Не выбрано' :
    selected.size === 1 ? monthLabel([...selected][0]) :
    `Месяцев: ${selected.size}`

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <CardTitle className="text-sm flex items-center gap-1.5">
            <FileText className="h-3.5 w-3.5" />
            Период загрузки
          </CardTitle>
          <CardDescription className="text-xs">{summary}</CardDescription>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-3 gap-y-0.5 max-h-[180px] overflow-y-auto pr-1">
          {months.map((m) => {
            const on = selected.has(m)
            return (
              <label key={m}
                className="flex items-center gap-2 py-1 px-1.5 rounded text-xs hover:bg-accent/30 cursor-pointer">
                <Checkbox
                  checked={on}
                  onCheckedChange={() => toggle(m)}
                  className="h-3.5 w-3.5"
                />
                <span className="truncate">{monthLabel(m)}</span>
              </label>
            )
          })}
        </div>
        <div className="flex items-center flex-wrap gap-1 mt-3 pt-2 border-t border-border/40">
          <Button size="sm" variant="outline" className="h-6 text-[10px] px-2"
            onClick={() => pickPreset('current')}>
            Текущий
          </Button>
          <Button size="sm" variant="outline" className="h-6 text-[10px] px-2"
            onClick={() => pickPreset('last3')}>
            3 месяца
          </Button>
          <Button size="sm" variant="outline" className="h-6 text-[10px] px-2"
            onClick={() => pickPreset('last6')}>
            6 месяцев
          </Button>
          <Button size="sm" variant="outline" className="h-6 text-[10px] px-2"
            onClick={() => pickPreset('all')}>
            Все 12
          </Button>
          <Button size="sm" variant="ghost" className="h-6 text-[10px] px-2 text-muted-foreground"
            onClick={() => pickPreset('none')}>
            Очистить
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}


// ─── Карточка Станций — inline-чекбоксы ──────────────────

interface StationCheckEntry {
  code: number
  systemId: number
  name: string
  locationId?: string
}

/**
 * Универсум станций: точки из справочника по STS-привязкам + станции,
 * добавленные вручную в этот канал (даже если их нет в справочнике).
 */
function collectStationUniverse(
  stsSourceId: string | undefined,
  channelStations: ChannelStation[],
): StationCheckEntry[] {
  const seen = new Set<string>()
  const entries: StationCheckEntry[] = []
  for (const loc of getLocations()) {
    if (loc.type !== 'fuel_station') continue
    for (const b of loc.sourceBindings) {
      if (stsSourceId && b.sourceId !== stsSourceId) continue
      const systemId = Number(b.config?.system_id ?? b.config?.systemId)
      const code = Number(b.config?.station ?? b.config?.code ?? loc.code)
      if (!systemId || !code) continue
      const key = `${systemId}|${code}`
      if (seen.has(key)) continue
      seen.add(key)
      entries.push({ code, systemId, name: loc.name, locationId: loc.id })
    }
  }
  for (const s of channelStations) {
    const key = `${s.systemId}|${s.code}`
    if (seen.has(key)) continue
    seen.add(key)
    entries.push({
      code: s.code, systemId: s.systemId,
      name: s.name ?? `Станция ${s.code}`,
      locationId: s.locationId,
    })
  }
  entries.sort((a, b) => a.systemId - b.systemId || a.code - b.code)
  return entries
}

function StationsCard({
  channel, onUpdate,
}: {
  channel: Channel
  onUpdate: (ch: Channel) => void
}) {
  const stsSource = getSources().find((s) => s.type === 'rest')
  const channelStations = getChannelStations(channel)
  const universe = useMemo(
    () => collectStationUniverse(stsSource?.id, channelStations),
    [stsSource?.id, channel.id, channelStations.length],
  )
  const selectedKeys = useMemo(() => {
    const s = new Set<string>()
    for (const x of channelStations) s.add(`${x.systemId}|${x.code}`)
    return s
  }, [channelStations])

  const [newCode, setNewCode] = useState('')
  const [newSys, setNewSys] = useState('65')

  const groups = useMemo(() => {
    const m = new Map<number, StationCheckEntry[]>()
    for (const e of universe) {
      if (!m.has(e.systemId)) m.set(e.systemId, [])
      m.get(e.systemId)!.push(e)
    }
    return Array.from(m.entries()).sort((a, b) => a[0] - b[0])
  }, [universe])

  function saveFromKeys(keys: Set<string>) {
    const next: ChannelStation[] = []
    for (const e of universe) {
      const k = `${e.systemId}|${e.code}`
      if (!keys.has(k)) continue
      next.push({
        code: e.code, systemId: e.systemId,
        name: e.name, locationId: e.locationId,
      })
    }
    next.sort((a, b) => a.systemId - b.systemId || a.code - b.code)
    const updated = updateChannel(channel.id, {
      config: { ...channel.config, stations: next, stationCodes: undefined },
    })
    if (updated) onUpdate(updated)
  }

  function toggle(key: string) {
    const next = new Set(selectedKeys)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    saveFromKeys(next)
  }

  function toggleGroup(sys: number, on: boolean) {
    const next = new Set(selectedKeys)
    const items = groups.find(([s]) => s === sys)?.[1] ?? []
    for (const e of items) {
      const k = `${e.systemId}|${e.code}`
      if (on) next.add(k)
      else next.delete(k)
    }
    saveFromKeys(next)
  }

  function addManual() {
    const code = Number(newCode)
    const systemId = Number(newSys)
    if (!code || !systemId) return
    if (selectedKeys.has(`${systemId}|${code}`)) return
    const newStation: ChannelStation = { code, systemId }
    const next: ChannelStation[] = [...channelStations, newStation]
    next.sort((a, b) => a.systemId - b.systemId || a.code - b.code)
    const updated = updateChannel(channel.id, {
      config: { ...channel.config, stations: next, stationCodes: undefined },
    })
    if (updated) {
      onUpdate(updated)
      setNewCode('')
    }
  }

  return (
    <Card className="md:col-span-2">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm flex items-center gap-1.5">
            <MapPin className="h-3.5 w-3.5" />
            Станции
          </CardTitle>
          <CardDescription className="text-xs">
            Выбрано {selectedKeys.size} из {universe.length}
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent>
        {universe.length === 0 ? (
          <p className="text-xs text-muted-foreground py-4 text-center">
            Нет станций. Откройте «Настройки → Точки обслуживания»
            и запустите «Импорт из STS» либо добавьте вручную ниже.
          </p>
        ) : (
          <div className="space-y-3 max-h-[260px] overflow-y-auto pr-1">
            {groups.map(([sys, items]) => {
              const allOn = items.every((e) => selectedKeys.has(`${e.systemId}|${e.code}`))
              const someOn = items.some((e) => selectedKeys.has(`${e.systemId}|${e.code}`))
              return (
                <div key={sys} className="space-y-1">
                  <label className="flex items-center gap-2 text-[11px] font-semibold text-muted-foreground/80 uppercase tracking-wide cursor-pointer hover:text-foreground">
                    <Checkbox
                      checked={allOn ? true : (someOn ? 'indeterminate' as any : false)}
                      onCheckedChange={(v) => toggleGroup(sys, !!v)}
                      className="h-3.5 w-3.5"
                    />
                    Сеть system_id = {sys}{' '}
                    <span className="text-muted-foreground/50 normal-case">· {items.length}</span>
                  </label>
                  <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 pl-5">
                    {items.map((e) => {
                      const key = `${e.systemId}|${e.code}`
                      const on = selectedKeys.has(key)
                      return (
                        <label key={key}
                          className="flex items-center gap-2 py-1 px-1.5 rounded text-xs hover:bg-accent/30 cursor-pointer">
                          <Checkbox
                            checked={on}
                            onCheckedChange={() => toggle(key)}
                            className="h-3.5 w-3.5"
                          />
                          <span className="font-mono w-8 shrink-0 text-muted-foreground">
                            {e.code}
                          </span>
                          <span className="truncate">{e.name}</span>
                        </label>
                      )
                    })}
                  </div>
                </div>
              )
            })}
          </div>
        )}

        <div className="flex items-center gap-1 mt-3 pt-2 border-t border-border/40">
          <Input value={newCode} onChange={(e) => setNewCode(e.target.value)}
            placeholder="Код вручную" className="h-7 text-xs flex-1 min-w-0" type="number"
            onKeyDown={(e) => e.key === 'Enter' && addManual()} />
          <Select value={newSys} onValueChange={setNewSys}>
            <SelectTrigger className="h-7 text-xs w-[88px] shrink-0"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="65" className="text-xs">sys 65</SelectItem>
              <SelectItem value="15" className="text-xs">sys 15</SelectItem>
            </SelectContent>
          </Select>
          <Button size="sm" variant="outline" className="h-7 text-xs gap-1" onClick={addManual}
            disabled={!newCode}>
            <Plus className="h-3 w-3" />
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}


// ─── Вкладка: Обзор ────────────────────────────────────────

function OverviewTab({ channel, onSync, onUpdate }: { channel: Channel; onSync: () => void; onUpdate: (ch: Channel) => void }) {
  const sources = getSources()
  const channelSourceIds = getChannelSourceIds(channel)
  const channelSources = sources.filter((s) => channelSourceIds.includes(s.id))
  const status = STATUS_MAP[channel.status] ?? STATUS_MAP.draft
  const docs = getAllLoadedDocs().filter((d) => d.channelId === channel.id)

  // Список станций канала используется только для disabled-state кнопки.
  // Все CRUD-операции теперь внутри StationsCard.
  const stations = getChannelStations(channel)

  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
      {/* Статус */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Статус</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-2 mb-3">
            <span className={`text-2xl font-bold ${status.color}`}>● {status.label}</span>
          </div>
          {channel.lastSync && (
            <p className="text-xs text-muted-foreground">
              Последняя синхронизация: {format(new Date(channel.lastSync), 'dd.MM.yyyy HH:mm')}
            </p>
          )}
          <Button size="sm" className="mt-3 gap-1.5" onClick={onSync}
            disabled={stations.length === 0 || channelSources.length === 0}>
            <Play className="h-3.5 w-3.5" />
            Запустить pipeline
          </Button>
          {stations.length === 0 && (
            <p className="text-[10px] text-amber-500 mt-1">Укажите хотя бы одну станцию</p>
          )}
        </CardContent>
      </Card>

      {/* Станции — inline-чекбоксы (StationsCard сам шириной 2 ячейки) */}
      <StationsCard channel={channel} onUpdate={onUpdate} />

      {/* Источники */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Источники</CardTitle>
          <CardDescription className="text-xs">{channelSources.length} подключено</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            {channelSources.map((src) => (
              <div key={src.id} className="flex items-center gap-2 text-xs">
                <Database className="h-3.5 w-3.5 text-muted-foreground" />
                <span className="font-medium">{src.name}</span>
                <Badge variant="outline" className="text-[9px] h-4 ml-auto">{src.type}</Badge>
              </div>
            ))}
            {channelSources.length === 0 && (
              <p className="text-xs text-muted-foreground">Нет подключённых источников</p>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Расписание */}
      <ScheduleCard channel={channel} onUpdate={onUpdate} />

      {/* Период загрузки */}
      <PeriodCard channel={channel} onUpdate={onUpdate} />

      {/* Данные */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Загружено</CardTitle>
          <CardDescription className="text-xs">{docs.length} документов</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-1.5">
            {channel.streams.filter((s) => s.enabled).map((s) => {
              const count = docs.filter((d) => d.streamId === s.id).length
              return (
                <div key={s.id} className="flex items-center justify-between text-xs">
                  <span>{s.name}</span>
                  <Badge variant="secondary" className="text-[10px]">{count}</Badge>
                </div>
              )
            })}
          </div>
        </CardContent>
      </Card>

      {/* Pipeline */}
      <Card className="md:col-span-2">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Pipeline</CardTitle>
          <CardDescription className="text-xs">
            {channel.stages.filter((s) => s.enabled).length} активных этапов
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-2 flex-wrap">
            {channel.stages.sort((a, b) => a.order - b.order).map((stage, i) => {
              const meta = STAGE_TYPE_META[stage.type]
              return (
                <div key={stage.id} className="flex items-center gap-2">
                  {i > 0 && <span className="text-muted-foreground/30">→</span>}
                  <div className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md border text-xs ${
                    stage.enabled ? 'border-border bg-card' : 'border-border/30 bg-muted/30 text-muted-foreground line-through'
                  }`}>
                    <span>{meta.label}</span>
                  </div>
                </div>
              )
            })}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

// ─── Вкладка: Источники ─────────────────────────────────────

function SourcesTab({ channel, onUpdate }: { channel: Channel; onUpdate: (ch: Channel) => void }) {
  const allSources = getSources()
  const channelSourceIds = getChannelSourceIds(channel)
  const available = allSources.filter((s) => !channelSourceIds.includes(s.id))
  const connected = allSources.filter((s) => channelSourceIds.includes(s.id))
  const [addingSourceId, setAddingSourceId] = useState('')

  function handleAdd() {
    if (!addingSourceId) return
    const updated = addSourceToChannel(channel.id, addingSourceId)
    if (updated) {
      onUpdate(updated)
      setAddingSourceId('')
      toast.success('Источник добавлен в обработку')
    }
  }

  function handleRemove(sourceId: string) {
    const updated = removeSourceFromChannel(channel.id, sourceId)
    if (updated) {
      onUpdate(updated)
      toast.success('Источник отключён')
    }
  }

  return (
    <div className="space-y-6">
      {/* Подключённые */}
      <div className="space-y-3">
        <h3 className="text-sm font-semibold">Подключённые источники</h3>
        {connected.length === 0 ? (
          <Card>
            <CardContent className="py-8 text-center">
              <Database className="h-8 w-8 text-muted-foreground/30 mx-auto mb-2" />
              <p className="text-sm text-muted-foreground">Нет подключённых источников</p>
            </CardContent>
          </Card>
        ) : (
          <div className="grid gap-3">
            {connected.map((src) => {
              const streams = channel.streams.filter((s) => s.sourceId === src.id)
              return (
                <Card key={src.id}>
                  <CardContent className="py-4">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <div className="flex items-center justify-center w-9 h-9 rounded-lg bg-primary/10">
                          <Database className="h-4 w-4 text-primary" />
                        </div>
                        <div>
                          <p className="text-sm font-medium">{src.name}</p>
                          <p className="text-xs text-muted-foreground">
                            {src.type} · {streams.length} потоков · {src.status === 'connected' ? '● подключён' : '○ не подключён'}
                          </p>
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <Badge variant="outline" className="text-[10px]">{src.type}</Badge>
                        <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground hover:text-destructive"
                          onClick={() => handleRemove(src.id)}>
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </div>

                    {/* Потоки от этого источника */}
                    {streams.length > 0 && (
                      <div className="mt-3 pl-12 space-y-1">
                        {streams.map((st) => (
                          <div key={st.id} className="flex items-center gap-2 text-xs text-muted-foreground">
                            <Checkbox checked={st.enabled} className="h-3 w-3"
                              onCheckedChange={(checked) => {
                                const updated = updateChannel(channel.id, {
                                  streams: channel.streams.map((s) =>
                                    s.id === st.id ? { ...s, enabled: !!checked } : s
                                  ),
                                })
                                if (updated) onUpdate(updated)
                              }} />
                            <span className={st.enabled ? 'text-foreground' : 'line-through'}>{st.name}</span>
                            <span className="font-mono text-[10px] ml-auto">{st.docTypeId}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </CardContent>
                </Card>
              )
            })}
          </div>
        )}
      </div>

      {/* Добавить */}
      {available.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-sm font-semibold">Добавить источник</h3>
          <div className="flex items-center gap-2">
            <Select value={addingSourceId} onValueChange={setAddingSourceId}>
              <SelectTrigger className="w-[300px] h-8 text-sm">
                <SelectValue placeholder="Выберите источник" />
              </SelectTrigger>
              <SelectContent>
                {available.map((s) => (
                  <SelectItem key={s.id} value={s.id}>{s.name} ({s.type})</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button size="sm" className="h-8 gap-1" onClick={handleAdd} disabled={!addingSourceId}>
              <Plus className="h-3.5 w-3.5" />
              Подключить
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Вкладка: Pipeline (Обработка) ─────────────────────────

function PipelineTab({ channel, onUpdate }: { channel: Channel; onUpdate: (ch: Channel) => void }) {
  const stages = [...channel.stages].sort((a, b) => a.order - b.order)

  function toggleStage(stageId: string) {
    const updated = updateChannel(channel.id, {
      stages: channel.stages.map((s) =>
        s.id === stageId ? { ...s, enabled: !s.enabled } : s
      ),
    })
    if (updated) onUpdate(updated)
  }

  function removeStage(stageId: string) {
    const updated = updateChannel(channel.id, {
      stages: channel.stages.filter((s) => s.id !== stageId),
    })
    if (updated) onUpdate(updated)
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold">Этапы обработки</h3>
          <p className="text-xs text-muted-foreground">
            Данные проходят через pipeline слева направо
          </p>
        </div>
      </div>

      <div className="space-y-2">
        {stages.map((stage, i) => {
          const meta = STAGE_TYPE_META[stage.type]
          const IconComp = STAGE_ICONS[meta.icon] ?? Download
          return (
            <div key={stage.id}>
              {i > 0 && (
                <div className="flex items-center justify-center py-1">
                  <div className="w-px h-4 bg-border" />
                </div>
              )}
              <Card className={stage.enabled ? '' : 'opacity-50'}>
                <CardContent className="py-3">
                  <div className="flex items-center gap-3">
                    <GripVertical className="h-4 w-4 text-muted-foreground/30 cursor-grab" />
                    <Checkbox checked={stage.enabled} className="h-4 w-4"
                      onCheckedChange={() => toggleStage(stage.id)} />
                    <div className="flex items-center justify-center w-8 h-8 rounded-md bg-primary/10">
                      <IconComp className="h-4 w-4 text-primary" />
                    </div>
                    <div className="flex-1">
                      <p className="text-sm font-medium">{stage.name}</p>
                      <p className="text-xs text-muted-foreground">{meta.description}</p>
                    </div>
                    <Badge variant="outline" className="text-[10px]">{meta.label}</Badge>
                    <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground hover:text-destructive"
                      onClick={() => removeStage(stage.id)}>
                      <Trash2 className="h-3 w-3" />
                    </Button>
                  </div>
                </CardContent>
              </Card>
            </div>
          )
        })}
      </div>

      {stages.length === 0 && (
        <Card>
          <CardContent className="py-8 text-center">
            <Settings2 className="h-8 w-8 text-muted-foreground/30 mx-auto mb-2" />
            <p className="text-sm text-muted-foreground">Pipeline пуст</p>
            <p className="text-xs text-muted-foreground">Добавьте источники — этапы создадутся автоматически</p>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

// ─── Вкладка: Данные ────────────────────────────────────────

function DataTab({ channel }: { channel: Channel }) {
  const docs = getAllLoadedDocs().filter((d) => d.channelId === channel.id)
  const grouped = useMemo(() => {
    const map = new Map<string, typeof docs>()
    for (const doc of docs) {
      const key = doc.docType
      if (!map.has(key)) map.set(key, [])
      map.get(key)!.push(doc)
    }
    return map
  }, [docs])

  if (docs.length === 0) {
    return (
      <Card>
        <CardContent className="py-12 text-center">
          <FileText className="h-10 w-10 text-muted-foreground/30 mx-auto mb-3" />
          <p className="text-sm font-medium text-muted-foreground">Нет загруженных данных</p>
          <p className="text-xs text-muted-foreground mt-1">
            Запустите pipeline для загрузки данных из источников
          </p>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">Загружено {docs.length} документов</p>
      {Array.from(grouped.entries()).map(([type, items]) => (
        <Card key={type}>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">{type === 'shift_report' ? 'Сменные отчёты' : type === 'receipt' ? 'ТТН' : type}</CardTitle>
            <CardDescription className="text-xs">{items.length} документов</CardDescription>
          </CardHeader>
          <CardContent>
            <ScrollArea className="max-h-[300px]">
              <div className="space-y-1">
                {items.slice(0, 50).map((doc) => (
                  <div key={doc.id} className="flex items-center gap-3 text-xs py-1.5 px-2 rounded hover:bg-accent/30">
                    <FileText className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                    <span className="font-medium flex-1 truncate">{doc.title}</span>
                    <span className="text-muted-foreground shrink-0">
                      {format(new Date(doc.date), 'dd.MM.yyyy')}
                    </span>
                  </div>
                ))}
                {items.length > 50 && (
                  <p className="text-xs text-muted-foreground py-2 text-center">
                    ... и ещё {items.length - 50}
                  </p>
                )}
              </div>
            </ScrollArea>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}

// ─── Вкладка: Лог ───────────────────────────────────────────

function LogTab({ channel }: { channel: Channel }) {
  const log = channel.syncLog ?? []

  if (log.length === 0) {
    return (
      <Card>
        <CardContent className="py-12 text-center">
          <History className="h-10 w-10 text-muted-foreground/30 mx-auto mb-3" />
          <p className="text-sm font-medium text-muted-foreground">Лог пуст</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardContent className="py-3">
        <ScrollArea className="max-h-[500px]">
          <div className="space-y-0.5 font-mono text-[11px]">
            {log.map((entry, i) => (
              <div key={i} className={`flex gap-3 py-0.5 ${
                entry.level === 'error' ? 'text-destructive' :
                entry.level === 'success' ? 'text-emerald-500' :
                entry.level === 'warn' ? 'text-amber-500' :
                'text-muted-foreground'
              }`}>
                <span className="shrink-0 w-16">{format(new Date(entry.timestamp), 'HH:mm:ss')}</span>
                <span className="shrink-0 w-20 font-semibold">{entry.event}</span>
                <span>{entry.message}</span>
              </div>
            ))}
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  )
}

// ─── Главная страница канала ─────────────────────────────────

export function ChannelDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [channel, setChannel] = useState<Channel | undefined>(() => id ? getChannel(id) : undefined)
  const [activeTab, setActiveTab] = useState<TabId>('overview')
  const [syncing, setSyncing] = useState(false)
  const [syncProgress, setSyncProgress] = useState('')

  if (!channel) {
    return (
      <div className="flex flex-col items-center justify-center h-[60vh] gap-4">
        <XCircle className="h-10 w-10 text-muted-foreground/30" />
        <p className="text-lg text-muted-foreground">Обработка не найдена</p>
        <Link to="/channels" className="text-primary hover:underline text-sm">← К списку обработок</Link>
      </div>
    )
  }

  function refresh() {
    if (id) setChannel(getChannel(id))
  }

  async function handleSync() {
    if (!channel) return
    setSyncing(true)
    setSyncProgress('Запуск...')
    try {
      // Если канал извлекает из сменных отчётов — другой pipeline
      if (channel.config?.extractFrom === 'shift_reports') {
        await extractDeliveries(channel, {
          onProgress: (_l, _t, msg) => setSyncProgress(msg),
        })
      } else {
        await syncChannel(channel, {
          onProgress: (_l, _t, msg) => setSyncProgress(msg),
        })
      }
      refresh()
      toast.success('Pipeline завершён')
    } catch (err) {
      toast.error(String(err))
    } finally {
      setSyncing(false)
      setSyncProgress('')
    }
  }

  const status = STATUS_MAP[channel.status] ?? STATUS_MAP.draft

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => navigate('/channels')}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="flex-1">
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-bold">{channel.name}</h1>
            <Badge variant={status.variant} className="text-[10px]">{status.label}</Badge>
          </div>
          {channel.description && (
            <p className="text-sm text-muted-foreground mt-0.5">{channel.description}</p>
          )}
        </div>
        <Button size="sm" className="gap-1.5" onClick={handleSync} disabled={syncing}>
          {syncing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
          Запустить
        </Button>
      </div>

      {/* Прогресс */}
      {syncing && (
        <div className="space-y-1">
          <Progress className="h-1.5" />
          <p className="text-[10px] text-muted-foreground">{syncProgress}</p>
        </div>
      )}

      {/* Tabs */}
      <div className="flex items-center gap-1 border-b border-border/40 pb-px">
        {TABS.map((tab) => {
          const Icon = tab.icon
          const isActive = activeTab === tab.id
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-1.5 px-3 py-2 text-sm font-medium border-b-2 transition-colors ${
                isActive
                  ? 'border-primary text-primary'
                  : 'border-transparent text-muted-foreground hover:text-foreground hover:border-border'
              }`}
            >
              <Icon className="h-3.5 w-3.5" />
              {tab.label}
            </button>
          )
        })}
      </div>

      {/* Content */}
      <div className="pt-2">
        {activeTab === 'overview' && <OverviewTab channel={channel} onSync={handleSync} onUpdate={(ch) => { setChannel(ch); refresh() }} />}
        {activeTab === 'sources' && <SourcesTab channel={channel} onUpdate={(ch) => { setChannel(ch); refresh() }} />}
        {activeTab === 'pipeline' && <PipelineTab channel={channel} onUpdate={(ch) => { setChannel(ch); refresh() }} />}
        {activeTab === 'data' && <DataTab channel={channel} />}
        {activeTab === 'log' && <LogTab channel={channel} />}
      </div>
    </div>
  )
}

export default ChannelDetailPage
