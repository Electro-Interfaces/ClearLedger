import { useDeferredValue, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, ChevronLeft, ChevronRight, CircleDashed, Search } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { getLoadedReceipts, type LoadedReceipt } from '@/services/fuel/fuelMappingService'
import { ReceiptDetailsModal } from './ReceiptDetailsModal'

type CostStatus = 'all' | 'costed' | 'missing' | 'invalid'

const PAGE_SIZE = 25
const EMPTY_RECEIPTS: LoadedReceipt[] = []
const integer = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const price = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const price4 = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 4, maximumFractionDigits: 4 })

function receiptStatus(receipt: LoadedReceipt): Exclude<CostStatus, 'all'> {
  const invalidVolume = receipt.doc_volume_liters <= 0
  const invalidDensity = receipt.density == null || receipt.density <= 0
  if (invalidVolume || invalidDensity) return 'invalid'
  return receipt.has_cost ? 'costed' : 'missing'
}

function dateValue(receipt: LoadedReceipt) {
  return receipt.received_at || receipt.created_at
}

function CostBadge({ receipt }: { receipt: LoadedReceipt }) {
  const status = receiptStatus(receipt)
  if (status === 'costed') return <Badge><CheckCircle2 />Заполнена</Badge>
  if (status === 'missing') return <Badge variant="secondary"><CircleDashed />Не заполнена</Badge>
  return <Badge variant="destructive"><AlertTriangle />Некорректные данные</Badge>
}

