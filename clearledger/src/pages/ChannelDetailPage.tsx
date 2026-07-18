/**
 * Страница канала — pipeline данных.
 * /channels/:id — вкладки: Обзор, Источники, Схема, Загружено, Лог.
 */

import { useState, useMemo, useEffect } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { BindingKeyBadge } from '@/components/onec/BindingKeyBadge'
import { AdvancedHint } from '@/components/common/AdvancedOnly'
import { useUiLevel } from '@/hooks/useUiLevel'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { Checkbox } from '@/components/ui/checkbox'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useQueryClient, useQuery } from '@tanstack/react-query'
import { getChannel, loadChannels, updateChannel, addSourceToChannel, removeSourceFromChannel, runChannel, getChannelRunStatus, getChannelRuns, type ChannelRun, type ChannelRunStatus } from '@/services/channelService'
import { uploadTableFile, getNomenclature, getWarehouses, getCounterparties } from '@/services/referenceService'
import { enrichChargeSessions, reenrichChargeSessions } from '@/services/chargeSessionsService'
import { getSources, loadSources } from '@/services/sourceService'
import { listMappings, createMapping, deleteMapping, type ReconcileMapping, type MappingKind } from '@/services/mappingService'
import { isApiEnabled } from '@/services/apiClient'
import { useCompany } from '@/contexts/CompanyContext'
import { getLocations, loadLocations } from '@/services/locationService'
import { useFilters } from '@/contexts/FilterContext'
import { syncChannel, getAllLoadedDocs, type LoadedDocument } from '@/services/channelSyncService'
import { getLoadedShifts, getLoadedReceipts, getShiftDocuments, getReceiptDocuments, deleteFuelPeriod, getLoadedStations, type LoadedShift, type LoadedReceipt, type FuelDocument } from '@/services/fuel/fuelMappingService'
import { ShiftDetailsDialog } from '@/components/fuel/ShiftDetailsDialog'
import { ReceiptsJournal } from '@/components/fuel/ReceiptsJournal'
import { extractDeliveries } from '@/services/receiptExtractService'
import { getChannelSourceIds, getChannelStations, STAGE_TYPE_META } from '@/types/channel'
import type { Channel, ChannelStation, DuplicatePolicy } from '@/types/channel'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from '@/components/ui/dialog'
import {
  DropdownMenu, DropdownMenuTrigger, DropdownMenuContent,
  DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList,
} from '@/components/ui/command'
import {
  ArrowLeft, Play, Loader2, Radio, Database, Download, Shuffle,
  GitCompare, ShieldCheck, ArrowRightLeft, Trash2, Plus, History,
  Settings2, FileText, AlertTriangle, CheckCircle2, XCircle, GripVertical, MapPin,
  Search, Filter, Upload, RotateCcw, ChevronsUpDown, Check, ChevronDown, Sparkles,
} from 'lucide-react'
import { toast } from 'sonner'
import { format } from 'date-fns'

type TabId = 'overview' | 'data' | 'mapping' | 'settings'

