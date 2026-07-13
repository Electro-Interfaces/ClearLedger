import { useCallback, useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertCircle, Pause, Play, RefreshCw, Search, Smartphone } from 'lucide-react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { cn } from '@/lib/utils'
import {
  getLoadedOnlineOrders,
  refreshOnlineOrders,
  type LoadedOnlineOrder,
} from '@/services/fuel/onlineOrdersService'

const PAGE_SIZE = 100

type OrderStatus = 'completed' | 'pending' | 'failed' | 'cancelled' | 'unknown'

const statusMeta: Record<OrderStatus, { label: string; className: string }> = {
  completed: { label: 'Выполнен', className: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-500' },
  pending: { label: 'Ожидание', className: 'border-amber-500/40 bg-amber-500/10 text-amber-500' },
  failed: { label: 'Ошибка', className: 'border-red-500/40 bg-red-500/10 text-red-500' },
  cancelled: { label: 'Отменён', className: 'border-muted-foreground/40 bg-muted text-muted-foreground' },
  unknown: { label: 'Не определён', className: 'border-border bg-muted text-muted-foreground' },
}

function orderStatus(value: string | null): OrderStatus {
  switch ((value ?? '').trim().toLowerCase()) {
    case 'success':
    case 's':
    case '2':
      return 'completed'
    case 'wait':
    case 'w':
    case '3':
      return 'pending'
    case 'error':
    case 'e':
    case '1':
      return 'failed'
    case 'cancel':
    case 'cancelled':
    case 'c':
    case '4':
      return 'cancelled'
    default:
      return 'unknown'
  }
}

const number0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const number2 = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const volume = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 0, maximumFractionDigits: 3 })

