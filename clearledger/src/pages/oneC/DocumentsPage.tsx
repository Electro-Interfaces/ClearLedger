/**
 * Страница «1С → Документы». Просмотр импортированных учётных
 * документов БП ГИГ (AccountingDoc): ПТУ, ОРП, ОПЗС,
 * КорректировкаПоступления. Фильтры: тип, период, поиск, статус
 * сверки. Сортировка по дате/сумме. Пагинация.
 */

import { useState, useMemo } from 'react'
import { useQuery, useMutation, keepPreviousData, useQueryClient } from '@tanstack/react-query'
import {
  Card, CardContent, CardHeader, CardTitle, CardDescription,
} from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import {
  Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription,
} from '@/components/ui/sheet'
import {
  FileText, Search, RefreshCw, Loader2, ChevronLeft, ChevronRight,
  ArrowDown, ArrowUp, Download,
} from 'lucide-react'
import { toast } from 'sonner'
import { format } from 'date-fns'

import { useCompany } from '@/contexts/CompanyContext'
import { useOneCConnections, useSyncDocuments } from '@/hooks/useOneCSync'
import {
  searchAccountingDocs,
  getAccountingDocsStats,
  getAccountingDocDetails,
  loadDocumentLines,
  type DocSort,
} from '@/services/accountingDocService'

const PAGE_SIZE = 50

const DOC_TYPES = [
  { value: 'all', label: 'Все типы' },
  { value: 'ПТУ', label: 'ПТУ (поступления)' },
  { value: 'ОРП', label: 'ОРП (розница)' },
  { value: 'ОПЗС', label: 'ОПЗС (производство)' },
  { value: 'КорректировкаПоступления', label: 'Корректировка' },
]

// Состояние сверки (см. docs/sverka-spec.md §7a) — приходит в discrepancyStatus.
// matchStatus оставлен для обратной совместимости (пока не пересчитан).
const DISCREPANCY_STATUSES = [
  { value: 'all',       label: 'Все' },
  { value: 'pending',   label: 'Не сверен' },
  { value: 'none',      label: 'OK' },
  { value: 'rounding',  label: 'Округление' },
  { value: 'minor',     label: 'Малое' },
  { value: 'material',  label: 'Значимое' },
  { value: 'critical',  label: 'Критичное' },
  { value: 'unmatched', label: 'Без пары' },
]

const PERIOD_STATUSES = [
  { value: 'all',    label: 'Все периоды' },
  { value: 'open',   label: 'Открытые' },
  { value: 'closed', label: 'Закрытые' },
]

const SORT_OPTIONS: { value: DocSort; label: string; icon: typeof ArrowDown }[] = [
  { value: 'date_desc',   label: 'Дата ↓',  icon: ArrowDown },
  { value: 'date_asc',    label: 'Дата ↑',  icon: ArrowUp },
  { value: 'amount_desc', label: 'Сумма ↓', icon: ArrowDown },
  { value: 'amount_asc',  label: 'Сумма ↑', icon: ArrowUp },
]

// Цветовая палитра расхождений. В закрытом периоде те же градации, но
// в UI ниже добавляется красный outline+замок к строкам closed-периодов.
const DISCREPANCY_STYLE: Record<string, string> = {
  none:      'border-emerald-400/50 text-emerald-300/80',
  rounding:  'border-yellow-600/50  text-yellow-400/80',
  minor:     'border-amber-400/50   text-amber-300/80',
  material:  'border-orange-400/50  text-orange-300/80',
  critical:  'border-red-400/50     text-red-300/80',
  unmatched: 'border-zinc-600       text-zinc-400',
  pending:   'border-blue-400/50    text-blue-300/80',
}

const STATUS_1C_STYLE: Record<string, string> = {
  'Проведён': 'border-emerald-400/50 text-emerald-300/80',
  'Записан':  'border-blue-400/50    text-blue-300/80',
}