// Сверка — отдельный раздел продукта и идёт на уровне РАЗРЕЗОВ, не каналов.
// Канал отвечает за получение сырых данных из источника и их ПРЕДОБРАБОТКУ
// (маппинг внешних ключей на справочники 1С, нормализация) — до сверки.
const TABS: { id: TabId; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { id: 'overview', label: 'Обзор', icon: Radio },
  { id: 'data', label: 'Данные', icon: FileText },
  { id: 'mapping', label: 'Маппинг', icon: ArrowRightLeft },
  { id: 'settings', label: 'Настройки', icon: Settings2 },
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

// Расписание: авто-запуск по расписанию в бэкенде НЕ реализован — планировщика нет,
// единственный триггер прогона это ручной asyncio.create_task в channels_router.
// Поэтому карточка информационная (помечена «скоро»), без декоративного селектора,
// который сохранял бы интервал, но ничего бы не запускал.
function ScheduleCard() {
  return (
    <Card className="py-3 gap-2">
      <CardHeader className="pb-0">
        <CardTitle className="text-sm flex items-center gap-1.5">
          <History className="h-3.5 w-3.5" />
          Расписание
          <Badge variant="outline" className="ml-auto h-4 px-1.5 text-[9px] font-normal text-muted-foreground border-border">
            скоро
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-0 pb-3">
        <p className="text-[11px] text-muted-foreground leading-relaxed">
          Запуск вручную — кнопкой «Запустить». Авто-запуск по интервалу/расписанию
          в разработке.
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

const MONTH_SHORT_RU = [
  'янв', 'фев', 'мар', 'апр', 'май', 'июн',
  'июл', 'авг', 'сен', 'окт', 'ноя', 'дек',
]

/** Компактная подпись периода для кнопки запуска: «Май 2026», «апр–май 2026»,
 *  «дек 2025 – янв 2026». null, если диапазон не задан. */
function periodShortLabel(dateFrom?: string | null, dateTo?: string | null): string | null {
  if (!dateFrom || !dateTo) return null
  const [y1, m1] = dateFrom.slice(0, 7).split('-').map(Number)
  const [y2, m2] = dateTo.slice(0, 7).split('-').map(Number)
  if (!y1 || !m1 || !y2 || !m2) return null
  if (y1 === y2 && m1 === m2) return `${MONTH_NAMES_RU[m1 - 1]} ${y1}`
  if (y1 === y2) return `${MONTH_SHORT_RU[m1 - 1]}–${MONTH_SHORT_RU[m2 - 1]} ${y1}`
  return `${MONTH_SHORT_RU[m1 - 1]} ${y1} – ${MONTH_SHORT_RU[m2 - 1]} ${y2}`
}

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
      <CardContent className="pt-0 pb-3 space-y-2.5">
        <div className="flex flex-wrap gap-3">
          <div className="w-full sm:flex-1 sm:min-w-[180px]">
            <Label className="text-xs text-muted-foreground">С месяца</Label>
            <Input type="month" value={dateFrom ? dateFrom.slice(0, 7) : ''}
              max={dateTo ? dateTo.slice(0, 7) : undefined}
              onChange={(e) => setFromMonth(e.target.value)}
              className="mt-1 bg-di-surface-low dark:bg-di-surface-low border-di-outline-variant/20" />
          </div>
          <div className="w-full sm:flex-1 sm:min-w-[180px]">
            <Label className="text-xs text-muted-foreground">По месяц</Label>
            <Input type="month" value={dateTo ? dateTo.slice(0, 7) : ''}
              min={dateFrom ? dateFrom.slice(0, 7) : undefined}
              onChange={(e) => setToMonth(e.target.value)}
              className="mt-1 bg-di-surface-low dark:bg-di-surface-low border-di-outline-variant/20" />
          </div>
        </div>
        <div className="flex items-center flex-wrap gap-1.5 pt-2.5 border-t border-border/40">
          <span className="text-xs text-muted-foreground mr-1">Быстро:</span>
          <Button size="sm" variant="outline" className="h-7 text-xs px-2.5"
            onClick={() => preset('current')}>Текущий</Button>
          <Button size="sm" variant="outline" className="h-7 text-xs px-2.5"
            onClick={() => preset('last3')}>3 мес</Button>
          <Button size="sm" variant="outline" className="h-7 text-xs px-2.5"
            onClick={() => preset('last6')}>6 мес</Button>
          <Button size="sm" variant="outline" className="h-7 text-xs px-2.5"
            onClick={() => preset('last12')}>12 мес</Button>
          <Button size="sm" variant="outline" className="h-7 text-xs px-2.5"
            onClick={() => preset('year')}>Год</Button>
          <Button size="sm" variant="ghost" className="h-7 text-xs px-2.5 text-muted-foreground ml-auto"
            onClick={() => preset('none')}>Сбросить</Button>
        </div>
        {!hasRange && (
          <p className="text-[11px] text-muted-foreground/70">
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

/**
 * Карточка станций — ИНФОРМАЦИОННАЯ.
 *
 * Прогон канала охватывает ВСЮ сеть системы: оркестратор тянет станции из STS
 * `/v1/points` (см. channel_orchestrator._fuel_context), а config.stations
 * используется лишь как фолбэк при недоступности /v1/points. Поэтому здесь —
 * не селектор (он обещал бы scoping, которого нет), а сводка известных станций.
 * Точечный отбор для конкретной загрузки — в окне «Запустить» / «Управление».
 */
function StationsCard({ channel }: { channel: Channel }) {
  const stsSource = getSources().find((s) => s.type === 'rest')
  const channelStations = getChannelStations(channel)
  const universe = useMemo(
    () => collectStationUniverse(stsSource?.id, channelStations),
    [stsSource?.id, channel.id, channelStations.length],
  )

  // Группировка известных станций по системе
  const bySystem = useMemo(() => {
    const m = new Map<number, StationCheckEntry[]>()
    for (const s of universe) {
      if (!m.has(s.systemId)) m.set(s.systemId, [])
      m.get(s.systemId)!.push(s)
    }
    return Array.from(m.entries()).sort((a, b) => a[0] - b[0])
  }, [universe])

  return (
    <Card className="md:col-span-2 py-3 gap-2">
      <CardHeader className="pb-0">
        <CardTitle className="text-sm flex items-center gap-1.5">
          <MapPin className="h-3.5 w-3.5" />
          Станции сети
          <span className="text-xs text-muted-foreground font-normal ml-auto tabular-nums">
            {universe.length}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-0 pb-3">
        {universe.length === 0 ? (
          <p className="text-xs text-muted-foreground py-1">
            Станции появятся после первой загрузки — они читаются из STS.
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
                      className="flex items-center gap-2 text-[11px] py-0.5 px-1 rounded min-w-0">
                      <span className="font-mono text-muted-foreground w-7 shrink-0 text-right tabular-nums">{s.code}</span>
                      <span className="truncate">{s.name ?? ''}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}

        <p className="mt-2 pt-2 border-t border-border/40 text-[10px] text-muted-foreground/80 leading-relaxed">
          Загрузка охватывает всю сеть системы (станции читаются из STS автоматически).
          Ограничить станции для конкретной загрузки можно в окне «Запустить» или «Управление».
        </p>
      </CardContent>
    </Card>
  )
}


// ─── Карточка ручной таблицы (источник manual_table): загрузка + обработка ──

/** Слот файла-реестра (config.uploadFiles[fmt]) — канал «Энергоснабжение и аренда ЭЗС». */
interface ReestrSlot {
  fileId?: string
  fileName?: string | null
  uploadedAt?: string
  processedAt?: string
  rows?: number
  unmatched?: number
}
const REESTR_SLOTS: { key: string; label: string }[] = [
  { key: 'svodnaya', label: 'Сводная: договоры + объёмы э/э' },
  { key: 'obshaya', label: 'Сводная выработка 2024–2026 (кВт·ч/₽)' },
  { key: 'arenda', label: 'Договоры аренды (актуальные)' },
  { key: 'tariffs', label: 'Тарифы э/э входящие' },
  { key: 'svod', label: 'Общий свод (старый формат)' },
]

function ManualTableCard({ channel }: { channel: Channel }) {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [prog, setProg] = useState<{ pct: number | null; msg: string } | null>(null)  // прогресс загрузки
  // Режим загрузки таблицы сессий ЭЗС: 'append' подгрузить новые / 'replace' переписать всё.
  const [mode, setMode] = useState<'append' | 'replace'>('append')
  const isSessions = channel.templateId === 'charge_sessions'
  const isStations = channel.templateId === 'stations'
  const isReestr = channel.templateId === 'reestr_contracts_payments'
  const supportsMode = isSessions || isStations   // таблицы с режимом подгрузить/переписать
  const fileId = (channel.config ?? {}).uploadFileId as string | undefined
  const slots = ((channel.config ?? {}).uploadFiles ?? {}) as Record<string, ReestrSlot>
  const slotCount = REESTR_SLOTS.filter((s) => slots[s.key]?.fileId).length

  async function uploadAndRun(runMode?: 'all') {
    if (runMode !== 'all' && !file && !fileId) { toast.error('Выберите файл таблицы (xlsx)'); return }
    setBusy(true)
    try {
      if (file && runMode !== 'all') {
        const r = await uploadTableFile(companyId, file)
        await updateChannel(channel.id, { config: { ...channel.config, uploadFileId: r.source_id } })
        toast.success('Таблица загружена (L1)')
      }
      // Прогон идёт В ФОНЕ (эндпоинт сразу возвращает running) — поллим статус до
      // завершения и показываем итог (для «переписать» — «удалено N, загружено M»).
      await runChannel(channel.id, runMode === 'all' ? { mode: 'all' } : (supportsMode ? { mode } : undefined))
      setProg({ pct: null, msg: 'Обработка…' })
      let final: ChannelRunStatus | null = null
      for (let i = 0; i < 400 && !final; i++) {
        await new Promise((r) => setTimeout(r, i === 0 ? 700 : 1200))
        try {
          const st = await getChannelRunStatus(channel.id)
          if (st.running) {
            // stations_done/stations_total = строки-прогресс (done/total) → проценты
            const p = st.stations_total > 0 ? Math.round((st.stations_done / st.stations_total) * 100) : null
            setProg({ pct: p, msg: st.message || 'Обработка…' })
          } else {
            final = st
          }
        } catch { /* транзиентная ошибка сети — повторим */ }
      }
      setProg(null)
      if (final) {
        const msg = final.message || `Загружено ${final.loaded ?? 0}`
        if (final.status === 'error') toast.error(msg)
        else toast.success('Обработано: ' + msg)
      } else {
        toast.message('Обработка продолжается в фоне', { description: 'Обновите страницу позже' })
      }
      qc.invalidateQueries({ queryKey: ['axis'] })
      qc.invalidateQueries({ queryKey: ['channel-runs', channel.id] })
      qc.invalidateQueries({ queryKey: ['channel-loaded', channel.id] })
      setFile(null)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
      setProg(null)
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
          {isSessions
            ? 'Файл выгрузки зарядных сессий (xlsx, ChargeTransactions) → L1 RAW → нормализация (коннектор/ФЛ-ЮЛ) → сессии (L2).'
            : isStations
            ? 'Справочник станций ЭЗС (xlsx, лист «Станции») → L1 RAW → нормализация паспорта → объекты / Точки обслуживания (L2, ЭЗС).'
            : isReestr
            ? 'Файлы реестров грузятся ПО ОЧЕРЕДИ, формат определяется автоматически (Сводная / Договоры аренды / Тарифы э/э) — каждый занимает свой слот. Загрузка → L1 RAW → сопряжение со станциями (№ БУ / зав. номер / координаты) → L2 (договоры, платёжная дисциплина, объёмы и тарифы э/э).'
            : 'Файл реестра (xlsx) → загрузка как сырьё (L1) → нормализация → нормализованная БД (L2) и разрезы «Поставщики э/э» / «Аренда».'}
        </p>
        {isReestr && (
          <div className="rounded-md border border-border/50">
            <table className="w-full text-xs">
              <tbody>
                {REESTR_SLOTS.filter((s) => s.key !== 'svod' || slots.svod?.fileId).map((s) => {
                  const slot = slots[s.key]
                  return (
                    <tr key={s.key} className="border-b border-border/40 last:border-0">
                      <td className="px-2 py-1.5 font-medium">{s.label}</td>
                      <td className="px-2 py-1.5 text-muted-foreground">
                        {slot?.fileId
                          ? <>
                              {slot.fileName || `${String(slot.fileId).slice(0, 8)}…`}
                              {slot.processedAt && <span className="ml-1 text-[10px] text-muted-foreground/70">· {slot.processedAt.slice(0, 10)}</span>}
                            </>
                          : <span className="text-muted-foreground/60">не загружен</span>}
                      </td>
                      <td className="px-2 py-1.5 text-right tabular-nums text-muted-foreground whitespace-nowrap">
                        {slot?.rows != null && <>{slot.rows} строк{slot.unmatched ? <span className="text-amber-600 dark:text-amber-400"> · {slot.unmatched} без объекта</span> : null}</>}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
        {supportsMode && (
          <div className="flex flex-col gap-1">
            <span className="text-[11px] font-medium text-muted-foreground">Режим загрузки таблицы</span>
            <div className="inline-flex w-fit rounded-md border border-border p-0.5 gap-0.5">
              <button type="button" disabled={busy} onClick={() => setMode('append')}
                className={`px-2.5 py-1 text-xs rounded-[5px] transition-colors ${mode === 'append' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'}`}>
                Подгрузить
              </button>
              <button type="button" disabled={busy} onClick={() => setMode('replace')}
                className={`px-2.5 py-1 text-xs rounded-[5px] transition-colors ${mode === 'replace' ? 'bg-destructive text-white' : 'text-muted-foreground hover:text-foreground'}`}>
                Переписать
              </button>
            </div>
            <span className="text-[10px] text-muted-foreground/80 leading-snug">
              {mode === 'append'
                ? (isStations
                    ? 'Добавит только новые станции (дедуп по «ID станции»); имеющиеся не тронет.'
                    : 'Добавит только новые сессии (дедуп по «ID сессии»); имеющиеся не тронет.')
                : (isStations
                    ? 'Обновит существующие станции и добавит новые (справочник = источник истины). Пропавшие из файла не удаляются.'
                    : 'Удалит ВСЕ сессии компании и загрузит заново из этой таблицы (полная замена).')}
            </span>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <Input type="file" accept=".xlsx,.xls"
            className="h-8 max-w-xs text-xs"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          <Button size="sm" className="h-8 gap-1.5" disabled={busy || (!file && !fileId)} onClick={() => uploadAndRun()}>
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
            {file ? 'Загрузить и обработать' : 'Запустить обработку'}
          </Button>
          {isReestr && slotCount > 0 && (
            <Button size="sm" variant="outline" className="h-8 gap-1.5" disabled={busy}
              onClick={() => uploadAndRun('all')}
              title="Переобработать все сохранённые файлы-слоты в порядке каскада (Сводная → Аренда → Тарифы). Полезно после обновления справочника станций.">
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
              Обработать все ({slotCount})
            </Button>
          )}
          {fileId && !file && !isReestr && (
            <span className="text-[10px] text-muted-foreground">файл загружен ранее · {String(fileId).slice(0, 8)}…</span>
          )}
        </div>
        {prog && (
          <div className="space-y-1">
            <div className="flex items-center justify-between text-[11px] text-muted-foreground">
              <span className="truncate">{prog.msg}</span>
              {prog.pct != null && <span className="tabular-nums shrink-0">{prog.pct}%</span>}
            </div>
            <Progress value={prog.pct ?? undefined} className={prog.pct == null ? 'animate-pulse' : ''} />
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ─── Карточка обогащения сессий справочником «Организации» ──────────────────

/** Пример enrichment-шага канала: подгрузка справочника + джойн в основную
 *  таблицу. Проставляет наименование корпоративного клиента (client_name)
 *  ЮЛ-сессиям по телефону. Идемпотентно, отдельно от загрузки сессий. */
function OrgEnrichmentCard() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [lastMsg, setLastMsg] = useState<string | null>(null)

  async function run(fn: () => Promise<{ message: string }>) {
    setBusy(true)
    try {
      const r = await fn()
      setLastMsg(r.message)
      toast.success('Обогащение выполнено', { description: r.message })
      qc.invalidateQueries({ queryKey: ['axis'] })
      qc.invalidateQueries({ queryKey: ['charge-sessions'] })
      setFile(null)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }
  function apply() {
    if (!file) { toast.error('Выберите файл справочника (xlsx)'); return }
    run(() => enrichChargeSessions(companyId, file))
  }

  return (
    <Card className="md:col-span-3 py-3 gap-2 border-l-2 border-l-violet-500/70">
      <CardHeader className="pb-0">
        <CardTitle className="text-sm flex items-center gap-1.5">
          <Sparkles className="h-3.5 w-3.5 text-violet-400" />
          Обогащение: справочник организаций
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-0 pb-3 space-y-2">
        <p className="text-xs text-muted-foreground">
          Файл «Организации (тарифы)» (xlsx) → наименование клиента + договорной тариф +
          корп-выручка проставляются ЮЛ-сессиям по телефону. Идемпотентно, реестр клиентов
          сохраняется. <b>После перезагрузки таблицы сессий</b> распределение по ЮЛ восстанавливается
          кнопкой «Переприменить» — файл заново не нужен.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <Input type="file" accept=".xlsx,.xls"
            className="h-8 max-w-xs text-xs"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          <Button size="sm" variant="outline" className="h-8 gap-1.5 border-violet-500/40"
            disabled={busy || !file} onClick={apply}>
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
            Загрузить справочник и обогатить
          </Button>
          <Button size="sm" variant="ghost" className="h-8 gap-1.5 text-violet-300/90"
            disabled={busy} onClick={() => run(() => reenrichChargeSessions(companyId))}
            title="Переприменить обогащение из сохранённого реестра (без файла)">
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RotateCcw className="h-3.5 w-3.5" />}
            Переприменить из реестра
          </Button>
          {lastMsg && <span className="text-[10px] text-muted-foreground">{lastMsg}</span>}
        </div>
      </CardContent>
    </Card>
  )
}

// ─── Вкладка: Обзор ────────────────────────────────────────

/** Загруженные документы канала: в API-режиме из БД (/fuel/shifts|receipts),
 *  иначе localStorage. Решает «Загружено 0» при реально загруженных сменах. */
function useChannelDocs(channel: Channel): LoadedDocument[] {
  const isShift = channel.templateId === 'fuel_shift'
  const isDelivery = channel.templateId === 'fuel_delivery'
  const apiFuel = isApiEnabled() && (isShift || isDelivery)
  const anchorStreamId = channel.streams.find((s) => s.enabled)?.id ?? channel.streams[0]?.id ?? ''
  const { data } = useQuery({
    queryKey: ['channel-loaded', channel.id, channel.templateId],
    enabled: apiFuel,
    queryFn: async (): Promise<LoadedDocument[]> => {
      if (isDelivery) {
        const rows = await getLoadedReceipts()
        return rows.map((r: LoadedReceipt) => ({
          id: r.id, channelId: channel.id, streamId: anchorStreamId, docType: 'receipt',
          fingerprint: r.id, title: `ТТН ${r.ttn} · ${r.fuel_name}`,
          stationId: r.station_code ?? 0,
          date: '', data: { ...r, totalLiters: r.doc_volume_liters },
          catalog: r.supplier ?? '', loadedAt: r.created_at ?? '',
        }))
      }
      const rows = await getLoadedShifts()
      return rows.map((s: LoadedShift) => ({
        id: s.id, channelId: channel.id, streamId: anchorStreamId, docType: 'shift_report',
        fingerprint: s.id, title: `Смена №${s.shift_number}`,
        stationId: s.station_code ?? 0,
        date: s.opened_at ?? '', data: { ...s, totalLiters: s.total_liters },
        catalog: s.station_name ?? '', loadedAt: s.created_at ?? '',
      }))
    },
  })
  if (apiFuel) return data ?? []
  return getAllLoadedDocs().filter((d) => d.channelId === channel.id)
}

/** Лёгкая подпись зоны на «Обзоре» — sentence-case, не трекинг-капс (не eyebrow). */
function ZoneLabel({ children }: { children: React.ReactNode }) {
  return <h2 className="text-xs font-semibold text-muted-foreground/80 px-0.5">{children}</h2>
}

// ─── Обзор = кокпит прогона: панель загрузки + лента прогонов ───────────

const RUN_STATUS_META: Record<string, { Icon: React.ComponentType<{ className?: string }>; cls: string; label: string }> = {
  success: { Icon: CheckCircle2, cls: 'text-emerald-500', label: 'Успешно' },
  partial: { Icon: AlertTriangle, cls: 'text-amber-500', label: 'Частично' },
  error: { Icon: XCircle, cls: 'text-destructive', label: 'Ошибка' },
  running: { Icon: Loader2, cls: 'text-primary', label: 'Идёт…' },
}

function runUnit(channel: Channel): string {
  return channel.templateId === 'fuel_delivery' ? 'ТТН'
    : channel.templateId === 'fuel_shift' ? 'смен' : 'док'
}

/**
 * Панель «Загрузка» — единая точка запуска: период (PeriodCard, пишет в config)
 * + опциональный фильтр станций для прогона + кнопка «Запустить».
 * Период — единственный источник правды (он же в подписи кнопки шапки).
 */
function LoadPanel({ channel, onUpdate, syncing, isFuelApi, availableStations, onRun }: {
  channel: Channel
  onUpdate: (ch: Channel) => void
  syncing: boolean
  isFuelApi: boolean
  availableStations: { code: number; name: string }[]
  onRun: (p: { dateFrom?: string; dateTo?: string; stationCodes?: number[] }) => void
}) {
  const cfg = channel.config ?? {}
  const [sel, setSel] = useState<number[]>([])   // фильтр станций для прогона (пусто = вся сеть)
  const [stOpen, setStOpen] = useState(false)
  const periodLabel = periodShortLabel(cfg.dateFrom, cfg.dateTo) ?? `последние ${channel.periodDays ?? 30} дн.`
  const stLabel = sel.length === 0 ? `вся сеть · ${availableStations.length || '—'} ст.` : `${sel.length} ст.`

  return (
    <section className="space-y-2">
      <ZoneLabel>Загрузка</ZoneLabel>
      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <PeriodCard channel={channel} onUpdate={onUpdate} />
        </div>
        <Card className="py-3 gap-2 border-primary/20">
          <CardHeader className="pb-0">
            <CardTitle className="text-sm flex items-center gap-1.5">
              <Play className="h-3.5 w-3.5 text-primary" />
              Загрузить
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0 pb-3 space-y-2">
            {isFuelApi && availableStations.length > 0 && (
              <Popover open={stOpen} onOpenChange={setStOpen}>
                <PopoverTrigger asChild>
                  <Button variant="outline" size="sm" className="h-9 text-sm w-full justify-between gap-1.5 font-normal bg-di-surface-low dark:bg-di-surface-low border-di-outline-variant/20">
                    <span className="flex items-center gap-1.5 truncate">
                      <MapPin className="h-3.5 w-3.5 shrink-0" /> {stLabel}
                    </span>
                    <ChevronsUpDown className="h-3 w-3 opacity-50 shrink-0" />
                  </Button>
                </PopoverTrigger>
                <PopoverContent className="w-64 p-2" align="end">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs font-medium">Станции загрузки</span>
                    <button type="button" className="text-xs text-primary hover:underline"
                      onClick={() => setSel([])}>Вся сеть</button>
                  </div>
                  <div className="max-h-56 overflow-y-auto space-y-0.5">
                    {availableStations.map((s) => {
                      const checked = sel.includes(s.code)
                      return (
                        <label key={s.code} className="flex items-center gap-2 text-sm py-0.5 cursor-pointer">
                          <Checkbox checked={checked} onCheckedChange={(v) =>
                            setSel((prev) => v ? [...prev, s.code] : prev.filter((c) => c !== s.code))} />
                          <span className="truncate flex-1">{s.name}</span>
                          <span className="text-[10px] text-muted-foreground font-mono">{s.code}</span>
                        </label>
                      )
                    })}
                  </div>
                  <p className="text-[10px] text-muted-foreground mt-1">Пусто = вся сеть системы.</p>
                </PopoverContent>
              </Popover>
            )}
            <Button size="sm" className="w-full gap-1.5 h-9" disabled={syncing}
              onClick={() => onRun({ dateFrom: cfg.dateFrom, dateTo: cfg.dateTo, stationCodes: sel })}>
              {syncing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
              <span className="truncate">Загрузить · {periodLabel}</span>
            </Button>
            <p className="text-[10px] text-muted-foreground/70 leading-relaxed">
              Грузит период из настроек слева. Прогресс — в ленте «Загрузки» ниже.
            </p>
          </CardContent>
        </Card>
      </div>
    </section>
  )
}

/** Лента прогонов — история загрузок: строка = прогон, раскрывается в детали. */
function RunsList({ channel, isFuelApi, onRepeat, onDelete }: {
  channel: Channel
  isFuelApi: boolean
  onRepeat: (r: ChannelRun) => void
  onDelete: (r: ChannelRun) => void
}) {
  const { data, isLoading } = useQuery({
    queryKey: ['channel-runs', channel.id],
    enabled: isApiEnabled(),
    queryFn: () => getChannelRuns(channel.id),
  })
  const runs = data ?? []
  const [openId, setOpenId] = useState<string | null>(null)
  const unit = runUnit(channel)
  const stationName = useMemo(() => {
    const m = new Map<number, string>()
    for (const loc of getLocations()) {
      if (loc.type !== 'fuel_station') continue
      const c = Number(loc.code)
      if (Number.isFinite(c) && !m.has(c)) m.set(c, loc.name)
    }
    return (c: number) => m.get(c) ?? `Станция ${c}`
  }, [])

  return (
    <section className="space-y-2">
      <ZoneLabel>Загрузки</ZoneLabel>
      {isLoading ? (
        <div className="space-y-2">
          {[0, 1, 2].map((i) => <Skeleton key={i} className="h-12 w-full rounded-lg" />)}
        </div>
      ) : runs.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-center">
            <History className="h-9 w-9 text-muted-foreground/30 mx-auto mb-2" />
            <p className="text-sm font-medium text-muted-foreground">Загрузок ещё не было</p>
            <p className="text-xs text-muted-foreground mt-0.5">Выберите период выше и нажмите «Загрузить».</p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-1">
            {runs.map((r) => {
              const meta = RUN_STATUS_META[r.status] ?? RUN_STATUS_META.running
              const Icon = meta.Icon
              const period = periodShortLabel(r.date_from, r.date_to)
              const ts = r.finished_at || r.started_at
              const canManage = isFuelApi && !!r.date_from && !!r.date_to
              const expandable = r.by_station.length > 0 || canManage
              const open = expandable && openId === r.id
              return (
                <div key={r.id} className="bg-di-surface-low rounded-xl overflow-hidden">
                  <div
                    onClick={expandable ? () => setOpenId(open ? null : r.id) : undefined}
                    className={`flex items-center gap-4 py-3 px-3 transition-colors ${expandable ? 'cursor-pointer hover:bg-di-surface-high' : ''}`}
                  >
                    <Icon className={`h-4 w-4 shrink-0 ${meta.cls} ${r.status === 'running' ? 'animate-spin' : ''}`} />
                    <span className="text-sm font-medium w-28 shrink-0 truncate">{period ?? 'весь период'}</span>
                    {/* объём */}
                    <span className="text-sm tabular-nums shrink-0 w-24">
                      <b className="text-foreground">{r.loaded}</b> <span className="text-muted-foreground">{unit}</span>
                    </span>
                    {/* станции */}
                    <span className="text-sm text-muted-foreground tabular-nums shrink-0 w-20 hidden sm:block">
                      {r.stations_done}/{r.stations_total} ст
                    </span>
                    {/* разбивка — прямо в строке */}
                    <span className="text-xs text-muted-foreground tabular-nums hidden lg:flex items-center gap-3 shrink-0">
                      <span>проп <span className="text-foreground/70">{r.skipped}</span></span>
                      <span>дубл <span className="text-foreground/70">{r.duplicates}</span></span>
                      <span className={r.errors > 0 ? 'text-destructive' : ''}>
                        ошиб <span className={r.errors > 0 ? 'font-semibold' : 'text-foreground/70'}>{r.errors}</span>
                      </span>
                    </span>
                    <span className="ml-auto flex items-center gap-3 shrink-0">
                      {!r.date_from && r.status !== 'running' && (
                        <span className="text-[10px] text-muted-foreground/45 hidden xl:inline">период не сохранён</span>
                      )}
                      <span className="text-[11px] text-muted-foreground/80 tabular-nums w-[118px] text-right hidden sm:block">
                        {ts ? format(new Date(ts), 'dd.MM.yyyy HH:mm') : ''}
                      </span>
                      {expandable
                        ? <ChevronDown className={`h-4 w-4 text-muted-foreground/60 transition-transform ${open ? 'rotate-180' : ''}`} />
                        : <span className="w-4 shrink-0" />}
                    </span>
                  </div>
                  {open && (
                    <div className="px-3 pb-3 pt-2 space-y-2 border-t border-border/40">
                      {r.by_station.length > 0 && (
                        <div className="grid grid-cols-2 xl:grid-cols-3 gap-x-4 gap-y-0.5 max-h-40 overflow-y-auto pr-1">
                          {r.by_station.map((s, i) => (
                            <div key={i} className="flex items-center gap-2 text-[11px]">
                              <span className="font-mono text-muted-foreground w-7 text-right tabular-nums shrink-0">{s.station}</span>
                              <span className="truncate flex-1">{s.name ?? stationName(s.station)}</span>
                              {s.error
                                ? <span className="text-destructive text-[10px] shrink-0" title={s.error}>ошибка</span>
                                : <span className="text-muted-foreground tabular-nums shrink-0">{s.created ?? 0}</span>}
                            </div>
                          ))}
                        </div>
                      )}
                      {canManage && (
                        <div className="flex gap-2 pt-1">
                          <Button size="sm" variant="outline" className="h-7 text-xs gap-1.5"
                            onClick={(e) => { e.stopPropagation(); onRepeat(r) }}>
                            <RotateCcw className="h-3 w-3" /> Повторить период
                          </Button>
                          <Button size="sm" variant="outline"
                            className="h-7 text-xs gap-1.5 text-destructive hover:text-destructive"
                            onClick={(e) => { e.stopPropagation(); onDelete(r) }}>
                            <Trash2 className="h-3 w-3" /> Удалить период
                          </Button>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
        </div>
      )}
    </section>
  )
}

const ROLE_META: Record<string, { label: string; cls: string; dot: string }> = {
  anchor: { label: 'Опорный', cls: 'text-foreground/80', dot: 'bg-primary' },
  control: { label: 'Сверяемый', cls: 'text-emerald-500', dot: 'bg-emerald-500' },
  reference: { label: 'Справочный', cls: 'text-muted-foreground', dot: 'bg-muted-foreground/50' },
  external: { label: 'Внешний', cls: 'text-amber-500', dot: 'bg-amber-500' },
}

/** Разрезы учёта канала: какие потоки он формирует и какие из них сверяемы. */
function ChannelCutsCard({ channel }: { channel: Channel }) {
  const navigate = useNavigate()
  const cuts = channel.streams
  const anchor = cuts.find((s) => (s.role ?? 'control') === 'anchor')
  const reconcilable = cuts.filter((s) => s.role === 'control')
  return (
    <Card className="py-3 gap-2">
      <CardHeader className="pb-0">
        <CardTitle className="text-sm flex items-center gap-1.5">
          <GitCompare className="h-3.5 w-3.5 text-muted-foreground" />
          Разрезы учёта
          <span className="text-xs text-muted-foreground font-normal ml-2 tabular-nums">{cuts.length}</span>
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-0 pb-3">
        {cuts.length === 0 ? (
          <p className="text-sm text-muted-foreground py-2">Разрезов учёта нет</p>
        ) : (
          <div className="space-y-1">
            {cuts.map((s) => {
              const m = ROLE_META[s.role ?? 'control'] ?? ROLE_META.control
              return (
                <div key={s.id} className={`flex items-center gap-2.5 px-3 py-2 bg-di-surface-low rounded-xl${s.sourceId ? '' : ' opacity-70'}`}>
                  <span className={`h-2 w-2 rounded-full shrink-0 ${m.dot}`} />
                  <span className="text-sm text-foreground/90 truncate">{s.name}</span>
                  {!s.sourceId && <span className="text-[10px] uppercase tracking-wide text-muted-foreground/60 shrink-0">не подключён</span>}
                  {s.sourceId && (
                    <button type="button" onClick={() => navigate(`/sources?focus=${s.sourceId}`)}
                      className="text-[10px] text-primary hover:underline shrink-0" title="Настроить подключение (связь + тест)">
                      Настроить
                    </button>
                  )}
                  <span className={`ml-auto text-[10px] font-semibold uppercase tracking-wide shrink-0 ${m.cls}`}>{m.label}</span>
                </div>
              )
            })}
          </div>
        )}
        <p className="text-[11px] text-muted-foreground mt-2.5 px-0.5">
          {reconcilable.length > 0
            ? `Сверяемых разрезов: ${reconcilable.length}${anchor ? ` · опорный — «${anchor.name}»` : ''}`
            : 'Дополнительной сверки разрезов нет'}
        </p>
      </CardContent>
    </Card>
  )
}

function OverviewTab({ channel, onUpdate, isFuelApi, syncing, availableStations, onRun, onRepeat, onDelete }: {
  channel: Channel
  onUpdate: (ch: Channel) => void
  isFuelApi: boolean
  syncing: boolean
  availableStations: { code: number; name: string }[]
  onRun: (p: { dateFrom?: string; dateTo?: string; stationCodes?: number[] }) => void
  onRepeat: (r: ChannelRun) => void
  onDelete: (r: ChannelRun) => void
}) {
  // Каналы с ручной загрузкой xlsx: реестр энергоснабжения/аренды и зарядные сессии ЭЗС.
  const isManualTable = channel.templateId === 'reestr_contracts_payments'
    || channel.templateId === 'charge_sessions'
    || channel.templateId === 'stations'
  const isSessions = channel.templateId === 'charge_sessions'
  return (
    <div className="space-y-5">
      {isManualTable ? (
        // Файловый канал (реестр/сессии): единственный способ загрузки — карточка с
        // файлом + режимом. STS-панель «Период → Загрузить · N дн.» здесь не нужна
        // (у файла нет периода — оркестратор даты игнорирует), поэтому её скрываем.
        // Для сессий — доп. карточка обогащения справочником организаций.
        <div className="grid gap-3 md:grid-cols-3">
          <ManualTableCard channel={channel} />
          {isSessions && <OrgEnrichmentCard />}
        </div>
      ) : (
        <LoadPanel channel={channel} onUpdate={onUpdate} syncing={syncing}
          isFuelApi={isFuelApi} availableStations={availableStations} onRun={onRun} />
      )}
      <ChannelCutsCard channel={channel} />
      <RunsList channel={channel} isFuelApi={isFuelApi} onRepeat={onRepeat} onDelete={onDelete} />
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

  // Визуализация этапов — только для клиентского (localStorage) pipeline.
  // В API-режиме обработку ведёт серверный оркестратор (загрузка из STS по всем
  // станциям → нормализация → сохранение); channel.stages он не использует,
  // поэтому пустой блок «Этапы конвейера» здесь не нужен.
  const showStages = stages.length > 0 || !isApiEnabled()

  return (
    <div className="space-y-6">
      {/* Этапы pipeline (клиентский режим) */}
      {showStages && (
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
      )}

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
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold">Параметры канала</h3>
          <p className="text-xs text-muted-foreground">
            Специфичные для этой загрузки. Применяются на этапах нормализации
            и сохранения.
          </p>
        </div>
        <BindingKeyBadge className="shrink-0" />
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
              <p className="text-[11px] text-muted-foreground/70 leading-relaxed">
                Сменный отчёт обрабатывается полностью: продажи раскладываются по каналам
                оплаты (для документов 1С), резервуары и счётчики ТРК сохраняются для
                контроля. Приём топлива (ТТН) идёт отдельным каналом «Топливо: приём».
              </p>
              <div className="border-t border-border/40" />
              <div className="grid sm:grid-cols-3 gap-3 items-start">
                <div>
                  <Label className="text-xs font-medium">Порог расхождения по резервуару</Label>
                  <p className="text-[10px] text-muted-foreground mt-0.5 leading-tight">
                    Смена помечается «Расхождения», если |факт − расчёт| остатка в баке
                    превышает это значение. По умолчанию 10 л.
                  </p>
                </div>
                <div className="sm:col-span-2 flex items-center gap-2">
                  <Input
                    type="number" min="0" step="1"
                    value={cfg.tankThreshold ?? 10}
                    onChange={(e) => update({ tankThreshold: Number(e.target.value) || 0 })}
                    className="h-8 text-xs sm:max-w-[140px] bg-di-surface-low dark:bg-di-surface-low border-di-outline-variant/20"
                  />
                  <span className="text-xs text-muted-foreground">литров</span>
                </div>
              </div>
            </>
          )}

          {primaryDocType === 'receipt' && (
            <>
              <div className="border-t border-border/40" />
              <p className="text-[11px] text-muted-foreground/70 leading-relaxed">
                По каждой ТТН сохраняются объём (литры), масса (тонны) и плотность; масса
                пересчитывается из объёма по плотности при отсутствии в документе.
                Расхождения «факт vs документ» фиксируются автоматически.
              </p>
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

// Какой справочник 1С стоит за видом маппинга (для пикера записи 1С).
// paytype не имеет синхронизируемого справочника → остаётся ручной ввод GUID.
const CATALOG_KIND: Partial<Record<MappingKind, 'nomenclature' | 'warehouse' | 'counterparty'>> = {
  fuel: 'nomenclature',
  nomenclature: 'nomenclature',
  station: 'warehouse',
  counterparty: 'counterparty',
}

interface RefOption { ref?: string; name: string; sub?: string }

/** Опции справочника 1С по виду маппинга (номенклатура/склад/контрагент). */
function useRefOptions(kind: MappingKind, companyId: string): { options: RefOption[]; loading: boolean } {
  const catalog = CATALOG_KIND[kind]
  const { data, isLoading } = useQuery({
    queryKey: ['ref-catalog', catalog, companyId],
    enabled: !!catalog && isApiEnabled(),
    queryFn: async (): Promise<RefOption[]> => {
      if (catalog === 'nomenclature') {
        return (await getNomenclature(companyId)).map((n) => ({ ref: n.externalRef, name: n.name, sub: n.code }))
      }
      if (catalog === 'warehouse') {
        return (await getWarehouses(companyId)).map((w) => ({ ref: w.externalRef, name: w.name, sub: w.code }))
      }
      return (await getCounterparties(companyId)).map((c) => ({ ref: c.externalRef, name: c.name, sub: c.inn }))
    },
  })
  return { options: data ?? [], loading: isLoading }
}

/**
 * Пикер записи 1С: combobox с поиском по справочнику (вместо ручного ввода GUID).
 * Записи без external_ref (нет GUID 1С — заведены вручную) показываются, но
 * недоступны для выбора как цель маппинга. Выбор заполняет и GUID, и название.
 */
function RefPicker({ kind, companyId, valueRef, valueName, onPick }: {
  kind: MappingKind
  companyId: string
  valueRef: string
  valueName: string
  onPick: (ref: string, name: string) => void
}) {
  const [open, setOpen] = useState(false)
  const { options, loading } = useRefOptions(kind, companyId)
  const label = valueName || valueRef || 'Выбрать запись 1С…'

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" role="combobox" aria-expanded={open}
          className="h-8 text-xs w-64 justify-between font-normal">
          <span className={`truncate ${valueRef ? '' : 'text-muted-foreground'}`}>{label}</span>
          <ChevronsUpDown className="h-3 w-3 opacity-50 shrink-0" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-72 p-0" align="start">
        <Command filter={(value, search) => value.toLowerCase().includes(search.toLowerCase()) ? 1 : 0}>
          <CommandInput placeholder="Поиск по названию/коду…" className="text-xs" />
          <CommandList>
            {loading ? (
              <div className="py-6 text-center text-xs text-muted-foreground">Загрузка справочника…</div>
            ) : (
              <>
                <CommandEmpty className="py-6 text-center text-xs text-muted-foreground">
                  Ничего не найдено. Синхронизируйте справочники 1С.
                </CommandEmpty>
                <CommandGroup>
                  {options.map((o, i) => (
                    <CommandItem
                      key={(o.ref ?? 'noref') + i}
                      value={`${o.name} ${o.sub ?? ''}`}
                      disabled={!o.ref}
                      onSelect={() => { if (o.ref) { onPick(o.ref, o.name); setOpen(false) } }}
                      className="text-xs gap-2"
                    >
                      <Check className={`h-3 w-3 shrink-0 ${valueRef && valueRef === o.ref ? 'opacity-100' : 'opacity-0'}`} />
                      <span className="truncate flex-1">{o.name}</span>
                      {o.sub && <span className="text-[10px] text-muted-foreground font-mono shrink-0">{o.sub}</span>}
                      {!o.ref && <span className="text-[9px] text-amber-500 shrink-0">нет GUID</span>}
                    </CommandItem>
                  ))}
                </CommandGroup>
              </>
            )}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
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
              <Label className="text-[11px] text-muted-foreground">Ключ источника</Label>
              <Input value={srcKey} onChange={(e) => setSrcKey(e.target.value)}
                placeholder={meta.ph} className="h-8 text-xs w-44" />
            </div>
            {CATALOG_KIND[kind] ? (
              <div className="space-y-1">
                <Label className="text-[11px] text-muted-foreground">Запись 1С</Label>
                <RefPicker
                  kind={kind} companyId={companyId}
                  valueRef={tgtRef} valueName={tgtName}
                  onPick={(ref, name) => { setTgtRef(ref); setTgtName(name) }}
                />
              </div>
            ) : (
              <>
                <div className="space-y-1">
                  <Label className="text-[11px] text-muted-foreground">Ref 1С (GUID)</Label>
                  <Input value={tgtRef} onChange={(e) => setTgtRef(e.target.value)}
                    placeholder="GUID в БП" className="h-8 text-xs w-44 font-mono" />
                </div>
                <div className="space-y-1">
                  <Label className="text-[11px] text-muted-foreground">Название (для UI)</Label>
                  <Input value={tgtName} onChange={(e) => setTgtName(e.target.value)}
                    placeholder="напр. Купон" className="h-8 text-xs w-44" />
                </div>
              </>
            )}
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
  const allDocs = useChannelDocs(channel)
  // Порог расхождения по резервуару (л) из настроек канала → в просмотрщик смены.
  const tankThreshold = Number((channel.config as Record<string, any>)?.tankThreshold) || 10

  // Глобальные фильтры из шапки (Компания/Точки/Типы документов).
  // Применяются ПОВЕРХ локальных фильтров вкладки (AND-логика):
  // если в шапке выбраны точки A,B,C — даже при «Все станции» локально
  // мы видим только их.
  const { locationIds: globalLocIds } = useFilters()

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

  // Состояние фильтров (локально для вкладки)
  const [query, setQuery] = useState('')
  const [stationFilter, setStationFilter] = useState<number[]>([])
  const [monthFilter, setMonthFilter] = useState<string>('all')
  const [sortKey, setSortKey] = useState<SortKey>('date_desc')

  // Доступные значения для локальных фильтров — только из документов,
  // прошедших глобальный фильтр (иначе в селекте «Станция 208» при
  // глобально выбранной АЗС 5 — пустота).
  const docsForLocalFilters = useMemo(() => {
    if (!globalStationCodes) return allDocs
    return allDocs.filter((d) => globalStationCodes.has(d.stationId))
  }, [allDocs, globalStationCodes])

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
  }, [allDocs, query, stationFilter, monthFilter, sortKey, globalStationCodes])

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
          {hasFilters || globalStationCodes
            ? `Показано ${filteredDocs.length} из ${allDocs.length}`
            : `Загружено ${allDocs.length} документов`}
        </p>
        {globalStationCodes && (
          <div className="flex items-center gap-1 text-[10px] text-muted-foreground">
            <Filter className="h-3 w-3" />
            <span>Действует глобальный фильтр</span>
            {globalStationCodes && (
              <Badge variant="outline" className="text-[9px] h-4 px-1">
                точек {globalStationCodes.size}
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
          <DocumentsTable key={type} type={type} items={items} tankThreshold={tankThreshold} />
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
function DocumentsTable({ type, items, tankThreshold = 10 }: { type: string; items: ReturnType<typeof getAllLoadedDocs>; tankThreshold?: number }) {
  const [openDoc, setOpenDoc] = useState<ReturnType<typeof getAllLoadedDocs>[number] | null>(null)
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
        <div className="grid grid-cols-[1fr_220px_110px_140px_90px] gap-3 px-3 pb-2 text-[10px] font-semibold text-muted-foreground/70 uppercase tracking-wide">
          <span>Документ</span>
          <span>Станция</span>
          <span>Дата</span>
          <span>Загружено</span>
          <span className="text-right">Размер</span>
        </div>

        {/* Строки — плитки-поверхности (стиль TradeFrame) */}
        <div className="max-h-[460px] overflow-y-auto space-y-1 pr-1">
          {visible.map((doc) => {
            const size = docSize(doc)
            return (
              <div key={doc.id} onClick={() => setOpenDoc(doc)}
                className="grid grid-cols-[1fr_220px_110px_140px_90px] gap-3 items-center px-3 py-2.5 text-xs bg-di-surface-low rounded-xl hover:bg-di-surface-high transition-colors cursor-pointer">
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
      {openDoc?.docType === 'shift_report' ? (
        <ShiftDetailsDialog shiftId={openDoc.id} open onClose={() => setOpenDoc(null)} tankThreshold={tankThreshold} />
      ) : (
        <DocumentDetailDialog doc={openDoc} onClose={() => setOpenDoc(null)} />
      )}
    </Card>
  )
}

const DOC_KIND_LABEL: Record<string, string> = {
  shift_orp: 'Отчёт о розничных продажах (ОРП)',
  cash_pko: 'Приходный кассовый ордер (ПКО)',
  fuel_transfer: 'Перемещение на склад канала',
  fuel_writeoff: 'Списание топлива',
  ttn_transfer: 'Перемещение тонн (41.01)',
  ttn_assembly: 'Комплектация тонны → литры (41.02)',
}

/** Диалог с документами 1С:Бухгалтерии, которые сформирует смена/ТТН. */
function DocumentDetailDialog({ doc, onClose }: {
  doc: ReturnType<typeof getAllLoadedDocs>[number] | null
  onClose: () => void
}) {
  const isReceipt = doc?.docType === 'receipt'
  const { data, isLoading } = useQuery({
    queryKey: ['doc-1c', doc?.id, doc?.docType],
    enabled: !!doc && isApiEnabled(),
    queryFn: () => (isReceipt ? getReceiptDocuments(doc!.id) : getShiftDocuments(doc!.id)),
  })
  const docs: FuelDocument[] = data?.documents ?? []
  return (
    <Dialog open={!!doc} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{doc?.title}</DialogTitle>
          <DialogDescription>
            Документы 1С:Бухгалтерии, которые сформирует {isReceipt ? 'эта ТТН' : 'эта смена'}
          </DialogDescription>
        </DialogHeader>
        {!isApiEnabled() ? (
          <p className="text-sm text-muted-foreground py-6 text-center">Доступно при подключённом API</p>
        ) : isLoading ? (
          <div className="flex justify-center py-8"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
        ) : docs.length === 0 ? (
          <p className="text-sm text-muted-foreground py-6 text-center">
            Документы пока не сформированы (нет продаж/приёма за этот период)
          </p>
        ) : (
          <div className="space-y-3 max-h-[60vh] overflow-y-auto pr-1">
            {docs.map((d, i) => {
              const p = d.payload as Record<string, any>
              const lines: any[] = Array.isArray(p.lines) ? p.lines : []
              return (
                <div key={i} className="rounded-lg border border-border/50 p-3 space-y-1.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium">{DOC_KIND_LABEL[d.kind] ?? d.kind}</span>
                    <span className="text-[10px] text-muted-foreground font-mono">{p.time ?? ''}</span>
                  </div>
                  <div className="text-[11px] text-muted-foreground">
                    {p.doc_type}{p.warehouse ? ` · склад ${p.warehouse}` : ''}
                    {p.warehouse_from ? ` · ${p.warehouse_from} → ${p.warehouse_to}` : ''}
                  </div>
                  {lines.map((ln, j) => (
                    <div key={j} className="flex items-center justify-between text-xs gap-2 border-t border-border/30 pt-1">
                      <span className="truncate">{ln.nomenclature || ln.fuel_name || '—'}</span>
                      <span className="tabular-nums text-muted-foreground shrink-0">
                        {ln.liters != null ? `${ln.liters} л` : ''}
                        {ln.tonnes != null ? ` ${ln.tonnes} т` : ''}
                        {ln.amount ? ` · ${Number(ln.amount).toLocaleString('ru')} ₽` : ''}
                      </span>
                    </div>
                  ))}
                  {p.amount != null && lines.length === 0 && (
                    <div className="text-xs text-right tabular-nums">{Number(p.amount).toLocaleString('ru')} ₽</div>
                  )}
                  {p.product && (
                    <div className="flex justify-between text-xs border-t border-border/30 pt-1">
                      <span className="truncate">{p.product.nomenclature}</span>
                      <span className="tabular-nums text-muted-foreground shrink-0">{p.product.liters} л</span>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

// ─── Вкладка: Настройки (Источники + Станции + Расписание + Обработка) ──────
// Редко используемая конфигурация канала. Источники, охват/станции сети,
// расписание и параметры обработки. Период загрузки здесь НЕ дублируется —
// он живёт в панели «Загрузка» кокпита (вкладка «Обзор»).

function SettingsTab({ channel, onUpdate }: { channel: Channel; onUpdate: (ch: Channel) => void }) {
  return (
    <div className="space-y-8">
      <SourcesTab channel={channel} onUpdate={onUpdate} />
      <div className="border-t border-border/40" />
      <div>
        <h3 className="text-sm font-semibold mb-3">Станции и расписание</h3>
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
          <StationsCard channel={channel} />
          <ScheduleCard />
        </div>
      </div>
      <div className="border-t border-border/40" />
      <PipelineTab channel={channel} onUpdate={onUpdate} />
    </div>
  )
}

// ─── Главная страница канала ─────────────────────────────────

export function ChannelDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [channel, setChannel] = useState<Channel | undefined>(() => id ? getChannel(id) : undefined)
  const [activeTab, setActiveTab] = useState<TabId>('overview')
  // «Настройки» — конфигурация канала (источники, станции, расписание,
  // конвейер). По собственному описанию вкладки — редко используемая, поэтому
  // в простом режиме её нет. «Маппинг» остаётся всегда: он определяет, куда
  // лягут данные, а сигнала о незакрытых сопоставлениях на вкладках нет —
  // спрятать его значило бы спрятать вопрос корректности.
  const { isSimple } = useUiLevel()
  const visibleTabs = isSimple ? TABS.filter((t) => t.id !== 'settings') : TABS
  useEffect(() => {
    if (isSimple && activeTab === 'settings') setActiveTab('overview')
  }, [isSimple, activeTab])
  const [syncing, setSyncing] = useState(false)
  const [syncProgress, setSyncProgress] = useState('')
  const [syncPercent, setSyncPercent] = useState<number | null>(null)
  // Живая статистика прогона для панели прогресса (станции + объём).
  const [syncStats, setSyncStats] = useState<{ loaded: number; done: number; total: number } | null>(null)
  // Период загрузки — указывается явно перед каждым запуском (дефолт: текущий месяц)
  const _now = new Date()
  const [runFrom, setRunFrom] = useState(
    `${_now.getFullYear()}-${String(_now.getMonth() + 1).padStart(2, '0')}-01`,
  )
  const [runTo, setRunTo] = useState(_now.toISOString().slice(0, 10))
  // Диалог «Удалить»/«Обновить» за период + выбор станций
  const [manageOpen, setManageOpen] = useState(false)
  const [manageMode, setManageMode] = useState<'delete' | 'refresh'>('refresh')
  const [manageBusy, setManageBusy] = useState(false)
  const [selStations, setSelStations] = useState<number[]>([])
  const [allPeriod, setAllPeriod] = useState(false)
  const { companyId } = useCompany()

  // Станции, по которым есть загруженные данные (вкладка «Загружено» —
  // данные всей компании, не только станций канала). Для диалога удаления.
  const { data: loadedStations } = useQuery({
    queryKey: ['fuel-loaded-stations', id],
    enabled: isApiEnabled() && !!id,
    queryFn: getLoadedStations,
  })

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

  async function handleSync(period?: { dateFrom?: string; dateTo?: string; stationCodes?: number[]; allPeriod?: boolean }) {
    if (!channel) return
    setSyncing(true)
    setSyncPercent(null)
    setSyncStats(null)
    setSyncProgress('Запуск…')
    try {
      if (isApiEnabled()) {
        // API-режим: прогон запускается В ФОНЕ (возвращает сразу), поллим прогресс.
        await runChannel(channel.id, period)
        setSyncProgress('Подключение к STS…')
        for (let i = 0; i < 1800; i++) {           // защитный лимит
          await new Promise((r) => setTimeout(r, i === 0 ? 1200 : 2000))
          let st
          try {
            st = await getChannelRunStatus(channel.id)
          } catch {
            continue                                // транзиентная ошибка сети — повторим
          }
          if (st.running) {
            if (st.stations_total > 0) {
              const p = Math.round((st.stations_done / st.stations_total) * 100)
              // 0% (станция ещё качается) → бегущий индикатор, а не статичный 0
              setSyncPercent(p > 0 ? p : null)
            }
            // бэк присылает осмысленный статус: «Станция X/12: загрузка смен…»
            setSyncProgress(st.message || 'Подключение к STS…')
            setSyncStats({ loaded: st.loaded ?? 0, done: st.stations_done ?? 0, total: st.stations_total ?? 0 })
            if (i % 2 === 0) {
              refresh()
              qc.invalidateQueries({ queryKey: ['fuel-count', channel.id] }) // живой рост числа
              qc.invalidateQueries({ queryKey: ['channel-runs', channel.id] })
            }
          } else {
            setSyncPercent(100)
            refresh()
            // обновить карточку/вкладку «Загружено» без F5 (список + реальный count)
            qc.invalidateQueries({ queryKey: ['channel-loaded', channel.id] })
            qc.invalidateQueries({ queryKey: ['fuel-count', channel.id] })
            qc.invalidateQueries({ queryKey: ['channel-runs', channel.id] })
            if (st.status === 'error') toast.error(st.message || 'Ошибка прогона')
            else toast.success(st.message || `Загрузка завершена · ${st.loaded}`)
            return
          }
        }
        toast.message('Загрузка продолжается в фоне', { description: 'Обновите страницу позже' })
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
      setSyncPercent(null)
      setSyncStats(null)
    }
  }

  const status = STATUS_MAP[channel.status] ?? STATUS_MAP.draft

  // Канал топлива в API-режиме — для него доступны «Обновить»/«Удалить» загруженного.
  const isFuelApi = isApiEnabled() &&
    (channel.templateId === 'fuel_shift' || channel.templateId === 'fuel_delivery')
  const fuelKind: 'shift' | 'receipt' = channel.templateId === 'fuel_delivery' ? 'receipt' : 'shift'
  // Имена станций по коду из справочника точек (как в списке «Загружено»).
  const stationNameByCode = (() => {
    const m = new Map<number, string>()
    for (const loc of getLocations()) {
      if (loc.type !== 'fuel_station') continue
      const c = Number(loc.code)
      if (Number.isFinite(c) && !m.has(c)) m.set(c, loc.name)
    }
    return m
  })()
  // Станции для диалога = настройки канала ∪ станции с загруженными данными
  // (вкладка «Загружено» показывает данные всей компании, не только канала).
  const availableStations: { code: number; name: string }[] = (() => {
    const m = new Map<number, string>()
    for (const s of ((channel.config?.stations as any[]) || [])) {
      const c = Number(s.code)
      if (Number.isFinite(c) && c) m.set(c, stationNameByCode.get(c) || String(s.name || `Станция ${c}`))
    }
    for (const s of (loadedStations || [])) {
      const c = Number(s.code)
      if (Number.isFinite(c) && c && !m.has(c)) m.set(c, stationNameByCode.get(c) || s.name || `Станция ${c}`)
    }
    return [...m.entries()].map(([code, name]) => ({ code, name })).sort((a, b) => a.code - b.code)
  })()

  // Повтор/удаление за период конкретного прогона (строка ленты «Прогоны»).
  // Перезагрузка = удалить период + загрузить заново (нужно для полного raw_report).
  async function deleteRun(r: ChannelRun) {
    if (!channel || !r.date_from || !r.date_to) return
    try {
      const res = await deleteFuelPeriod({
        kind: fuelKind, station_codes: [], date_from: r.date_from, date_to: r.date_to,
      })
      qc.invalidateQueries({ queryKey: ['channel-loaded', channel.id] })
      qc.invalidateQueries({ queryKey: ['fuel-count', channel.id] })
      qc.invalidateQueries({ queryKey: ['channel-runs', channel.id] })
      refresh()
      toast.success(`Удалено документов: ${res.deleted}`)
    } catch (e) {
      toast.error(`Не удалось удалить: ${String(e)}`)
    }
  }

  async function repeatRun(r: ChannelRun) {
    if (!channel || !r.date_from || !r.date_to) return
    try {
      await deleteFuelPeriod({
        kind: fuelKind, station_codes: [], date_from: r.date_from, date_to: r.date_to,
      })
    } catch (e) {
      toast.error(`Не удалось перезагрузить: ${String(e)}`)
      return
    }
    await handleSync({ dateFrom: r.date_from, dateTo: r.date_to })
  }

  function openManage(mode: 'delete' | 'refresh') {
    if (!channel) return
    const cfg = channel.config || {}
    if (cfg.dateFrom && cfg.dateTo) {     // период из настроек канала (покрывает загруженное)
      setRunFrom(String(cfg.dateFrom).slice(0, 10))
      setRunTo(String(cfg.dateTo).slice(0, 10))
    }
    // «Удалить» по умолчанию — за ВЕСЬ период (чтобы «удалить всё» не зависело
    // от того, попадает ли период настроек канала в реально загруженные даты).
    // «Обновить» — за конкретный период (из настроек канала).
    setAllPeriod(mode === 'delete')
    setSelStations([])   // пусто = вся сеть системы (по умолчанию все станции STS)
    setManageMode(mode)
    setManageOpen(true)
  }

  async function handleManageConfirm() {
    if (!channel) return
    // Пустой выбор → вся сеть системы (бэкенд/оркестратор трактуют пусто как «все»).
    const codes = selStations
    setManageBusy(true)
    try {
      const r = await deleteFuelPeriod({
        kind: fuelKind, station_codes: codes,
        date_from: allPeriod ? undefined : runFrom,
        date_to: allPeriod ? undefined : runTo,
      })
      qc.invalidateQueries({ queryKey: ['channel-loaded', channel.id] })
      qc.invalidateQueries({ queryKey: ['fuel-count', channel.id] })
      refresh()
      setManageOpen(false)
      if (manageMode === 'delete') {
        toast.success(`Удалено документов: ${r.deleted}`)
      } else {
        toast.message(`Удалено ${r.deleted} — перезагружаю из STS…`)
        await handleSync({ dateFrom: runFrom, dateTo: runTo, stationCodes: codes, allPeriod })
      }
    } catch (e) {
      toast.error(`Не удалось: ${String(e)}`)
    } finally {
      setManageBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => navigate('/connectors')}>
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
        {isFuelApi && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button size="sm" variant="outline" className="gap-1.5" disabled={syncing || manageBusy}>
                <Settings2 className="h-3.5 w-3.5" /> Управление
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              <DropdownMenuLabel>Загруженные данные</DropdownMenuLabel>
              <DropdownMenuItem onClick={() => openManage('refresh')}>
                <RotateCcw className="h-3.5 w-3.5" /> Перезагрузить период…
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem variant="destructive" onClick={() => openManage('delete')}>
                <Trash2 className="h-3.5 w-3.5" /> Удалить загруженное…
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>

      {/* Диалог «Удалить»/«Обновить» загруженного — период + выбор станций */}
      <Dialog open={manageOpen} onOpenChange={(o) => { if (!manageBusy) setManageOpen(o) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {manageMode === 'delete' ? 'Удалить загруженные данные' : 'Обновить (перезагрузить) период'}
            </DialogTitle>
            <DialogDescription>
              {manageMode === 'delete'
                ? `Удалит загруженные ${fuelKind === 'receipt' ? 'ТТН' : 'смены'} за период по выбранным станциям. Смены закрытых периодов пропускаются.`
                : 'Удалит загруженные смены за период и сразу загрузит их заново из STS — нужно для полной формы детали смены (сырой отчёт).'}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label htmlFor="m-from">С даты</Label>
                <Input id="m-from" type="date" value={runFrom} disabled={allPeriod}
                  onChange={(e) => setRunFrom(e.target.value)} />
              </div>
              <div className="space-y-1">
                <Label htmlFor="m-to">По дату</Label>
                <Input id="m-to" type="date" value={runTo} disabled={allPeriod}
                  onChange={(e) => setRunTo(e.target.value)} />
              </div>
            </div>
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <Checkbox checked={allPeriod} onCheckedChange={(v) => setAllPeriod(!!v)} />
              <span>{manageMode === 'delete'
                ? 'За весь период (игнорировать даты — удалить всё по станциям)'
                : 'За весь период (загрузить всю историю — дольше)'}</span>
            </label>
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <Label>Станции</Label>
                <div className="flex gap-3 text-xs">
                  <button type="button" className="text-primary hover:underline"
                    onClick={() => setSelStations(availableStations.map((s) => s.code))}>Все</button>
                  <button type="button" className="text-muted-foreground hover:underline"
                    onClick={() => setSelStations([])}>Сбросить</button>
                </div>
              </div>
              <div className="max-h-48 overflow-y-auto rounded-md border border-border/50 p-2 space-y-0.5">
                {availableStations.length === 0 && (
                  <p className="text-xs text-muted-foreground">У канала не выбраны станции</p>
                )}
                {availableStations.map((s) => {
                  const checked = selStations.includes(s.code)
                  return (
                    <label key={s.code} className="flex items-center gap-2 text-sm py-0.5 cursor-pointer">
                      <Checkbox checked={checked} onCheckedChange={(v) =>
                        setSelStations((prev) => v ? [...prev, s.code] : prev.filter((c) => c !== s.code))} />
                      <span className="truncate">{s.name}</span>
                      <span className="text-[10px] text-muted-foreground font-mono ml-auto">код {s.code}</span>
                    </label>
                  )
                })}
              </div>
              <p className="text-[10px] text-muted-foreground">
                Пусто = вся сеть системы (все станции STS). Выбрано: {selStations.length || 'все'}.
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setManageOpen(false)} disabled={manageBusy}>Отмена</Button>
            <Button
              variant={manageMode === 'delete' ? 'destructive' : 'default'}
              disabled={manageBusy || (!allPeriod && (!runFrom || !runTo || runFrom > runTo))}
              onClick={handleManageConfirm}
            >
              {manageBusy
                ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                : (manageMode === 'delete' ? <Trash2 className="h-3.5 w-3.5" /> : <RotateCcw className="h-3.5 w-3.5" />)}
              {manageMode === 'delete' ? 'Удалить за период' : 'Обновить за период'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Прогресс: детерминированный по станциям, indeterminate пока 0 */}
      {syncing && (
        <Card className="border-primary/30 bg-primary/[0.03]">
          <CardContent className="py-3 space-y-2">
            <div className="flex items-center gap-2">
              <Loader2 className="h-4 w-4 animate-spin text-primary shrink-0" />
              <span className="text-sm font-medium">Загрузка из STS</span>
              {syncStats && syncStats.total > 0 && (
                <span className="text-xs text-muted-foreground ml-auto tabular-nums">
                  станций {syncStats.done}/{syncStats.total}
                </span>
              )}
            </div>
            <Progress className="h-2" value={syncPercent ?? undefined} />
            <div className="flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
              <span className="truncate">{syncProgress || 'Подключение…'}</span>
              <span className="shrink-0 tabular-nums">
                {syncStats ? `загружено ${syncStats.loaded}` : ''}
                {syncPercent != null ? ` · ${syncPercent}%` : ''}
              </span>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Tabs */}
      <div className="flex items-center gap-1 border-b border-border/40 pb-px">
        {visibleTabs.map((tab) => {
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
        <AdvancedHint count={1} what="вкладка — настройки канала" />
      </div>

      {/* Content */}
      <div className="pt-2">
        {activeTab === 'overview' && (
          <OverviewTab
            channel={channel}
            onUpdate={(ch) => { setChannel(ch); refresh() }}
            isFuelApi={isFuelApi}
            syncing={syncing}
            availableStations={availableStations}
            onRun={(p) => handleSync(p)}
            onRepeat={repeatRun}
            onDelete={deleteRun}
          />
        )}
        {activeTab === 'data' && (
          isFuelApi && channel.templateId === 'fuel_delivery'
            ? <ReceiptsJournal />
            : <DataTab channel={channel} />
        )}
        {activeTab === 'mapping' && (
          <div className="space-y-3">
            {(channel.templateId === 'fuel_shift' || channel.templateId === 'fuel_delivery') && (
              <p className="text-xs text-muted-foreground">
                Канонические справочники (виды топлива, каналы оплаты) — на странице
                «Каналы» → блок «Маппинги компании». Здесь — переопределения уровня канала.
              </p>
            )}
            <MappingTab channel={channel} companyId={companyId} />
          </div>
        )}
        {activeTab === 'settings' && <SettingsTab channel={channel} onUpdate={(ch) => { setChannel(ch); refresh() }} />}
      </div>
    </div>
  )
}

export default ChannelDetailPage
