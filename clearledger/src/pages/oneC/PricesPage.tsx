/**
 * Страница «1С → Цены номенклатуры».
 *
 * Срез РегС.ЦеныНоменклатуры из БП ГИГ — последняя цена на каждую пару
 * (Номенклатура, ВидЦен). Используется для:
 * - проверки входной цены ТТН против актуальной закупочной цены
 * - сверки розничной выручки против актуальной розничной цены
 *
 * Источник:
 *   POST /api/onec/connections/{id}/sync/prices — pull
 *   GET  /api/prices — список
 */

import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { RefreshCw, Loader2, Tag, Search, Fuel, ExternalLink, FileText } from 'lucide-react'
import { toast } from 'sonner'
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '@/components/ui/sheet'
import { useNavigate } from 'react-router-dom'

import { useCompany } from '@/contexts/CompanyContext'
import { get, post } from '@/services/apiClient'

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

interface PriceRow {
  id: string
  nomenclature_ref: string
  nomenclature_name: string | null
  price_type_ref: string
  price_type_name: string | null
  period: string
  price: number
  currency: string | null
  unit: string | null
}

interface Connection {
  id: string
  company_id: string
  name: string
  status: string
}

async function fetchPrices(companyId: string): Promise<PriceRow[]> {
  return get<PriceRow[]>('/api/prices', { company_id: companyId, limit: 2000 })
}

async function fetchConnections(companyId: string): Promise<Connection[]> {
  return get<Connection[]>('/api/onec/connections', { company_id: companyId })
}

async function syncPrices(connectionId: string): Promise<{ stats: { processed: number } }> {
  return post(`/api/onec/connections/${connectionId}/sync/prices`)
}

// Идентификация нефтепродуктов — для подсветки и сортировки в начало.
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

export function PricesPage() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<PriceRow | null>(null)

  const { data: prices, isLoading, error } = useQuery({
    queryKey: ['nomenclature-prices', companyId],
    queryFn: () => fetchPrices(companyId),
  })

  const { data: connections } = useQuery({
    queryKey: ['onec-connections', companyId],
    queryFn: () => fetchConnections(companyId),
  })

  const activeConn = connections?.find((c) => c.status === 'active') ?? connections?.[0]

  const sync = useMutation({
    mutationFn: () => {
      if (!activeConn) throw new Error('Нет активного подключения')
      return syncPrices(activeConn.id)
    },
    onSuccess: (r) => {
      toast.success(`Обновлено цен: ${r.stats.processed}`)
      qc.invalidateQueries({ queryKey: ['nomenclature-prices', companyId] })
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Ошибка sync'),
  })

  const filtered = useMemo(() => {
    if (!prices) return []
    const q = search.trim().toLowerCase()
    if (!q) return prices
    return prices.filter((p) =>
      (p.nomenclature_name ?? '').toLowerCase().includes(q) ||
      p.nomenclature_ref.toLowerCase().includes(q) ||
      (p.price_type_name ?? '').toLowerCase().includes(q)
    )
  }, [prices, search])

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold flex items-center gap-2">
            <Tag className="h-6 w-6" />
            Цены номенклатуры
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Срез РегС.ЦеныНоменклатуры из БП ГИГ — актуальные оптовые/розничные цены
            для проверки входных цен ТТН и розничной выручки.
          </p>
        </div>
        <Button
          size="sm"
          onClick={() => sync.mutate()}
          disabled={!activeConn || sync.isPending}
        >
          {sync.isPending ? <Loader2 className="h-4 w-4 mr-1.5 animate-spin" /> : <RefreshCw className="h-4 w-4 mr-1.5" />}
          Обновить из 1С
        </Button>
      </div>

      <div className="flex items-center gap-2">
        <Search className="h-4 w-4 text-muted-foreground" />
        <Input
          placeholder="Поиск по номенклатуре или виду цены..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="max-w-md"
        />
        <span className="text-xs text-muted-foreground">
          {filtered.length} из {prices?.length ?? 0}
        </span>
      </div>

      {error && (
        <Card className="border-red-500/40">
          <CardContent className="pt-6 text-sm text-red-400">
            Ошибка: {error instanceof Error ? error.message : String(error)}
          </CardContent>
        </Card>
      )}
      {isLoading && (
        <div className="flex items-center justify-center py-12 text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin mr-2" />
          Загрузка...
        </div>
      )}

      {!isLoading && filtered.length === 0 && (
        <Card>
          <CardContent className="pt-6 text-sm text-muted-foreground text-center">
            {search ? 'Ничего не найдено' : 'Цены не загружены. Нажмите «Обновить из 1С».'}
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
                  <TableHead>Вид цены</TableHead>
                  <TableHead>Период</TableHead>
                  <TableHead className="text-right">Цена</TableHead>
                  <TableHead>Валюта</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.slice(0, 500).map((p) => {
                  const isFuel = isFuelName(p.nomenclature_name)
                  return (
                  <TableRow
                    key={p.id}
                    className={`cursor-pointer hover:bg-muted/50 ${isFuel ? 'bg-amber-500/5' : ''}`}
                    onClick={() => setSelected(p)}
                  >
                    <TableCell className="font-medium">
                      <div className="flex items-center gap-1.5">
                        {isFuel && <Fuel className="h-3.5 w-3.5 text-amber-500 shrink-0" />}
                        {p.nomenclature_name ?? <span className="text-muted-foreground font-mono text-xs">{p.nomenclature_ref.slice(0, 8)}...</span>}
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline">{p.price_type_name ?? p.price_type_ref.slice(0, 8)}</Badge>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {p.period ? new Date(p.period).toLocaleDateString('ru-RU') : '—'}
                    </TableCell>
                    <TableCell className="text-right font-mono">
                      {new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 4 }).format(p.price)}
                    </TableCell>
                    <TableCell className="text-xs">{p.currency ?? 'RUB'}</TableCell>
                  </TableRow>
                  )
                })}
              </TableBody>
            </Table>
            {filtered.length > 500 && (
              <div className="p-3 text-xs text-muted-foreground text-center border-t border-border/30">
                Показано первые 500 из {filtered.length}. Уточните поиск.
              </div>
            )}
          </CardContent>
        </Card>
      )}

      <PurchaseDocsSheet
        priceRow={selected}
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

