import { useDeferredValue, useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  AlertCircle, ArrowDownToLine, ChevronDown, ChevronLeft, ChevronRight, FileCheck2,
  FileSearch, Files, Link2, LoaderCircle, Printer, RefreshCw, Search, ShieldAlert,
  Trash2, Upload,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import {
  downloadStoreDocumentFile, getStoreDocumentBundle, getStoreDocumentPayload,
  DIFF_PRINTABLE_KINDS, listStoreDocuments, openStoreDocumentPrintForm, PRINTABLE_KINDS,
  rebuildStoreDocuments, tombstoneStoreDocumentFile, uploadStoreDocumentFile,
  type StoreDocumentBrief, type StoreDocumentBundle, type StoreDocumentCounter,
  type StoreDocumentFile, type StoreDocumentPayloadResponse, type StoreDocumentStats,
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

const KIND_OPTIONS = Object.entries(KIND_LABELS)

// Каждый счётчик — рабочий отбор: сервер считает и фильтрует одним выражением,
// поэтому число над таблицей и содержимое таблицы не могут разойтись.
const COUNTERS: Array<{ key: StoreDocumentCounter; label: string; icon: typeof AlertCircle }> = [
  { key: 'attention', label: 'Требуют внимания', icon: AlertCircle },
  { key: 'missing_evidence', label: 'Нет подтверждений', icon: Files },
  { key: 'not_accounting_ready', label: 'Не готовы к учёту', icon: FileCheck2 },
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
}

const SOURCE_LABELS: Record<string, string> = {
  edge: 'Агент станции', store: 'Центральный магазин', onec_legacy: '1С до перехода',
  edo: 'ЭДО', cash: 'Касса', bp: 'БП ГИГ',
}

interface StoreDocumentsPanelProps {
  dateFrom: string
  dateTo: string
  stations: string[]
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

function DocumentSheet({ record, onClose }: { record: StoreDocumentBrief | null; onClose: () => void }) {
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
    if (!record) return
    setPrinting(true)
    setError('')
    try {
      await openStoreDocumentPrintForm(record.record_id, variant)
    } catch (reason) {
      setError(reason instanceof ApiError && reason.status === 409
        ? (reason.message || 'Печатной формы у этого документа нет')
        : reason instanceof Error ? reason.message : 'Печатная форма не открылась')
    } finally {
      setPrinting(false)
    }
  }

  useEffect(() => {
    if (!record) return
    let active = true
    setLoading(true)
    setError('')
    setBundle(null)
    setPayload(null)
    setFileWriteDenied(false)
    setUploadFile(null)
    setTombstoneId('')
    getStoreDocumentBundle(record.record_id)
      .then((next) => { if (active) setBundle(next) })
      .catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : 'Не удалось открыть документ') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [record])

  const loadPayload = async () => {
    if (!record) return
    setPayloadLoading(true)
    try {
      setPayload(await getStoreDocumentPayload(record.record_id))
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
    if (!record) return
    setBundle(await getStoreDocumentBundle(record.record_id))
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
    if (!record || !uploadFile) return
    setFileBusy(true)
    setError('')
    try {
      await uploadStoreDocumentFile(record.record_id, uploadFile, uploadRole, uploadNote.trim() || undefined)
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
    if (!record || !tombstoneId || tombstoneReason.trim().length < 3) return
    setFileBusy(true)
    setError('')
    try {
      await tombstoneStoreDocumentFile(record.record_id, tombstoneId, tombstoneReason.trim())
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
  const lines = detail ? documentLines(detail.document) : []
  // «строк нет» и «источник их не отдаёт» — разные вещи, и путать их нельзя
  const headerOnly = detail?.document.detail_mode === 'header_only'
  const readOnlyFiscal = detail?.kind === 'fiscal_receipt' || detail?.kind === 'store_shift'
  const canWriteFiles = Boolean(detail?.file_write_allowed) && !readOnlyFiscal && !fileWriteDenied

  return (
    <Sheet open={Boolean(record)} onOpenChange={(open) => { if (!open) onClose() }}>
      <SheetContent className="w-full gap-0 p-0 sm:max-w-3xl [&>button.absolute]:min-h-6 [&>button.absolute]:min-w-6">
        <SheetHeader className="border-b pr-14">
          <div className="flex flex-wrap items-center gap-2">
            <SheetTitle>{record ? KIND_LABELS[record.kind] ?? record.kind : 'Документ'}</SheetTitle>
            {record && <StatusBadge value={record.accounting_status} attention={record.requires_attention} />}
            {readOnlyFiscal && <Badge variant="outline">только просмотр</Badge>}
          </div>
          <SheetDescription>
            {record?.number ? `№ ${record.number}` : 'Без номера'} · {fmtDate(record?.document_at)}
          </SheetDescription>
          <div className="flex flex-wrap gap-2">
            {record && PRINTABLE_KINDS.has(record.kind) && (
              <Button variant="outline" size="sm" disabled={printing}
                onClick={() => void printForm()}>
                {printing ? <LoaderCircle data-icon className="animate-spin" /> : <Printer data-icon />}
                Печатная форма
              </Button>
            )}
            {record && DIFF_PRINTABLE_KINDS.has(record.kind) && (
              <Button variant="outline" size="sm" disabled={printing}
                onClick={() => void printForm('diff')}>
                <Printer data-icon />
                {record.kind === 'purchase' ? 'Акт расхождения (ТОРГ-2)' : 'Сличительная ведомость (ИНВ-19)'}
              </Button>
            )}
          </div>
        </SheetHeader>

        <ScrollArea className="min-h-0 flex-1">
          <div className="grid gap-5 p-4 sm:p-5">
            {loading && <div className="grid gap-3" aria-label="Загрузка документа"><Skeleton className="h-24" /><Skeleton className="h-40" /><Skeleton className="h-28" /></div>}
            {error && (
              <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive" role="alert">
                <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />{error}
              </div>
            )}
            {detail && (
              <>
                <DetailSection title="1. Реквизиты">
                  <dl className="grid gap-3 rounded-md border p-3 sm:grid-cols-2">
                    <DetailField label="Станция">{detail.station_id ? `АЗС ${detail.station_id}` : 'Центральный склад'}</DetailField>
                    <DetailField label="Контрагент">{detail.counterparty || '—'}</DetailField>
                    <DetailField label="ИНН">{detail.counterparty_inn || '—'}</DetailField>
                    <DetailField label="Сумма">{fmtMoney(detail.amount)}</DetailField>
                    <DetailField label="НДС">{fmtMoney(detail.vat_amount)}</DetailField>
                    <DetailField label="Источник">{SOURCE_LABELS[detail.projection_source] ?? detail.projection_source}</DetailField>
                  </dl>
                </DetailSection>
                <Separator />
                <DetailSection title="2. Строки">
                  {headerOnly ? (
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
                  {bundle.relations.length ? <div className="grid gap-2">{bundle.relations.map((relation, index) => (
                    <div key={`${relation.kind}-${index}`} className="flex items-center gap-2 rounded-md border p-3 text-sm">
                      <Link2 className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                      {'movement' in relation
                        ? <span>Движение: {relation.movement.kind} · {relation.movement.count}</span>
                        : <span>{KIND_LABELS[relation.related.kind] ?? relation.related.kind} {relation.related.number ? `№ ${relation.related.number}` : ''}</span>}
                    </div>
                  ))}</div> : <p className="text-sm text-muted-foreground">Связанные документы и движения не найдены.</p>}
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
        </ScrollArea>
      </SheetContent>
    </Sheet>
  )
}

export function StoreDocumentsPanel({ dateFrom, dateTo, stations }: StoreDocumentsPanelProps) {
  const [documents, setDocuments] = useState<StoreDocumentBrief[]>([])
  const [stats, setStats] = useState(EMPTY_STATS)
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [error, setError] = useState('')
  const [refreshKey, setRefreshKey] = useState(0)
  const [selected, setSelected] = useState<StoreDocumentBrief | null>(null)
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
  const filterKey = [dateFrom, dateTo, stationKey, deferredSearch, supplier, kind, operationalStatus,
    syncStatus, accountingStatus, discrepancyStatus, source, files, deferredWarehouse, counter].join('|')
  const requestKey = `${filterKey}|${offset}|${refreshKey}`
  const [resolvedKey, setResolvedKey] = useState('')
  const loading = resolvedKey !== requestKey

  useEffect(() => {
    let active = true
    listStoreDocuments({
      dateFrom, dateTo, stations, kind: kind || undefined, search: deferredSearch || undefined,
      supplier: supplier.trim() || undefined, operationalStatus: operationalStatus || undefined,
      syncStatus: syncStatus || undefined, accountingStatus: accountingStatus || undefined,
      discrepancyStatus: discrepancyStatus || undefined, source: source || undefined,
      hasFiles: files ? files === 'yes' : undefined, warehouse: deferredWarehouse || undefined,
      counter: counter || undefined,
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
    source, stationKey, stations, supplier, syncStatus])

  const page = Math.floor(offset / PAGE_SIZE) + 1
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const range = useMemo(() => total ? `${offset + 1}–${Math.min(offset + PAGE_SIZE, total)} из ${total}` : '0 документов', [offset, total])
  const advancedFilterCount = [supplier.trim(), kind, operationalStatus, source, files,
    syncStatus, accountingStatus, discrepancyStatus, warehouse.trim()].filter(Boolean).length

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <header className="flex flex-wrap items-start justify-between gap-3 border-b px-4 py-3 lg:px-5">
        <div>
          <h2 className="text-base font-semibold">Документы магазина</h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Сопутка и общепит: от первичного факта до готовности к учёту
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
          <Button variant="outline" size="sm" onClick={() => setRefreshKey((value) => value + 1)} disabled={loading}>
            <RefreshCw data-icon className={loading ? 'animate-spin' : ''} />Обновить
          </Button>
        </div>
      </header>

      <div className="grid grid-cols-2 border-b md:grid-cols-4">
        {COUNTERS.map(({ key, label, icon }) => (
          <Metric key={key} label={label} value={stats[key]} icon={icon} active={counter === key}
            onClick={() => { setOffset(0); setCounter((value) => (value === key ? '' : key)) }} />
        ))}
      </div>

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

      <div className="min-h-0 flex-1 overflow-auto">
        {error && <div className="m-4 flex items-center justify-between gap-3 rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive" role="alert"><span>{error}</span><Button variant="outline" size="sm" onClick={() => setRefreshKey((value) => value + 1)}>Повторить</Button></div>}
        {!error && loading && <div className="grid gap-2 p-4" aria-label="Загрузка реестра">{Array.from({ length: 8 }, (_, index) => <Skeleton key={index} className="h-11" />)}</div>}
        {!error && !loading && documents.length === 0 && <div className="flex h-full min-h-72 flex-col items-center justify-center gap-2 px-6 text-center"><FileSearch className="size-8 text-muted-foreground" aria-hidden="true" /><h3 className="text-sm font-medium">Документы не найдены</h3><p className="max-w-md text-sm text-muted-foreground">В выбранном сверху периоде и области нет документов, отвечающих локальным фильтрам.</p></div>}
        {!error && !loading && documents.length > 0 && (
          <Table>
            <TableHeader className="sticky top-0 z-10 bg-background"><TableRow><TableHead>Документ</TableHead><TableHead>Дата</TableHead><TableHead>АЗС</TableHead><TableHead>Контрагент</TableHead><TableHead className="text-right">Сумма</TableHead><TableHead>Операция</TableHead><TableHead>Учёт</TableHead><TableHead>Сверка</TableHead><TableHead>Источник</TableHead></TableRow></TableHeader>
            <TableBody>{documents.map((document) => (
              <TableRow key={document.record_id}>
                <TableCell><Button type="button" variant="link" className="h-auto max-w-72 flex-col items-start gap-0 whitespace-normal p-0 text-left" onClick={() => setSelected(document)}><span className="font-medium">{KIND_LABELS[document.kind] ?? document.kind}</span><span className="text-xs font-normal text-muted-foreground">{document.number ? `№ ${document.number}` : 'без номера'} · рев. {document.revision}</span></Button></TableCell>
                <TableCell>{fmtDate(document.document_at)}</TableCell><TableCell>{document.station_id ?? 'Центральный склад'}</TableCell>
                <TableCell className="max-w-64 whitespace-normal"><div>{document.counterparty || '—'}</div>{document.counterparty_inn && <div className="text-xs text-muted-foreground">ИНН {document.counterparty_inn}</div>}</TableCell>
                <TableCell className="text-right tabular-nums">{fmtMoney(document.amount)}</TableCell>
                <TableCell><StatusBadge value={document.operational_status} attention={document.requires_attention} /></TableCell>
                <TableCell><StatusBadge value={document.accounting_status} /></TableCell><TableCell><StatusBadge value={document.discrepancy_status} /></TableCell>
                <TableCell>{SOURCE_LABELS[document.projection_source] ?? document.projection_source}</TableCell>
              </TableRow>
            ))}</TableBody>
          </Table>
        )}
      </div>

      <footer className="flex items-center justify-between gap-3 border-t px-4 py-2 text-xs text-muted-foreground">
        <span>{range}</span><div className="flex items-center gap-2"><span>Страница {page} из {pageCount}</span><Button size="icon-sm" variant="outline" disabled={offset === 0 || loading} onClick={() => setOffset((value) => Math.max(0, value - PAGE_SIZE))} aria-label="Предыдущая страница"><ChevronLeft data-icon /></Button><Button size="icon-sm" variant="outline" disabled={offset + PAGE_SIZE >= total || loading} onClick={() => setOffset((value) => value + PAGE_SIZE)} aria-label="Следующая страница"><ChevronRight data-icon /></Button></div>
      </footer>
      <DocumentSheet record={selected} onClose={() => setSelected(null)} />
    </div>
  )
}