export function ReceiptCostRegistry() {
  const query = useQuery({ queryKey: ['fuel-receipts-journal'], queryFn: getLoadedReceipts })
  const receipts = query.data ?? EMPTY_RECEIPTS
  const [status, setStatus] = useState<CostStatus>('all')
  const [fuel, setFuel] = useState('all')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [openReceipt, setOpenReceipt] = useState<LoadedReceipt | null>(null)
  const deferredSearch = useDeferredValue(search.trim().toLocaleLowerCase('ru-RU'))

  const counts = useMemo(() => {
    const result = { all: receipts.length, costed: 0, missing: 0, invalid: 0 }
    for (const receipt of receipts) result[receiptStatus(receipt)] += 1
    return result
  }, [receipts])

  const fuelOptions = useMemo(() => {
    const values = new Map<string, string>()
    for (const receipt of receipts) values.set(String(receipt.fuel_code ?? -1), receipt.fuel_name || `Код ${receipt.fuel_code ?? '—'}`)
    return [...values.entries()].sort((a, b) => a[1].localeCompare(b[1], 'ru'))
  }, [receipts])

  const filtered = useMemo(() => {
    const result: LoadedReceipt[] = []
    for (const receipt of receipts) {
      if (status !== 'all' && receiptStatus(receipt) !== status) continue
      if (fuel !== 'all' && String(receipt.fuel_code ?? -1) !== fuel) continue
      if (deferredSearch) {
        const haystack = [receipt.ttn, receipt.station_name, receipt.station_code, receipt.fuel_name, receipt.supplier]
          .filter((value) => value != null)
          .join(' ')
          .toLocaleLowerCase('ru-RU')
        if (!haystack.includes(deferredSearch)) continue
      }
      result.push(receipt)
    }
    return result.sort((a, b) => new Date(dateValue(b)).getTime() - new Date(dateValue(a)).getTime())
  }, [deferredSearch, fuel, receipts, status])

  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const currentPage = Math.min(page, pages)
  const visible = filtered.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE)
  const changeStatus = (value: string) => { setStatus(value as CostStatus); setPage(1) }
  const changeFuel = (value: string) => { setFuel(value); setPage(1) }

  return (
    <>
      <Card>
        <CardHeader className="gap-3 border-b">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle className="text-base">Партии по ТТН и АЗС</CardTitle>
              <CardDescription>Партия определяется связкой «ТТН + АЗС + топливо»: одинаковый номер на разных станциях учитывается отдельно.</CardDescription>
            </div>
            <div className="flex flex-wrap gap-1.5">
              <Badge variant="outline">Всего {integer.format(counts.all)}</Badge>
              <Badge>Заполнено {integer.format(counts.costed)}</Badge>
              <Badge variant="secondary">Не заполнено {integer.format(counts.missing)}</Badge>
              {counts.invalid > 0 && <Badge variant="destructive">Некорректных {integer.format(counts.invalid)}</Badge>}
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Tabs value={status} onValueChange={changeStatus}>
              <TabsList className="h-8">
                <TabsTrigger value="all">Все</TabsTrigger>
                <TabsTrigger value="costed">Заполненные</TabsTrigger>
                <TabsTrigger value="missing">Не заполненные</TabsTrigger>
                <TabsTrigger value="invalid">Некорректные</TabsTrigger>
              </TabsList>
            </Tabs>
            <div className="relative min-w-56 flex-1 sm:max-w-80">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={search}
                onChange={(event) => { setSearch(event.target.value); setPage(1) }}
                className="h-8 pl-8"
                placeholder="ТТН, АЗС, поставщик…"
                aria-label="Поиск партий ТТН"
              />
            </div>
            <Select value={fuel} onValueChange={changeFuel}>
              <SelectTrigger size="sm" className="w-48"><SelectValue placeholder="Все виды топлива" /></SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value="all">Все виды топлива</SelectItem>
                  {fuelOptions.map(([code, name]) => <SelectItem key={code} value={code}>{name}</SelectItem>)}
                </SelectGroup>
              </SelectContent>
            </Select>
          </div>
        </CardHeader>

        <CardContent className="p-0">
          {query.isLoading ? (
            <div className="flex flex-col gap-2 p-4">
              {Array.from({ length: 6 }, (_, index) => <Skeleton key={index} className="h-10 w-full" />)}
            </div>
          ) : query.error ? (
            <div className="p-6 text-center text-sm text-destructive">Не удалось загрузить партии ТТН.</div>
          ) : visible.length === 0 ? (
            <div className="p-8 text-center">
              <div className="text-sm font-medium">Партии не найдены</div>
              <p className="mt-1 text-xs text-muted-foreground">Измените статус, вид топлива или строку поиска.</p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Дата</TableHead>
                  <TableHead>ТТН</TableHead>
                  <TableHead>АЗС</TableHead>
                  <TableHead>Топливо</TableHead>
                  <TableHead className="text-right">Объём</TableHead>
                  <TableHead className="text-right">Плотность ТТН</TableHead>
                  <TableHead className="text-right">Закупочная цена</TableHead>
                  <TableHead className="text-right">FIFO ₽/л</TableHead>
                  <TableHead>Статус</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {visible.map((receipt) => (
                  <TableRow
                    key={receipt.id}
                    className="cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
                    tabIndex={0}
                    aria-label={`Открыть партию ТТН ${receipt.ttn}, ${receipt.station_name || `АЗС №${receipt.station_code}`}, ${receipt.fuel_name}`}
                    onClick={() => setOpenReceipt(receipt)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault()
                        setOpenReceipt(receipt)
                      }
                    }}
                  >
                    <TableCell className="text-muted-foreground">{new Date(dateValue(receipt)).toLocaleDateString('ru-RU')}</TableCell>
                    <TableCell className="font-mono font-medium">{receipt.ttn}</TableCell>
                    <TableCell>{receipt.station_name || `АЗС №${receipt.station_code}`}</TableCell>
                    <TableCell>{receipt.fuel_name}</TableCell>
                    <TableCell className="text-right tabular-nums">{integer.format(receipt.doc_volume_liters)} л</TableCell>
                    <TableCell className="text-right tabular-nums">{receipt.density != null ? receipt.density.toFixed(4) : '—'}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {receipt.has_cost && receipt.cost_unit_price != null
                        ? `${price4.format(receipt.cost_unit_price)} ₽/${receipt.cost_unit === 'kg' ? 'кг' : 'л'}`
                        : '—'}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{receipt.has_cost && receipt.cost_per_liter != null ? `${price.format(receipt.cost_per_liter)} ₽` : '—'}</TableCell>
                    <TableCell><CostBadge receipt={receipt} /></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}

          {!query.isLoading && filtered.length > 0 && (
            <div className="flex flex-wrap items-center justify-between gap-2 border-t px-4 py-3 text-xs text-muted-foreground">
              <span>Показано {integer.format((currentPage - 1) * PAGE_SIZE + 1)}–{integer.format(Math.min(currentPage * PAGE_SIZE, filtered.length))} из {integer.format(filtered.length)}</span>
              <div className="flex items-center gap-2">
                <Button variant="outline" size="sm" disabled={currentPage <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))}>
                  <ChevronLeft data-icon="inline-start" />Назад
                </Button>
                <span className="min-w-20 text-center tabular-nums">{currentPage} из {pages}</span>
                <Button variant="outline" size="sm" disabled={currentPage >= pages} onClick={() => setPage((value) => Math.min(pages, value + 1))}>
                  Вперёд<ChevronRight data-icon="inline-end" />
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <ReceiptDetailsModal receipt={openReceipt} open={openReceipt !== null} onClose={() => setOpenReceipt(null)} />
    </>
  )
}