function formatRub(n: number): string {
  if (!isFinite(n)) return '—'
  return new Intl.NumberFormat('ru-RU', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(n)
}

function formatDate(s: string): string {
  if (!s) return '—'
  try { return format(new Date(s), 'dd.MM.yyyy') } catch { return s }
}

export function DocumentsPage() {
  const { companyId } = useCompany()
  const { data: connections } = useOneCConnections()
  const syncMutation = useSyncDocuments()
  const connection = connections?.[0]

  const [q, setQ] = useState('')
  const [docType, setDocType] = useState<string>('all')
  const [discrepancyStatus, setDiscrepancyStatus] = useState<string>('all')
  const [periodStatus, setPeriodStatus] = useState<string>('all')
  const [sort, setSort] = useState<DocSort>('date_desc')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [offset, setOffset] = useState(0)
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null)
  const qc = useQueryClient()

  const params = useMemo(() => ({
    q,
    docType: docType === 'all' ? undefined : docType,
    discrepancyStatus: discrepancyStatus === 'all' ? undefined : discrepancyStatus,
    periodStatus: periodStatus === 'all' ? undefined : periodStatus,
    sort,
    dateFrom: dateFrom || undefined,
    dateTo: dateTo || undefined,
    limit: PAGE_SIZE,
    offset,
  }), [q, docType, discrepancyStatus, periodStatus, sort, dateFrom, dateTo, offset])

  const { data, isFetching, error } = useQuery({
    queryKey: ['acc-docs', companyId, params],
    queryFn: () => searchAccountingDocs(companyId, params),
    placeholderData: keepPreviousData,
  })

  const { data: stats } = useQuery({
    queryKey: ['acc-docs-stats', companyId],
    queryFn: () => getAccountingDocsStats(companyId),
  })

  function resetOffset() { setOffset(0) }

  async function handleSync() {
    if (!connection) {
      toast.error('Сначала создайте подключение к 1С на вкладке «Подключение»')
      return
    }
    const id = toast.loading('Тяну документы из 1С — это занимает 1-3 минуты')
    try {
      const r = await syncMutation.mutateAsync(connection.id)
      toast.dismiss(id)
      toast.success(
        `Готово. Создано ${r.stats.created}, обновлено ${r.stats.updated}, ошибок ${r.stats.errors}`,
      )
    } catch (err) {
      toast.dismiss(id)
      toast.error(err instanceof Error ? err.message : 'Ошибка sync_documents')
    }
  }

  const total = data?.total ?? 0
  const from = total === 0 ? 0 : offset + 1
  const to = Math.min(total, offset + PAGE_SIZE)
  const canPrev = offset > 0
  const canNext = offset + PAGE_SIZE < total

  return (
    <div className="space-y-4 max-w-7xl">
      {/* Заголовок */}
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Документы из 1С</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Импортированные учётные документы БП ГИГ: ПТУ, ОРП, ОПЗС, корректировки.
          </p>
        </div>
        <Button
          size="sm"
          variant="outline"
          onClick={handleSync}
          disabled={!connection || syncMutation.isPending}
          className="gap-1.5 shrink-0"
        >
          {syncMutation.isPending
            ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
            : <RefreshCw className="h-3.5 w-3.5" />}
          Обновить из 1С
        </Button>
      </div>

      {/* KPI */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
          <Card className="py-2 gap-0">
            <CardContent className="p-3">
              <div className="text-[10px] text-muted-foreground uppercase">Всего</div>
              <div className="text-lg font-semibold mt-0.5">{stats.total.toLocaleString('ru-RU')}</div>
            </CardContent>
          </Card>
          {(['ПТУ', 'ОРП', 'ОПЗС', 'КорректировкаПоступления'] as const).map((t) => (
            <Card key={t} className="py-2 gap-0">
              <CardContent className="p-3">
                <div className="text-[10px] text-muted-foreground uppercase truncate">
                  {t === 'КорректировкаПоступления' ? 'Корр.' : t}
                </div>
                <div className="text-lg font-semibold mt-0.5">
                  {(stats.byType[t] ?? 0).toLocaleString('ru-RU')}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Фильтры */}
      <Card className="py-3 gap-2">
        <CardHeader className="pb-0">
          <CardTitle className="text-sm">Фильтры</CardTitle>
          <CardDescription className="text-xs">
            Поиск по номеру, контрагенту, ИНН и организации. Период по дате документа.
          </CardDescription>
        </CardHeader>
        <CardContent className="pt-0">
          <div className="grid grid-cols-1 md:grid-cols-12 gap-2">
            <div className="md:col-span-4 relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
              <Input
                value={q}
                onChange={(e) => { setQ(e.target.value); resetOffset() }}
                placeholder="Поиск номер / контрагент / ИНН…"
                className="h-8 pl-8 text-xs"
              />
            </div>
            <div className="md:col-span-2">
              <Select value={docType} onValueChange={(v) => { setDocType(v); resetOffset() }}>
                <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {DOC_TYPES.map((t) => (
                    <SelectItem key={t.value} value={t.value} className="text-xs">{t.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="md:col-span-2">
              <Select value={discrepancyStatus} onValueChange={(v) => { setDiscrepancyStatus(v); resetOffset() }}>
                <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="Сверка" /></SelectTrigger>
                <SelectContent>
                  {DISCREPANCY_STATUSES.map((s) => (
                    <SelectItem key={s.value} value={s.value} className="text-xs">{s.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="md:col-span-2">
              <Select value={periodStatus} onValueChange={(v) => { setPeriodStatus(v); resetOffset() }}>
                <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="Период" /></SelectTrigger>
                <SelectContent>
                  {PERIOD_STATUSES.map((s) => (
                    <SelectItem key={s.value} value={s.value} className="text-xs">{s.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="md:col-span-1">
              <Input type="date"
                value={dateFrom}
                onChange={(e) => { setDateFrom(e.target.value); resetOffset() }}
                placeholder="С"
                className="h-8 text-xs"
              />
            </div>
            <div className="md:col-span-1">
              <Input type="date"
                value={dateTo}
                onChange={(e) => { setDateTo(e.target.value); resetOffset() }}
                placeholder="По"
                className="h-8 text-xs"
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Таблица */}
      <Card className="py-3 gap-2">
        <CardHeader className="pb-0">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm flex items-center gap-2">
              <FileText className="h-4 w-4 text-muted-foreground" />
              Документы
              <Badge variant="outline" className="text-[10px] font-mono ml-1">{total.toLocaleString('ru-RU')}</Badge>
            </CardTitle>
            <Select value={sort} onValueChange={(v) => setSort(v as DocSort)}>
              <SelectTrigger className="h-7 text-xs w-32"><SelectValue /></SelectTrigger>
              <SelectContent>
                {SORT_OPTIONS.map((o) => (
                  <SelectItem key={o.value} value={o.value} className="text-xs">{o.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </CardHeader>
        <CardContent className="pt-0">
          {error && <p className="text-[11px] text-destructive">{(error as Error).message}</p>}
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="h-7 text-[10px] w-20">Тип</TableHead>
                <TableHead className="h-7 text-[10px] w-32">Номер / ТТН №</TableHead>
                <TableHead className="h-7 text-[10px] w-24">Дата</TableHead>
                <TableHead className="h-7 text-[10px]">Контрагент</TableHead>
                <TableHead className="h-7 text-[10px]">Организация</TableHead>
                <TableHead className="h-7 text-[10px] w-32 text-right">Сумма, ₽</TableHead>
                <TableHead className="h-7 text-[10px] w-20">Период</TableHead>
                <TableHead className="h-7 text-[10px] w-24">Статус 1С</TableHead>
                <TableHead className="h-7 text-[10px] w-28">Сверка</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(data?.items ?? []).map((d) => {
                const isClosed = d.periodStatus === 'closed'
                const ds = d.discrepancyStatus || 'pending'
                // В закрытом периоде ЛЮБОЕ расхождение (даже rounding) тревожнее
                // см. docs/sverka-spec.md §7a.4 — добавляем красный outline на строку.
                const rowAttention = isClosed && ['rounding','minor','material','critical'].includes(ds)
                return (
                <TableRow
                  key={d.id}
                  className={`text-xs cursor-pointer hover:bg-muted/40 ${rowAttention ? 'bg-red-500/5' : ''}`}
                  onClick={() => setSelectedDocId(d.id)}
                >
                  <TableCell className="py-1.5">
                    <Badge variant="outline" className="text-[9px] h-4 px-1 font-mono">
                      {d.docType === 'КорректировкаПоступления' ? 'Корр.' : d.docType}
                    </Badge>
                  </TableCell>
                  <TableCell className="py-1.5 font-mono text-[11px]">
                    <div>{d.number || '—'}</div>
                    {d.externalNumber && (
                      <div className="text-[9px] text-muted-foreground">
                        ТТН №{d.externalNumber} {d.externalDate ? `от ${formatDate(d.externalDate)}` : ''}
                      </div>
                    )}
                  </TableCell>
                  <TableCell className="py-1.5 text-[11px]">{formatDate(d.date)}</TableCell>
                  <TableCell className="py-1.5">
                    <div>{d.counterpartyName || '—'}</div>
                    {d.counterpartyInn && (
                      <div className="text-[10px] text-muted-foreground font-mono">ИНН {d.counterpartyInn}</div>
                    )}
                  </TableCell>
                  <TableCell className="py-1.5 text-[11px] text-muted-foreground">
                    {d.organizationName || '—'}
                  </TableCell>
                  <TableCell className="py-1.5 text-right font-mono text-[11px]">
                    {formatRub(d.amount)}
                  </TableCell>
                  <TableCell className="py-1.5">
                    <Badge
                      variant="outline"
                      className={`text-[9px] h-4 px-1 ${isClosed
                        ? 'border-red-400/50 text-red-300/80'
                        : 'border-emerald-400/50 text-emerald-300/80'}`}
                      title={isClosed
                        ? 'Период закрыт — изменения требуют корректировки'
                        : 'Период открыт'}
                    >
                      {isClosed ? '🔒 закрыт' : 'открыт'}
                    </Badge>
                  </TableCell>
                  <TableCell className="py-1.5">
                    <Badge variant="outline" className={`text-[9px] h-4 px-1 ${STATUS_1C_STYLE[d.status1c] ?? ''}`}>
                      {d.status1c}
                    </Badge>
                    {d.operationType && (
                      <div className="text-[9px] text-muted-foreground mt-0.5 truncate" title={d.operationType}>
                        {d.operationType}
                      </div>
                    )}
                  </TableCell>
                  <TableCell className="py-1.5">
                    <Badge
                      variant="outline"
                      className={`text-[9px] h-4 px-1 ${DISCREPANCY_STYLE[ds] ?? ''}`}
                      title={d.discrepancySummary || DISCREPANCY_STATUSES.find((s) => s.value === ds)?.label}
                    >
                      {DISCREPANCY_STATUSES.find((s) => s.value === ds)?.label ?? ds}
                    </Badge>
                    {d.discrepancySummary && (
                      <div className="text-[9px] text-muted-foreground mt-0.5 truncate" title={d.discrepancySummary}>
                        {d.discrepancySummary}
                      </div>
                    )}
                  </TableCell>
                </TableRow>
                )
              })}
              {data && data.items.length === 0 && (
                <TableRow>
                  <TableCell colSpan={9} className="text-center text-[11px] text-muted-foreground py-6">
                    Документы не найдены — измените фильтры или обновите из 1С
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>

          {/* Пагинация */}
          <div className="flex items-center justify-between text-[11px] text-muted-foreground py-2 px-1">
            <div className="font-mono">
              {isFetching ? <Loader2 className="h-3 w-3 animate-spin inline" /> : null}
              {' '}{from}–{to} из {total.toLocaleString('ru-RU')}
            </div>
            <div className="flex items-center gap-1">
              <Button size="sm" variant="ghost" className="h-6 px-2"
                disabled={!canPrev || isFetching}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
                <ChevronLeft className="h-3.5 w-3.5" />
              </Button>
              <Button size="sm" variant="ghost" className="h-6 px-2"
                disabled={!canNext || isFetching}
                onClick={() => setOffset(offset + PAGE_SIZE)}>
                <ChevronRight className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <DocumentDetailSheet
        docId={selectedDocId}
        companyId={companyId}
        connectionId={connection?.id}
        onClose={() => setSelectedDocId(null)}
        onLinesLoaded={() => {
          qc.invalidateQueries({ queryKey: ['acc-docs', companyId] })
        }}
      />
    </div>
  )
}


// ─── Sheet деталей одного документа ─────────────────────────────────

interface DetailSheetProps {
  docId: string | null
  companyId: string
  connectionId: string | undefined
  onClose: () => void
  onLinesLoaded: () => void
}

function DocumentDetailSheet({ docId, companyId, connectionId, onClose, onLinesLoaded }: DetailSheetProps) {
  const { data: doc, isLoading, refetch } = useQuery({
    queryKey: ['acc-doc-detail', docId],
    queryFn: () => getAccountingDocDetails(companyId, docId!),
    enabled: !!docId,
  })

  const loadMutation = useMutation({
    mutationFn: () => loadDocumentLines(connectionId!, docId!),
    onSuccess: async (r) => {
      const totals = Object.entries(r.tabular_counts).map(([k, v]) => `${k}: ${v}`).join(', ')
      toast.success(`Позиции загружены из 1С (${totals})`)
      await refetch()
      onLinesLoaded()
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : 'Не удалось загрузить позиции')
    },
  })

  if (!docId) return null

  const lines = (doc?.lines as { tabular?: Record<string, unknown[]>; fetched_at?: string } | unknown[]) || null
  const tabular = lines && !Array.isArray(lines) ? lines.tabular || {} : {}
  const fetchedAt = lines && !Array.isArray(lines) ? lines.fetched_at : null
  const hasLines = Object.keys(tabular).length > 0

  return (
    <Sheet open={!!docId} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="!max-w-2xl overflow-y-auto p-0">
        <SheetHeader className="p-4 pb-2">
          <SheetTitle className="text-base flex items-center gap-2">
            <FileText className="h-4 w-4" />
            {doc ? `${doc.docType} ${doc.number}` : 'Документ'}
          </SheetTitle>
          <SheetDescription className="text-xs">
            {doc?.organizationName ?? '—'}
          </SheetDescription>
        </SheetHeader>

        {isLoading && (
          <div className="p-4 flex items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        )}

        {doc && (
          <div className="px-4 pb-6 space-y-3">
            {/* Шапка */}
            <Card className="py-3 gap-1">
              <CardHeader className="pb-0">
                <CardTitle className="text-xs uppercase text-muted-foreground">Шапка</CardTitle>
              </CardHeader>
              <CardContent className="pt-0 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
                <div className="text-muted-foreground">Дата</div>
                <div>{doc.date}</div>
                <div className="text-muted-foreground">Сумма</div>
                <div className="font-mono">{new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2 }).format(doc.amount)} ₽</div>
                {doc.vatAmount != null && (<>
                  <div className="text-muted-foreground">НДС</div>
                  <div className="font-mono">{new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2 }).format(doc.vatAmount)} ₽</div>
                </>)}
                <div className="text-muted-foreground">Контрагент</div>
                <div>{doc.counterpartyName || '—'}{doc.counterpartyInn ? ` · ИНН ${doc.counterpartyInn}` : ''}</div>
                {doc.externalNumber && (<>
                  <div className="text-muted-foreground">№ входящего</div>
                  <div className="font-mono">{doc.externalNumber}{doc.externalDate ? ` от ${doc.externalDate}` : ''}</div>
                </>)}
                {doc.operationType && (<>
                  <div className="text-muted-foreground">ВидОперации</div>
                  <div>{doc.operationType}</div>
                </>)}
                <div className="text-muted-foreground">Склад</div>
                <div className="font-mono">{doc.warehouseCode || '—'}</div>
                <div className="text-muted-foreground">Период</div>
                <div>
                  <Badge variant="outline" className={`text-[9px] h-4 px-1 ${doc.periodStatus === 'closed' ? 'border-red-400/50 text-red-300/80' : 'border-emerald-400/50 text-emerald-300/80'}`}>
                    {doc.periodStatus === 'closed' ? '🔒 закрыт' : 'открыт'}
                  </Badge>
                </div>
                <div className="text-muted-foreground">Статус 1С</div>
                <div>{doc.status1c}</div>
              </CardContent>
            </Card>

            {/* Сверка */}
            <Card className="py-3 gap-1">
              <CardHeader className="pb-0">
                <CardTitle className="text-xs uppercase text-muted-foreground">Сверка</CardTitle>
              </CardHeader>
              <CardContent className="pt-0 text-xs">
                <div className="flex items-center gap-2 mb-1">
                  <Badge variant="outline" className={`text-[10px] h-5 px-1.5 ${DISCREPANCY_STYLE[doc.discrepancyStatus ?? 'pending'] ?? ''}`}>
                    {DISCREPANCY_STATUSES.find((s) => s.value === doc.discrepancyStatus)?.label ?? doc.discrepancyStatus}
                  </Badge>
                  <span className="text-muted-foreground">{doc.discrepancySummary || '—'}</span>
                </div>
                {Array.isArray((doc as { discrepancyDetails?: unknown }).discrepancyDetails) && (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="h-6 text-[10px]">Поле</TableHead>
                        <TableHead className="h-6 text-[10px] text-right">ClearLedger</TableHead>
                        <TableHead className="h-6 text-[10px] text-right">БП ГИГ</TableHead>
                        <TableHead className="h-6 text-[10px] text-right">Δ</TableHead>
                        <TableHead className="h-6 text-[10px]">Severity</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {((doc as { discrepancyDetails: Array<{ field: string; source: number | null; target: number | null; delta: number | null; severity: string }> }).discrepancyDetails).map((dd, i) => (
                        <TableRow key={i} className="text-[10px]">
                          <TableCell className="py-1">{dd.field}</TableCell>
                          <TableCell className="py-1 text-right font-mono">{dd.source ?? '—'}</TableCell>
                          <TableCell className="py-1 text-right font-mono">{dd.target ?? '—'}</TableCell>
                          <TableCell className="py-1 text-right font-mono">{dd.delta != null ? dd.delta.toFixed(2) : '—'}</TableCell>
                          <TableCell className="py-1">
                            <Badge variant="outline" className={`text-[9px] h-4 px-1 ${DISCREPANCY_STYLE[dd.severity] ?? ''}`}>{dd.severity}</Badge>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </CardContent>
            </Card>

            {/* ТЧ */}
            <Card className="py-3 gap-1">
              <CardHeader className="pb-0">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-xs uppercase text-muted-foreground">Позиции</CardTitle>
                  <Button
                    size="sm" variant="outline"
                    onClick={() => loadMutation.mutate()}
                    disabled={!connectionId || loadMutation.isPending}
                    className="h-7 text-xs gap-1.5"
                  >
                    {loadMutation.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Download className="h-3 w-3" />}
                    {hasLines ? 'Перезагрузить из 1С' : 'Загрузить из 1С'}
                  </Button>
                </div>
                {fetchedAt && (
                  <CardDescription className="text-[10px]">Подгружено: {format(new Date(fetchedAt), 'dd.MM.yyyy HH:mm')}</CardDescription>
                )}
              </CardHeader>
              <CardContent className="pt-0 text-xs">
                {!hasLines && (
                  <p className="text-[10px] text-muted-foreground">
                    Позиции ещё не подгружены. Нажми «Загрузить из 1С» —
                    это вызов /api/onec/connections/{'{id}'}/document-lines/{'{doc}'}.
                  </p>
                )}
                {hasLines && Object.entries(tabular).map(([tabName, rows]) => (
                  <div key={tabName} className="mb-3">
                    <div className="text-[10px] font-semibold uppercase text-muted-foreground mb-1">{tabName} ({(rows as unknown[]).length})</div>
                    {((rows as Array<Record<string, unknown>>).length > 0) ? (
                      <Table>
                        <TableHeader>
                          <TableRow>
                            {Object.keys((rows as Array<Record<string, unknown>>)[0]).map((k) => (
                              <TableHead key={k} className="h-6 text-[10px]">{k}</TableHead>
                            ))}
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {(rows as Array<Record<string, unknown>>).slice(0, 20).map((row, i) => (
                            <TableRow key={i} className="text-[10px]">
                              {Object.keys((rows as Array<Record<string, unknown>>)[0]).map((k) => (
                                <TableCell key={k} className="py-1 font-mono truncate max-w-[140px]" title={String(row[k] ?? '')}>
                                  {row[k] == null ? '—' : String(row[k]).slice(0, 24)}
                                </TableCell>
                              ))}
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    ) : (
                      <p className="text-[10px] text-muted-foreground italic">пусто</p>
                    )}
                  </div>
                ))}
              </CardContent>
            </Card>
          </div>
        )}
      </SheetContent>
    </Sheet>
  )
}

