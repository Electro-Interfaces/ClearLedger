/**
 * «Загрузка» — единый портал приёма данных.
 *
 * Таб «Загрузка файлов» — ручная загрузка документов/таблиц с локального диска
 * через реальный intake-pipeline (detect→extract→classify→verify→dedup→save).
 * Пользователь указывает целевой канал явно или оставляет «Автоподбор» — тогда
 * канал подбирается по формату/имени файла (`channelAutoMatch`).
 *
 * Таб «Каналы и расписание» — обзор всех каналов: статус, режим расписания,
 * последняя/следующая синхронизация, «Запустить сейчас» (ручная эскалация) и
 * переход к настройке расписания (`ScheduleOverview`).
 */

import { useCallback, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { IntakeDocs } from '@/components/books/IntakeDocs'
import { MailConnector } from '@/components/books/MailConnector'
import { AdvancedOnly, AdvancedHint } from '@/components/common/AdvancedOnly'
import {
  Upload, FileText, Image, FileSpreadsheet, File, Trash2, Wand2, Radio,
  Play, Clock, CheckCircle2, AlertCircle, Pause, Loader2, Settings2, ExternalLink,
  Database, Calendar, Table2, Sheet, FileCheck, Mail } from 'lucide-react'
import { toast } from 'sonner'
import { nanoid } from 'nanoid'
import { format } from 'date-fns'
import * as XLSX from 'xlsx'
import { useQueryClient } from '@tanstack/react-query'
import { useLocations } from '@/hooks/useLocations'
import { useFilters } from '@/contexts/FilterContext'
import { useCompany } from '@/contexts/CompanyContext'
import { processFile } from '@/services/intake/pipeline'
import { runChannel } from '@/services/channelService'
import { syncChannel } from '@/services/channelSyncService'
import { useChannels, useSources } from '@/hooks/useChannels'
import { isApiEnabled } from '@/services/apiClient'
import { getNextSyncTime } from '@/services/channelScheduler'
import { suggestChannelForFile } from '@/services/channelAutoMatch'
import { ScheduleOverview } from '@/components/channels/ScheduleOverview'
import {
  getChannelSourceIds, DEFAULT_SCHEDULE, type Channel, type ScheduleConfig, type ScheduleMode,
} from '@/types/channel'

/* ─────────────────────────── общее ─────────────────────────── */

type DocKind = 'shift_report' | 'receipt' | 'invoice' | 'bank_statement' | 'cash_doc' | 'contract' | 'other'
interface DocKindOption { id: string; kind: DocKind; label: string; hint: string }

const DOC_KINDS_FUEL: DocKindOption[] = [
  { id: 'shift_report', kind: 'shift_report', label: 'Сменный отчёт', hint: 'ОРП, фискальный документ за смену' },
  { id: 'receipt', kind: 'receipt', label: 'ТТН / Поступление', hint: 'Накладная на приём топлива или товара' },
  { id: 'invoice', kind: 'invoice', label: 'Счёт-фактура', hint: 'СФ от поставщика для НДС' },
  { id: 'bank_statement', kind: 'bank_statement', label: 'Банковская выписка', hint: 'Платёжный документ из банка' },
  { id: 'cash_doc', kind: 'cash_doc', label: 'Кассовый документ', hint: 'ПКО / РКО / акт инкассации' },
  { id: 'contract', kind: 'contract', label: 'Договор / соглашение', hint: 'Контракт с контрагентом' },
  { id: 'other', kind: 'other', label: 'Прочее', hint: 'Не подходит под другие типы' },
]
const DOC_KINDS_ENERGY: DocKindOption[] = [
  { id: 'maintenance_act', kind: 'receipt', label: 'Акт ТО оборудования', hint: 'Плановое / аварийное обслуживание' },
  { id: 'defect_sheet', kind: 'other', label: 'Дефектная ведомость', hint: 'Перечень выявленных дефектов' },
  { id: 'inspection_journal', kind: 'shift_report', label: 'Журнал обходов', hint: 'Записи о плановых обходах объекта' },
  { id: 'work_permit', kind: 'contract', label: 'Наряд-допуск', hint: 'Разрешение на проведение работ' },
  { id: 'supplier_invoice', kind: 'invoice', label: 'Счёт поставщика', hint: 'Счёт / счёт-фактура от контрагента' },
  { id: 'payment_order', kind: 'bank_statement', label: 'Платёжное поручение', hint: 'Платёжный документ' },
  { id: 'other', kind: 'other', label: 'Прочее', hint: 'Не подходит под другие типы' },
]

const FILE_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  'application/pdf': FileText,
  'image/': Image,
  'application/vnd.openxmlformats': FileSpreadsheet,
  'application/vnd.ms-excel': FileSpreadsheet,
  'text/csv': FileSpreadsheet,
}
function getFileIcon(mimeType: string) {
  for (const [key, Icon] of Object.entries(FILE_ICONS)) {
    if (mimeType.startsWith(key)) return Icon
  }
  return File
}
function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} КБ`
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`
}