function displayDate(value: string | null) {
  if (!value) return '—'
  return new Date(value).toLocaleString('ru-RU', {
    day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}

function effectiveVolume(order: LoadedOnlineOrder) {
  return orderStatus(order.operation_result) === 'completed' ? order.actual_volume : order.ordered_volume
}

function effectiveAmount(order: LoadedOnlineOrder) {
  return orderStatus(order.operation_result) === 'completed' ? order.actual_sum : order.ordered_sum
}

function orderPrice(order: LoadedOnlineOrder) {
  if (order.actual_volume > 0) return order.actual_sum / order.actual_volume
  if (order.ordered_volume > 0) return order.ordered_sum / order.ordered_volume
  return 0
}

function DetailField({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="min-w-0 border-b border-border/60 py-2 last:border-b-0">
      <dt className="text-[11px] text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 break-words text-sm font-medium tabular-nums">{value}</dd>
    </div>
  )
}

function unique(values: Array<string | null>) {
  return [...new Set(values.filter((value): value is string => !!value))].sort((a, b) => a.localeCompare(b, 'ru'))
}

export function OnlineOrdersPanel({ companyId, dateFrom, dateTo, stationCode }: {
  companyId: string
  dateFrom: string
  dateTo: string
  stationCode: string
}) {
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [syncError, setSyncError] = useState<string | null>(null)
  const [lastSync, setLastSync] = useState<Date | null>(null)
  const [status, setStatus] = useState('all')
  const [fuel, setFuel] = useState('all')
  const [aggregator, setAggregator] = useState('all')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(0)
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const queryParams = useMemo(() => ({ companyId, dateFrom, dateTo, stationCode, limit: 5000 }), [companyId, dateFrom, dateTo, stationCode])
  const ordersQuery = useQuery({
    queryKey: ['online-orders', companyId, dateFrom, dateTo, stationCode],
    queryFn: () => getLoadedOnlineOrders(queryParams),
    staleTime: 5_000,
    refetchInterval: autoRefresh ? 30_000 : false,
  })
  const refetchOrders = ordersQuery.refetch

  const sync = useCallback(async (manual = false) => {
    setRefreshing(true)
    try {
      const result = await refreshOnlineOrders(queryParams)
      setSyncError(result.warning ?? null)
      setLastSync(new Date())
      await refetchOrders()
      if (manual) {
        if (result.warning) toast.warning(result.warning)
        else toast.success('Синхронизация MSTO завершена', {
          description: `Получено ${number0.format(result.fetched)} · добавлено ${number0.format(result.created)} · обновлено ${number0.format(result.updated ?? 0)}`,
        })
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'MSTO недоступен'
      setSyncError(message)
      if (manual) toast.error('Не удалось обновить заказы из MSTO', { description: message })
    } finally {
      setRefreshing(false)
    }
  }, [queryParams, refetchOrders])

  const orders = useMemo(() => ordersQuery.data ?? [], [ordersQuery.data])
  const selectedOrder = useMemo(
    () => orders.find((order) => order.id === selectedId) ?? null,
    [orders, selectedId],
  )
  const fuelOptions = useMemo(() => unique(orders.map((order) => order.fuel_name)), [orders])
  const aggregatorOptions = useMemo(() => unique(orders.map((order) => order.aggregator)), [orders])

  const filtered = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase('ru')
    return orders.filter((order) => {
      if (status !== 'all' && orderStatus(order.operation_result) !== status) return false
      if (fuel !== 'all' && order.fuel_name !== fuel) return false
      if (aggregator !== 'all' && order.aggregator !== aggregator) return false
      if (!needle) return true
      return [order.external_id, order.station_name, order.service_point_name, order.aggregator, order.fuel_name]
        .some((value) => value?.toLocaleLowerCase('ru').includes(needle))
    })
  }, [aggregator, fuel, orders, search, status])

  useEffect(() => { setPage(0) }, [aggregator, fuel, search, status, dateFrom, dateTo, stationCode])

  const stats = useMemo(() => filtered.reduce((acc, order) => {
    const currentStatus = orderStatus(order.operation_result)
    acc.count += 1
    acc.amount += effectiveAmount(order)
    acc.volume += effectiveVolume(order)
    if (currentStatus === 'completed') acc.completed += 1
    if (currentStatus === 'pending') acc.pending += 1
    if (currentStatus === 'failed' || currentStatus === 'cancelled') acc.problem += 1
    return acc
  }, { count: 0, amount: 0, volume: 0, completed: 0, pending: 0, problem: 0 }), [filtered])

  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const currentPage = Math.min(page, pages - 1)
  const visible = filtered.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE)

  const summary = [
    ['Заказов', number0.format(stats.count)],
    ['Выполнено', number0.format(stats.completed)],
    ['Ожидают', number0.format(stats.pending)],
    ['Ошибки / отмены', number0.format(stats.problem)],
    ['Отпуск', `${volume.format(stats.volume)} л`],
    ['Сумма', `${number2.format(stats.amount)} ₽`],
  ]

  return (
    <div className="space-y-3 p-3">
      <section className="rounded-lg border border-border bg-card">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border px-4 py-3">
          <div>
            <h2 className="flex items-center gap-2 text-sm font-semibold">
              <Smartphone className="h-4 w-4 text-primary" />
              Онлайн-заказы MSTO
            </h2>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Заказы агрегаторов за рабочий период. Строка открывается выбором, без отдельной кнопки.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <span className={cn('h-2 w-2 rounded-full', syncError ? 'bg-amber-500' : autoRefresh ? 'bg-emerald-500' : 'bg-muted-foreground')} />
              {syncError ? 'Последние сохранённые данные' : autoRefresh ? 'Локальная база · обновление каждые 30 сек.' : 'Автообновление экрана остановлено'}
              {lastSync && ` · MSTO ${lastSync.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}`}
            </span>
            <Button variant="outline" size="sm" className="h-8 text-xs" onClick={() => setAutoRefresh((value) => !value)}>
              {autoRefresh ? <Pause /> : <Play />}
              {autoRefresh ? 'Остановить' : 'Включить'}
            </Button>
            <Button variant="outline" size="sm" className="h-8 text-xs" disabled={refreshing} onClick={() => void sync(true)}>
              <RefreshCw className={cn(refreshing && 'animate-spin')} />
              Синхронизировать MSTO
            </Button>
          </div>
        </div>

        {syncError && (
          <div className="flex items-start gap-2 border-b border-amber-500/30 bg-amber-500/5 px-4 py-2 text-xs text-amber-500">
            <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>{syncError}. Таблица остаётся доступна по последней успешной загрузке.</span>
          </div>
        )}

        <div className="grid grid-cols-2 divide-x divide-y divide-border sm:grid-cols-3 lg:grid-cols-6 lg:divide-y-0">
          {summary.map(([label, value]) => (
            <div key={label} className="px-4 py-3">
              <div className="text-[11px] text-muted-foreground">{label}</div>
              <div className="mt-0.5 text-sm font-semibold tabular-nums">{value}</div>
            </div>
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-2 border-t border-border px-3 py-2">
          <div className="relative min-w-52 flex-1 sm:max-w-72">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Заказ, АЗС, агрегатор…" className="h-8 pl-8 text-xs" />
          </div>
          <Select value={status} onValueChange={setStatus}>
            <SelectTrigger className="h-8 w-40 text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Все статусы</SelectItem>
              <SelectItem value="completed">Выполненные</SelectItem>
              <SelectItem value="pending">Ожидают</SelectItem>
              <SelectItem value="failed">Ошибки</SelectItem>
              <SelectItem value="cancelled">Отменённые</SelectItem>
              <SelectItem value="unknown">Не определены</SelectItem>
            </SelectContent>
          </Select>
          <Select value={fuel} onValueChange={setFuel}>
            <SelectTrigger className="h-8 w-40 text-xs"><SelectValue placeholder="Топливо" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Все виды топлива</SelectItem>
              {fuelOptions.map((value) => <SelectItem key={value} value={value}>{value}</SelectItem>)}
            </SelectContent>
          </Select>
          <Select value={aggregator} onValueChange={setAggregator}>
            <SelectTrigger className="h-8 w-44 text-xs"><SelectValue placeholder="Агрегатор" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Все агрегаторы</SelectItem>
              {aggregatorOptions.map((value) => <SelectItem key={value} value={value}>{value}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
      </section>

      <section className="overflow-hidden rounded-lg border border-border bg-card">
        {ordersQuery.isLoading ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 8 }).map((_, index) => <Skeleton key={index} className="h-9 w-full" />)}
          </div>
        ) : ordersQuery.error && orders.length === 0 ? (
          <div className="p-8 text-center text-sm text-red-400">Не удалось загрузить сохранённые онлайн-заказы.</div>
        ) : visible.length === 0 ? (
          <div className="p-10 text-center">
            <Smartphone className="mx-auto h-8 w-8 text-muted-foreground" />
            <div className="mt-2 text-sm font-medium">Заказов по выбранным условиям нет</div>
            <p className="mt-1 text-xs text-muted-foreground">Проверьте период, выбранную АЗС и подключение источника MSTO.</p>
          </div>
        ) : (
          <Table className="text-xs">
            <TableHeader className="bg-muted/40">
              <TableRow>
                <TableHead className="h-9">Дата и время</TableHead>
                <TableHead className="h-9">АЗС</TableHead>
                <TableHead className="h-9">Агрегатор</TableHead>
                <TableHead className="h-9">Топливо</TableHead>
                <TableHead className="h-9">Статус</TableHead>
                <TableHead className="h-9 text-right">Заказано</TableHead>
                <TableHead className="h-9 text-right">Отпущено</TableHead>
                <TableHead className="h-9 text-right">Цена</TableHead>
                <TableHead className="h-9 text-right">Сумма факта</TableHead>
                <TableHead className="h-9 text-center">ТРК</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visible.map((order) => {
                const currentStatus = orderStatus(order.operation_result)
                const selected = selectedId === order.id
                const actualPrice = orderPrice(order)
                return (
                  <TableRow
                    key={order.id}
                    data-state={selected ? 'selected' : undefined}
                    tabIndex={0}
                    aria-haspopup="dialog"
                    className="cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                    onClick={() => setSelectedId(order.id)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault()
                        setSelectedId(order.id)
                      }
                    }}
                  >
                    <TableCell className="font-mono text-muted-foreground">{displayDate(order.order_date)}</TableCell>
                    <TableCell>
                      <div className="max-w-52 truncate font-medium">{order.station_name ?? order.service_point_name ?? 'Не сопоставлена'}</div>
                      {order.station_code && <div className="text-[10px] text-muted-foreground">АЗС №{order.station_code}</div>}
                    </TableCell>
                    <TableCell>{order.aggregator ?? '—'}</TableCell>
                    <TableCell>{order.fuel_name ?? '—'}</TableCell>
                    <TableCell><Badge variant="outline" className={cn('text-[10px]', statusMeta[currentStatus].className)}>{statusMeta[currentStatus].label}</Badge></TableCell>
                    <TableCell className="text-right tabular-nums">{volume.format(order.ordered_volume)} л</TableCell>
                    <TableCell className={cn('text-right tabular-nums', Math.abs(order.actual_volume - order.ordered_volume) > 0.01 && 'text-amber-500')}>{order.actual_volume > 0 ? `${volume.format(order.actual_volume)} л` : '—'}</TableCell>
                    <TableCell className="text-right tabular-nums">{actualPrice > 0 ? `${number2.format(actualPrice)} ₽` : '—'}</TableCell>
                    <TableCell className="text-right font-medium tabular-nums">{order.actual_sum > 0 ? `${number2.format(order.actual_sum)} ₽` : '—'}</TableCell>
                    <TableCell className="text-center tabular-nums">{order.post_number ?? '—'}</TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        )}
      </section>

      {filtered.length > 0 && (
        <div className="flex items-center justify-between px-1 text-xs text-muted-foreground">
          <span>{number0.format(currentPage * PAGE_SIZE + 1)}–{number0.format(Math.min((currentPage + 1) * PAGE_SIZE, filtered.length))} из {number0.format(filtered.length)}</span>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" className="h-7 text-xs" disabled={currentPage === 0} onClick={() => setPage((value) => Math.max(0, value - 1))}>Назад</Button>
            <span className="tabular-nums">{currentPage + 1} / {pages}</span>
            <Button variant="outline" size="sm" className="h-7 text-xs" disabled={currentPage + 1 >= pages} onClick={() => setPage((value) => value + 1)}>Далее</Button>
          </div>
        </div>
      )}

      <Dialog open={!!selectedOrder} onOpenChange={(open) => !open && setSelectedId(null)}>
        <DialogContent className="max-h-[88vh] max-w-3xl overflow-y-auto p-0">
          {selectedOrder && (() => {
            const currentStatus = orderStatus(selectedOrder.operation_result)
            const price = orderPrice(selectedOrder)
            const station = selectedOrder.station_name ?? selectedOrder.service_point_name ?? 'Не сопоставлена'
            const volumeDelta = selectedOrder.actual_volume - selectedOrder.ordered_volume
            const amountDelta = selectedOrder.actual_sum - selectedOrder.ordered_sum
            return (
              <>
                <DialogHeader className="border-b border-border px-6 py-5 pr-12">
                  <div className="flex flex-wrap items-center gap-2">
                    <DialogTitle>Расшифровка онлайн-заказа</DialogTitle>
                    <Badge variant="outline" className={statusMeta[currentStatus].className}>{statusMeta[currentStatus].label}</Badge>
                  </div>
                  <DialogDescription>{station} · {displayDate(selectedOrder.order_date)}</DialogDescription>
                </DialogHeader>

                <div className="grid grid-cols-2 divide-x divide-y divide-border border-b border-border sm:grid-cols-4 sm:divide-y-0">
                  {[
                    ['Заказано', `${volume.format(selectedOrder.ordered_volume)} л`, `${number2.format(selectedOrder.ordered_sum)} ₽`],
                    ['Отпущено', `${volume.format(selectedOrder.actual_volume)} л`, `${number2.format(selectedOrder.actual_sum)} ₽`],
                    ['Цена', price > 0 ? `${number2.format(price)} ₽/л` : '—', selectedOrder.fuel_name ?? 'Топливо не указано'],
                    ['Отклонение', `${volume.format(volumeDelta)} л`, `${number2.format(amountDelta)} ₽`],
                  ].map(([label, value, hint]) => (
                    <div key={label} className="px-4 py-3">
                      <div className="text-[11px] text-muted-foreground">{label}</div>
                      <div className="mt-0.5 text-sm font-semibold tabular-nums">{value}</div>
                      <div className="mt-0.5 text-[11px] text-muted-foreground">{hint}</div>
                    </div>
                  ))}
                </div>

                <div className="grid gap-x-8 px-6 py-4 sm:grid-cols-2">
                  <dl>
                    <DetailField label="ID заказа MSTO" value={selectedOrder.external_id} />
                    <DetailField label="Агрегатор" value={selectedOrder.aggregator ?? '—'} />
                    <DetailField label="АЗС Ledger" value={`${station}${selectedOrder.station_code ? ` · №${selectedOrder.station_code}` : ''}`} />
                    <DetailField label="Точка MSTO" value={selectedOrder.service_point_name ?? '—'} />
                  </dl>
                  <dl>
                    <DetailField label="servicePointId" value={selectedOrder.service_point_id ?? '—'} />
                    <DetailField label="ТРК" value={selectedOrder.post_number ?? '—'} />
                    <DetailField label="Код топлива" value={selectedOrder.fuel_code ?? '—'} />
                    <DetailField label="Загружен в Ledger" value={displayDate(selectedOrder.created_at)} />
                  </dl>
                </div>
              </>
            )
          })()}
        </DialogContent>
      </Dialog>
    </div>
  )
}
