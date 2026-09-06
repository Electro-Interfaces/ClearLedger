import { useDeferredValue, useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  AlertCircle, ArrowDownToLine, CheckCircle2, ChevronDown, ChevronLeft, ChevronRight, Circle, FileCheck2,
  FileSearch, Files, Link2, LoaderCircle, Printer, RefreshCw, Search, ShieldAlert,
  Trash2, Upload,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { ShiftPassportSheet } from './ShiftPassportSheet'
import {
  downloadStoreDocumentFile, getStoreDocumentBundle, getStoreDocumentPayload,
  DIFF_PRINTABLE_KINDS, listStoreDocuments, openStoreDocumentPrintForm, PRINTABLE_KINDS,
  rebuildStoreDocuments, tombstoneStoreDocumentFile, uploadStoreDocumentFile,
  type StoreDocumentBrief, type StoreDocumentBundle, type StoreDocumentCounter,
  type StoreDocumentFile, type StoreDocumentPayloadResponse, type StoreDocumentStats,
  listStoreShifts, type StoreShiftBrief,
  getStoreTriage, type StoreTriageQueue,
} from '@/services/storeDocumentsService'
import { ApiError } from '@/services/apiClient'

const PAGE_SIZE = 50
const EMPTY_STATS: StoreDocumentStats = {
  attention: 0, missing_evidence: 0, not_accounting_ready: 0, onec_mismatch: 0,
}

const KIND_LABELS: Record<string, string> = {
  purchase: 'Поступление', return_purchase: 'Возврат поставщику', transfer: 'Перемещение',
  inventory: 'Инвентаризация', gain: 'Оприходование', writeoff: 'Списание',
  retail_sale_sidegoods: 'Отчёт о розничных продажах', return_sale: 'Возврат продажи',
  recipe: 'Рецептура', production_release: 'Выпуск продукции',
  ingredients_writeoff: 'Списание ингредиентов', fiscal_receipt: 'Кассовый чек',
  store_shift: 'Смена магазина', revaluation: 'Переоценка',
}

// Виды движений остатка (по строке на товар) — для свёрнутой строки в «Связи и
// движения», чтобы не сыпать техническими кодами receipt_acceptance ×N.
const MOVEMENT_LABELS: Record<string, string> = {
  receipt_acceptance: 'приёмка на склад', sale: 'продажа', return_sale: 'возврат продажи',
  writeoff: 'списание', gain: 'оприходование', inventory: 'инвентаризация',
  transfer: 'перемещение', return_purchase: 'возврат поставщику',
}

// Секции-фильтры реестра смен: группа → виды документов, входящие в неё. Клик по
// чипу оставляет смены, где такой разрез есть («где были поступления»). Группы
// совпадают с секциями листа документа ОРП (макет orp-shema-predstavleniya).
const SECTION_FILTERS: { key: string; label: string; kinds: string[] }[] = [
  { key: 'sale', label: 'Продажи', kinds: ['retail_sale_sidegoods', 'return_sale'] },
  { key: 'food', label: 'Общепит', kinds: ['production_release', 'recipe', 'ingredients_writeoff'] },
  { key: 'purchase', label: 'Поступления', kinds: ['purchase', 'return_purchase'] },
  { key: 'inventory', label: 'Инвентаризации', kinds: ['inventory'] },
  { key: 'transfer', label: 'Перемещения', kinds: ['transfer'] },
  { key: 'gain', label: 'Оприходования', kinds: ['gain'] },
  { key: 'writeoff', label: 'Списания', kinds: ['writeoff'] },
  { key: 'price', label: 'Переоценки', kinds: ['revaluation'] },
]

// Готовность смены к выгрузке в бухгалтерию — светофор макета. Пока двухцветно:
// Светофор смены — из readiness бэка (тот же источник, что лист смены), чтобы
// цвет в списке и внутри совпадал. g готова · y можно грузить · r не грузить.
function shiftReadiness(s: StoreShiftBrief): { color: 'g' | 'y' | 'r'; label: string } {
  if (s.readiness === 'r') return { color: 'r', label: 'не уедет' }
  if (s.readiness === 'y') return { color: 'y', label: 'можно грузить' }
  return { color: 'g', label: 'готова' }
}

// Чек и кассовая смена в фильтр не выносятся: они доказательство продажи, а не
// учётный документ, и разбираются в разделе «Касса». Раздел «Документы» —
// про всё остальное: приёмки, перемещения, пересчёты, списания, отчёты смен.
const KIND_OPTIONS = Object.entries(KIND_LABELS)
  .filter(([вид]) => вид !== 'fiscal_receipt' && вид !== 'store_shift')


// Каждый счётчик — рабочий отбор: сервер считает и фильтрует одним выражением,
// поэтому число над таблицей и содержимое таблицы не могут разойтись.
// Карточки-счётчики наверху — только те, что есть в StoreDocumentStats
// (waiting_receipt своей карточки не имеет, живёт лишь как переход из Разбора).
const COUNTERS: Array<{ key: keyof StoreDocumentStats; label: string; icon: typeof AlertCircle }> = [
  { key: 'attention', label: 'Требуют внимания', icon: AlertCircle },
  { key: 'missing_evidence', label: 'Нет подтверждений', icon: Files },
  { key: 'not_accounting_ready', label: 'Учёт вернул документ', icon: FileCheck2 },
  { key: 'onec_mismatch', label: 'Расхождение с 1С', icon: ShieldAlert },
]

const STATUS_LABELS: Record<string, string> = {
  ready: 'готов', accepted: 'принят', needs_review: 'нужна проверка', blocked: 'заблокирован',
  pending: 'ожидает', queued: 'в очереди', sent_waiting_ack: 'ждёт ответа', rejected: 'отклонён',
  draft: 'черновик', expected: 'ожидается', done: 'выполнен', sent: 'поставлен в очередь',
  reversed: 'сторнирован', unposted: 'не проведён', posted: 'проведён',
  onec_snapshot: 'снимок 1С', validated: 'проверен', shadow_validated: 'теневая проверка пройдена',
  shadow_rejected: 'теневая проверка не пройдена', shadow_mismatch: 'расхождение теневой проверки',
  not_applicable: 'Не учётный документ',
  matched: 'сверен', unmatched: 'не сопоставлен', none: 'нет расхождений',
  minor: 'небольшое', material: 'существенное', critical: 'критическое',
  // Коды, которые до сих пор доезжали до экрана как есть. Оператор читает
  // «line_identity_ambiguous» как поломку, хотя это норма розницы: две
  // одинаковых позиции в чеке дают строки без собственного идентификатора.
  received: 'доставлен', local: 'на станции', unknown: 'неизвестно',
  // Приход, попавший в стартовый остаток: документ реален, но движений не даёт —
  // иначе товар посчитается дважды. Такое бывает один раз, при переносе учёта.
  in_baseline: 'учтено в стартовом остатке',
  quarantined: 'на карантине', line_identity_ambiguous: 'строки без ключа',
  sale: 'продажа', return: 'возврат', closed: 'закрыта', open: 'открыта',
  station: 'со станции', center: 'из центра', edo: 'из ЭДО',
}

const SOURCE_LABELS: Record<string, string> = {
  edge: 'Агент станции', store: 'Центральный магазин', onec_legacy: '1С до перехода',
  edo: 'ЭДО', cash: 'Касса', bp: 'БП ГИГ',
}

interface StoreDocumentsPanelProps {
  dateFrom: string
  dateTo: string
  stations: string[]
  /** С какого вида открывается пункт меню: разбор, смены или список. */
  startView?: 'triage' | 'list' | 'shifts'
  /** Какие вкладки показывать в переключателе (по умолчанию все три). */
  views?: Array<'triage' | 'shifts' | 'list'>
  /** Виды документов пункта: пусто — весь документооборот станции. */
  kinds?: string[]
  /** Заголовок пункта меню; без него — общий заголовок раздела. */
  heading?: { title: string; subtitle: string }
}

interface SelectFilterProps {
  label: string
  value: string
  options: Array<[string, string]>
  onChange: (value: string) => void
}

function SelectFilter({ label, value, options, onChange }: SelectFilterProps) {
  return (
    <Select value={value || 'all'} onValueChange={(next) => onChange(next === 'all' ? '' : next)}>
      <SelectTrigger size="sm" className="min-w-36 max-w-52" aria-label={label}>
        <SelectValue placeholder={label} />
      </SelectTrigger>
      <SelectContent>
        <SelectGroup>
          <SelectItem value="all">{label}: все</SelectItem>
          {options.map(([key, name]) => <SelectItem key={key} value={key}>{name}</SelectItem>)}
        </SelectGroup>
      </SelectContent>
    </Select>
  )
}

function fmtMoney(value: number | null | undefined) {
  return value == null ? '—' : new Intl.NumberFormat('ru-RU', {
    style: 'currency', currency: 'RUB', maximumFractionDigits: 2,
  }).format(value)
}

function fmtDate(value: string | null | undefined) {
  return value ? new Date(value).toLocaleString('ru-RU', {
    day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
  }) : '—'
}

function fmtBytes(value: number) {
  if (value < 1024) return `${value} Б`
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} КБ`
  return `${(value / 1024 / 1024).toFixed(1)} МБ`
}

function statusLabel(value: string | null | undefined) {
  return value ? STATUS_LABELS[value] ?? value : 'не задан'
}

function StatusBadge({ value, attention = false }: { value: string | null | undefined; attention?: boolean }) {
  const variant = attention || ['blocked', 'rejected', 'critical', 'needs_review', 'unmatched'].includes(value ?? '')
    ? 'destructive' : ['ready', 'accepted', 'matched', 'none'].includes(value ?? '') ? 'secondary' : 'outline'
  return <Badge variant={variant}>{statusLabel(value)}</Badge>
}

function Metric({ label, value, icon: Icon, active, onClick }: { label: string; value: number; icon: typeof AlertCircle; active?: boolean; onClick?: () => void }) {
  const content = (
    <div className="flex min-w-0 items-center gap-3 px-4 py-3">
      <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
      <div className="min-w-0">
        <div className="text-lg font-semibold tabular-nums leading-none">{value.toLocaleString('ru-RU')}</div>
        <div className="mt-1 truncate text-xs text-muted-foreground">{label}</div>
      </div>
    </div>
  )
  return onClick ? <button type="button" onClick={onClick} aria-pressed={active} className="min-w-0 border-r border-border text-left last:border-r-0 hover:bg-muted/40 aria-pressed:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset">{content}</button>
    : <div className="min-w-0 border-r border-border last:border-r-0">{content}</div>
}

function DetailField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 break-words text-sm">{children || '—'}</dd>
    </div>
  )
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function documentLines(document: Record<string, unknown>) {
  const rows: Array<{ section: string; value: Record<string, unknown> }> = []
  for (const [section, value] of Object.entries(document)) {
    if (!Array.isArray(value)) continue
    if (!['Товары', 'Услуги', 'lines', 'services', 'items', 'Строки'].includes(section)) continue
    value.forEach((item) => rows.push({ section, value: asRecord(item) }))
  }
  return rows
}

function firstValue(row: Record<string, unknown>, keys: string[]) {
  for (const key of keys) if (row[key] !== undefined && row[key] !== null && row[key] !== '') return String(row[key])
  return '—'
}

function DetailSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="grid gap-3" aria-label={title}>
      <h3 className="text-sm font-semibold">{title}</h3>
      {children}
    </section>
  )
}

type DocHint = { kind: string; number: string | null; document_at: string | null }

function DocumentSheet({ recordId, hint, onClose }: { recordId: string | null; hint?: DocHint | null; onClose: () => void }) {
  const [bundle, setBundle] = useState<StoreDocumentBundle | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [payload, setPayload] = useState<StoreDocumentPayloadResponse | null>(null)
  const [payloadLoading, setPayloadLoading] = useState(false)
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [uploadRole, setUploadRole] = useState('накладная')
  const [uploadNote, setUploadNote] = useState('')
  const [fileBusy, setFileBusy] = useState(false)
  const [fileWriteDenied, setFileWriteDenied] = useState(false)
  const [tombstoneId, setTombstoneId] = useState('')
  const [tombstoneReason, setTombstoneReason] = useState('')
  const [printing, setPrinting] = useState(false)

  const printForm = async (variant: 'main' | 'diff' = 'main') => {
    if (!recordId) return
    setPrinting(true)
    setError('')
    try {
      await openStoreDocumentPrintForm(recordId, variant)
    } catch (reason) {
      setError(reason instanceof ApiError && reason.status === 409
        ? (reason.message || 'Печатной формы у этого документа нет')
        : reason instanceof Error ? reason.message : 'Печатная форма не открылась')
    } finally {
      setPrinting(false)
    }
  }

  useEffect(() => {
    if (!recordId) return
    let active = true
    setLoading(true)
    setError('')
    setBundle(null)
    setPayload(null)
    setFileWriteDenied(false)
    setUploadFile(null)
    setTombstoneId('')
    getStoreDocumentBundle(recordId)
      .then((next) => { if (active) setBundle(next) })
      .catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : 'Не удалось открыть документ') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [recordId])

  const loadPayload = async () => {
    if (!recordId) return
    setPayloadLoading(true)
    try {
      setPayload(await getStoreDocumentPayload(recordId))
    } catch (reason) {
      setPayload({ available: false, detail: reason instanceof Error ? reason.message : 'Не удалось получить данные' })
    } finally {
      setPayloadLoading(false)
    }
  }

  const download = async (file: StoreDocumentFile) => {
    try {
      await downloadStoreDocumentFile(file)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Не удалось скачать файл')
    }
  }

  const refreshFiles = async () => {
    if (!recordId) return
    setBundle(await getStoreDocumentBundle(recordId))
  }

  const handleFileError = (reason: unknown) => {
    if (reason instanceof ApiError && reason.status === 403) {
      setFileWriteDenied(true)
      setError('Для вашей роли файлы доступны только для просмотра.')
      return
    }
    setError(reason instanceof Error ? reason.message : 'Операция с файлом не выполнена')
  }

  const addFile = async () => {
    if (!recordId || !uploadFile) return
    setFileBusy(true)
    setError('')
    try {
      await uploadStoreDocumentFile(recordId, uploadFile, uploadRole, uploadNote.trim() || undefined)
      await refreshFiles()
      setUploadFile(null)
      setUploadNote('')
    } catch (reason) {
      handleFileError(reason)
    } finally {
      setFileBusy(false)
    }
  }

  const tombstone = async () => {
    if (!recordId || !tombstoneId || tombstoneReason.trim().length < 3) return
    setFileBusy(true)
    setError('')
    try {
      await tombstoneStoreDocumentFile(recordId, tombstoneId, tombstoneReason.trim())
      await refreshFiles()
      setTombstoneId('')
      setTombstoneReason('')
    } catch (reason) {
      handleFileError(reason)
    } finally {
      setFileBusy(false)
    }
  }

  const detail = bundle?.detail
  // Шапку показываем сразу из подсказки (kind/number/дата от строки-источника),
  // а после загрузки уточняем из detail — статус и печать зависят от него.
  const вид = detail?.kind ?? hint?.kind ?? ''
  const номер = detail?.number ?? hint?.number ?? null
  const когда = detail?.document_at ?? hint?.document_at ?? null
  const lines = detail ? documentLines(detail.document) : []
  // «строк нет» и «источник их не отдаёт» — разные вещи, и путать их нельзя
  const headerOnly = detail?.document.detail_mode === 'header_only'
  const readOnlyFiscal = detail?.kind === 'fiscal_receipt' || detail?.kind === 'store_shift'
  const canWriteFiles = Boolean(detail?.file_write_allowed) && !readOnlyFiscal && !fileWriteDenied

  return (
    <Dialog open={Boolean(recordId)} onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent className="flex max-h-[92vh] max-w-4xl flex-col gap-0 overflow-hidden p-0">
        <DialogHeader className="border-b px-6 py-4 pr-14 text-left">
          <div className="flex flex-wrap items-center gap-2">
            <DialogTitle>{вид ? KIND_LABELS[вид] ?? вид : 'Документ'}</DialogTitle>
            {detail && <StatusBadge value={detail.accounting_status} attention={detail.requires_attention} />}
            {readOnlyFiscal && <Badge variant="outline">только просмотр</Badge>}
          </div>
          <DialogDescription>
            {номер ? `№ ${номер}` : 'Без номера'} · {fmtDate(когда)}
          </DialogDescription>
          <div className="flex flex-wrap gap-2">
            {вид && PRINTABLE_KINDS.has(вид) && (
              <Button variant="outline" size="sm" disabled={printing}
                onClick={() => void printForm()}>
                {printing ? <LoaderCircle data-icon className="animate-spin" /> : <Printer data-icon />}
                Печатная форма
              </Button>
            )}
            {вид && DIFF_PRINTABLE_KINDS.has(вид) && (
              <Button variant="outline" size="sm" disabled={printing}
                onClick={() => void printForm('diff')}>
                <Printer data-icon />
                {вид === 'purchase' ? 'Акт расхождения (ТОРГ-2)' : 'Сличительная ведомость (ИНВ-19)'}
              </Button>
            )}
          </div>
        </DialogHeader>

        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="grid gap-5 p-4 sm:p-5">
            {loading && <div className="grid gap-3" aria-label="Загрузка документа"><Skeleton className="h-24" /><Skeleton className="h-40" /><Skeleton className="h-28" /></div>}
            {error && (
              <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive" role="alert">
                <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />{error}
              </div>
            )}
            {detail && (
              <>
                {(detail.issues?.length ?? 0) > 0 && (
                  <ul className="grid gap-2">
                    {detail.issues!.map((проблема) => (
                      <li key={проблема.code}
                        className={`rounded-md border p-3 text-sm ${
                          проблема.owner === 'человек' ? 'border-amber-500/40 bg-amber-500/5'
                            : проблема.owner === 'разработка' ? 'border-destructive/40 bg-destructive/5'
                            : 'border-border'}`}>
                        <div className="flex items-start gap-2">
                          {проблема.owner === 'никто'
                            ? <FileSearch className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                            : <AlertCircle className={`mt-0.5 size-4 shrink-0 ${
                                проблема.owner === 'человек' ? 'text-amber-500' : 'text-destructive'}`} aria-hidden="true" />}
                          <div className="min-w-0">
                            <div className="font-medium">{проблема.text}</div>
                            <div className="mt-0.5 text-muted-foreground">{проблема.hint}</div>
                            <div className="mt-1 text-xs text-muted-foreground">
                              {проблема.owner === 'человек' ? 'Исправляется здесь, в интерфейсе'
                                : проблема.owner === 'разработка' ? 'Чинится в коде — сообщите разработке'
                                : 'Действий не требует'}
                            </div>
                          </div>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
                {(detail.timeline?.length ?? 0) > 0 && (
                  <ol className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-md border p-3 text-sm">
                    {detail.timeline!.map((шаг, индекс) => (
                      <li key={шаг.code} className="flex items-center gap-2">
                        {индекс > 0 && <ChevronRight className="size-3 text-muted-foreground" aria-hidden="true" />}
                        <span className={`flex items-center gap-1.5 ${шаг.done ? '' : 'text-muted-foreground'}`}>
                          {шаг.done
                            ? <CheckCircle2 className="size-3.5 shrink-0 text-emerald-500" aria-hidden="true" />
                            : <Circle className="size-3.5 shrink-0" aria-hidden="true" />}
                          {шаг.text}
                          {шаг.at && <span className="text-xs text-muted-foreground">{fmtDate(шаг.at)}</span>}
                        </span>
                      </li>
                    ))}
                  </ol>
                )}
                <DetailSection title="1. Реквизиты">
                  <dl className="grid gap-3 rounded-md border p-3 sm:grid-cols-2">
                    <DetailField label="Станция">{detail.station_id ? `АЗС ${detail.station_id}` : 'Центральный склад'}</DetailField>
                    <DetailField label="Смена">
                      {detail.shift_no
                        ? `№ ${detail.shift_no} — документ порождён сменой`
                        : 'вне смены — документ влияет на остаток, но в смену не входит'}
                    </DetailField>
                    <DetailField label="Контрагент">{detail.counterparty || '—'}</DetailField>
                    <DetailField label="ИНН">{detail.counterparty_inn || '—'}</DetailField>
                    <DetailField label="Сумма">{fmtMoney(detail.amount)}</DetailField>
                    <DetailField label="НДС">{fmtMoney(detail.vat_amount)}</DetailField>
                    <DetailField label="Источник">{SOURCE_LABELS[detail.projection_source] ?? detail.projection_source}</DetailField>
                    {detail.transfer_route && <DetailField label="Направление">{detail.transfer_route}</DetailField>}
                  </dl>
                </DetailSection>
                <Separator />
                <DetailSection title={detail.revaluation ? '2. Изменение цены' : '2. Строки'}>
                  {detail.revaluation ? (
                    <dl className="grid gap-3 rounded-md border p-3 sm:grid-cols-2">
                      <DetailField label="Товар">{detail.revaluation.name || detail.revaluation.barcode || '—'}</DetailField>
                      <DetailField label="Штрихкод">{detail.revaluation.barcode || '—'}</DetailField>
                      <DetailField label="Было">{fmtMoney(detail.revaluation.from)}</DetailField>
                      <DetailField label="Стало">{fmtMoney(detail.revaluation.to)}</DetailField>
                      <DetailField label="Причина">{detail.revaluation.reason || '—'}</DetailField>
                    </dl>
                  ) : headerOnly ? (
                    <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
                      Доступна только шапка документа. {detail.document.detail_note}
                    </p>
                  ) : lines.length ? (
                    <div className="overflow-x-auto rounded-md border">
                      <Table className="min-w-[32rem]">
                        <TableHeader><TableRow><TableHead>Номенклатура / услуга</TableHead><TableHead>Количество</TableHead><TableHead className="text-right">Сумма</TableHead></TableRow></TableHeader>
                        <TableBody>{lines.map((line, index) => (
                          <TableRow key={`${line.section}-${index}`}>
                            <TableCell className="max-w-96 whitespace-normal">{firstValue(line.value, ['name', 'Наименование', 'Номенклатура', 'НоменклатураНаименование', 'service_name'])}</TableCell>
                            <TableCell>{firstValue(line.value, ['quantity', 'qty', 'Количество', 'qty_fact'])}</TableCell>
                            <TableCell className="text-right tabular-nums">{firstValue(line.value, ['amount', 'Сумма', 'sum'])}</TableCell>
                          </TableRow>
                        ))}</TableBody>
                      </Table>
                    </div>
                  ) : <p className="text-sm text-muted-foreground">Безопасные товарные строки для этого документа не опубликованы.</p>}
                </DetailSection>
                <Separator />
                <DetailSection title="3. Подтверждения и файлы">
                  {bundle.files.length ? <div className="grid gap-2">{bundle.files.map((file) => (
                    <div key={file.id} className="flex items-center justify-between gap-3 rounded-md border p-3">
                      <div className="min-w-0"><div className="truncate text-sm font-medium">{file.file_name}</div><div className="text-xs text-muted-foreground">{file.role} · {fmtBytes(file.size_bytes)} · рев. {file.revision}</div></div>
                      <div className="flex shrink-0 items-center gap-1"><Button size="icon-sm" variant="ghost" onClick={() => void download(file)} aria-label={`Скачать ${file.file_name}`}><ArrowDownToLine data-icon aria-hidden="true" /></Button>{canWriteFiles && <Button size="icon-sm" variant="ghost" onClick={() => { setTombstoneId(file.id); setTombstoneReason('') }} aria-label={`Убрать ${file.file_name}`}><Trash2 data-icon aria-hidden="true" /></Button>}</div>
                    </div>
                  ))}</div> : <p className="text-sm text-muted-foreground">Файлы-подтверждения не приложены.</p>}
                  {canWriteFiles && <div className="grid gap-2 rounded-md border border-dashed p-3">
                    <div className="flex flex-wrap gap-2">
                      <Select value={uploadRole} onValueChange={setUploadRole}><SelectTrigger size="sm" aria-label="Роль файла"><SelectValue /></SelectTrigger><SelectContent><SelectGroup>{['накладная', 'упд', 'акт', 'опись', 'фото', 'прочее'].map((role) => <SelectItem key={role} value={role}>{role}</SelectItem>)}</SelectGroup></SelectContent></Select>
                      <Input type="file" accept="application/pdf,image/jpeg,image/png,image/webp" className="h-8 min-w-52 flex-1" onChange={(event) => setUploadFile(event.target.files?.[0] ?? null)} aria-label="Файл подтверждения" />
                    </div>
                    <div className="flex flex-wrap gap-2"><Input value={uploadNote} onChange={(event) => setUploadNote(event.target.value)} placeholder="Примечание, необязательно" aria-label="Примечание к файлу" className="h-8 min-w-52 flex-1" /><Button size="sm" onClick={() => void addFile()} disabled={!uploadFile || fileBusy}>{fileBusy ? <LoaderCircle data-icon className="animate-spin" /> : <Upload data-icon />}Приложить</Button></div>
                    <p className="text-xs text-muted-foreground">Запись доступна только в пределах выданных сервером полномочий.</p>
                  </div>}
                  {tombstoneId && canWriteFiles && <div className="flex flex-wrap gap-2 rounded-md border p-3"><Input value={tombstoneReason} onChange={(event) => setTombstoneReason(event.target.value)} placeholder="Причина удаления (не менее 3 символов)" aria-label="Причина удаления файла" className="min-w-64 flex-1" autoFocus /><Button variant="destructive" size="sm" disabled={tombstoneReason.trim().length < 3 || fileBusy} onClick={() => void tombstone()}>Убрать файл</Button><Button variant="ghost" size="sm" onClick={() => setTombstoneId('')}>Отмена</Button></div>}
                </DetailSection>
                <Separator />
                <DetailSection title="4. Связи и движения">
                  {bundle.relations.length ? (() => {
                    // Приёмка на 28 строк даёт 28 движений receipt_acceptance по одной
                    // штуке — портянка. Сворачиваем однотипные движения в одну строку с
                    // суммой, связанные документы оставляем поштучно.
                    const движения = new Map<string, number>()
                    const документы = bundle.relations.filter(
                      (r): r is { kind: string; related: StoreDocumentBrief } => 'related' in r)
                    for (const rel of bundle.relations) {
                      if ('movement' in rel)
                        движения.set(rel.movement.kind, (движения.get(rel.movement.kind) ?? 0) + rel.movement.count)
                    }
                    return (
                      <div className="grid gap-2">
                        {документы.map((rel, i) => (
                          <div key={`doc-${i}`} className="flex items-center gap-2 rounded-md border p-3 text-sm">
                            <Link2 className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                            <span>{KIND_LABELS[rel.related.kind] ?? rel.related.kind}{rel.related.number ? ` № ${rel.related.number}` : ''}</span>
                          </div>
                        ))}
                        {[...движения].map(([kind, count]) => (
                          <div key={`mv-${kind}`} className="flex items-center justify-between gap-2 rounded-md border p-3 text-sm">
                            <span className="flex items-center gap-2">
                              <Link2 className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                              Движение остатка · {MOVEMENT_LABELS[kind] ?? kind}
                            </span>
                            <span className="tabular-nums text-muted-foreground">{count} {count === 1 ? 'позиция' : 'позиций'}</span>
                          </div>
                        ))}
                      </div>
                    )
                  })() : <p className="text-sm text-muted-foreground">Связанные документы и движения не найдены.</p>}
                </DetailSection>
                <Separator />
                <DetailSection title="5. Ревизии и сверка">
                  <dl className="grid gap-3 rounded-md border p-3 sm:grid-cols-2">
                    <DetailField label="Ревизия">{detail.revision}</DetailField>
                    <DetailField label="Оперативный статус"><StatusBadge value={detail.operational_status} /></DetailField>
                    <DetailField label="Синхронизация"><StatusBadge value={detail.sync_status} /></DetailField>
                    <DetailField label="Бухгалтерская готовность"><StatusBadge value={detail.accounting_status} /></DetailField>
                    <DetailField label="Сверка с 1С"><StatusBadge value={detail.discrepancy_status} /></DetailField>
                    <DetailField label="Роль документа">{detail.document_role || '—'}</DetailField>
                  </dl>
                  {detail.has_fuel && <p className="flex items-center gap-2 text-xs text-muted-foreground"><ShieldAlert className="size-4" aria-hidden="true" />Исходный чек был смешанным; в реестре показана только подтверждённая товарная часть.</p>}
                  <div className="flex flex-wrap items-center gap-2">
                    <Button variant="outline" size="sm" onClick={() => void loadPayload()} disabled={payloadLoading}>
                      {payloadLoading ? <LoaderCircle data-icon className="animate-spin" /> : <FileSearch data-icon />}
                      Проверить исходные данные
                    </Button>
                    <span className="text-xs text-muted-foreground">Полный пакет доступен только бухгалтеру или суперадминистратору.</span>
                  </div>
                  {payload?.detail && <p className="text-sm text-muted-foreground">{payload.detail}</p>}
                  {payload?.payload !== undefined && <pre className="max-h-80 overflow-auto rounded-md border bg-muted/30 p-3 text-xs">{JSON.stringify(payload.payload, null, 2)}</pre>}
                </DetailSection>
              </>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

export function StoreDocumentsPanel({ dateFrom, dateTo, stations, startView = 'triage', kinds, views, heading }: StoreDocumentsPanelProps) {
  const [documents, setDocuments] = useState<StoreDocumentBrief[]>([])
  const [stats, setStats] = useState(EMPTY_STATS)
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [error, setError] = useState('')
  const [refreshKey, setRefreshKey] = useState(0)
  const [selected, setSelected] = useState<{ recordId: string; hint?: DocHint } | null>(null)
  const [search, setSearch] = useState('')
  const deferredSearch = useDeferredValue(search.trim())
  const [supplier, setSupplier] = useState('')
  const [kind, setKind] = useState('')
  const [operationalStatus, setOperationalStatus] = useState('')
  const [syncStatus, setSyncStatus] = useState('')
  const [accountingStatus, setAccountingStatus] = useState('')
  const [discrepancyStatus, setDiscrepancyStatus] = useState('')
  const [source, setSource] = useState('')
  const [files, setFiles] = useState('')
  const [warehouse, setWarehouse] = useState('')
  const deferredWarehouse = useDeferredValue(warehouse.trim())
  const [counter, setCounter] = useState<StoreDocumentCounter | ''>('')
  // Смена — главный разрез товарного контура: продажи, выпуск и чеки порождены
  // ею. Плоский список из полутора тысяч строк этого не показывает, поэтому у
  // реестра два режима, а не один.
  // Разбор идёт первым: менеджер приходит сюда с вопросом «что не так», а не
  // «покажи все документы». Реестр никуда не делся — он второй.
  const [view, setView] = useState<'triage' | 'list' | 'shifts'>(startView)
  const [triage, setTriage] = useState<StoreTriageQueue[]>([])
  const [triageLoading, setTriageLoading] = useState(false)
  const [shifts, setShifts] = useState<StoreShiftBrief[]>([])
  const [shiftsLoading, setShiftsLoading] = useState(false)
  // Фильтр реестра по секции: пусто — все смены, иначе только те, где разрез есть.
  // Набор выбранных разрезов: можно выбрать несколько (Продажи + Инвентаризации),
  // смена проходит, если содержит любой из них. Пустой набор = «Все».
  const [secFilters, setSecFilters] = useState<string[]>([])
  // Отбор по светофору готовности: g готова · y можно грузить · r не грузить.
  const [readyFilters, setReadyFilters] = useState<Array<'g' | 'y' | 'r'>>([])
  const [passport, setPassport] = useState<{ station: number; shift: number } | null>(null)
  const [shiftNo, setShiftNo] = useState<number | null>(null)
  const [filtersExpanded, setFiltersExpanded] = useState(false)
  const [rebuiltAt, setRebuiltAt] = useState<string | null>(null)
  const [rebuildAllowed, setRebuildAllowed] = useState(false)
  const [rebuilding, setRebuilding] = useState(false)

  const rebuild = async () => {
    setRebuilding(true)
    setError('')
    try {
      await rebuildStoreDocuments()
      setRefreshKey((value) => value + 1)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Пересборка реестра не выполнена')
    } finally {
      setRebuilding(false)
    }
  }

  const stationKey = stations.join(',')

  useEffect(() => {
    if (view !== 'triage') return
    let active = true
    setTriageLoading(true)
    getStoreTriage({ stations, dateFrom, dateTo })
      .then((result) => { if (active) { setTriage(result.queues); setError('') } })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : 'Разбор не загрузился')
      })
      .finally(() => { if (active) setTriageLoading(false) })
    return () => { active = false }
  }, [dateFrom, dateTo, refreshKey, stationKey, stations, view])

  useEffect(() => {
    if (view !== 'shifts') return
    let active = true
    setShiftsLoading(true)
    listStoreShifts({ stations, dateFrom, dateTo })
      .then((result) => { if (active) { setShifts(result.shifts); setError('') } })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : 'Смены не загрузились')
      })
      .finally(() => { if (active) setShiftsLoading(false) })
    return () => { active = false }
  }, [dateFrom, dateTo, refreshKey, stationKey, stations, view])

  const filterKey = [dateFrom, dateTo, stationKey, deferredSearch, supplier, kind, operationalStatus,
    syncStatus, accountingStatus, discrepancyStatus, source, files, deferredWarehouse, counter,
    shiftNo ?? '', kinds?.join(',') ?? ''].join('|')
  const requestKey = `${filterKey}|${offset}|${refreshKey}`
  const [resolvedKey, setResolvedKey] = useState('')
  const loading = resolvedKey !== requestKey

  useEffect(() => {
    let active = true
    listStoreDocuments({
      dateFrom, dateTo, stations,
      kind: kind || kinds?.join(',') || undefined,
      search: deferredSearch || undefined,
      supplier: supplier.trim() || undefined, operationalStatus: operationalStatus || undefined,
      syncStatus: syncStatus || undefined, accountingStatus: accountingStatus || undefined,
      discrepancyStatus: discrepancyStatus || undefined, source: source || undefined,
      hasFiles: files ? files === 'yes' : undefined, warehouse: deferredWarehouse || undefined,
      counter: counter || undefined, shiftNo: shiftNo ?? undefined,
      limit: PAGE_SIZE, offset,
    }).then((result) => {
      if (!active) return
      setError('')
      setDocuments(result.documents)
      setStats(result.stats ?? EMPTY_STATS)
      setTotal(result.total)
      setRebuiltAt(result.rebuilt_at ?? null)
      setRebuildAllowed(Boolean(result.rebuild_allowed))
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : 'Не удалось загрузить документы')
    }).finally(() => { if (active) setResolvedKey(requestKey) })
    return () => { active = false }
  }, [accountingStatus, counter, dateFrom, dateTo, deferredSearch, deferredWarehouse,
    discrepancyStatus, files, kind, offset, operationalStatus, refreshKey, requestKey,
    shiftNo, source, stationKey, stations, supplier, syncStatus])

  // Из очереди — сразу в отфильтрованный реестр: разбор без перехода к работе
  // остаётся отчётом, а не инструментом.
  const открытьОчередь = (код: string) => {
    if (код === 'shifts_review') { setView('shifts'); return }
    setOffset(0); setShiftNo(null); setCounter('')
    setKind(''); setOperationalStatus('')
    if (код === 'waiting_receipt' || код === 'missing_evidence' || код === 'attention'
        || код === 'onec_mismatch' || код === 'not_accounting_ready') {
      setCounter(код as StoreDocumentCounter)
    }
    setView('list')
  }

  const page = Math.floor(offset / PAGE_SIZE) + 1
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const range = useMemo(() => total ? `${offset + 1}–${Math.min(offset + PAGE_SIZE, total)} из ${total}` : '0 документов', [offset, total])
  const advancedFilterCount = [supplier.trim(), kind, operationalStatus, source, files,
    syncStatus, accountingStatus, discrepancyStatus, warehouse.trim()].filter(Boolean).length

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <header className="flex flex-wrap items-start justify-between gap-3 border-b px-4 py-3 lg:px-5">
        <div>
          <h2 className="text-base font-semibold">{heading?.title ?? 'Документы магазина'}</h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {heading?.subtitle ?? 'Сопутка и общепит: от первичного факта до готовности к учёту'}
            {rebuiltAt && ` · реестр собран ${fmtDate(rebuiltAt)}`}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {rebuildAllowed && (
            <Button variant="outline" size="sm" onClick={() => void rebuild()} disabled={rebuilding || loading}>
              {rebuilding ? <LoaderCircle data-icon className="animate-spin" /> : <FileCheck2 data-icon />}
              Пересобрать реестр
            </Button>
          )}
          {/* Переключатель нужен только на входном экране: в пункте меню человек
              уже выбрал, что смотрит, и вторая навигация внутри путает. */}
          {!kinds && (() => {
            const вкладки = views ?? ['triage', 'shifts', 'list']
            const подпись: Record<string, string> = { triage: 'Разбор', shifts: 'Смены', list: 'Документы' }
            return вкладки.length > 1 && (
              <div className="flex rounded-md border p-0.5" role="group" aria-label="Как показывать реестр">
                {вкладки.map((v) => (
                  <Button key={v} variant={view === v ? 'secondary' : 'ghost'} size="sm" className="h-7"
                    onClick={() => { setView(v); if (v === 'triage') setShiftNo(null) }}>{подпись[v]}</Button>
                ))}
              </div>
            )
          })()}
          <Button variant="outline" size="sm" onClick={() => setRefreshKey((value) => value + 1)} disabled={loading}>
            <RefreshCw data-icon className={loading ? 'animate-spin' : ''} />Обновить
          </Button>
        </div>
      </header>

      {/* Счётчики и фильтры — инструменты реестра. В разборе они лишние: очередь
          уже названа причиной, и вторая линия тех же чисел только дробит внимание. */}
            {view === 'list' && (
      <div className="grid grid-cols-2 border-b md:grid-cols-4">
        {COUNTERS.map(({ key, label, icon }) => (
          <Metric key={key} label={label} value={stats[key]} icon={icon} active={counter === key}
            onClick={() => { setOffset(0); setCounter((value) => (value === key ? '' : key)) }} />
        ))}
      </div>
      )}

      {view === 'list' && (
      <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-2 border-b p-3 lg:grid-cols-[minmax(15rem,1fr)_minmax(12rem,0.55fr)_auto]">
        <label className="relative min-w-0">
          <span className="sr-only">Поиск по номеру, поставщику или ИНН</span>
          <Search className="pointer-events-none absolute left-3 top-2.5 size-4 text-muted-foreground" aria-hidden="true" />
          <Input className="pl-9" value={search} onChange={(event) => { setOffset(0); setSearch(event.target.value) }} placeholder="Номер, поставщик или ИНН" />
        </label>
        <Button type="button" variant="outline" size="sm" className="lg:hidden" aria-expanded={filtersExpanded} aria-controls="store-document-advanced-filters" onClick={() => setFiltersExpanded((value) => !value)}>
          Фильтры реестра{advancedFilterCount > 0 && <Badge variant="secondary">{advancedFilterCount}</Badge>}
          <ChevronDown data-icon className={filtersExpanded ? 'rotate-180' : ''} />
        </Button>
        <Input className={`${filtersExpanded ? 'block' : 'hidden'} col-span-2 lg:col-span-1 lg:block`} value={supplier} onChange={(event) => { setOffset(0); setSupplier(event.target.value) }} placeholder="Поставщик / ИНН" aria-label="Поставщик или ИНН" />
        <div id="store-document-advanced-filters" className={`${filtersExpanded ? 'flex' : 'hidden'} col-span-2 flex-wrap gap-2 lg:col-span-1 lg:flex lg:justify-end`}>
          <SelectFilter label="Вид" value={kind} options={KIND_OPTIONS} onChange={(value) => { setOffset(0); setKind(value) }} />
          <SelectFilter label="Операция" value={operationalStatus} options={[["accepted", "Принят"], ["needs_review", "Нужна проверка"], ["blocked", "Заблокирован"]]} onChange={(value) => { setOffset(0); setOperationalStatus(value) }} />
          <SelectFilter label="Источник" value={source} options={Object.entries(SOURCE_LABELS)} onChange={(value) => { setOffset(0); setSource(value) }} />
          <SelectFilter label="Файлы" value={files} options={[["yes", "Есть"], ["no", "Нет"]]} onChange={(value) => { setOffset(0); setFiles(value) }} />
          <SelectFilter label="Синхронизация" value={syncStatus} options={[["pending", "Ожидает"], ["queued", "В очереди"], ["accepted", "Принята"], ["rejected", "Отклонена"]]} onChange={(value) => { setOffset(0); setSyncStatus(value) }} />
          <SelectFilter label="Готовность" value={accountingStatus} options={[["ready", "Готов"], ["needs_review", "Нужна проверка"], ["accepted", "Принят"], ["rejected", "Отклонён"], ["not_applicable", "Не учётный документ"]]} onChange={(value) => { setOffset(0); setAccountingStatus(value) }} />
          <SelectFilter label="Расхождение" value={discrepancyStatus} options={[["none", "Нет"], ["minor", "Небольшое"], ["material", "Существенное"], ["critical", "Критическое"], ["unmatched", "Не сопоставлено"]]} onChange={(value) => { setOffset(0); setDiscrepancyStatus(value) }} />
          <Input value={warehouse} onChange={(event) => { setOffset(0); setWarehouse(event.target.value) }} placeholder="Склад" aria-label="Склад или направление" className="h-8 min-w-36 max-w-52" />
        </div>
      </div>
      )}

      {shiftNo != null && (
        <div className="flex items-center gap-2 border-b bg-muted/40 px-4 py-2 text-sm">
          <span>Показаны документы смены № {shiftNo}</span>
          <Button variant="link" size="sm" className="h-auto p-0"
            onClick={() => { setShiftNo(null); setOffset(0) }}>снять</Button>
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-auto">
        {view === 'triage' && (
          <>
            {triageLoading && <div className="grid gap-2 p-4">{Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-16" />)}</div>}
            {!triageLoading && triage.length === 0 && (
              <div className="flex h-full min-h-72 flex-col items-center justify-center gap-2 px-6 text-center">
                <FileCheck2 className="size-8 text-muted-foreground" aria-hidden="true" />
                <h3 className="text-sm font-medium">Разбирать нечего</h3>
                <p className="max-w-md text-sm text-muted-foreground">
                  За выбранный период все документы приняты, подтверждены и готовы к учёту.
                </p>
              </div>
            )}
            {!triageLoading && triage.length > 0 && (
              <ul className="divide-y">
                {triage.map((очередь) => (
                  <li key={очередь.code}>
                    <button type="button" onClick={() => открытьОчередь(очередь.code)}
                      className="flex w-full items-start gap-4 px-4 py-4 text-left hover:bg-muted/40 focus-visible:bg-muted/40 focus-visible:outline-none lg:px-5">
                      <span className="mt-0.5 min-w-14 text-2xl font-semibold tabular-nums leading-none">
                        {очередь.count}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-sm font-medium">{очередь.title}</span>
                        <span className="mt-0.5 block text-sm text-muted-foreground">{очередь.reason}</span>
                        <span className="mt-1.5 inline-flex items-center gap-1 text-xs text-primary">
                          {очередь.action}<ChevronRight className="size-3" aria-hidden="true" />
                        </span>
                      </span>
                      {очередь.amount > 0 && (
                        <span className="shrink-0 text-right text-sm tabular-nums text-muted-foreground">
                          {fmtMoney(очередь.amount)}
                        </span>
                      )}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
        {view === 'shifts' && (
          <>
            {shiftsLoading && <div className="grid gap-2 p-4">{Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-11" />)}</div>}
            {!shiftsLoading && shifts.length === 0 && (
              <div className="flex h-full min-h-72 flex-col items-center justify-center gap-2 px-6 text-center">
                <FileSearch className="size-8 text-muted-foreground" aria-hidden="true" />
                <h3 className="text-sm font-medium">Смен за период нет</h3>
                <p className="max-w-md text-sm text-muted-foreground">
                  Смена появляется здесь, когда её пакет доехал со станции.
                </p>
              </div>
            )}
            {!shiftsLoading && shifts.length > 0 && (() => {
              const выбраны = SECTION_FILTERS.filter((s) => secFilters.includes(s.key))
              // Несколько разрезов объединяются по ИЛИ: смена видна, если в ней
              // есть хотя бы один из выбранных («Поступления или Инвентаризации»).
              // Плюс отбор по светофору готовности, если он задан.
              const видимые = shifts
                .filter((с) => !выбраны.length || выбраны.some((g) => g.kinds.some((k) => (с.kinds[k] ?? 0) > 0)))
                .filter((с) => !readyFilters.length || readyFilters.includes(с.readiness))
              const счёт = (g: (typeof SECTION_FILTERS)[number]) =>
                shifts.filter((с) => g.kinds.some((k) => (с.kinds[k] ?? 0) > 0)).length
              const chipCls = (on: boolean) =>
                `rounded-full border px-3 py-1.5 text-xs transition ${on ? 'border-primary bg-primary/15 text-primary' : 'border-border text-muted-foreground hover:text-foreground'}`
              const bulbCls = (c: 'g' | 'y' | 'r') =>
                c === 'g' ? 'bg-emerald-500' : c === 'y' ? 'bg-amber-500' : 'bg-red-500'
              const gotovCls = (c: 'g' | 'y' | 'r') =>
                c === 'g' ? 'text-emerald-500' : c === 'y' ? 'text-amber-500' : 'text-red-500'
              return (
              <div className="p-3">
                <div className="mb-3 flex flex-wrap gap-1.5">
                  <button type="button" className={chipCls(secFilters.length === 0)} onClick={() => setSecFilters([])}>Все</button>
                  {SECTION_FILTERS.map((g) => (
                    <button key={g.key} type="button" className={chipCls(secFilters.includes(g.key))}
                      onClick={() => setSecFilters((prev) =>
                        prev.includes(g.key) ? prev.filter((k) => k !== g.key) : [...prev, g.key])}>
                      {g.label}<span className="ml-1 tabular-nums opacity-60">{счёт(g)}</span>
                    </button>
                  ))}
                  <span className="mx-1 w-px self-stretch bg-border" aria-hidden="true" />
                  {([
                    ['g', 'Готовы'], ['y', 'Можно грузить'], ['r', 'Не грузить'],
                  ] as const).map(([c, подпись]) => {
                    const кол = shifts.filter((с) => с.readiness === c).length
                    return (
                      <button key={c} type="button" className={chipCls(readyFilters.includes(c))}
                        onClick={() => setReadyFilters((prev) =>
                          prev.includes(c) ? prev.filter((x) => x !== c) : [...prev, c])}>
                        <span className={`mr-1.5 inline-block size-2 rounded-full ${bulbCls(c)}`} aria-hidden="true" />
                        {подпись}<span className="ml-1 tabular-nums opacity-60">{кол}</span>
                      </button>
                    )
                  })}
                </div>
                <Table>
                  <TableHeader className="sticky top-0 z-10 bg-background">
                    <TableRow>
                      <TableHead className="w-8" aria-label="Готовность"></TableHead>
                      <TableHead>Смена</TableHead><TableHead>АЗС</TableHead><TableHead>Открыта</TableHead>
                      <TableHead>Закрыта</TableHead><TableHead className="text-right">Выручка</TableHead>
                      <TableHead className="text-right">Докум.</TableHead><TableHead>Состав</TableHead>
                      <TableHead>Готовность</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>{видимые.map((смена) => {
                    const гот = shiftReadiness(смена)
                    return (
                    <TableRow key={`${смена.station_id}-${смена.shift_no}`} className="cursor-pointer"
                      onClick={() => { if (смена.station_id != null) setPassport({ station: смена.station_id, shift: смена.shift_no }) }}>
                      <TableCell><span className={`inline-block size-2.5 rounded-full ${bulbCls(гот.color)}`} aria-hidden="true" /></TableCell>
                      <TableCell><span className="font-medium text-primary underline-offset-2 hover:underline">№ {смена.shift_no}</span></TableCell>
                      <TableCell>{смена.station_id ?? '—'}</TableCell>
                      <TableCell className="tabular-nums text-muted-foreground">{fmtDate(смена.started_at)}</TableCell>
                      <TableCell className="tabular-nums text-muted-foreground">{fmtDate(смена.finished_at)}</TableCell>
                      <TableCell className="text-right tabular-nums">{fmtMoney(смена.revenue)}</TableCell>
                      <TableCell className="text-right tabular-nums">
                        <Button type="button" variant="link" className="h-auto p-0"
                          onClick={(event) => { event.stopPropagation(); setShiftNo(смена.shift_no); setOffset(0); setView('list') }}>{смена.documents}</Button>
                      </TableCell>
                      <TableCell className="max-w-80 whitespace-normal">
                        <div className="flex flex-wrap gap-1">
                          {Object.entries(смена.kinds).map(([вид, шт]) => (
                            <span key={вид} className="rounded border border-border bg-muted/40 px-1.5 py-0.5 text-[10px] text-muted-foreground">
                              {KIND_LABELS[вид] ?? вид}{шт > 1 ? ` ${шт}` : ''}
                            </span>
                          ))}
                        </div>
                      </TableCell>
                      <TableCell className="max-w-64 whitespace-normal">
                        <span className={`whitespace-nowrap text-xs ${gotovCls(гот.color)}`}>● {гот.label}</span>
                        {(смена.blockers ?? []).length > 0 && (
                          <div className="mt-0.5 text-[11px] leading-snug text-muted-foreground">
                            {(смена.blockers ?? []).join(' · ')}
                          </div>
                        )}
                      </TableCell>
                    </TableRow>
                    )
                  })}</TableBody>
                </Table>
              </div>
              )
            })()}
          </>
        )}
        {view === 'list' && error && <div className="m-4 flex items-center justify-between gap-3 rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive" role="alert"><span>{error}</span><Button variant="outline" size="sm" onClick={() => setRefreshKey((value) => value + 1)}>Повторить</Button></div>}
        {view === 'list' && !error && loading && <div className="grid gap-2 p-4" aria-label="Загрузка реестра">{Array.from({ length: 8 }, (_, index) => <Skeleton key={index} className="h-11" />)}</div>}
        {view === 'list' && !error && !loading && documents.length === 0 && <div className="flex h-full min-h-72 flex-col items-center justify-center gap-2 px-6 text-center"><FileSearch className="size-8 text-muted-foreground" aria-hidden="true" /><h3 className="text-sm font-medium">Документы не найдены</h3><p className="max-w-md text-sm text-muted-foreground">В выбранном сверху периоде и области нет документов, отвечающих локальным фильтрам.</p></div>}
        {view === 'list' && !error && !loading && documents.length > 0 && (
          <Table>
            <TableHeader className="sticky top-0 z-10 bg-background"><TableRow><TableHead>Документ</TableHead><TableHead>Дата</TableHead><TableHead>АЗС</TableHead><TableHead>Смена</TableHead><TableHead>Контрагент</TableHead><TableHead className="text-right">Сумма</TableHead><TableHead>Операция</TableHead><TableHead>Учёт</TableHead>
              <TableHead>Сверка</TableHead>
              <TableHead>Источник</TableHead></TableRow></TableHeader>
            <TableBody>{documents.map((document) => (
              <TableRow key={document.record_id}>
                <TableCell><Button type="button" variant="link" className="h-auto max-w-72 flex-col items-start gap-0 whitespace-normal p-0 text-left" onClick={() => setSelected({ recordId: document.record_id, hint: { kind: document.kind, number: document.number, document_at: document.document_at } })}><span className="font-medium">{KIND_LABELS[document.kind] ?? document.kind}</span><span className="text-xs font-normal text-muted-foreground">{document.number ? `№ ${document.number}` : 'без номера'} · рев. {document.revision}</span>{document.transfer_route && <span className="text-xs font-normal text-primary/80">{document.transfer_route}</span>}{document.revaluation && (document.revaluation.name || document.revaluation.from != null || document.revaluation.to != null) && <span className="text-xs font-normal text-primary/80">{document.revaluation.name ? `${document.revaluation.name}: ` : ''}{fmtMoney(document.revaluation.from)} → {fmtMoney(document.revaluation.to)}</span>}</Button></TableCell>
                <TableCell>{fmtDate(document.document_at)}</TableCell><TableCell>{document.station_id ?? 'Центральный склад'}</TableCell>
                <TableCell>
                  {document.shift_no && document.station_id != null ? (
                    <Button type="button" variant="link" className="h-auto p-0"
                      onClick={() => setPassport({ station: document.station_id!, shift: document.shift_no! })}>
                      № {document.shift_no}
                    </Button>
                  ) : <span className="text-xs text-muted-foreground">вне смены</span>}
                </TableCell>
                <TableCell className="max-w-64 whitespace-normal"><div>{document.counterparty || '—'}</div>{document.counterparty_inn && <div className="text-xs text-muted-foreground">ИНН {document.counterparty_inn}</div>}</TableCell>
                <TableCell className="text-right tabular-nums">{fmtMoney(document.amount)}</TableCell>
                <TableCell><StatusBadge value={document.operational_status} attention={document.requires_attention} /></TableCell>
                <TableCell><StatusBadge value={document.accounting_status} /></TableCell>
                <TableCell><StatusBadge value={document.discrepancy_status} /></TableCell>
                <TableCell>{SOURCE_LABELS[document.projection_source] ?? document.projection_source}</TableCell>
              </TableRow>
            ))}</TableBody>
          </Table>
        )}
      </div>

      <footer className="flex items-center justify-between gap-3 border-t px-4 py-2 text-xs text-muted-foreground">
        <span>{range}</span><div className="flex items-center gap-2"><span>Страница {page} из {pageCount}</span><Button size="icon-sm" variant="outline" disabled={offset === 0 || loading} onClick={() => setOffset((value) => Math.max(0, value - PAGE_SIZE))} aria-label="Предыдущая страница"><ChevronLeft data-icon /></Button><Button size="icon-sm" variant="outline" disabled={offset + PAGE_SIZE >= total || loading} onClick={() => setOffset((value) => value + PAGE_SIZE)} aria-label="Следующая страница"><ChevronRight data-icon /></Button></div>
      </footer>
      <DocumentSheet recordId={selected?.recordId ?? null} hint={selected?.hint} onClose={() => setSelected(null)} />
      <ShiftPassportSheet
        station={passport?.station ?? null}
        shift={passport?.shift ?? null}
        onClose={() => setPassport(null)}
        onOpenDocuments={(_station, shift) => {
          setPassport(null); setShiftNo(shift); setOffset(0); setView('list')
        }}
        onOpenDocument={(recordId, hint) => setSelected({ recordId, hint })}
      />
    </div>
  )
}