const AUTO = '__auto__'

/* ─────────────────────── Таб: загрузка файлов ─────────────────────── */

type UploadStatus = 'queued' | 'processing' | 'done' | 'error'
interface UploadItem {
  key: string
  file: File
  status: UploadStatus
  progress: number
  stage?: string
  channelName?: string   // подобранный/выбранный канал
  matchReason?: string   // почему подобран (для «Автоподбора»)
  resultLabel?: string   // распознанный тип
  error?: string
}

function FilesUploadTab() {
  const queryClient = useQueryClient()
  const locations = useLocations()
  const { locationIds: globalLocIds } = useFilters()
  const { company, companyId } = useCompany()
  const isEnergy = company.profileId === 'energy'
  const docKinds = isEnergy ? DOC_KINDS_ENERGY : DOC_KINDS_FUEL

  const { data: channels = [] } = useChannels()
  const { data: sources = [] } = useSources()
  const defaultLocationId = globalLocIds.length === 1 ? globalLocIds[0] : ''

  const [items, setItems] = useState<UploadItem[]>([])
  const [dragging, setDragging] = useState(false)
  const [processing, setProcessing] = useState(false)

  // Параметры следующей загрузки
  const [pendingChannel, setPendingChannel] = useState<string>(AUTO)
  const [pendingKindId, setPendingKindId] = useState<string>(() => docKinds[docKinds.length - 1].id)
  const [pendingLocationId, setPendingLocationId] = useState<string>(defaultLocationId)
  const [pendingDate, setPendingDate] = useState<string>(format(new Date(), 'yyyy-MM-dd'))
  const pendingOption = docKinds.find((k) => k.id === pendingKindId) ?? docKinds[docKinds.length - 1]

  const addFiles = useCallback((fileList: FileList) => {
    const added: UploadItem[] = Array.from(fileList).map((f) => ({
      key: nanoid(8), file: f, status: 'queued' as const, progress: 0,
    }))
    setItems((prev) => [...added, ...prev])
  }, [])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault(); setDragging(false)
    if (e.dataTransfer.files.length > 0) addFiles(e.dataTransfer.files)
  }, [addFiles])

  const patchItem = useCallback((key: string, patch: Partial<UploadItem>) => {
    setItems((prev) => prev.map((it) => (it.key === key ? { ...it, ...patch } : it)))
  }, [])

  async function processOne(it: UploadItem) {
    let channelId = pendingChannel === AUTO ? '' : pendingChannel
    let channelName = ''
    let matchReason = ''

    if (!channelId) {
      const sug = suggestChannelForFile(it.file, channels, sources)
      if (sug) { channelId = sug.channel.id; channelName = sug.channel.name; matchReason = sug.reason }
    } else {
      channelName = channels.find((c) => c.id === channelId)?.name ?? ''
    }

    const meta: Record<string, string> = {
      _manualIntake: 'true',
      _docKindHint: pendingOption.id,
    }
    if (channelId) { meta._channelId = channelId; meta._channelName = channelName }
    if (pendingLocationId) meta.locationId = pendingLocationId
    if (pendingDate) meta.docDate = pendingDate

    patchItem(it.key, { status: 'processing', progress: 5, channelName: channelName || undefined, matchReason: matchReason || undefined })

    try {
      let lastLabel = ''
      await processFile(it.file, {
        companyId,
        profileId: company.profileId,
        _extraMeta: meta,
        onUpdate: (item) => {
          if (item.classification?.docTypeId) lastLabel = item.classification.docTypeId
          patchItem(it.key, { progress: item.progress, stage: item.stage })
        },
      })
      patchItem(it.key, { status: 'done', progress: 100, resultLabel: lastLabel || undefined })
    } catch (e) {
      patchItem(it.key, { status: 'error', error: String(e) })
    }
  }

  async function handleProcess() {
    const queued = items.filter((it) => it.status === 'queued')
    if (queued.length === 0) return
    setProcessing(true)
    try {
      for (const it of queued) {
        await processOne(it)
      }
      queryClient.invalidateQueries({ queryKey: ['entries'] })
      const ok = items.filter((it) => it.status !== 'error').length
      toast.success(`Обработка завершена · ${queued.length} файл(ов)`, {
        description: ok < queued.length ? 'Часть файлов с ошибками — см. список' : 'Документы попали в раздел «Документы»',
      })
    } finally {
      setProcessing(false)
    }
  }

  const queuedCount = items.filter((it) => it.status === 'queued').length

  return (
    <div className="space-y-4">
      {/* Параметры загрузки */}
      <Card className="py-3 gap-2">
        <CardHeader className="pb-0">
          <CardTitle className="text-sm">Параметры загрузки</CardTitle>
          <CardDescription className="text-[11px]">
            Применяются к следующим добавленным файлам. Канал можно оставить «Автоподбор» —
            система определит его по формату и имени файла.
          </CardDescription>
          <AdvancedHint count={3} what="параметра — канал, тип документа, точка обслуживания" />
        </CardHeader>
        <CardContent className="pt-0 pb-0">
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
            {/* Канал, тип и точка имеют безопасные умолчания: канал подбирается
                по формату файла, тип — лишь подсказка классификатору (он
                определяет тип сам), точка — «без привязки». В простом режиме убраны.
                Дата документа ниже остаётся всегда: её умолчание — сегодня, и для
                документа, где дату распознать не удалось, скрытое поле молча
                проставило бы неверный период. */}
            <AdvancedOnly>
            <div className="space-y-1.5">
              <Label className="text-xs flex items-center gap-1"><Radio className="h-3 w-3" /> Канал</Label>
              <Select value={pendingChannel} onValueChange={setPendingChannel}>
                <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value={AUTO} className="text-xs">
                    <span className="flex items-center gap-1.5"><Wand2 className="h-3 w-3" /> Автоподбор</span>
                  </SelectItem>
                  {channels.map((c) => (
                    <SelectItem key={c.id} value={c.id} className="text-xs">{c.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label className="text-xs">Тип документа</Label>
              <Select value={pendingOption.id} onValueChange={setPendingKindId}>
                <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {docKinds.map((k) => (
                    <SelectItem key={k.id} value={k.id} className="text-xs">
                      <div className="flex flex-col">
                        <span>{k.label}</span>
                        <span className="text-[10px] text-muted-foreground">{k.hint}</span>
                      </div>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label className="text-xs">Точка обслуживания</Label>
              <Select value={pendingLocationId || 'none'}
                onValueChange={(v) => setPendingLocationId(v === 'none' ? '' : v)}>
                <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="Без привязки" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="none" className="text-xs text-muted-foreground">Без привязки</SelectItem>
                  {locations.map((l) => (
                    <SelectItem key={l.id} value={l.id} className="text-xs">
                      <span className="font-mono text-muted-foreground mr-2">{l.code}</span>{l.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            </AdvancedOnly>

            <div className="space-y-1.5">
              <Label className="text-xs flex items-center gap-1"><Calendar className="h-3 w-3" /> Дата документа</Label>
              <Input type="date" value={pendingDate} onChange={(e) => setPendingDate(e.target.value)} className="h-8 text-xs" />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Drop zone */}
      <Card
        className={`py-3 gap-2 border-2 border-dashed transition-colors cursor-pointer ${
          dragging ? 'border-primary bg-primary/5' : 'border-border/60 hover:border-primary/50'
        }`}
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        onClick={() => {
          const input = document.createElement('input')
          input.type = 'file'; input.multiple = true
          input.accept = '.pdf,.xlsx,.xls,.csv,.xml,.jpg,.jpeg,.png,.tiff,.eml,.txt,.json,.doc,.docx'
          input.onchange = () => { if (input.files) addFiles(input.files) }
          input.click()
        }}
      >
        <CardContent className="flex flex-col items-center justify-center py-8 gap-2">
          <Upload className={`h-8 w-8 ${dragging ? 'text-primary' : 'text-muted-foreground/40'}`} />
          <div className="text-center">
            <p className="text-sm font-medium">{dragging ? 'Отпустите файлы' : 'Перетащите файлы сюда'}</p>
            <p className="text-[10px] text-muted-foreground mt-1">
              или нажмите для выбора · PDF · Excel · CSV · XML · фото · Email · до 50 МБ
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Очередь + обработка */}
      {items.length > 0 && (
        <Card className="py-3 gap-2">
          <CardHeader className="pb-0">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm flex items-center gap-1.5">
                <FileText className="h-3.5 w-3.5 text-muted-foreground" />
                Файлы
                <span className="text-xs text-muted-foreground font-normal ml-1 tabular-nums">{items.length}</span>
              </CardTitle>
              <div className="flex items-center gap-2">
                <Button variant="ghost" size="sm" className="text-xs h-7 text-muted-foreground"
                  onClick={() => setItems([])} disabled={processing}>Очистить</Button>
                <Button size="sm" className="text-xs h-7 gap-1.5" onClick={handleProcess} disabled={processing || queuedCount === 0}>
                  {processing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
                  Обработать{queuedCount > 0 ? ` (${queuedCount})` : ''}
                </Button>
              </div>
            </div>
          </CardHeader>
          <CardContent className="pt-0 pb-0">
            <div className="space-y-1 max-h-[440px] overflow-y-auto">
              {items.map((it) => {
                const IconComp = getFileIcon(it.file.type)
                return (
                  <div key={it.key} className="flex items-center gap-3 px-2 py-2 text-xs border-b border-border/30 last:border-b-0 hover:bg-accent/20">
                    <IconComp className="h-4 w-4 text-muted-foreground shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-medium truncate">{it.file.name}</span>
                        <span className="text-muted-foreground tabular-nums shrink-0">{formatSize(it.file.size)}</span>
                      </div>
                      {/* прогресс / статус */}
                      {it.status === 'processing' && (
                        <div className="mt-1 h-1 bg-muted rounded overflow-hidden">
                          <div className="h-full bg-primary transition-all" style={{ width: `${it.progress}%` }} />
                        </div>
                      )}
                      <div className="mt-0.5 flex items-center gap-2 text-[10px] text-muted-foreground">
                        {it.channelName && (
                          <span className="inline-flex items-center gap-1"><Radio className="h-2.5 w-2.5" />{it.channelName}</span>
                        )}
                        {it.matchReason && <span className="text-primary/70">авто: {it.matchReason}</span>}
                        {it.resultLabel && <span>распознано: {it.resultLabel}</span>}
                        {it.error && <span className="text-destructive truncate">{it.error}</span>}
                      </div>
                    </div>
                    <StatusPill status={it.status} />
                    {it.status === 'queued' && (
                      <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground hover:text-destructive shrink-0"
                        onClick={() => setItems((prev) => prev.filter((x) => x.key !== it.key))}>
                        <Trash2 className="h-3 w-3" />
                      </Button>
                    )}
                  </div>
                )
              })}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Подсказка */}
      <Card className="py-3 gap-2 border-l-2 border-l-primary/40">
        <CardContent className="pt-0 pb-0">
          <p className="text-xs text-muted-foreground">
            <Badge variant="outline" className="text-[9px] h-4 px-1 mr-1">i</Badge>
            Файлы проходят распознавание и попадают в нормализованную БД (раздел «Документы»)
            с указанным каналом и атрибутами. Если канал не выбран — подбирается автоматически по формату.
          </p>
          <p className="text-xs text-muted-foreground mt-1 pl-1">
            Не нашли нужный канал? <Link to="/channels" className="text-primary hover:underline">Создайте его в разделе «Каналы»</Link>.
          </p>
        </CardContent>
      </Card>
    </div>
  )
}

function StatusPill({ status }: { status: UploadStatus }) {
  if (status === 'done') return <span className="inline-flex items-center gap-1 text-emerald-500 text-[10px] shrink-0"><CheckCircle2 className="h-3.5 w-3.5" />Готово</span>
  if (status === 'error') return <span className="inline-flex items-center gap-1 text-destructive text-[10px] shrink-0"><AlertCircle className="h-3.5 w-3.5" />Ошибка</span>
  if (status === 'processing') return <span className="inline-flex items-center gap-1 text-primary text-[10px] shrink-0"><Loader2 className="h-3.5 w-3.5 animate-spin" />Обработка</span>
  return <span className="text-muted-foreground/60 text-[10px] shrink-0">В очереди</span>
}

/* ─────────────────────── Таб: загрузка таблиц ─────────────────────── */

function TablesUploadTab() {
  const { company, companyId } = useCompany()
  const { data: channels = [] } = useChannels()
  const { data: sources = [] } = useSources()
  const locations = useLocations()
  const { locationIds: globalLocIds } = useFilters()
  const queryClient = useQueryClient()

  const [file, setFile] = useState<File | null>(null)
  const [wb, setWb] = useState<XLSX.WorkBook | null>(null)
  const [sheetNames, setSheetNames] = useState<string[]>([])
  const [activeSheet, setActiveSheet] = useState('')
  const [rows, setRows] = useState<(string | number)[][]>([])
  const [dragging, setDragging] = useState(false)
  const [processing, setProcessing] = useState(false)
  const [error, setError] = useState('')

  const [pendingChannel, setPendingChannel] = useState<string>(AUTO)
  const [pendingLocationId, setPendingLocationId] = useState<string>(globalLocIds.length === 1 ? globalLocIds[0] : '')
  const [pendingDate, setPendingDate] = useState<string>(format(new Date(), 'yyyy-MM-dd'))

  function renderSheet(book: XLSX.WorkBook, name: string) {
    const ws = book.Sheets[name]
    const data = XLSX.utils.sheet_to_json(ws, { header: 1, blankrows: false, defval: '' }) as (string | number)[][]
    setRows(data.slice(0, 60))
  }

  async function loadFile(f: File) {
    setError('')
    try {
      const buf = await f.arrayBuffer()
      const book = XLSX.read(buf, { type: 'array' })
      if (book.SheetNames.length === 0) { setError('В файле нет листов'); return }
      setFile(f); setWb(book); setSheetNames(book.SheetNames)
      setActiveSheet(book.SheetNames[0])
      renderSheet(book, book.SheetNames[0])
    } catch (e) {
      setError('Не удалось прочитать таблицу: ' + String(e))
    }
  }

  function selectSheet(name: string) { setActiveSheet(name); if (wb) renderSheet(wb, name) }
  function reset() { setFile(null); setWb(null); setSheetNames([]); setActiveSheet(''); setRows([]); setError('') }

  function pickFile() {
    const input = document.createElement('input')
    input.type = 'file'; input.accept = '.xlsx,.xls,.csv'
    input.onchange = () => { if (input.files?.[0]) loadFile(input.files[0]) }
    input.click()
  }

  async function handleImport() {
    if (!file) return
    setProcessing(true)
    const channelId = pendingChannel === AUTO
      ? (suggestChannelForFile(file, channels, sources)?.channel.id ?? '')
      : pendingChannel
    const channelName = channels.find((c) => c.id === channelId)?.name ?? ''
    const meta: Record<string, string> = {
      _tableImport: 'true',
      _tableSheet: activeSheet,
    }
    if (channelId) { meta._channelId = channelId; meta._channelName = channelName }
    if (pendingLocationId) meta.locationId = pendingLocationId
    if (pendingDate) meta.docDate = pendingDate
    try {
      await processFile(file, { companyId, profileId: company.profileId, _extraMeta: meta, onUpdate: () => {} })
      queryClient.invalidateQueries({ queryKey: ['entries'] })
      toast.success(`Таблица «${file.name}» импортирована`, { description: `Лист «${activeSheet}» → раздел «Документы»` })
      reset()
    } catch (e) {
      toast.error('Ошибка импорта: ' + String(e))
    } finally { setProcessing(false) }
  }

  const header = rows[0] ?? []
  const body = rows.slice(1)
  const maxCols = Math.min(Math.max(header.length, rows[0]?.length ?? 0) || 1, 12)

  if (!file) {
    return (
      <Card
        className={`py-3 gap-2 border-2 border-dashed transition-colors cursor-pointer ${dragging ? 'border-primary bg-primary/5' : 'border-border/60 hover:border-primary/50'}`}
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); if (e.dataTransfer.files[0]) loadFile(e.dataTransfer.files[0]) }}
        onClick={pickFile}
      >
        <CardContent className="flex flex-col items-center justify-center py-12 gap-2">
          <Table2 className={`h-8 w-8 ${dragging ? 'text-primary' : 'text-muted-foreground/40'}`} />
          <p className="text-sm font-medium">{dragging ? 'Отпустите таблицу' : 'Перетащите Excel или CSV'}</p>
          <p className="text-[10px] text-muted-foreground">или нажмите для выбора · .xlsx · .xls · .csv · с предпросмотром и выбором листа</p>
          {error && <p className="text-xs text-destructive mt-1">{error}</p>}
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      {/* Файл + листы */}
      <Card className="py-3 gap-2">
        <CardContent className="pt-0 pb-0 flex items-center gap-3 flex-wrap">
          <FileSpreadsheet className="h-5 w-5 text-emerald-500 shrink-0" />
          <div className="min-w-0">
            <div className="text-sm font-medium truncate">{file.name}</div>
            <div className="text-[11px] text-muted-foreground">{formatSize(file.size)} · листов: {sheetNames.length}</div>
          </div>
          {sheetNames.length > 1 && (
            <div className="flex items-center gap-1.5 ml-2">
              <Sheet className="h-3.5 w-3.5 text-muted-foreground" />
              <Select value={activeSheet} onValueChange={selectSheet}>
                <SelectTrigger className="h-8 w-[180px] text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {sheetNames.map((n) => <SelectItem key={n} value={n} className="text-xs">{n}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          )}
          <Button variant="ghost" size="sm" className="h-8 text-xs ml-auto" onClick={reset}>Выбрать другой</Button>
        </CardContent>
      </Card>

      {/* Параметры */}
      <Card className="py-3 gap-2">
        <CardContent className="pt-0 pb-0">
          <div className="grid sm:grid-cols-3 gap-3">
            <div className="space-y-1.5">
              <Label className="text-xs flex items-center gap-1"><Radio className="h-3 w-3" /> Канал</Label>
              <Select value={pendingChannel} onValueChange={setPendingChannel}>
                <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value={AUTO} className="text-xs"><span className="flex items-center gap-1.5"><Wand2 className="h-3 w-3" /> Автоподбор</span></SelectItem>
                  {channels.map((c) => <SelectItem key={c.id} value={c.id} className="text-xs">{c.name}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Точка обслуживания</Label>
              <Select value={pendingLocationId || 'none'} onValueChange={(v) => setPendingLocationId(v === 'none' ? '' : v)}>
                <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="Без привязки" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="none" className="text-xs text-muted-foreground">Без привязки</SelectItem>
                  {locations.map((l) => <SelectItem key={l.id} value={l.id} className="text-xs"><span className="font-mono text-muted-foreground mr-2">{l.code}</span>{l.name}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs flex items-center gap-1"><Calendar className="h-3 w-3" /> Дата</Label>
              <Input type="date" value={pendingDate} onChange={(e) => setPendingDate(e.target.value)} className="h-8 text-xs" />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Предпросмотр */}
      <Card className="py-3 gap-2">
        <CardHeader className="pb-0">
          <CardTitle className="text-sm flex items-center gap-1.5">
            <Table2 className="h-3.5 w-3.5 text-muted-foreground" /> Предпросмотр · лист «{activeSheet}»
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-0 pb-0">
          <div className="overflow-auto max-h-[360px] rounded-md border border-border/60">
            <table className="text-xs border-collapse w-full">
              <thead className="sticky top-0 bg-card">
                <tr>
                  <th className="px-2 py-1 text-[10px] text-muted-foreground/60 border-b border-r border-border/50 w-10">#</th>
                  {Array.from({ length: maxCols }).map((_, i) => (
                    <th key={i} className="px-2 py-1 text-left font-medium border-b border-r border-border/50 whitespace-nowrap">
                      {String(header[i] ?? `Кол. ${i + 1}`)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {body.slice(0, 40).map((row, ri) => (
                  <tr key={ri} className="hover:bg-accent/30">
                    <td className="px-2 py-1 text-[10px] text-muted-foreground/50 border-b border-r border-border/40 tabular-nums">{ri + 1}</td>
                    {Array.from({ length: maxCols }).map((_, ci) => (
                      <td key={ci} className="px-2 py-1 border-b border-r border-border/40 whitespace-nowrap max-w-[220px] truncate">{String(row[ci] ?? '')}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between mt-3 gap-3 flex-wrap">
            <p className="text-[11px] text-muted-foreground">Показаны первые строки листа. При импорте таблица сохраняется как документ в разделе «Документы».</p>
            <Button size="sm" className="h-8 text-xs gap-1.5" onClick={handleImport} disabled={processing}>
              {processing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
              Импортировать таблицу
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

/* ─────────────────────── Таб: каналы и расписание ─────────────────────── */

const STATUS_META: Record<string, { label: string; cls: string; Icon: typeof CheckCircle2 }> = {
  active: { label: 'Активен', cls: 'text-emerald-500', Icon: CheckCircle2 },
  paused: { label: 'Пауза', cls: 'text-amber-500', Icon: Pause },
  error: { label: 'Ошибка', cls: 'text-red-500', Icon: AlertCircle },
  draft: { label: 'Черновик', cls: 'text-muted-foreground', Icon: Clock },
}

function scheduleOf(ch: Channel): ScheduleConfig {
  if (typeof ch.schedule === 'string' || !ch.schedule) return { ...DEFAULT_SCHEDULE }
  return ch.schedule
}
function modeLabel(mode: ScheduleMode, cfg: ScheduleConfig): string {
  if (mode === 'manual') return 'Вручную'
  if (mode === 'interval') return `Каждые ${cfg.intervalMinutes ?? 60} мин`
  return `Cron${cfg.cronExpression ? ` · ${cfg.cronExpression}` : ''}`
}

function ChannelsScheduleTab() {
  const { data: channels = [], refetch } = useChannels()
  const { data: sources = [] } = useSources()
  const [scheduleOpen, setScheduleOpen] = useState(false)
  const [runningId, setRunningId] = useState<string | null>(null)

  const refresh = () => { refetch() }
  const autoCount = channels.filter((c) => scheduleOf(c).mode !== 'manual').length

  async function handleRun(ch: Channel) {
    // Файловые каналы (реестр/сессии) запускаются НЕ отсюда, а со страницы канала
    // (карточка «Загрузка таблицы» — файл + режим); на мониторе у них ссылка
    // «Открыть канал». Поэтому handleRun вызывается только для STS/API-каналов.
    setRunningId(ch.id)
    try {
      if (isApiEnabled()) {
        await runChannel(ch.id)
        toast.success(`Прогон «${ch.name}» запущен`, { description: 'Идёт в фоне — прогресс на странице канала' })
      } else {
        await syncChannel(ch, {})
        toast.success(`Pipeline «${ch.name}» завершён`)
      }
      refresh()
    } catch (e) {
      toast.error(String(e))
    } finally {
      setRunningId(null)
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">
          {channels.length} каналов · {autoCount} на автозагрузке
        </p>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" className="h-8 text-xs gap-1.5" onClick={() => setScheduleOpen(true)}>
            <Settings2 className="h-3.5 w-3.5" /> Настроить расписание
          </Button>
          <Button asChild variant="ghost" size="sm" className="h-8 text-xs gap-1.5">
            <Link to="/channels"><ExternalLink className="h-3.5 w-3.5" /> Все каналы</Link>
          </Button>
        </div>
      </div>

      {channels.length === 0 ? (
        <Card className="py-8">
          <CardContent className="flex flex-col items-center justify-center gap-2 text-muted-foreground">
            <Radio className="h-8 w-8 opacity-30" />
            <p className="text-sm">Каналов пока нет</p>
            <Button asChild size="sm" variant="outline" className="text-xs h-7 mt-1">
              <Link to="/channels">Создать канал</Link>
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-2">
          {channels.map((ch) => {
            const cfg = scheduleOf(ch)
            const meta = STATUS_META[ch.status] ?? STATUS_META.draft
            const chSources = sources.filter((s) => getChannelSourceIds(ch).includes(s.id))
            const nextSync = getNextSyncTime(ch)
            const running = runningId === ch.id
            // Файловый канал (реестр/сессии): загрузка — только на странице канала
            // (файл + режим Подгрузить/Переписать). На мониторе — ссылка «Открыть
            // канал», а не «Запустить сейчас» (у файла нет расписания/автотяги).
            const isFileChannel = ch.templateId === 'charge_sessions'
              || ch.templateId === 'reestr_contracts_payments'
            return (
              <Card key={ch.id} className="py-3 gap-1">
                <CardContent className="py-0 flex items-center gap-3 flex-wrap">
                  <Radio className="h-4 w-4 text-primary shrink-0" />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <Link to={`/connectors/${ch.id}`} className="font-medium text-sm hover:underline truncate">{ch.name}</Link>
                      <span className={`inline-flex items-center gap-1 text-[11px] ${meta.cls}`}>
                        <meta.Icon className="h-3.5 w-3.5" />{meta.label}
                      </span>
                      <Badge variant="outline" className="text-[10px] gap-1">
                        <Clock className="h-2.5 w-2.5" />{modeLabel(cfg.mode, cfg)}
                      </Badge>
                    </div>
                    <div className="mt-0.5 flex items-center gap-3 text-[11px] text-muted-foreground flex-wrap">
                      {chSources.length > 0 && (
                        <span className="inline-flex items-center gap-1">
                          <Database className="h-2.5 w-2.5" />{chSources.map((s) => s.name).join(', ')}
                        </span>
                      )}
                      <span className="tabular-nums">{ch.docsLoaded} док.</span>
                      {ch.lastSync && <span>синхр: {format(new Date(ch.lastSync), 'dd.MM HH:mm')}</span>}
                      {nextSync && <span className="text-primary">след: {format(nextSync, 'dd.MM HH:mm')}</span>}
                    </div>
                  </div>
                  {isFileChannel ? (
                    <Button asChild size="sm" variant="outline" className="h-8 text-xs gap-1.5 shrink-0">
                      <Link to={`/connectors/${ch.id}`}>
                        <ExternalLink className="h-3.5 w-3.5" />
                        Открыть канал
                      </Link>
                    </Button>
                  ) : (
                    <Button size="sm" className="h-8 text-xs gap-1.5 shrink-0" onClick={() => handleRun(ch)} disabled={running}>
                      {running ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
                      Запустить сейчас
                    </Button>
                  )}
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}

      <ScheduleOverview open={scheduleOpen} onOpenChange={(v) => { setScheduleOpen(v); if (!v) refresh() }} />
    </div>
  )
}

/* ─────────────────────────── страница ─────────────────────────── */

export function IntakePage() {
  return (
    <div className="space-y-4 max-w-6xl">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Загрузка</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Приём данных в пространство: первичные документы с разбором и проверками,
          загрузка файлов и таблиц с диска, каналы и расписание обновления.
        </p>
      </div>

      <Tabs defaultValue="primary">
        <TabsList variant="line" className="w-full justify-start gap-5 rounded-none border-b border-border/50 px-0 h-10">
          {/* Первичка — главный вход раздела: документы в учёт принимаются здесь,
              с разбором и проверками. Остальные вкладки — вспомогательный контур. */}
          <TabsTrigger value="primary" className="flex-none gap-1.5 px-1 text-[13px]">
            <FileCheck className="h-3.5 w-3.5" /> Первичные документы
          </TabsTrigger>
          <TabsTrigger value="mail" className="flex-none gap-1.5 px-1 text-[13px]">
            <Mail className="h-3.5 w-3.5" /> Почта
          </TabsTrigger>
          <TabsTrigger value="files" className="flex-none gap-1.5 px-1 text-[13px]">
            <Upload className="h-3.5 w-3.5" /> Загрузка файлов
          </TabsTrigger>
          <TabsTrigger value="tables" className="flex-none gap-1.5 px-1 text-[13px]">
            <Table2 className="h-3.5 w-3.5" /> Таблицы
          </TabsTrigger>
          <TabsTrigger value="channels" className="flex-none gap-1.5 px-1 text-[13px]">
            <Radio className="h-3.5 w-3.5" /> Каналы и расписание
          </TabsTrigger>
        </TabsList>
        <TabsContent value="primary" className="mt-4">
          <IntakeDocs />
        </TabsContent>
        <TabsContent value="mail" className="mt-4">
          <MailConnector />
        </TabsContent>
        <TabsContent value="files" className="mt-4">
          <FilesUploadTab />
        </TabsContent>
        <TabsContent value="tables" className="mt-4">
          <TablesUploadTab />
        </TabsContent>
        <TabsContent value="channels" className="mt-4">
          <ChannelsScheduleTab />
        </TabsContent>
      </Tabs>
    </div>
  )
}

export default IntakePage
