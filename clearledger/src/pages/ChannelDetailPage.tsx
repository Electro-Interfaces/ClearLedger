/**
 * Страница канала — pipeline данных.
 * /channels/:id — вкладки: Обзор, Источники, Схема, Загружено, Лог.
 */

import { useState, useMemo, useEffect } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Progress } from '@/components/ui/progress'
import { Checkbox } from '@/components/ui/checkbox'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useQueryClient } from '@tanstack/react-query'
import { getChannel, loadChannels, updateChannel, addSourceToChannel, removeSourceFromChannel, runChannel } from '@/services/channelService'
import { uploadTableFile } from '@/services/referenceService'
import { getSources, loadSources } from '@/services/sourceService'
import { listMappings, createMapping, deleteMapping, type ReconcileMapping, type MappingKind } from '@/services/mappingService'
import { isApiEnabled } from '@/services/apiClient'
import { useCompany } from '@/contexts/CompanyContext'
import { getLocations, loadLocations } from '@/services/locationService'
import { useFilters } from '@/contexts/FilterContext'
import { StationsSelectorDialog } from '@/components/stations/StationsSelectorDialog'
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
  Search, Filter, Upload,
} from 'lucide-react'
import { toast } from 'sonner'
import { format } from 'date-fns'

type TabId = 'overview' | 'sources' | 'pipeline' | 'mapping' | 'data' | 'log'

