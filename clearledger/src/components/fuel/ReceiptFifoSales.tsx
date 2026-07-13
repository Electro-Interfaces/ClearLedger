import { useState } from 'react'
import { format } from 'date-fns'
import { ru } from 'date-fns/locale'
import { Layers3, WalletCards } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { cn } from '@/lib/utils'
import type { ReceiptCosting } from '@/services/fuel/fuelMappingService'

const PAGE_SIZE = 50

const channelNames: Record<string, string> = {
  retail_cash: 'Розница · наличные',
  retail_card: 'Розница · карта',
  cards: 'Топливные карты',
  online: 'Онлайн-заказы',
  voucher: 'Талоны / ведомость',
  ledger: 'Ведомость',
  writeoff_fuel: 'Списание',
}

const money = (value = 0) => new Intl.NumberFormat('ru-RU', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
}).format(value)

const liters = (value = 0) => new Intl.NumberFormat('ru-RU', {
  maximumFractionDigits: 3,
}).format(value)

const marginClass = (value = 0) => value >= 0 ? 'text-emerald-500' : 'text-red-500'

export function ReceiptFifoSales({ costing, loading }: {
  costing?: ReceiptCosting
  loading: boolean
}) {
  const [page, setPage] = useState(0)
  const microLots = costing?.micro_lots ?? []
  const channels = costing?.channels ?? []
  const pages = Math.max(1, Math.ceil(microLots.length / PAGE_SIZE))
  const currentPage = Math.min(page, pages - 1)
  const visibleLots = microLots.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE)

  if (loading) {
    return (
      <div className="rounded-lg border border-border bg-background p-4">
        <Skeleton className="h-5 w-64" />
        <div className="mt-4 grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
          {Array.from({ length: 6 }).map((_, index) => <Skeleton key={index} className="h-16" />)}
        </div>
        <Skeleton className="mt-4 h-44 w-full" />
      </div>
    )
  }

  if (!costing?.has_cost) return null

  const summary = [
    ['Поступило', `${liters(costing.total_liters)} л`],
    ['Продано по FIFO', `${liters(costing.consumed_liters)} л`],
    ['Остаток партии', `${liters(costing.remaining_liters)} л`],
    ['Выручка с НДС', `${money(costing.revenue_consumed)} ₽`],
    ['Себестоимость', `${money(costing.cogs_consumed)} ₽`],
    ['Маржа без НДС', `${money(costing.margin_consumed)} ₽`],
  ]

  return (
    <section className="rounded-lg border border-sky-400/30 bg-background p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
            <Layers3 className="h-4 w-4 text-sky-500" />
            Как продана партия по FIFO
          </h3>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            Микропартия — часть этой ТТН в конкретной смене и способе оплаты. Маржа = выручка без НДС − FIFO-себестоимость.
          </p>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            {costing.allocation_method_label ?? 'Каналы оплаты берутся из очищенного сменного отчёта БП ГИГ.'}
          </p>
        </div>
        <Badge variant="outline" className={cn('font-mono text-xs', marginClass(costing.margin_consumed))}>
          {money(costing.margin_consumed)} ₽ · {money(costing.margin_pct)}%
        </Badge>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        {summary.map(([label, value], index) => (
          <div key={label} className="rounded-md border border-border/70 bg-card px-2.5 py-2">
            <div className="text-[10px] text-muted-foreground">{label}</div>
            <div className={cn('mt-0.5 whitespace-nowrap text-xs font-semibold tabular-nums', index === 5 && marginClass(costing.margin_consumed))}>
              {value}
            </div>
          </div>
        ))}
      </div>

      <Tabs defaultValue="channels" className="mt-3">
        <TabsList variant="line" className="h-8">
          <TabsTrigger value="channels" className="text-xs">
            <WalletCards /> По способам оплаты
            <Badge variant="secondary" className="h-5 px-1.5 text-[10px]">{channels.length}</Badge>
          </TabsTrigger>
          <TabsTrigger value="micro" className="text-xs">
            <Layers3 /> Микропартии
            <Badge variant="secondary" className="h-5 px-1.5 text-[10px]">{microLots.length}</Badge>
          </TabsTrigger>
        </TabsList>

        <TabsContent value="channels" className="mt-1 overflow-hidden rounded-md border border-border">
          <Table className="text-xs">
            <TableHeader className="bg-muted/40">
              <TableRow>
                <TableHead className="h-8">Способ оплаты</TableHead>
                <TableHead className="h-8 text-right">Продано</TableHead>
                <TableHead className="h-8 text-right">Доля</TableHead>
                <TableHead className="h-8 text-right">Ср. цена</TableHead>
                <TableHead className="h-8 text-right">Выручка с НДС</TableHead>
                <TableHead className="h-8 text-right">Себестоимость</TableHead>
                <TableHead className="h-8 text-right">Маржа без НДС</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {channels.map((channel) => (
                <TableRow key={channel.channel}>
                  <TableCell className="py-2 font-medium">{channelNames[channel.channel] ?? channel.channel}</TableCell>
                  <TableCell className="py-2 text-right tabular-nums">{liters(channel.liters)} л</TableCell>
                  <TableCell className="py-2 text-right tabular-nums">{money(channel.share_pct)}%</TableCell>
                  <TableCell className="py-2 text-right tabular-nums">{money(channel.avg_sale_price)} ₽/л</TableCell>
                  <TableCell className="py-2 text-right tabular-nums">{money(channel.revenue)} ₽</TableCell>
                  <TableCell className="py-2 text-right tabular-nums">{money(channel.cogs)} ₽</TableCell>
                  <TableCell className={cn('py-2 text-right font-medium tabular-nums', marginClass(channel.margin))}>
                    {money(channel.margin)} ₽ · {money(channel.margin_pct)}%
                  </TableCell>
                </TableRow>
              ))}
              {channels.length === 0 && (
                <TableRow><TableCell colSpan={7} className="h-20 text-center text-muted-foreground">Партия ещё не списывалась в продажи.</TableCell></TableRow>
              )}
            </TableBody>
          </Table>
        </TabsContent>

        <TabsContent value="micro" className="mt-1">
          <div className="max-h-[340px] overflow-auto rounded-md border border-border">
            <Table className="text-xs">
              <TableHeader className="sticky top-0 z-10 bg-card">
                <TableRow>
                  <TableHead className="h-8">Дата и смена</TableHead>
                  <TableHead className="h-8">Способ оплаты</TableHead>
                  <TableHead className="h-8 text-right">Литры</TableHead>
                  <TableHead className="h-8 text-right">Цена</TableHead>
                  <TableHead className="h-8 text-right">Выручка с НДС</TableHead>
                  <TableHead className="h-8 text-right">Себестоимость</TableHead>
                  <TableHead className="h-8 text-right">Маржа без НДС</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {visibleLots.map((lot) => (
                  <TableRow key={lot.id}>
                    <TableCell className="py-2">
                      <div className="font-medium">{lot.opened_at ? format(new Date(lot.opened_at), 'dd.MM.yyyy HH:mm', { locale: ru }) : 'Дата не указана'}</div>
                      <div className="text-[10px] text-muted-foreground">Смена №{lot.shift_number ?? '—'}</div>
                    </TableCell>
                    <TableCell className="py-2">{channelNames[lot.channel] ?? lot.channel}</TableCell>
                    <TableCell className="py-2 text-right tabular-nums">{liters(lot.liters)} л</TableCell>
                    <TableCell className="py-2 text-right tabular-nums">{money(lot.avg_sale_price)} ₽/л</TableCell>
                    <TableCell className="py-2 text-right tabular-nums">{money(lot.revenue)} ₽</TableCell>
                    <TableCell className="py-2 text-right tabular-nums">{money(lot.cogs)} ₽</TableCell>
                    <TableCell className={cn('py-2 text-right font-medium tabular-nums', marginClass(lot.margin))}>
                      {money(lot.margin)} ₽ · {money(lot.margin_pct)}%
                    </TableCell>
                  </TableRow>
                ))}
                {microLots.length === 0 && (
                  <TableRow><TableCell colSpan={7} className="h-20 text-center text-muted-foreground">Партия ещё не списывалась в продажи.</TableCell></TableRow>
                )}
              </TableBody>
            </Table>
          </div>
          {pages > 1 && (
            <div className="mt-2 flex items-center justify-between text-[11px] text-muted-foreground">
              <span>Строки {currentPage * PAGE_SIZE + 1}–{Math.min((currentPage + 1) * PAGE_SIZE, microLots.length)} из {microLots.length}</span>
              <div className="flex gap-1">
                <Button size="sm" variant="outline" className="h-7 text-xs" disabled={currentPage === 0} onClick={() => setPage((value) => Math.max(0, value - 1))}>Назад</Button>
                <Button size="sm" variant="outline" className="h-7 text-xs" disabled={currentPage >= pages - 1} onClick={() => setPage((value) => Math.min(pages - 1, value + 1))}>Далее</Button>
              </div>
            </div>
          )}
        </TabsContent>
      </Tabs>
    </section>
  )
}
