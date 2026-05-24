/**
 * Страница «1С → Партии товаров (FIFO)».
 *
 * Срез РегистрНакопления.ПартииТоваровНаСкладах из БП ГИГ —
 * остаток партии (по документу-регистратору) на каждую пару
 * (Номенклатура, Склад). Используется для:
 * - проверки наличия партий перед СПИС/Перемещением при Дне X
 * - расчёта плановой себестоимости FIFO
 *
 * Источник:
 *   POST /api/onec/connections/{id}/sync/batches
 *   GET  /api/batches
 */

import { useEffect, useMemo, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { RefreshCw, Loader2, Layers, Search, Fuel, ExternalLink, FileText } from 'lucide-react'
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '@/components/ui/sheet'
import { useNavigate } from 'react-router-dom'

interface PurchaseDoc {
  id: string
  external_id: string
  doc_type: string
  number: string
  date: string
  counterparty_name: string
  counterparty_inn: string | null
  organization_name: string | null
  amount: number
  line_quantity: number | null
  line_price: number | null
  line_sum: number | null
}

// Идентификация нефтепродуктов
const FUEL_PATTERNS = [
  'АИ-', 'АИ ', 'А-92', 'А-95', 'А-98',
  'ДТ', 'Дизель', 'Дизельное',
  'Бензин', 'Топливо',
  'СУГ', 'ПБ', 'Пропан', 'Бутан', 'СПБТ', 'Газ моторн',
  'Нефть', 'Мазут',
]
function isFuelName(name: string | null | undefined): boolean {
  if (!name) return false
  const upper = name.toUpperCase()
  return FUEL_PATTERNS.some((p) => upper.includes(p.toUpperCase()))
}
import { toast } from 'sonner'

import { useCompany } from '@/contexts/CompanyContext'
import { get, post } from '@/services/apiClient'

interface BatchRow {
  id: string
  batch_doc_type: string | null
  batch_doc_ref: string
  batch_doc_number: string | null
  batch_doc_date: string | null
  nomenclature_ref: string
  nomenclature_name: string | null
  warehouse_ref: string | null
  warehouse_name: string | null
  quantity_remaining: number
  amount_remaining: number
  unit_price: number | null
  source: string
}

interface Connection {
  id: string
  company_id: string
  name: string
  status: string
}

async function fetchBatches(companyId: string): Promise<BatchRow[]> {
  return get<BatchRow[]>('/api/batches', { company_id: companyId, limit: 3000 })
}
async function fetchConnections(companyId: string): Promise<Connection[]> {
  return get<Connection[]>('/api/onec/connections', { company_id: companyId })
}
async function syncBatches(connectionId: string): Promise<{ stats: { processed: number }; details: Record<string, unknown> }> {
  return post(`/api/onec/connections/${connectionId}/sync/batches`)
}

export function BatchesPage() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const [bpInfo, setBpInfo] = useState<string | null>(null)
  const [selected, setSelected] = useState<BatchRow | null>(null)

  const { data: batches, isLoading } = useQuery({
    queryKey: ['inventory-batches', companyId],
    queryFn: () => fetchBatches(companyId),
  })

  // При первом заходе — показываем причину пустого списка из последнего лога sync
  // (запрашиваем последний sync log с типом batches)
  useEffect(() => {
    if (batches !== undefined && batches.length === 0 && !bpInfo) {
      // батчей нет — это означает что либо ещё не синкали, либо БП без партий.
      // Подсказку показываем только если уже был sync — определяем по факту наличия
      // лога. Простая эвристика: если есть какие-либо записи в БД — лог был.
      // Иначе подсказка появится только после клика «Обновить из 1С».
      // Здесь предзаполняем bpInfo дефолтным explainer.
      setBpInfo(
        'Партионный учёт в БП ГИГ не ведётся, и регистр ТоварыНаСкладах недоступен. ' +
        'Для ГИГ типична работа без партий (БП 3.0 базовая поставка, не Управление торговлей). ' +
        'Раздел остаётся пустым — это нормальное состояние.'
      )
    }
  }, [batches, bpInfo])
  const { data: connections } = useQuery({
    queryKey: ['onec-connections', companyId],
    queryFn: () => fetchConnections(companyId),
  })
  const activeConn = connections?.find((c) => c.status === 'active') ?? connections?.[0]

  const sync = useMutation({
    mutationFn: () => {
      if (!activeConn) throw new Error('Нет активного подключения')
      return syncBatches(activeConn.id)
    },
    onSuccess: (r) => {
      const d = r.details ?? {}
      const info = d.info as string | undefined
      const batches = (d.batches as number | undefined) ?? r.stats?.processed ?? 0
      if (info) {
        setBpInfo(info)
        toast.info('Партионный учёт не настроен в БП ГИГ', { duration: 8000, description: info.slice(0, 100) })
      } else {
        setBpInfo(null)
        toast.success(`Партий обновлено: ${batches}`, {
          description: `Из движений: ${d.raw_movements ?? '—'}, нулевых пропущено: ${d.skipped_empty ?? '—'}`,
        })
      }
      qc.invalidateQueries({ queryKey: ['inventory-batches', companyId] })
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Ошибка sync'),
  })

  const filtered = useMemo(() => {
    if (!batches) return []
    const q = search.trim().toLowerCase()
    if (!q) return batches
    return batches.filter((b) =>
      (b.nomenclature_name ?? '').toLowerCase().includes(q) ||
      (b.warehouse_name ?? '').toLowerCase().includes(q) ||
      b.batch_doc_ref.toLowerCase().includes(q)
    )
  }, [batches, search])

  const totals = useMemo(() => {
    const t = { qty: 0, amt: 0, count: 0 }
    for (const b of filtered) {
      t.qty += b.quantity_remaining
      t.amt += b.amount_remaining
      t.count += 1
    }
    return t
  }, [filtered])

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold flex items-center gap-2">
            <Layers className="h-6 w-6" />
            Партии товаров (FIFO)
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Остатки по партиям из РегистрНакопления.ПартииТоваровНаСкладах БП ГИГ.
            Каждая партия — отдельный документ-регистратор (ПТУ или ВводОстатков).
          </p>
        </div>
        <Button size="sm" onClick={() => sync.mutate()} disabled={!activeConn || sync.isPending}>
          {sync.isPending ? <Loader2 className="h-4 w-4 mr-1.5 animate-spin" /> : <RefreshCw className="h-4 w-4 mr-1.5" />}
          Обновить из 1С
        </Button>
      </div>

      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2 flex-1">
          <Search className="h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Поиск по номенклатуре / складу / GUID партии..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="max-w-md"
          />
        </div>
        <div className="text-xs text-muted-foreground space-x-3">
          <span>Партий: <span className="font-mono text-foreground">{totals.count}</span></span>
          <span>Итого: <span className="font-mono text-foreground">{new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2 }).format(totals.amt)} ₽</span></span>
        </div>
      </div>

      {isLoading && (
        <div className="flex items-center justify-center py-12 text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin mr-2" />
          Загрузка...
        </div>
      )}

      {!isLoading && filtered.length === 0 && bpInfo && (
        <Card className="border-amber-500/40 bg-amber-500/5">
          <CardContent className="pt-6 text-sm space-y-2">
            <div className="flex items-start gap-2">
              <Layers className="h-5 w-5 text-amber-500 mt-0.5 shrink-0" />
              <div>
                <p className="font-medium text-amber-200">Партионный учёт в БП ГИГ не настроен</p>
                <p className="text-xs text-muted-foreground mt-1">{bpInfo}</p>
                <p className="text-[11px] text-muted-foreground mt-2">
                  В БП ГИГ ред. 3.0.194 отсутствуют регистры накопления для товарных партий
                  (<code>ПартииТоваровНаСкладах</code>, <code>ТоварыНаСкладах</code>, <code>ТоварыОрганизаций</code>).
                  Это означает что учёт ведётся по средней себестоимости через бухгалтерский регистр{' '}
                  <code>Хозрасчетный</code>, без выделения партий FIFO. Для включения FIFO потребуется
                  смена учётной политики в БП и активация партионного регистра.
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {!isLoading && filtered.length === 0 && !bpInfo && (
        <Card>
          <CardContent className="pt-6 text-sm text-muted-foreground text-center">
            {search ? 'Ничего не найдено' : 'Партии не загружены. Нажмите «Обновить из 1С».'}
          </CardContent>
        </Card>
      )}

      {filtered.length > 0 && (
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Номенклатура</TableHead>
                  <TableHead>Склад</TableHead>
                  <TableHead className="text-xs">Партия (рег.)</TableHead>
                  <TableHead className="text-right">Кол-во</TableHead>
                  <TableHead className="text-right">Сумма, ₽</TableHead>
                  <TableHead className="text-right">Цена, ₽</TableHead>
                  <TableHead>Источник</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.slice(0, 800).map((b) => {
                  const isFuel = isFuelName(b.nomenclature_name)
                  return (
                  <TableRow
                    key={b.id}
                    className={`cursor-pointer hover:bg-muted/50 ${isFuel ? 'bg-amber-500/5' : ''}`}
                    onClick={() => setSelected(b)}
                  >
                    <TableCell className="font-medium">
                      <div className="flex items-center gap-1.5">
                        {isFuel && <Fuel className="h-3.5 w-3.5 text-amber-500 shrink-0" />}
                        {b.nomenclature_name ?? <span className="text-muted-foreground font-mono text-xs">{b.nomenclature_ref.slice(0, 8)}...</span>}
                      </div>
                    </TableCell>
                    <TableCell className="text-xs">{b.warehouse_name ?? '—'}</TableCell>
                    <TableCell className="font-mono text-[10px] text-muted-foreground">
                      {b.batch_doc_ref.slice(0, 8)}...
                    </TableCell>
                    <TableCell className="text-right font-mono">
                      {new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 4 }).format(b.quantity_remaining)}
                    </TableCell>
                    <TableCell className="text-right font-mono">
                      {new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2 }).format(b.amount_remaining)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-muted-foreground">
                      {b.unit_price != null ? new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 4 }).format(b.unit_price) : '—'}
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className="text-[10px]">{b.source}</Badge>
                    </TableCell>
                  </TableRow>
                  )
                })}
              </TableBody>
            </Table>
            {filtered.length > 800 && (
              <div className="p-3 text-xs text-muted-foreground text-center border-t border-border/30">
                Показано первые 800 из {filtered.length}. Уточните поиск.
              </div>
            )}
          </CardContent>
        </Card>
      )}

      <BatchDocsSheet
        batch={selected}
        companyId={companyId}
        onClose={() => setSelected(null)}
        onOpenDoc={(docId) => {
          setSelected(null)
          navigate(`/1c/documents?selected=${docId}`)
        }}
      />
    </div>
  )
}