function PurchaseDocsSheet({
  priceRow,
  companyId,
  onClose,
  onOpenDoc,
}: {
  priceRow: PriceRow | null
  companyId: string
  onClose: () => void
  onOpenDoc: (docId: string) => void
}) {
  const { data: docs, isLoading } = useQuery({
    queryKey: ['purchase-docs', priceRow?.nomenclature_ref, companyId],
    queryFn: () =>
      get<PurchaseDoc[]>(`/api/nomenclature/${priceRow!.nomenclature_ref}/purchase-docs`, {
        company_id: companyId,
        limit: 50,
      }),
    enabled: !!priceRow,
  })
  return (
    <Sheet open={!!priceRow} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="sm:max-w-[640px] overflow-y-auto">
        <SheetHeader>
          <SheetTitle className="text-base">
            {priceRow?.nomenclature_name ?? '—'}
          </SheetTitle>
          <SheetDescription className="text-xs">
            Текущая цена: {priceRow ? new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2 }).format(priceRow.price) : ''} ₽
            ({priceRow?.price_type_name})
          </SheetDescription>
        </SheetHeader>
        <div className="mt-4 space-y-2">
          <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider flex items-center gap-1.5">
            <FileText className="h-3.5 w-3.5" />
            Закупочные документы (ПТУ + корректировки)
          </div>
          {isLoading && (
            <div className="flex items-center justify-center py-8 text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin mr-2" />
              Поиск документов...
            </div>
          )}
          {!isLoading && (!docs || docs.length === 0) && (
            <Card>
              <CardContent className="pt-6 text-xs text-muted-foreground text-center">
                Закупочные документы с этой номенклатурой не найдены в локальной БД.
                Возможно ТЧ ПТУ ещё не подгружены — откройте журнал документов
                и подгрузите позиции каждого ПТУ.
              </CardContent>
            </Card>
          )}
          {docs && docs.length > 0 && (
            <div className="space-y-1.5">
              {docs.map((d) => (
                <Card
                  key={d.id}
                  className="cursor-pointer hover:bg-muted/50 transition-colors"
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
                        <div className="mt-1 flex items-center gap-3 text-[11px]">
                          {d.line_quantity != null && (
                            <span>Кол-во: <span className="font-mono text-foreground">{new Intl.NumberFormat('ru-RU').format(d.line_quantity)}</span></span>
                          )}
                          {d.line_price != null && (
                            <span>Цена: <span className="font-mono text-foreground">{new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2 }).format(d.line_price)} ₽</span></span>
                          )}
                          {d.line_sum != null && (
                            <span>Сумма: <span className="font-mono text-foreground">{new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2 }).format(d.line_sum)} ₽</span></span>
                          )}
                        </div>
                      </div>
                      <ExternalLink className="h-3.5 w-3.5 text-muted-foreground shrink-0 mt-1" />
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}
