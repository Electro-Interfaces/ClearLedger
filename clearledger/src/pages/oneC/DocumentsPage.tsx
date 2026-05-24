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
  ArrowDown, ArrowUp, Download, CheckCircle2,
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
  enrichNomenclature,
  packetsByDoc,
  getEntryLineage,
  normalizeEntry,
  getRelatedDocs,
  type DocSort,
  type ExportPacketBrief,
  type EntryLineage,
} from '@/services/accountingDocService'

const PAGE_SIZE = 50

const DOC_TYPES = [
  { value: 'all', label: 'Все типы' },
  { value: 'ПТУ', label: 'ПТУ (поступления)' },
  { value: 'ОРП', label: 'ОРП (розница)' },
  { value: 'ОПЗС', label: 'ОПЗС (производство)' },
  { value: 'КорректировкаПоступления', label: 'Корректировка' },
  { value: 'ПеремещениеТоваров', label: 'Перемещение (виртуальные склады)' },
  { value: 'СписаниеТоваров', label: 'Списание (по прочим)' },
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
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Документы из 1С</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Импортированные учётные документы БП ГИГ: ПТУ, ОРП, ОПЗС, корректировки.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="outline" className="h-8 text-xs"
            onClick={() => {
              setDocType('ОРП'); setDateFrom('2026-05-01'); setDateTo('2026-05-31');
              setSort('date_asc'); resetOffset()
            }}
          >
            ОРП май 2026
          </Button>
          <Button size="sm" variant="outline" className="h-8 text-xs"
            onClick={() => {
              setDocType('ПТУ'); setDateFrom(''); setDateTo('');
              setSort('date_desc'); resetOffset()
            }}
          >
            Все ТТН
          </Button>
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
      </div>

      {/* KPI */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-7 gap-2">
          <Card className="py-2 gap-0">
            <CardContent className="p-3">
              <div className="text-[10px] text-muted-foreground uppercase">Всего</div>
              <div className="text-lg font-semibold mt-0.5">{stats.total.toLocaleString('ru-RU')}</div>
            </CardContent>
          </Card>
          {([
            ['ПТУ', 'ПТУ'],
            ['ОРП', 'ОРП'],
            ['ПеремещениеТоваров', 'Перем.'],
            ['СписаниеТоваров', 'Спис.'],
            ['ОПЗС', 'ОПЗС'],
            ['КорректировкаПоступления', 'Корр.'],
          ] as const).map(([t, label]) => (
            <Card key={t} className="py-2 gap-0">
              <CardContent className="p-3">
                <div className="text-[10px] text-muted-foreground uppercase truncate">{label}</div>
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
        onNavigate={(id) => setSelectedDocId(id)}
      />
    </div>
  )
}


// ─── Sheet деталей одного документа ─────────────────────────────────

// ─── Инварианты розничной модели ОРП (см. docs/sverka-spec.md §1.2.5) ──
// Для розничной ОРП БП 3.0 (ВидОп=ОтчетККМОПродажах) должно выполняться:
//   Σ Кт 90.01.1 = СуммаДокумента (выручка с НДС)
//   Σ Кт 68.02   = round(СуммаДок × 22/122, 2) (выделение НДС)
//   Σ Дт 62.Р    = Σ Кт 62.Р = СуммаДокумента (баланс по контрагенту)
// Эти три проверки даём бухгалтеру прямо в UI.
function OrpInvariantsPanel({ postings, amount }: { postings: Array<Record<string, unknown>>; amount: number }) {
  function sumByAccount(side: 'AccountDt' | 'AccountCt', accountPrefix: string): number {
    return postings
      .filter((p) => String(p[side] ?? '').startsWith(accountPrefix))
      .reduce((acc, p) => acc + Number(p.Amount || 0), 0)
  }
  const k9001 = sumByAccount('AccountCt', '90.01')
  const k6802 = sumByAccount('AccountCt', '68.02')
  const dt62R = sumByAccount('AccountDt', '62')
  const k62R  = sumByAccount('AccountCt', '62')
  const expectedVat = Math.round((amount * 22 / 122) * 100) / 100

  const checks = [
    { label: 'Σ Кт 90.01.* = СуммаДок',  actual: k9001, expected: amount,       formula: `${k9001.toFixed(2)} vs ${amount.toFixed(2)}` },
    { label: 'Σ Кт 68.02 ≈ Док × 22/122', actual: k6802, expected: expectedVat,  formula: `${k6802.toFixed(2)} vs ${expectedVat.toFixed(2)}` },
    { label: 'Σ Дт 62.* = Σ Кт 62.*',     actual: dt62R, expected: k62R,         formula: `${dt62R.toFixed(2)} vs ${k62R.toFixed(2)}` },
  ]
  return (
    <div className="mt-2 pt-2 border-t border-border/40">
      <div className="text-[10px] font-semibold uppercase text-muted-foreground mb-1">
        Инварианты розничной модели ОРП
      </div>
      <div className="space-y-1">
        {checks.map((c) => {
          const delta = c.actual - c.expected
          const ok = Math.abs(delta) <= 0.01
          return (
            <div key={c.label} className="flex items-center gap-2 text-[10px]">
              <Badge variant="outline" className={`text-[9px] h-4 px-1 ${ok ? 'border-emerald-400/50 text-emerald-300/80' : 'border-red-400/50 text-red-300/80'}`}>
                {ok ? 'OK' : 'Δ'}
              </Badge>
              <span>{c.label}</span>
              <span className="font-mono text-muted-foreground ml-auto">{c.formula}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ─── Связанные документы для ОРП ─────────────────────────────────
// При проведении ОРП в БП формируются Перемещения на виртуальные склады
// (Талоны/Карты/Ведомости/Яндекс) и Списания «по прочим». Они не
// являются регистраторами ОРП, но связаны через Склад+Дата.
function RelatedDocsPanel({
  companyId, docId, onOpen,
}: { companyId: string; docId: string; onOpen: (id: string) => void }) {
  const { data: related = [], isLoading } = useQuery({
    queryKey: ['related-docs', docId],
    queryFn: () => getRelatedDocs(companyId, docId),
    enabled: !!docId,
  })
  if (!isLoading && related.length === 0) return null
  return (
    <Card className="py-3 gap-1">
      <CardHeader className="pb-0">
        <CardTitle className="text-xs uppercase text-muted-foreground">
          Связанные документы <span className="font-mono text-[10px] ml-1">({related.length})</span>
        </CardTitle>
        <CardDescription className="text-[10px]">
          Перемещения на виртуальные склады (Талоны/Карты/Ведомости/Яндекс)
          и Списания «по прочим» за тот же день со склада ОРП.
        </CardDescription>
      </CardHeader>
      <CardContent className="pt-0 text-xs">
        {isLoading && <Loader2 className="h-3 w-3 animate-spin inline mr-1" />}
        {related.length > 0 && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="h-6 text-[10px] w-32">Тип</TableHead>
                <TableHead className="h-6 text-[10px]">Номер</TableHead>
                <TableHead className="h-6 text-[10px] w-24">Дата</TableHead>
                <TableHead className="h-6 text-[10px] text-right">Сумма, ₽</TableHead>
                <TableHead className="h-6 text-[10px] w-24">Статус 1С</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {related.map((d) => (
                <TableRow key={d.id} className="text-[10px] cursor-pointer hover:bg-muted/40"
                  onClick={() => onOpen(d.id)}>
                  <TableCell className="py-1">
                    <Badge variant="outline" className="text-[9px] h-4 px-1 font-mono">
                      {d.docType === 'ПеремещениеТоваров' ? 'Перем.' : 'Спис.'}
                    </Badge>
                  </TableCell>
                  <TableCell className="py-1 font-mono">{d.number}</TableCell>
                  <TableCell className="py-1 font-mono">{d.date}</TableCell>
                  <TableCell className="py-1 text-right font-mono">
                    {(d.amount ?? 0).toLocaleString('ru-RU', { minimumFractionDigits: 2 })}
                  </TableCell>
                  <TableCell className="py-1 text-muted-foreground">{d.status1c}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}

// ─── Разбивка по видам нефтепродуктов ─────────────────────────────────
// Группирует строки ТЧ Товары по Catalog.Номенклатура (резолв через
// enrich) и считает суммы кол-ва/литров/денег по каждому виду.
// Применимо к ПТУ и ОРП.
function FuelBreakdownPanel({
  tovary,
  nomenclature,
}: {
  tovary: Array<Record<string, unknown>>
  nomenclature: Record<string, { name: string; unit?: string; density?: number; article?: string }>
}) {
  if (tovary.length === 0) return null
  type Row = { name: string; unit: string; qty: number; liters: number; sum: number; vat: number; rows: number }
  const groups = new Map<string, Row>()
  for (const row of tovary) {
    const ref = String(row.Номенклатура || '')
    const enr = nomenclature[ref] || {}
    const name = enr.name || ref.slice(0, 8) + '…'
    const unit = (enr.unit || '').toLowerCase()
    const qty = Number(row.Количество ?? 0)
    let liters = 0
    if (enr.density && enr.density > 0) {
      if (unit.includes('тонн') || unit === 'т') liters = qty * 1000 / enr.density
      else if (unit.includes('кг'))               liters = qty / enr.density
      else if (unit.includes('литр') || unit === 'л') liters = qty
    } else if (unit.includes('литр') || unit === 'л') {
      liters = qty
    }
    const sum = Number(row.Сумма ?? 0)
    const vat = Number(row.СуммаНДС ?? 0)
    const key = name
    const g = groups.get(key)
    if (g) {
      g.qty += qty; g.liters += liters; g.sum += sum; g.vat += vat; g.rows += 1
    } else {
      groups.set(key, { name, unit: enr.unit || '', qty, liters, sum, vat, rows: 1 })
    }
  }
  const totals = Array.from(groups.values()).sort((a, b) => b.sum - a.sum)
  const total_qty = totals.reduce((a, r) => a + r.qty, 0)
  const total_liters = totals.reduce((a, r) => a + r.liters, 0)
  const total_sum = totals.reduce((a, r) => a + r.sum, 0)
  const total_vat = totals.reduce((a, r) => a + r.vat, 0)

  return (
    <Card className="py-3 gap-1">
      <CardHeader className="pb-0">
        <CardTitle className="text-xs uppercase text-muted-foreground">
          Виды нефтепродуктов <span className="font-mono text-[10px] ml-1">({totals.length})</span>
        </CardTitle>
        <CardDescription className="text-[10px]">
          Группировка позиций ТЧ по Catalog.Номенклатура (имя через enrich).
        </CardDescription>
      </CardHeader>
      <CardContent className="pt-0 text-xs">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="h-6 text-[10px]">Номенклатура</TableHead>
              <TableHead className="h-6 text-[10px] text-right">Строк</TableHead>
              <TableHead className="h-6 text-[10px] text-right">Кол-во</TableHead>
              <TableHead className="h-6 text-[10px] w-10">Ед.</TableHead>
              <TableHead className="h-6 text-[10px] text-right">Литры</TableHead>
              <TableHead className="h-6 text-[10px] text-right">Сумма, ₽</TableHead>
              <TableHead className="h-6 text-[10px] text-right">НДС, ₽</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {totals.map((r) => (
              <TableRow key={r.name} className="text-[10px]">
                <TableCell className="py-1">{r.name}</TableCell>
                <TableCell className="py-1 text-right font-mono">{r.rows}</TableCell>
                <TableCell className="py-1 text-right font-mono">
                  {r.qty.toLocaleString('ru-RU', { maximumFractionDigits: 3 })}
                </TableCell>
                <TableCell className="py-1 text-muted-foreground">{r.unit || '—'}</TableCell>
                <TableCell className="py-1 text-right font-mono text-emerald-600 dark:text-emerald-300">
                  {r.liters > 0 ? r.liters.toLocaleString('ru-RU', { maximumFractionDigits: 1 }) : '—'}
                </TableCell>
                <TableCell className="py-1 text-right font-mono">
                  {r.sum.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </TableCell>
                <TableCell className="py-1 text-right font-mono">
                  {r.vat ? r.vat.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—'}
                </TableCell>
              </TableRow>
            ))}
            <TableRow className="text-[10px] font-semibold border-t-2">
              <TableCell className="py-1.5">Итого</TableCell>
              <TableCell className="py-1.5 text-right font-mono">{tovary.length}</TableCell>
              <TableCell className="py-1.5 text-right font-mono">
                {total_qty.toLocaleString('ru-RU', { maximumFractionDigits: 3 })}
              </TableCell>
              <TableCell className="py-1.5"></TableCell>
              <TableCell className="py-1.5 text-right font-mono text-emerald-600 dark:text-emerald-300">
                {total_liters > 0 ? total_liters.toLocaleString('ru-RU', { maximumFractionDigits: 1 }) : '—'}
              </TableCell>
              <TableCell className="py-1.5 text-right font-mono">
                {total_sum.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </TableCell>
              <TableCell className="py-1.5 text-right font-mono">
                {total_vat ? total_vat.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—'}
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

// ─── Цепочка слоёв L1→L2→L3→L4 (docs/sverka-spec.md §0) ─────────────
// Узлы: RAW (L1) — CLEAN (L2) — EXPORT (L3) — 1C_REF (L4)
// Между узлами — индикаторы: зелёный (есть и совпадает), жёлтый (есть с
// расхождениями), красный (разрыв), серый (нет данных для слоя).
function LayerChainPanel({ docId, matchedEntryId }: { docId: string; matchedEntryId: string | null | undefined }) {
  const qc = useQueryClient()
  // L3: пакеты выгрузки, привязанные к этому документу
  const { data: packets = [] } = useQuery<ExportPacketBrief[]>({
    queryKey: ['packets-by-doc', docId],
    queryFn: () => packetsByDoc(docId),
    enabled: !!docId,
  })
  // L1↔L2: lineage через matched DataEntry (если сверка нашла пару)
  const { data: lineage } = useQuery<EntryLineage>({
    queryKey: ['entry-lineage', matchedEntryId],
    queryFn: () => getEntryLineage(matchedEntryId!),
    enabled: !!matchedEntryId,
  })

  // Normalize L1→L2 кнопка
  const normalizeMut = useMutation({
    mutationFn: () => normalizeEntry(lineage!.raw!.id),
    onSuccess: () => {
      toast.success('L2 clean-копия создана/обновлена')
      qc.invalidateQueries({ queryKey: ['entry-lineage', matchedEntryId] })
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Ошибка нормализации'),
  })

  const hasL4 = true                                       // мы внутри документа — L4 точно есть
  const hasL3 = packets.length > 0
  const hasL2 = !!lineage?.clean
  const hasL1 = !!lineage?.raw

  // Состояние переходов
  const l1l2 = !hasL1 || !hasL2 ? 'gray'
              : (lineage!.diffStats.changed === 0 ? 'green' : 'yellow')
  const l2l3 = !hasL2 || !hasL3 ? 'gray'
              : (packets.some((p) => p.status === 'rejected') ? 'red'
                : packets.every((p) => p.status === 'acked') ? 'green' : 'yellow')
  const l3l4 = !hasL3 ? 'gray'
              : (packets.some((p) => p.targetDocId) ? 'green' : 'yellow')

  function nodeBadge(label: string, has: boolean, hint: string) {
    return (
      <div
        className={`px-2 py-1 rounded border text-[10px] font-mono ${
          has ? 'border-emerald-400/50 text-emerald-300/80 bg-emerald-500/5' : 'border-zinc-600 text-zinc-500'
        }`}
        title={hint}
      >
        {label}
      </div>
    )
  }
  function edge(state: 'green' | 'yellow' | 'red' | 'gray') {
    const styles = {
      green:  'border-emerald-400/50 text-emerald-300/80',
      yellow: 'border-amber-400/50   text-amber-300/80',
      red:    'border-red-400/50     text-red-300/80',
      gray:   'border-zinc-600       text-zinc-500',
    }
    const icons = { green: '✓', yellow: '≈', red: '✕', gray: '—' }
    return (
      <div className={`flex items-center h-5 px-1 text-[10px] border-t border-b ${styles[state]}`}>
        {icons[state]}
      </div>
    )
  }
  return (
    <Card className="py-3 gap-1">
      <CardHeader className="pb-0">
        <CardTitle className="text-xs uppercase text-muted-foreground">
          Цепочка слоёв
        </CardTitle>
        <CardDescription className="text-[10px]">
          L1 RAW (сырьё) → L2 CLEAN (норма) → L3 EXPORT (выгрузка) → L4 1C_REF (в БП ГИГ)
        </CardDescription>
      </CardHeader>
      <CardContent className="pt-0">
        <div className="flex items-stretch gap-0.5 mt-1">
          {nodeBadge('L1 RAW', hasL1, hasL1 ? `raw: ${lineage!.raw!.id.slice(0, 8)}…` : 'сырьё-пара не найдена')}
          {edge(l1l2)}
          {nodeBadge('L2 CLEAN', hasL2, hasL2 ? `clean: ${lineage!.clean!.id.slice(0, 8)}…` : 'нормализованная версия не найдена')}
          {edge(l2l3)}
          {nodeBadge('L3 EXPORT', hasL3, hasL3 ? `пакетов: ${packets.length}` : 'выгрузка в 1С не зафиксирована')}
          {edge(l3l4)}
          {nodeBadge('L4 1C_REF', hasL4, 'этот документ из БП ГИГ')}
        </div>
        {(hasL1 || hasL2 || hasL3) && (
          <div className="text-[10px] text-muted-foreground mt-2 space-y-0.5">
            {hasL1 && hasL2 && (
              <div>L1↔L2: {lineage!.diffStats.changed}/{lineage!.diffStats.total} полей с правками</div>
            )}
            {hasL3 && (
              <div>L3: {packets.map((p) => `${p.kind}/${p.status}`).join(', ')}</div>
            )}
          </div>
        )}
        {hasL1 && !hasL2 && (
          <div className="mt-2 pt-2 border-t border-border/40">
            <Button size="sm" variant="outline" onClick={() => normalizeMut.mutate()}
              disabled={normalizeMut.isPending}
              className="h-7 text-xs gap-1.5">
              {normalizeMut.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <CheckCircle2 className="h-3 w-3" />}
              Подтвердить как нормализованную (L1 → L2)
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ─── Инварианты ПТУ (см. docs/sverka-spec.md §2.4) ────────────────────
// Для типового поступления товаров и услуг:
//   Σ Кт 60.01      = СуммаДокумента (вся задолженность поставщику с НДС)
//   Σ Дт 19.03      = СуммаНДС (входной НДС к вычету)
//   Σ Дт (41/10/26) = СуммаДокумента − СуммаНДС (товары/материалы без НДС)
function PtuInvariantsPanel({ postings, amount }: { postings: Array<Record<string, unknown>>; amount: number }) {
  function sumByAccount(side: 'AccountDt' | 'AccountCt', accountPrefix: string): number {
    return postings
      .filter((p) => String(p[side] ?? '').startsWith(accountPrefix))
      .reduce((acc, p) => acc + Number(p.Amount || 0), 0)
  }
  const k60   = sumByAccount('AccountCt', '60.01')
  const dt19  = sumByAccount('AccountDt', '19.03')
  // Товары: 41.01 (опт-тонны), 41.02 (литры/розница), 10.* (материалы)
  const dt41  = sumByAccount('AccountDt', '41')
  const dt10  = sumByAccount('AccountDt', '10')
  const dtGoods = dt41 + dt10
  const expectedGoods = Math.max(0, amount - dt19)

  const checks = [
    { label: 'Σ Кт 60.01 = СуммаДок',        actual: k60,      expected: amount,         formula: `${k60.toFixed(2)} vs ${amount.toFixed(2)}` },
    { label: 'Σ Дт 41.* + 10.* ≈ Док − НДС', actual: dtGoods,  expected: expectedGoods,  formula: `${dtGoods.toFixed(2)} vs ${expectedGoods.toFixed(2)}` },
    { label: 'Σ Дт 19.03 (входной НДС)',     actual: dt19,     expected: dt19,           formula: `${dt19.toFixed(2)} ₽ к вычету` },
  ]
  return (
    <div className="mt-2 pt-2 border-t border-border/40">
      <div className="text-[10px] font-semibold uppercase text-muted-foreground mb-1">
        Инварианты ПТУ
      </div>
      <div className="space-y-1">
        {checks.map((c) => {
          const delta = c.actual - c.expected
          const ok = Math.abs(delta) <= 0.01
          const isInfoOnly = c.label.includes('к вычету')
          return (
            <div key={c.label} className="flex items-center gap-2 text-[10px]">
              <Badge variant="outline" className={`text-[9px] h-4 px-1 ${isInfoOnly ? 'border-blue-400/50 text-blue-300/80' : ok ? 'border-emerald-400/50 text-emerald-300/80' : 'border-red-400/50 text-red-300/80'}`}>
                {isInfoOnly ? 'ℹ' : ok ? 'OK' : 'Δ'}
              </Badge>
              <span>{c.label}</span>
              <span className="font-mono text-muted-foreground ml-auto">{c.formula}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

interface DetailSheetProps {
  docId: string | null
  companyId: string
  connectionId: string | undefined
  onClose: () => void
  onLinesLoaded: () => void
  onNavigate?: (id: string) => void
}

function DocumentDetailSheet({ docId, companyId, connectionId, onClose, onLinesLoaded, onNavigate }: DetailSheetProps) {
  const { data: doc, isLoading, refetch } = useQuery({
    queryKey: ['acc-doc-detail', docId],
    queryFn: () => getAccountingDocDetails(companyId, docId!),
    enabled: !!docId,
  })

  const loadMutation = useMutation({
    mutationFn: () => loadDocumentLines(connectionId!, docId!),
    onSuccess: async (r) => {
      const totals = Object.entries(r.tabular_counts).map(([k, v]) => `${k}: ${v}`).join(', ')
      toast.success(`Позиции из 1С: ${totals}${r.postings_count != null ? ` · проводок: ${r.postings_count}` : ''}`)
      await refetch()
      onLinesLoaded()
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : 'Не удалось загрузить позиции')
    },
  })

  // Enrich Номенклатуры — собираем GUID из всех Товаров и тянем имя+плотность.
  // Для ПТУ это даёт колонку «Литры» в ТЧ Товары.
  const [nomenclature, setNomenclature] = useState<Record<string, { name: string; unit?: string; density?: number; article?: string }>>({})
  const enrichMutation = useMutation({
    mutationFn: (refs: string[]) => enrichNomenclature(connectionId!, refs),
    onSuccess: (data) => setNomenclature((prev) => ({ ...prev, ...data })),
  })

  if (!docId) return null

  const lines = (doc?.lines as {
    tabular?: Record<string, unknown[]>;
    postings?: Array<Record<string, unknown>>;
    fetched_at?: string;
  } | unknown[]) || null
  const tabular = lines && !Array.isArray(lines) ? lines.tabular || {} : {}
  const postings = lines && !Array.isArray(lines) ? (lines.postings || []) : []
  const fetchedAt = lines && !Array.isArray(lines) ? lines.fetched_at : null
  const hasLines = Object.keys(tabular).length > 0 || postings.length > 0

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
            {/* Цепочка слоёв L1→L2→L3→L4 */}
            <LayerChainPanel docId={doc.id} matchedEntryId={doc.matchedEntryId} />

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

            {/* Проводки — что 1С реально записала в РегистрБухгалтерии.Хозрасчетный */}
            <Card className="py-3 gap-1">
              <CardHeader className="pb-0">
                <CardTitle className="text-xs uppercase text-muted-foreground flex items-center justify-between">
                  <span>Проводки <span className="font-mono text-[10px] ml-1">({postings.length})</span></span>
                </CardTitle>
              </CardHeader>
              <CardContent className="pt-0 text-xs">
                {postings.length === 0 && (
                  <p className="text-[10px] text-muted-foreground italic">
                    Проводки не подгружены — нажми «Загрузить из 1С» ниже.
                  </p>
                )}
                {postings.length > 0 && (
                  <>
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead className="h-6 text-[10px] w-12">№</TableHead>
                          <TableHead className="h-6 text-[10px]">Дт</TableHead>
                          <TableHead className="h-6 text-[10px]">Кт</TableHead>
                          <TableHead className="h-6 text-[10px] text-right">Сумма, ₽</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {postings.map((p, i) => (
                          <TableRow key={i} className="text-[10px]">
                            <TableCell className="py-1 font-mono text-muted-foreground">{i + 1}</TableCell>
                            <TableCell className="py-1 font-mono">{String(p.AccountDt ?? '—')}</TableCell>
                            <TableCell className="py-1 font-mono">{String(p.AccountCt ?? '—')}</TableCell>
                            <TableCell className="py-1 text-right font-mono">
                              {p.Amount != null ? new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2 }).format(Number(p.Amount)) : '—'}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                    {doc.docType === 'ОРП' && <OrpInvariantsPanel postings={postings} amount={doc.amount} />}
                    {doc.docType === 'ПТУ' && <PtuInvariantsPanel postings={postings} amount={doc.amount} />}
                  </>
                )}
              </CardContent>
            </Card>

            {/* Связанные документы — Перемещения на виртуальные склады и Списания */}
            {doc.docType === 'ОРП' && onNavigate && (
              <RelatedDocsPanel companyId={companyId} docId={doc.id} onOpen={onNavigate} />
            )}

            {/* Виды нефтепродуктов — группировка ТЧ Товары по Catalog.Номенклатура */}
            {Array.isArray((tabular as Record<string, unknown>).Товары) && ((tabular as Record<string, unknown>).Товары as unknown[]).length > 0 && (
              <FuelBreakdownPanel
                tovary={(tabular as Record<string, unknown>).Товары as Array<Record<string, unknown>>}
                nomenclature={nomenclature}
              />
            )}

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
                {hasLines && Object.entries(tabular).filter(([k]) => !k.startsWith('_')).map(([tabName, rows]) => {
                  const list = rows as Array<Record<string, unknown>>
                  if (list.length === 0) {
                    return (
                      <div key={tabName} className="mb-3">
                        <div className="text-[10px] font-semibold uppercase text-muted-foreground mb-1">{tabName} (0)</div>
                        <p className="text-[10px] text-muted-foreground italic">пусто</p>
                      </div>
                    )
                  }
                  const isTovary = tabName === 'Товары'
                  // Для ПТУ.Товары — собираем GUIDы Номенклатуры и автоматически дёргаем enrich
                  if (doc.docType === 'ПТУ' && isTovary && connectionId) {
                    const guids = list.map((r) => String(r.Номенклатура || '')).filter((g) => g && !nomenclature[g])
                    if (guids.length > 0 && !enrichMutation.isPending) {
                      enrichMutation.mutate(guids)
                    }
                  }
                  return (
                    <div key={tabName} className="mb-3">
                      <div className="text-[10px] font-semibold uppercase text-muted-foreground mb-1">
                        {tabName} ({list.length})
                        {doc.docType === 'ПТУ' && isTovary && enrichMutation.isPending && (
                          <Loader2 className="inline h-2.5 w-2.5 animate-spin ml-1" />
                        )}
                      </div>
                      {doc.docType === 'ПТУ' && isTovary ? (
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead className="h-6 text-[10px]">Номенклатура</TableHead>
                              <TableHead className="h-6 text-[10px] text-right">Кол-во</TableHead>
                              <TableHead className="h-6 text-[10px] w-12">Ед.</TableHead>
                              <TableHead className="h-6 text-[10px] text-right">Литры</TableHead>
                              <TableHead className="h-6 text-[10px] text-right">Цена</TableHead>
                              <TableHead className="h-6 text-[10px] text-right">Сумма</TableHead>
                              <TableHead className="h-6 text-[10px] text-right">НДС</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {list.map((row, i) => {
                              const ref = String(row.Номенклатура || '')
                              const enr = nomenclature[ref] || {}
                              const qty = Number(row.Количество ?? 0)
                              const density = enr.density
                              const unit = (enr.unit || '').toLowerCase()
                              // Если ед.изм похожа на тонны/кг — посчитать литры через плотность.
                              let liters: number | null = null
                              if (density && density > 0) {
                                if (unit.includes('тонн') || unit === 'т') liters = qty * 1000 / density
                                else if (unit.includes('кг'))               liters = qty / density
                                else if (unit.includes('литр') || unit === 'л') liters = qty
                              }
                              return (
                                <TableRow key={i} className="text-[10px]">
                                  <TableCell className="py-1 max-w-[200px] truncate" title={enr.name || ref}>
                                    {enr.name || <span className="font-mono text-muted-foreground">{ref.slice(0, 8)}…</span>}
                                  </TableCell>
                                  <TableCell className="py-1 text-right font-mono">{qty.toLocaleString('ru-RU')}</TableCell>
                                  <TableCell className="py-1 text-muted-foreground">{enr.unit || '—'}</TableCell>
                                  <TableCell className="py-1 text-right font-mono text-emerald-600 dark:text-emerald-300">
                                    {liters != null ? liters.toLocaleString('ru-RU', { maximumFractionDigits: 1 }) : '—'}
                                  </TableCell>
                                  <TableCell className="py-1 text-right font-mono">{row.Цена != null ? Number(row.Цена).toFixed(2) : '—'}</TableCell>
                                  <TableCell className="py-1 text-right font-mono">{row.Сумма != null ? Number(row.Сумма).toFixed(2) : '—'}</TableCell>
                                  <TableCell className="py-1 text-right font-mono">{row.СуммаНДС != null ? Number(row.СуммаНДС).toFixed(2) : '—'}</TableCell>
                                </TableRow>
                              )
                            })}
                          </TableBody>
                        </Table>
                      ) : (
                        <Table>
                          <TableHeader>
                            <TableRow>
                              {Object.keys(list[0]).map((k) => (
                                <TableHead key={k} className="h-6 text-[10px]">{k}</TableHead>
                              ))}
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {list.slice(0, 50).map((row, i) => (
                              <TableRow key={i} className="text-[10px]">
                                {Object.keys(list[0]).map((k) => (
                                  <TableCell key={k} className="py-1 font-mono truncate max-w-[140px]" title={String(row[k] ?? '')}>
                                    {row[k] == null ? '—' : String(row[k]).slice(0, 24)}
                                  </TableCell>
                                ))}
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      )}
                    </div>
                  )
                })}
              </CardContent>
            </Card>
          </div>
        )}
      </SheetContent>
    </Sheet>
  )
}

