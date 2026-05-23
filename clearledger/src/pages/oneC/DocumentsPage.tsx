/**
 * Страница «1С → Документы». Просмотр импортированных учётных
 * документов БП ГИГ (AccountingDoc): ПТУ, ОРП, ОПЗС,
 * КорректировкаПоступления. Фильтры: тип, период, поиск, статус
 * сверки. Сортировка по дате/сумме. Пагинация.
 */

import { useState, useMemo } from 'react'
import { useQuery, keepPreviousData } from '@tanstack/react-query'
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
  FileText, Search, RefreshCw, Loader2, ChevronLeft, ChevronRight,
  ArrowDown, ArrowUp,
} from 'lucide-react'
import { toast } from 'sonner'
import { format } from 'date-fns'

import { useCompany } from '@/contexts/CompanyContext'
import { useOneCConnections, useSyncDocuments } from '@/hooks/useOneCSync'
import {
  searchAccountingDocs,
  getAccountingDocsStats,
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

const MATCH_STATUSES = [
  { value: 'all',         label: 'Все статусы' },
  { value: 'pending',     label: 'Не сверен' },
  { value: 'matched',     label: 'Сверен' },
  { value: 'discrepancy', label: 'Расхождение' },
  { value: 'unmatched',   label: 'Без пары' },
]

const SORT_OPTIONS: { value: DocSort; label: string; icon: typeof ArrowDown }[] = [
  { value: 'date_desc',   label: 'Дата ↓',  icon: ArrowDown },
  { value: 'date_asc',    label: 'Дата ↑',  icon: ArrowUp },
  { value: 'amount_desc', label: 'Сумма ↓', icon: ArrowDown },
  { value: 'amount_asc',  label: 'Сумма ↑', icon: ArrowUp },
]

const STATUS_STYLE: Record<string, string> = {
  matched:     'border-emerald-400/50 text-emerald-300/80',
  discrepancy: 'border-amber-400/50 text-amber-300/80',
  unmatched:   'border-zinc-600 text-zinc-400',
  pending:     'border-blue-400/50 text-blue-300/80',
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
  const [matchStatus, setMatchStatus] = useState<string>('all')
  const [sort, setSort] = useState<DocSort>('date_desc')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [offset, setOffset] = useState(0)

  const params = useMemo(() => ({
    q,
    docType: docType === 'all' ? undefined : docType,
    matchStatus: matchStatus === 'all' ? undefined : matchStatus,
    sort,
    dateFrom: dateFrom || undefined,
    dateTo: dateTo || undefined,
    limit: PAGE_SIZE,
    offset,
  }), [q, docType, matchStatus, sort, dateFrom, dateTo, offset])

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
              <Select value={matchStatus} onValueChange={(v) => { setMatchStatus(v); resetOffset() }}>
                <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {MATCH_STATUSES.map((s) => (
                    <SelectItem key={s.value} value={s.value} className="text-xs">{s.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="md:col-span-2">
              <Input type="date"
                value={dateFrom}
                onChange={(e) => { setDateFrom(e.target.value); resetOffset() }}
                placeholder="С"
                className="h-8 text-xs"
              />
            </div>
            <div className="md:col-span-2">
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
                <TableHead className="h-7 text-[10px] w-24">Тип</TableHead>
                <TableHead className="h-7 text-[10px] w-28">Номер</TableHead>
                <TableHead className="h-7 text-[10px] w-24">Дата</TableHead>
                <TableHead className="h-7 text-[10px]">Контрагент</TableHead>
                <TableHead className="h-7 text-[10px]">Организация</TableHead>
                <TableHead className="h-7 text-[10px] w-32 text-right">Сумма, ₽</TableHead>
                <TableHead className="h-7 text-[10px] w-24">Статус</TableHead>
                <TableHead className="h-7 text-[10px] w-24">Сверка</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(data?.items ?? []).map((d) => (
                <TableRow key={d.id} className="text-xs">
                  <TableCell className="py-1.5">
                    <Badge variant="outline" className="text-[9px] h-4 px-1 font-mono">
                      {d.docType === 'КорректировкаПоступления' ? 'Корр.' : d.docType}
                    </Badge>
                  </TableCell>
                  <TableCell className="py-1.5 font-mono text-[11px]">{d.number || '—'}</TableCell>
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
                  <TableCell className="py-1.5 text-[10px] text-muted-foreground">{d.status1c}</TableCell>
                  <TableCell className="py-1.5">
                    <Badge variant="outline" className={`text-[9px] h-4 px-1 ${STATUS_STYLE[d.matchStatus] ?? ''}`}>
                      {MATCH_STATUSES.find((s) => s.value === d.matchStatus)?.label ?? d.matchStatus}
                    </Badge>
                  </TableCell>
                </TableRow>
              ))}
              {data && data.items.length === 0 && (
                <TableRow>
                  <TableCell colSpan={8} className="text-center text-[11px] text-muted-foreground py-6">
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
    </div>
  )
}