function BatchDocsSheet({
  batch,
  companyId,
  onClose,
  onOpenDoc,
}: {
  batch: BatchRow | null
  companyId: string
  onClose: () => void
  onOpenDoc: (docId: string) => void
}) {
  const { data: docs, isLoading } = useQuery({
    queryKey: ['purchase-docs', batch?.nomenclature_ref, companyId],
    queryFn: () =>
      get<PurchaseDoc[]>(`/api/nomenclature/${batch!.nomenclature_ref}/purchase-docs`, {
        company_id: companyId,
        limit: 50,
      }),
    enabled: !!batch,
  })
  // Если у партии есть batch_doc_ref — выделяем этот документ как «партия-регистратор»
  const registrator = batch?.batch_doc_ref
  const regDoc = docs?.find((d) => d.external_id === registrator)
  return (
    <Sheet open={!!batch} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="sm:max-w-[640px] overflow-y-auto">
        <SheetHeader>
          <SheetTitle className="text-base">{batch?.nomenclature_name ?? '—'}</SheetTitle>
          <SheetDescription className="text-xs">
            Остаток: {batch ? new Intl.NumberFormat('ru-RU').format(batch.quantity_remaining) : ''} ·
            Сумма: {batch ? new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2 }).format(batch.amount_remaining) : ''} ₽
            {batch?.warehouse_name && ` · Склад: ${batch.warehouse_name}`}
          </SheetDescription>
        </SheetHeader>
        <div className="mt-4 space-y-3">
          {regDoc && (
            <div>
              <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1.5">
                Документ-регистратор партии
              </div>
              <Card
                className="cursor-pointer hover:bg-muted/50 border-amber-500/40 bg-amber-500/5"
                onClick={() => onOpenDoc(regDoc.id)}
              >
                <CardContent className="p-3 text-xs">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <div className="font-semibold flex items-center gap-1.5">
                        <Badge variant="outline" className="text-[10px]">{regDoc.doc_type}</Badge>
                        № {regDoc.number} от {new Date(regDoc.date).toLocaleDateString('ru-RU')}
                      </div>
                      <div className="mt-1 text-muted-foreground">{regDoc.counterparty_name}</div>
                    </div>
                    <ExternalLink className="h-3.5 w-3.5 text-muted-foreground" />
                  </div>
                </CardContent>
              </Card>
            </div>
          )}
          <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider flex items-center gap-1.5">
            <FileText className="h-3.5 w-3.5" />
            Все закупочные документы с этой номенклатурой
          </div>
          {isLoading && (
            <div className="flex items-center justify-center py-6 text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin mr-2" />
              Поиск...
            </div>
          )}
          {!isLoading && (!docs || docs.length === 0) && (
            <Card>
              <CardContent className="pt-4 text-xs text-muted-foreground text-center">
                Документы не найдены. Откройте журнал и подгрузите ТЧ ПТУ.
              </CardContent>
            </Card>
          )}
          {docs && docs.filter((d) => d.id !== regDoc?.id).map((d) => (
            <Card
              key={d.id}
              className="cursor-pointer hover:bg-muted/50"
              onClick={() => onOpenDoc(d.id)}
            >
              <CardContent className="p-3 text-xs">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="font-semibold flex items-center gap-1.5">
                      <Badge variant="outline" className="text-[10px]">{d.doc_type}</Badge>
                      <span className="font-mono">№ {d.number}</span>
                      <span className="text-muted-foreground">от {new Date(d.date).toLocaleDateString('ru-RU')}</span>
                    </div>
                    <div className="mt-1 text-muted-foreground truncate">
                      {d.counterparty_name} {d.counterparty_inn && `· ИНН ${d.counterparty_inn}`}
                    </div>
                    {(d.line_quantity != null || d.line_price != null) && (
                      <div className="mt-1 flex items-center gap-3 text-[11px]">
                        {d.line_quantity != null && (
                          <span>Кол-во: <span className="font-mono text-foreground">{d.line_quantity}</span></span>
                        )}
                        {d.line_price != null && (
                          <span>Цена: <span className="font-mono text-foreground">{d.line_price.toFixed(2)} ₽</span></span>
                        )}
                      </div>
                    )}
                  </div>
                  <ExternalLink className="h-3.5 w-3.5 text-muted-foreground shrink-0 mt-1" />
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      </SheetContent>
    </Sheet>
  )
}