// Сверка — отдельный раздел продукта и идёт на уровне РАЗРЕЗОВ, не каналов.
// Канал отвечает за получение сырых данных из источника и их ПРЕДОБРАБОТКУ
// (маппинг внешних ключей на справочники 1С, нормализация) — до сверки.
const TABS: { id: TabId; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { id: 'overview', label: 'Обзор', icon: Radio },
  { id: 'sources', label: 'Источники', icon: Database },
  { id: 'pipeline', label: 'Схема', icon: Settings2 },
  { id: 'mapping', label: 'Маппинг', icon: ArrowRightLeft },
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

  async function pick(key: string) {
    const preset = SCHEDULE_PRESETS.find((p) => p.key === key)
    if (!preset) return
    const updated = await updateChannel(channel.id, {
      schedule: preset.mode === 'manual'
        ? { mode: 'manual', pauseOnError: true, maxRetries: 3 }
        : { mode: 'interval', intervalMinutes: preset.intervalMinutes, pauseOnError: true, maxRetries: 3 },
    })
    if (updated) onUpdate(updated)
  }

  return (
    <Card className="py-3 gap-2">
      <CardHeader className="pb-0">
        <CardTitle className="text-sm flex items-center gap-1.5">
          <History className="h-3.5 w-3.5" />
          Расписание
          <span className="text-xs text-muted-foreground font-normal ml-auto">{current.label}</span>
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-0 pb-3">
        <Select value={currentKey} onValueChange={pick}>
          <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            {SCHEDULE_PRESETS.map((p) => (
              <SelectItem key={p.key} value={p.key} className="text-xs">{p.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
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

function todayStr(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function firstDayOfMonth(monthStr: string): string {
  return `${monthStr}-01`
}

function lastDayOfMonth(monthStr: string): string {
  const [y, m] = monthStr.split('-').map(Number)
  const day = new Date(y, m, 0).getDate() // m=1..12 → день 0 след. месяца = последний день
  return `${monthStr}-${String(day).padStart(2, '0')}`
}

function fmtRu(dateStr: string): string {
  const [y, m, d] = dateStr.split('-')
  return `${d}.${m}.${y}`
}

function PeriodCard({ channel, onUpdate }: { channel: Channel; onUpdate: (ch: Channel) => void }) {
  const cfg = channel.config ?? {}
  const dateFrom: string | undefined = cfg.dateFrom
  const dateTo: string | undefined = cfg.dateTo

  async function save(df?: string, dt?: string) {
    // PATCH config МЕРЖИТ на бэкенде — чтобы очистить, шлём явный null
    // (undefined выпал бы из JSON и старое значение осталось бы). _period()
    // трактует null как «не задано» → фолбэк к period_days.
    const updated = await updateChannel(channel.id, {
      config: { ...channel.config, dateFrom: df ?? null, dateTo: dt ?? null, months: null },
    })
    if (updated) onUpdate(updated)
  }

  function setFromMonth(v: string) {
    if (!v) return save(undefined, dateTo)
    save(firstDayOfMonth(v), dateTo ?? todayStr())
  }
  function setToMonth(v: string) {
    if (!v) return save(dateFrom, undefined)
    save(dateFrom ?? firstDayOfMonth(v), lastDayOfMonth(v))
  }

  function preset(kind: 'current' | 'last3' | 'last6' | 'last12' | 'year' | 'none') {
    const now = new Date()
    const back = (n: number) => {
      const d = new Date(now.getFullYear(), now.getMonth() - n, 1)
      return monthKey(d.getFullYear(), d.getMonth())
    }
    if (kind === 'none') return save(undefined, undefined)
    if (kind === 'year') return save(`${now.getFullYear()}-01-01`, todayStr())
    const startMonth =
      kind === 'current' ? back(0) :
      kind === 'last3' ? back(2) :
      kind === 'last6' ? back(5) : back(11)
    save(firstDayOfMonth(startMonth), todayStr())
  }

  const hasRange = !!(dateFrom && dateTo)
  const summary = hasRange
    ? `${fmtRu(dateFrom!)} – ${fmtRu(dateTo!)}`
    : `По умолчанию · ${channel.periodDays ?? 30} дн.`

  return (
    <Card className="py-3 gap-2">
      <CardHeader className="pb-0">
        <CardTitle className="text-sm flex items-center gap-1.5">
          <FileText className="h-3.5 w-3.5" />
          Период загрузки
          <span className="text-xs text-muted-foreground font-normal ml-auto tabular-nums">{summary}</span>
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-0 pb-3 space-y-2">
        <div className="flex items-end gap-1.5">
          <div className="flex-1 min-w-0">
            <Label className="text-[10px] text-muted-foreground mb-0.5 block">С месяца</Label>
            <Input type="month" value={dateFrom ? dateFrom.slice(0, 7) : ''}
              max={dateTo ? dateTo.slice(0, 7) : undefined}
              onChange={(e) => setFromMonth(e.target.value)}
              className="h-7 text-xs" />
          </div>
          <span className="text-muted-foreground text-xs pb-1.5">–</span>
          <div className="flex-1 min-w-0">
            <Label className="text-[10px] text-muted-foreground mb-0.5 block">По месяц</Label>
            <Input type="month" value={dateTo ? dateTo.slice(0, 7) : ''}
              min={dateFrom ? dateFrom.slice(0, 7) : undefined}
              onChange={(e) => setToMonth(e.target.value)}
              className="h-7 text-xs" />
          </div>
        </div>
        <div className="flex items-center flex-wrap gap-1 pt-2 border-t border-border/40">
          <Button size="sm" variant="outline" className="h-5 text-[10px] px-1.5"
            onClick={() => preset('current')}>Текущий</Button>
          <Button size="sm" variant="outline" className="h-5 text-[10px] px-1.5"
            onClick={() => preset('last3')}>3 мес</Button>
          <Button size="sm" variant="outline" className="h-5 text-[10px] px-1.5"
            onClick={() => preset('last6')}>6 мес</Button>
          <Button size="sm" variant="outline" className="h-5 text-[10px] px-1.5"
            onClick={() => preset('last12')}>12 мес</Button>
          <Button size="sm" variant="outline" className="h-5 text-[10px] px-1.5"
            onClick={() => preset('year')}>Год</Button>
          <Button size="sm" variant="ghost" className="h-5 text-[10px] px-1.5 text-muted-foreground ml-auto"
            onClick={() => preset('none')}>Сбросить</Button>
        </div>
        {!hasRange && (
          <p className="text-[10px] text-muted-foreground/70">
            Без диапазона грузятся последние {channel.periodDays ?? 30} дн.
          </p>
        )}
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

  async function saveSelected(next: Array<{ code: number; systemId: number; name: string; locationId?: string }>) {
    next.sort((a, b) => a.systemId - b.systemId || a.code - b.code)
    const updated = await updateChannel(channel.id, {
      config: { ...channel.config, stations: next, stationCodes: undefined },
    })
    if (updated) onUpdate(updated)
  }

  // Группировка для preview-сводки
  const bySystem = useMemo(() => {
    const m = new Map<number, ChannelStation[]>()
    for (const s of channelStations) {
      if (!m.has(s.systemId)) m.set(s.systemId, [])
      m.get(s.systemId)!.push(s)
    }
    return Array.from(m.entries()).sort((a, b) => a[0] - b[0])
  }, [channelStations])

  return (
    <Card className="md:col-span-2 py-3 gap-2">
      <CardHeader className="pb-0">
        <CardTitle className="text-sm flex items-center gap-1.5">
          <MapPin className="h-3.5 w-3.5" />
          Станции
          <span className="text-xs text-muted-foreground font-normal ml-auto">
            {channelStations.length} из {universe.length}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-0 pb-3">
        {channelStations.length === 0 ? (
          <p className="text-xs text-muted-foreground py-1">
            Станции не выбраны.
          </p>
        ) : (
          <div className="max-h-44 overflow-y-auto pr-1 space-y-2">
            {bySystem.map(([sys, items]) => (
              <div key={sys}>
                <div className="sticky top-0 z-10 bg-card flex items-center gap-1.5 py-0.5 mb-0.5">
                  <span className="text-[10px] font-semibold text-muted-foreground/70 uppercase">
                    Система {sys}
                  </span>
                  <span className="text-[10px] text-muted-foreground/50 tabular-nums">· {items.length}</span>
                </div>
                <div className="grid grid-cols-2 xl:grid-cols-3 gap-x-3 gap-y-0">
                  {items.map((s) => (
                    <div key={`${s.systemId}-${s.code}`}
                      className="flex items-center gap-2 text-[11px] py-0.5 px-1 rounded hover:bg-accent/30 min-w-0">
                      <span className="font-mono text-muted-foreground w-7 shrink-0 text-right tabular-nums">{s.code}</span>
                      <span className="truncate">{s.name ?? ''}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}

        <div className="mt-2 pt-2 border-t border-border/40 flex items-center gap-2">
          <StationsSelectorDialog
            stsSourceId={stsSource?.id}
            selected={channelStations.map((s) => ({ code: s.code, systemId: s.systemId }))}
            onSave={(next) => saveSelected(next.map((o) => ({
              code: o.code, systemId: o.systemId,
              name: o.name, locationId: o.locationId,
            })))}
            trigger={
              <Button variant="outline" size="sm" className="h-7 text-xs gap-1.5 flex-1">
                <Search className="h-3.5 w-3.5" />
                {channelStations.length === 0 ? 'Выбрать станции' : 'Изменить выбор'}
              </Button>
            }
          />
          {channelStations.length > 0 && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 text-xs px-2 text-muted-foreground"
              onClick={() => saveSelected([])}
            >
              Очистить
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  )
}


// ─── Карточка ручной таблицы (источник manual_table): загрузка + обработка ──

function ManualTableCard({ channel }: { channel: Channel }) {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const fileId = (channel.config ?? {}).uploadFileId as string | undefined

  async function uploadAndRun() {
    if (!file && !fileId) { toast.error('Выберите файл таблицы (xlsx)'); return }
    setBusy(true)
    try {
      if (file) {
        const r = await uploadTableFile(companyId, file)
        await updateChannel(channel.id, { config: { ...channel.config, uploadFileId: r.source_id } })
        toast.success('Таблица загружена (L1)')
      }
      const res: any = await runChannel(channel.id)
      if (res?.status === 'success') {
        toast.success(
          `Обработано: строк ${res.shifts ?? res.rows ?? 0} · контрагентов +${res.counterparties ?? 0} · ` +
          `договоров +${res.contracts ?? 0} · платёжных записей ${res.settlements ?? 0}` +
          (res.unmatched ? ` · не сопоставлено ${res.unmatched}` : ''),
        )
      } else {
        toast.warning(res?.message || 'Обработка без изменений')
      }
      qc.invalidateQueries({ queryKey: ['axis'] })
      setFile(null)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card className="md:col-span-3 py-3 gap-2 border-l-2 border-l-primary">
      <CardHeader className="pb-0">
        <CardTitle className="text-sm flex items-center gap-1.5">
          <Upload className="h-3.5 w-3.5 text-primary" />
          Загрузка таблицы и обработка
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-0 pb-3 space-y-2">
        <p className="text-xs text-muted-foreground">
          Файл реестра (xlsx) → загрузка как сырьё (L1) → нормализация → нормализованная БД (L2)
          и разрезы «Поставщики э/э» / «Аренда».
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <Input type="file" accept=".xlsx,.xls"
            className="h-8 max-w-xs text-xs"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          <Button size="sm" className="h-8 gap-1.5" disabled={busy || (!file && !fileId)} onClick={uploadAndRun}>
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
            {file ? 'Загрузить и обработать' : 'Запустить обработку'}
          </Button>
          {fileId && !file && (
            <span className="text-[10px] text-muted-foreground">файл загружен ранее · {String(fileId).slice(0, 8)}…</span>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

// ─── Вкладка: Обзор ────────────────────────────────────────

function OverviewTab({ channel, onSync, onUpdate }: { channel: Channel; onSync: () => void; onUpdate: (ch: Channel) => void }) {
  const isManualTable = channel.templateId === 'reestr_contracts_payments'
  const sources = getSources()
  const channelSourceIds = getChannelSourceIds(channel)
  const channelSources = sources.filter((s) => channelSourceIds.includes(s.id))
  const status = STATUS_MAP[channel.status] ?? STATUS_MAP.draft
  const docs = getAllLoadedDocs().filter((d) => d.channelId === channel.id)

  // Список станций канала используется только для disabled-state кнопки.
  // Все CRUD-операции теперь внутри StationsCard.
  const stations = getChannelStations(channel)

  // shadcn Card по умолчанию имеет py-6 gap-6 — это съедает вертикаль.
  // Переопределяем на компактный режим для всех карточек Обзора.
  // (tailwind-merge правильно подменяет py-6→py-3, gap-6→gap-2.)
  const compactCard = "py-3 gap-2"

  // Цветовой акцент карточки Статус по состоянию. Используем border-l как
  // тонкий «маркер слева» — идиома из Stripe/Linear/Vercel: даёт читаемую
  // визуальную иерархию без агрессивных заливок.
  const statusBorder =
    channel.status === 'active' ? 'border-l-emerald-500' :
    channel.status === 'error' ? 'border-l-destructive' :
    channel.status === 'paused' ? 'border-l-muted-foreground' :
    'border-l-amber-500'
  const statusBadgeBg =
    channel.status === 'active' ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20' :
    channel.status === 'error' ? 'bg-destructive/10 text-destructive border-destructive/20' :
    channel.status === 'paused' ? 'bg-muted text-muted-foreground border-border' :
    'bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20'

  return (
    <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
      {/* Ручная таблица: загрузка файла + запуск обработки (manual_table) */}
      {isManualTable && <ManualTableCard channel={channel} />}

      {/* Row 1: meta — Статус, Источники, Расписание */}
      <Card className={`${compactCard} border-l-2 ${statusBorder}`}>
        <CardHeader className="pb-0">
          <CardTitle className="text-sm flex items-center gap-2">
            Статус
            <Badge
              variant="outline"
              className={`ml-auto h-5 px-1.5 text-[10px] font-medium ${statusBadgeBg}`}
            >
              {status.label}
            </Badge>
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-0 pb-3 space-y-2.5">
          <Button size="sm" className="w-full gap-1.5 font-medium" onClick={onSync}
            disabled={stations.length === 0 || channelSources.length === 0}>
            <Play className="h-3.5 w-3.5" />
            Запустить pipeline
          </Button>
          {channel.lastSync ? (
            <p className="text-[10px] text-muted-foreground">
              Последний прогон —{' '}
              <span className="text-foreground/70 font-medium">
                {format(new Date(channel.lastSync), 'dd.MM.yyyy HH:mm')}
              </span>
            </p>
          ) : (
            <p className="text-[10px] text-muted-foreground">Pipeline ещё не запускался</p>
          )}
          {stations.length === 0 && (
            <p className="text-[10px] text-amber-500">Укажите хотя бы одну станцию</p>
          )}
        </CardContent>
      </Card>

      {/* Источники */}
      <Card className={compactCard}>
        <CardHeader className="pb-0">
          <CardTitle className="text-sm flex items-center gap-1.5">
            <Database className="h-3.5 w-3.5 text-muted-foreground" />
            Источники
            <span className="text-xs text-muted-foreground font-normal ml-auto tabular-nums">
              {channelSources.length}
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-0 pb-3">
          <div className="space-y-1">
            {channelSources.map((src) => (
              <div key={src.id} className="flex items-center gap-2 text-xs">
                <span className="font-medium truncate">{src.name}</span>
                <Badge variant="outline" className="text-[9px] h-4 ml-auto shrink-0 uppercase tracking-wide">
                  {src.type}
                </Badge>
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

      {/* Row 2: конфигурация — Станции (2) + Период (1) */}
      <StationsCard channel={channel} onUpdate={onUpdate} />
      <PeriodCard channel={channel} onUpdate={onUpdate} />

      {/* Row 3: результат — Загружено (1) + Pipeline (2) */}
      <Card className={compactCard}>
        <CardHeader className="pb-0">
          <CardTitle className="text-sm flex items-center gap-1.5">
            <FileText className="h-3.5 w-3.5 text-muted-foreground" />
            Загружено
            <span className="text-xs text-muted-foreground font-normal ml-auto tabular-nums">
              {docs.length}
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-0 pb-3">
          <div className="space-y-1">
            {channel.streams.filter((s) => s.enabled).map((s) => {
              const count = docs.filter((d) => d.streamId === s.id).length
              return (
                <div key={s.id} className="flex items-center justify-between text-xs gap-2">
                  <span className="truncate">{s.name}</span>
                  <Badge variant="secondary" className="text-[10px] shrink-0 tabular-nums">
                    {count}
                  </Badge>
                </div>
              )
            })}
          </div>
        </CardContent>
      </Card>

      {/* Pipeline — визуальный путь обработки */}
      <Card className={`${compactCard} md:col-span-2`}>
        <CardHeader className="pb-0">
          <CardTitle className="text-sm flex items-center gap-1.5">
            <Settings2 className="h-3.5 w-3.5 text-muted-foreground" />
            Pipeline
            <span className="text-xs text-muted-foreground font-normal ml-auto">
              {channel.stages.filter((s) => s.enabled).length} активных
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-0 pb-3">
          <div className="flex items-center flex-wrap gap-y-2">
            {channel.stages.sort((a, b) => a.order - b.order).map((stage, i) => {
              const meta = STAGE_TYPE_META[stage.type]
              const active = stage.enabled
              return (
                <div key={stage.id} className="flex items-center">
                  {i > 0 && (
                    <span className="mx-2 text-muted-foreground/40 select-none">→</span>
                  )}
                  <div className={`px-3 py-1 rounded-full border text-[11px] font-medium transition-colors ${
                    active
                      ? 'border-primary/30 bg-primary/5 text-foreground'
                      : 'border-border/40 bg-muted/40 text-muted-foreground line-through'
                  }`}>
                    {meta.label}
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

  async function handleAdd() {
    if (!addingSourceId) return
    const updated = await addSourceToChannel(channel.id, addingSourceId)
    if (updated) {
      onUpdate(updated)
      setAddingSourceId('')
      toast.success('Источник добавлен в канал')
    }
  }

  async function handleRemove(sourceId: string) {
    const updated = await removeSourceFromChannel(channel.id, sourceId)
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
                              onCheckedChange={async (checked) => {
                                const updated = await updateChannel(channel.id, {
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

  async function toggleStage(stageId: string) {
    const updated = await updateChannel(channel.id, {
      stages: channel.stages.map((s) =>
        s.id === stageId ? { ...s, enabled: !s.enabled } : s
      ),
    })
    if (updated) onUpdate(updated)
  }

  async function removeStage(stageId: string) {
    const updated = await updateChannel(channel.id, {
      stages: channel.stages.filter((s) => s.id !== stageId),
    })
    if (updated) onUpdate(updated)
  }

  return (
    <div className="space-y-6">
      {/* Этапы pipeline */}
      <div className="space-y-3">
        <div>
          <h3 className="text-sm font-semibold">Этапы конвейера</h3>
          <p className="text-xs text-muted-foreground">
            Данные проходят через pipeline слева направо
          </p>
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

      {/* Параметры обработки — специфика конкретной обработки */}
      <ProcessingParametersCard channel={channel} onUpdate={onUpdate} />
    </div>
  )
}


/**
 * Параметры обработки — специфичные настройки конкретной загрузки.
 *
 * Общие параметры применимы к любому каналу. Доп. параметры по типу
 * первого активного потока (например, для shift_report — глубина деталей,
 * для receipt — режим парсинга масс).
 */
function ProcessingParametersCard({
  channel, onUpdate,
}: {
  channel: Channel
  onUpdate: (ch: Channel) => void
}) {
  // Определяем профиль обработки по активному потоку (для контекстных опций)
  const primaryDocType = channel.streams?.find((s) => s.enabled)?.docTypeId
  const cfg = channel.config ?? {}

  async function update(patch: Record<string, any>) {
    const updated = await updateChannel(channel.id, {
      config: { ...channel.config, ...patch },
    })
    if (updated) onUpdate(updated)
  }

  async function updatePolicy(value: DuplicatePolicy) {
    const updated = await updateChannel(channel.id, { duplicatePolicy: value })
    if (updated) onUpdate(updated)
  }

  return (
    <div className="space-y-3">
      <div>
        <h3 className="text-sm font-semibold">Параметры канала</h3>
        <p className="text-xs text-muted-foreground">
          Специфичные для этой загрузки. Применяются на этапах нормализации
          и сохранения.
        </p>
      </div>

      <Card>
        <CardContent className="py-4 space-y-4">
          {/* Дедупликация */}
          <div className="grid sm:grid-cols-3 gap-3 items-start">
            <div>
              <Label className="text-xs font-medium">Политика дубликатов</Label>
              <p className="text-[10px] text-muted-foreground mt-0.5 leading-tight">
                Что делать с документом, который уже загружен (по fingerprint)
              </p>
            </div>
            <div className="sm:col-span-2">
              <Select
                value={channel.duplicatePolicy ?? 'skip'}
                onValueChange={(v) => updatePolicy(v as DuplicatePolicy)}
              >
                <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="skip" className="text-xs">Пропустить (не загружать повторно)</SelectItem>
                  <SelectItem value="warn" className="text-xs">Предупредить (показать в логе)</SelectItem>
                  <SelectItem value="overwrite" className="text-xs">Перезаписать (обновить данные)</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="border-t border-border/40" />

          {/* Лимит документов за один запуск */}
          <div className="grid sm:grid-cols-3 gap-3 items-start">
            <div>
              <Label className="text-xs font-medium">Лимит за запуск</Label>
              <p className="text-[10px] text-muted-foreground mt-0.5 leading-tight">
                Макс. документов за один прогон. 0 = без ограничения.
              </p>
            </div>
            <div className="sm:col-span-2">
              <Input
                type="number"
                min="0"
                value={cfg.runLimit ?? 0}
                onChange={(e) => update({ runLimit: Number(e.target.value) || 0 })}
                className="h-8 text-xs sm:max-w-[160px]"
              />
            </div>
          </div>

          {/* Параметры специфики типа документа */}
          {primaryDocType === 'shift_report' && (
            <>
              <div className="border-t border-border/40" />
              <div className="space-y-3">
                <div className="text-[11px] font-semibold text-muted-foreground/80 uppercase tracking-wide">
                  Сменные отчёты
                </div>
                <label className="flex items-center gap-2 text-xs cursor-pointer">
                  <Checkbox
                    checked={cfg.includeReceipts ?? true}
                    onCheckedChange={(v) => update({ includeReceipts: !!v })}
                    className="h-3.5 w-3.5"
                  />
                  <span>Извлекать ТТН из сменных отчётов</span>
                </label>
                <label className="flex items-center gap-2 text-xs cursor-pointer">
                  <Checkbox
                    checked={cfg.includePayments ?? true}
                    onCheckedChange={(v) => update({ includePayments: !!v })}
                    className="h-3.5 w-3.5"
                  />
                  <span>Сохранять разбивку оплат (наличные / карты / талоны)</span>
                </label>
                <label className="flex items-center gap-2 text-xs cursor-pointer">
                  <Checkbox
                    checked={cfg.includeTanks ?? true}
                    onCheckedChange={(v) => update({ includeTanks: !!v })}
                    className="h-3.5 w-3.5"
                  />
                  <span>Сохранять остатки резервуаров</span>
                </label>
              </div>
            </>
          )}

          {primaryDocType === 'receipt' && (
            <>
              <div className="border-t border-border/40" />
              <div className="space-y-3">
                <div className="text-[11px] font-semibold text-muted-foreground/80 uppercase tracking-wide">
                  Поступления (ТТН)
                </div>
                <label className="flex items-center gap-2 text-xs cursor-pointer">
                  <Checkbox
                    checked={cfg.recomputeDensity ?? false}
                    onCheckedChange={(v) => update({ recomputeDensity: !!v })}
                    className="h-3.5 w-3.5"
                  />
                  <span>Пересчитывать плотность по факту (объём ↔ масса)</span>
                </label>
                <label className="flex items-center gap-2 text-xs cursor-pointer">
                  <Checkbox
                    checked={cfg.warnDiff ?? true}
                    onCheckedChange={(v) => update({ warnDiff: !!v })}
                    className="h-3.5 w-3.5"
                  />
                  <span>Помечать расхождения «факт vs документ» в логе</span>
                </label>
              </div>
            </>
          )}

          {!primaryDocType && (
            <div className="text-[11px] text-muted-foreground italic">
              Дополнительные параметры появятся после подключения первого
              источника к каналу.
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

// ─── Вкладка: Маппинг ───────────────────────────────────────
// Предобработка канала: внешние ключи источника → справочники 1С.
// Уровень канала (override) перекрывает дефолт компании. Резолв:
// канал → компания (NULL) → канон-сид. Окончательная сверка — на разрезах.

const MAPPING_KIND_META: Record<MappingKind, { label: string; hint: string; ph: string }> = {
  station: { label: 'АЗС', hint: 'код станции источника → Склад/АЗС 1С', ph: 'station_id (напр. 208)' },
  fuel: { label: 'Нефтепродукты', hint: 'код нефтепродукта STS → Номенклатура 1С', ph: 'fuel_type (напр. ДТ)' },
  paytype: { label: 'Каналы оплаты', hint: 'канал оплаты STS → вид оплаты 1С', ph: 'pay_type (напр. card)' },
  nomenclature: { label: 'Номенклатура', hint: 'артикул/код товара → Номенклатура 1С', ph: 'артикул поставщика' },
  counterparty: { label: 'Контрагенты', hint: 'ИНН/название → Контрагент 1С', ph: 'ИНН / название' },
}

// Какие виды маппинга относятся к каналу (по его шаблону)
const KINDS_BY_TEMPLATE: Record<string, MappingKind[]> = {
  // Топливо-продажи: маппинг по нефтепродуктам и каналам оплаты
  // (АЗС-станции — это точки обслуживания, привязаны отдельно, не маппинг).
  fuel_shift: ['fuel', 'paytype'],
  fuel_delivery: ['fuel', 'counterparty'],
  sidegoods: ['nomenclature', 'counterparty'],
  food: ['nomenclature', 'counterparty'],
}
function channelMappingKinds(channel: Channel): MappingKind[] {
  return KINDS_BY_TEMPLATE[channel.templateId ?? ''] ?? ['station', 'fuel', 'paytype', 'nomenclature', 'counterparty']
}

interface EffectiveRow {
  sourceKey: string
  targetRef: string
  targetName: string
  confidence: number
  level: 'channel' | 'company'
  channelMappingId?: string
}

function buildEffective(all: ReconcileMapping[], channelId: string): EffectiveRow[] {
  const byKey = new Map<string, EffectiveRow>()
  for (const m of all) {
    if (m.channel_id == null) {
      byKey.set(m.source_key, {
        sourceKey: m.source_key, targetRef: m.target_ref,
        targetName: m.target_name || m.target_ref, confidence: m.confidence, level: 'company',
      })
    }
  }
  for (const m of all) {
    if (m.channel_id === channelId) {
      byKey.set(m.source_key, {
        sourceKey: m.source_key, targetRef: m.target_ref,
        targetName: m.target_name || m.target_ref, confidence: m.confidence,
        level: 'channel', channelMappingId: m.id,
      })
    }
  }
  return [...byKey.values()].sort((a, b) => a.sourceKey.localeCompare(b.sourceKey))
}

function MappingTab({ channel, companyId }: { channel: Channel; companyId: string }) {
  const kinds = useMemo(() => channelMappingKinds(channel), [channel])
  const [kind, setKind] = useState<MappingKind>(kinds[0])
  const [all, setAll] = useState<ReconcileMapping[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [srcKey, setSrcKey] = useState('')
  const [tgtRef, setTgtRef] = useState('')
  const [tgtName, setTgtName] = useState('')

  async function reload() {
    setLoading(true); setError(null)
    try {
      setAll(await listMappings(companyId, kind))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { void reload() /* eslint-disable-next-line */ }, [kind, channel.id, companyId])

  const rows = useMemo(() => buildEffective(all, channel.id), [all, channel.id])

  async function add() {
    if (!srcKey.trim() || !tgtRef.trim()) return
    try {
      await createMapping({
        companyId, channelId: channel.id, kind,
        sourceKey: srcKey.trim(), targetRef: tgtRef.trim(),
        targetName: tgtName.trim() || undefined, method: 'manual',
      })
      setSrcKey(''); setTgtRef(''); setTgtName('')
      toast.success('Соответствие уровня канала добавлено')
      void reload()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }

  async function removeOverride(id: string) {
    if (!confirm('Удалить соответствие уровня канала? Останется дефолт компании, если он есть.')) return
    try {
      await deleteMapping(id)
      toast.success('Соответствие канала удалено')
      void reload()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }

  const meta = MAPPING_KIND_META[kind]

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-sm font-semibold">Маппинг канала</h3>
        <p className="text-xs text-muted-foreground">
          Предобработка: внешние ключи источника → справочники 1С. Соответствие уровня канала
          перекрывает дефолт компании.{' '}
          <Link to="/1c/mappings" className="text-primary hover:underline">Общие маппинги компании →</Link>
        </p>
      </div>

      {/* Виды маппинга канала */}
      <div className="flex flex-wrap gap-1">
        {kinds.map((k) => (
          <button
            key={k}
            onClick={() => setKind(k)}
            className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
              kind === k ? 'bg-primary/10 text-primary' : 'text-muted-foreground hover:bg-accent'
            }`}
          >
            {MAPPING_KIND_META[k].label}
          </button>
        ))}
      </div>

      <Card>
        <CardContent className="py-4 space-y-3">
          <p className="text-[11px] text-muted-foreground">{meta.hint}</p>

          {/* Форма добавления (уровень канала) */}
          <div className="flex flex-wrap items-end gap-2">
            <div className="space-y-1">
              <Label className="text-[10px] text-muted-foreground">Ключ источника</Label>
              <Input value={srcKey} onChange={(e) => setSrcKey(e.target.value)}
                placeholder={meta.ph} className="h-8 text-xs w-44" />
            </div>
            <div className="space-y-1">
              <Label className="text-[10px] text-muted-foreground">Ref 1С (GUID)</Label>
              <Input value={tgtRef} onChange={(e) => setTgtRef(e.target.value)}
                placeholder="GUID в БП" className="h-8 text-xs w-44 font-mono" />
            </div>
            <div className="space-y-1">
              <Label className="text-[10px] text-muted-foreground">Название (для UI)</Label>
              <Input value={tgtName} onChange={(e) => setTgtName(e.target.value)}
                placeholder="напр. ДТ Евро" className="h-8 text-xs w-44" />
            </div>
            <Button size="sm" className="h-8 text-xs gap-1" onClick={add} disabled={!srcKey.trim() || !tgtRef.trim()}>
              <Plus className="h-3 w-3" /> Добавить
            </Button>
          </div>

          <div className="border-t border-border/40" />

          {/* Таблица соответствий */}
          {loading ? (
            <p className="py-4 text-xs text-muted-foreground">Загрузка…</p>
          ) : error ? (
            <p className="py-4 text-xs text-destructive">Не удалось загрузить маппинги: {error}</p>
          ) : rows.length === 0 ? (
            <p className="py-4 text-xs text-muted-foreground">
              Соответствий по виду «{meta.label}» пока нет — добавьте выше.
            </p>
          ) : (
            <div className="space-y-1">
              <div className="grid grid-cols-[1fr_auto_2fr_auto_auto] gap-2 px-2 text-[10px] uppercase tracking-wide text-muted-foreground/60">
                <span>Ключ источника</span><span /><span>Запись 1С</span><span>Уровень</span><span />
              </div>
              {rows.map((r) => (
                <div key={r.sourceKey}
                  className="grid grid-cols-[1fr_auto_2fr_auto_auto] items-center gap-2 rounded-md px-2 py-1.5 text-xs hover:bg-accent/30">
                  <code className="font-mono text-[11px] truncate">{r.sourceKey}</code>
                  <ArrowRightLeft className="h-3 w-3 text-muted-foreground/40" />
                  <span className="truncate" title={r.targetRef}>{r.targetName}</span>
                  {r.level === 'channel' ? (
                    <Badge variant="default" className="h-4 px-1.5 text-[9px]">канал</Badge>
                  ) : (
                    <Badge variant="outline" className="h-4 px-1.5 text-[9px] border-zinc-600 text-zinc-400">компания</Badge>
                  )}
                  {r.level === 'channel' && r.channelMappingId ? (
                    <Button variant="ghost" size="icon" className="h-6 w-6 text-muted-foreground hover:text-destructive"
                      onClick={() => removeOverride(r.channelMappingId!)} title="Удалить override канала">
                      <Trash2 className="h-3 w-3" />
                    </Button>
                  ) : (
                    <Button variant="ghost" size="sm" className="h-6 px-1.5 text-[10px]"
                      onClick={() => { setSrcKey(r.sourceKey); setTgtRef(r.targetRef); setTgtName(r.targetName) }}
                      title="Переопределить для этого канала">
                      override
                    </Button>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

// ─── Вкладка: Данные ────────────────────────────────────────

type SortKey = 'date_desc' | 'date_asc' | 'station' | 'shift_no'

const DOC_TYPE_LABELS: Record<string, string> = {
  shift_report: 'Сменные отчёты',
  receipt: 'ТТН',
  delivery: 'ТТН',
  price: 'Цены',
  sts_transactions: 'Операции отпуска',
  sts_coupons: 'Купоны и талоны',
  sts_tanks: 'Остатки резервуаров',
}

function docTypeLabel(type: string): string {
  return DOC_TYPE_LABELS[type] ?? type
}

/** Извлечь номер смены из title вида «Смена №1847 — АКАЗС №5». */
function parseShiftNo(title: string): number | null {
  const m = title.match(/№\s*(\d+)/)
  return m ? Number(m[1]) : null
}


function DataTab({ channel }: { channel: Channel }) {
  const allDocs = getAllLoadedDocs().filter((d) => d.channelId === channel.id)

  // Глобальные фильтры из шапки (Компания/Точки/Типы документов).
  // Применяются ПОВЕРХ локальных фильтров вкладки (AND-логика):
  // если в шапке выбраны точки A,B,C — даже при «Все станции» локально
  // мы видим только их.
  const { locationIds: globalLocIds, docTypeIds: globalDocTypes } = useFilters()

  // Перевод выбранных точек обслуживания (ID) в коды станций для матча
  // с doc.stationId. Если ничего не выбрано — null (фильтр выключен).
  const globalStationCodes = useMemo<Set<number> | null>(() => {
    if (globalLocIds.length === 0) return null
    const set = new Set<number>()
    const locsById = new Map(getLocations().map((l) => [l.id, l]))
    for (const id of globalLocIds) {
      const loc = locsById.get(id)
      const code = Number(loc?.code)
      if (Number.isFinite(code) && code > 0) set.add(code)
    }
    return set.size > 0 ? set : null
  }, [globalLocIds])

  const globalDocTypeSet = useMemo<Set<string> | null>(() => {
    return globalDocTypes.length > 0 ? new Set(globalDocTypes) : null
  }, [globalDocTypes])

  // Состояние фильтров (локально для вкладки)
  const [query, setQuery] = useState('')
  const [stationFilter, setStationFilter] = useState<number[]>([])
  const [monthFilter, setMonthFilter] = useState<string>('all')
  const [sortKey, setSortKey] = useState<SortKey>('date_desc')

  // Доступные значения для локальных фильтров — только из документов,
  // прошедших глобальный фильтр (иначе в селекте «Станция 208» при
  // глобально выбранной АЗС 5 — пустота).
  const docsForLocalFilters = useMemo(() => {
    if (!globalStationCodes && !globalDocTypeSet) return allDocs
    return allDocs.filter((d) =>
      (!globalStationCodes || globalStationCodes.has(d.stationId)) &&
      (!globalDocTypeSet || globalDocTypeSet.has(d.docType)),
    )
  }, [allDocs, globalStationCodes, globalDocTypeSet])

  const allStations = useMemo(() => {
    const set = new Set<number>()
    for (const d of docsForLocalFilters) if (d.stationId) set.add(d.stationId)
    return Array.from(set).sort((a, b) => a - b)
  }, [docsForLocalFilters])

  const allMonths = useMemo(() => {
    const set = new Set<string>()
    for (const d of docsForLocalFilters) {
      const dt = new Date(d.date)
      if (!isNaN(dt.getTime())) {
        set.add(`${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}`)
      }
    }
    return Array.from(set).sort().reverse()
  }, [docsForLocalFilters])

  // Применить фильтры + сортировку (global AND local)
  const filteredDocs = useMemo(() => {
    const q = query.trim().toLowerCase()
    const stationSet = stationFilter.length > 0 ? new Set(stationFilter) : null

    let out = allDocs.filter((d) => {
      // Глобальные фильтры (из шапки)
      if (globalStationCodes && !globalStationCodes.has(d.stationId)) return false
      if (globalDocTypeSet && !globalDocTypeSet.has(d.docType)) return false
      // Локальные фильтры (вкладки)
      if (q && !d.title.toLowerCase().includes(q)) return false
      if (stationSet && !stationSet.has(d.stationId)) return false
      if (monthFilter !== 'all') {
        const dt = new Date(d.date)
        if (isNaN(dt.getTime())) return false
        const key = `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}`
        if (key !== monthFilter) return false
      }
      return true
    })

    out = [...out].sort((a, b) => {
      switch (sortKey) {
        case 'date_asc':
          return new Date(a.date).getTime() - new Date(b.date).getTime()
        case 'station':
          return (a.stationId - b.stationId) ||
            (new Date(b.date).getTime() - new Date(a.date).getTime())
        case 'shift_no': {
          const an = parseShiftNo(a.title) ?? 0
          const bn = parseShiftNo(b.title) ?? 0
          return bn - an
        }
        case 'date_desc':
        default:
          return new Date(b.date).getTime() - new Date(a.date).getTime()
      }
    })
    return out
  }, [allDocs, query, stationFilter, monthFilter, sortKey, globalStationCodes, globalDocTypeSet])

  // Группировка после фильтра — по типу документа
  const grouped = useMemo(() => {
    const map = new Map<string, typeof filteredDocs>()
    for (const doc of filteredDocs) {
      const key = doc.docType
      if (!map.has(key)) map.set(key, [])
      map.get(key)!.push(doc)
    }
    return map
  }, [filteredDocs])

  function clearFilters() {
    setQuery('')
    setStationFilter([])
    setMonthFilter('all')
  }

  const hasFilters = !!query || stationFilter.length > 0 || monthFilter !== 'all'

  if (allDocs.length === 0) {
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
      {/* Toolbar: поиск + фильтры + сортировка */}
      <Card>
        <CardContent className="py-3 flex flex-wrap items-center gap-2">
          {/* Поиск */}
          <div className="relative flex-1 min-w-[200px]">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Поиск по названию…"
              className="h-8 pl-7 text-xs"
            />
          </div>

          {/* Фильтр станций */}
          <Select
            value={stationFilter.length === 0 ? 'all' : stationFilter.length === 1 ? String(stationFilter[0]) : 'multi'}
            onValueChange={(v) => setStationFilter(v === 'all' ? [] : [Number(v)])}
          >
            <SelectTrigger className="h-8 text-xs w-[150px]">
              <SelectValue placeholder="Все станции" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all" className="text-xs">Все станции</SelectItem>
              {allStations.map((sid) => (
                <SelectItem key={sid} value={String(sid)} className="text-xs">
                  Станция {sid}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          {/* Фильтр месяца */}
          <Select value={monthFilter} onValueChange={setMonthFilter}>
            <SelectTrigger className="h-8 text-xs w-[160px]">
              <SelectValue placeholder="Все периоды" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all" className="text-xs">Все периоды</SelectItem>
              {allMonths.map((m) => {
                const [y, mm] = m.split('-').map(Number)
                const label = `${MONTH_NAMES_RU[(mm ?? 1) - 1]} ${y}`
                return (
                  <SelectItem key={m} value={m} className="text-xs">{label}</SelectItem>
                )
              })}
            </SelectContent>
          </Select>

          {/* Сортировка */}
          <Select value={sortKey} onValueChange={(v) => setSortKey(v as SortKey)}>
            <SelectTrigger className="h-8 text-xs w-[180px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="date_desc" className="text-xs">Дата ↓ (новые сверху)</SelectItem>
              <SelectItem value="date_asc" className="text-xs">Дата ↑ (старые сверху)</SelectItem>
              <SelectItem value="station" className="text-xs">По станции</SelectItem>
              <SelectItem value="shift_no" className="text-xs">По номеру смены ↓</SelectItem>
            </SelectContent>
          </Select>

          {hasFilters && (
            <Button variant="ghost" size="sm" className="h-8 text-xs gap-1 text-muted-foreground"
              onClick={clearFilters}>
              <Trash2 className="h-3 w-3" />
              Сброс
            </Button>
          )}
        </CardContent>
      </Card>

      <div className="flex items-center justify-between gap-2 flex-wrap">
        <p className="text-sm text-muted-foreground">
          {hasFilters || globalStationCodes || globalDocTypeSet
            ? `Показано ${filteredDocs.length} из ${allDocs.length}`
            : `Загружено ${allDocs.length} документов`}
        </p>
        {(globalStationCodes || globalDocTypeSet) && (
          <div className="flex items-center gap-1 text-[10px] text-muted-foreground">
            <Filter className="h-3 w-3" />
            <span>Действует глобальный фильтр</span>
            {globalStationCodes && (
              <Badge variant="outline" className="text-[9px] h-4 px-1">
                точек {globalStationCodes.size}
              </Badge>
            )}
            {globalDocTypeSet && (
              <Badge variant="outline" className="text-[9px] h-4 px-1">
                типов {globalDocTypeSet.size}
              </Badge>
            )}
          </div>
        )}
      </div>

      {filteredDocs.length === 0 ? (
        <Card>
          <CardContent className="py-8 text-center text-xs text-muted-foreground">
            По текущим фильтрам ничего не найдено.
          </CardContent>
        </Card>
      ) : (
        Array.from(grouped.entries()).map(([type, items]) => (
          <DocumentsTable key={type} type={type} items={items} />
        ))
      )}
    </div>
  )
}

/**
 * Таблица загруженных документов одного типа.
 *
 * Раньше каждая строка была сжатой однострочной с мелким бейджем
 * станции — нечитаемо. Сейчас полноценная таблица со столбцами:
 * Документ · Станция (название + код) · Дата документа · Загружено
 * · Размер (литры или нет данных). Имя станции подтягивается из
 * справочника по коду — если не найдено, показываем «Станция N».
 */
function DocumentsTable({ type, items }: { type: string; items: ReturnType<typeof getAllLoadedDocs> }) {
  // Кэш имён станций по коду
  const stationName = useMemo(() => {
    const map = new Map<number, string>()
    for (const loc of getLocations()) {
      if (loc.type !== 'fuel_station') continue
      const code = Number(loc.code)
      if (Number.isFinite(code) && !map.has(code)) {
        map.set(code, loc.name)
      }
    }
    return (id: number) => map.get(id) ?? `Станция ${id}`
  }, [])

  function docSize(doc: ReturnType<typeof getAllLoadedDocs>[number]): string | null {
    // Литры топлива из data — для ТТН и аналогов
    const d = doc.data as any
    if (typeof d?.totalLiters === 'number') return `${d.totalLiters.toFixed(0)} л`
    if (typeof d?.fact?.volume === 'number') return `${Number(d.fact.volume).toFixed(0)} л`
    // Размер JSON как фолбэк
    try {
      const bytes = JSON.stringify(doc.data).length
      if (bytes < 1024) return `${bytes} Б`
      if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} КБ`
      return `${(bytes / 1024 / 1024).toFixed(1)} МБ`
    } catch {
      return null
    }
  }

  const visible = items.slice(0, 200)

  return (
    <Card className="py-3 gap-2">
      <CardHeader className="pb-0">
        <CardTitle className="text-sm flex items-center gap-1.5">
          <FileText className="h-3.5 w-3.5 text-muted-foreground" />
          {docTypeLabel(type)}
          <span className="text-xs text-muted-foreground font-normal ml-auto tabular-nums">
            {items.length} документов
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-0 pb-3">
        {/* Заголовок таблицы */}
        <div className="grid grid-cols-[1fr_220px_110px_140px_90px] gap-3 px-2 py-1.5 text-[10px] font-semibold text-muted-foreground/70 uppercase tracking-wide border-b border-border/40">
          <span>Документ</span>
          <span>Станция</span>
          <span>Дата</span>
          <span>Загружено</span>
          <span className="text-right">Размер</span>
        </div>

        {/* Строки */}
        <div className="max-h-[440px] overflow-y-auto -mx-2 px-2">
          {visible.map((doc) => {
            const size = docSize(doc)
            return (
              <div key={doc.id}
                className="grid grid-cols-[1fr_220px_110px_140px_90px] gap-3 items-center px-2 py-2 text-xs border-b border-border/30 hover:bg-accent/30 transition-colors last:border-b-0">
                <div className="flex items-center gap-2 min-w-0">
                  <FileText className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                  <span className="font-medium truncate">{doc.title}</span>
                </div>
                <div className="min-w-0">
                  <span className="truncate block">{stationName(doc.stationId)}</span>
                  <span className="text-[10px] text-muted-foreground font-mono">
                    код {doc.stationId}
                  </span>
                </div>
                <span className="text-muted-foreground tabular-nums">
                  {format(new Date(doc.date), 'dd.MM.yyyy')}
                </span>
                <span className="text-muted-foreground tabular-nums text-[11px]">
                  {format(new Date(doc.loadedAt), 'dd.MM.yyyy HH:mm')}
                </span>
                <span className="text-right tabular-nums text-muted-foreground">
                  {size ?? '—'}
                </span>
              </div>
            )
          })}
          {items.length > 200 && (
            <p className="text-xs text-muted-foreground py-2 text-center">
              … и ещё {items.length - 200}
            </p>
          )}
        </div>
      </CardContent>
    </Card>
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
  const { companyId } = useCompany()

  // API-режим: гидрация источников+каналов из бэкенда при монтировании
  useEffect(() => {
    void Promise.all([loadSources(companyId), loadChannels(companyId), loadLocations(companyId)])
      .then(() => { if (id) setChannel(getChannel(id)) })
      .catch(() => { /* офлайн → localStorage */ })
  }, [companyId, id])

  if (!channel) {
    return (
      <div className="flex flex-col items-center justify-center h-[60vh] gap-4">
        <XCircle className="h-10 w-10 text-muted-foreground/30" />
        <p className="text-lg text-muted-foreground">Канал не найден</p>
        <Link to="/channels" className="text-primary hover:underline text-sm">← К списку каналов</Link>
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
      if (isApiEnabled()) {
        // API-режим: прогон через бэкенд-оркестратор (fetch→normalize→save)
        const res = await runChannel(channel.id)
        refresh()
        if (Array.isArray(res?.by_station)) {
          const created = res.by_station.reduce((a: number, r: { created?: number }) => a + (r.created || 0), 0)
          const label = res.kind === 'fuel_delivery' ? 'Приём ТТН' : res.kind === 'fuel_shift' ? 'Смены' : 'Записи'
          toast.success(`${label}: загружено ${created}, станций ${res.stations_ok}/${res.stations_total}`)
        } else {
          toast.success(res?.message || 'Канал запущен (бэкенд)')
        }
        return
      }
      // localStorage-режим: клиентский pipeline
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
        {activeTab === 'mapping' && <MappingTab channel={channel} companyId={companyId} />}
        {activeTab === 'data' && <DataTab channel={channel} />}
        {activeTab === 'log' && <LogTab channel={channel} />}
      </div>
    </div>
  )
}

export default ChannelDetailPage
