import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { RefreshCw, Warehouse } from 'lucide-react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { getFuelOpeningBalances, recalculateFuelOpeningBalances } from '@/services/fuel/fuelMappingService'

const number = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 3 })
const money = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const compact = new Intl.NumberFormat('ru-RU', { notation: 'compact', maximumFractionDigits: 2 })

export function OpeningBalancesPanel() {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: ['fuel-opening-balances'],
    queryFn: getFuelOpeningBalances,
  })
  const recalculate = useMutation({
    mutationFn: recalculateFuelOpeningBalances,
    onSuccess: async (result) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['fuel-opening-balances'] }),
        queryClient.invalidateQueries({ queryKey: ['margin-decision-dashboard'] }),
        queryClient.invalidateQueries({ queryKey: ['costing-margin'] }),
        queryClient.invalidateQueries({ queryKey: ['receipt-costing'] }),
      ])
      toast.success('Начальные остатки пересчитаны', {
        description: `${number.format(result.liters)} л в ${result.count} позициях`,
      })
    },
    onError: () => toast.error('Не удалось пересчитать начальные остатки'),
  })

  if (query.isLoading) {
    return <div className="space-y-2">{Array.from({ length: 6 }, (_, index) => <Skeleton key={index} className="h-11 w-full" />)}</div>
  }
  if (query.error || !query.data) {
    return <div className="rounded-lg border border-destructive/30 p-6 text-center text-sm text-destructive">Не удалось загрузить начальные остатки.</div>
  }

  const { rows, totals } = query.data
  return (
    <Card>
      <CardHeader className="gap-3 border-b">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-base"><Warehouse className="h-4 w-4" />Начальные остатки FIFO</CardTitle>
            <CardDescription className="mt-1">
              Отдельные учётные партии до начала загруженной истории. Не создают фиктивных ТТН.
            </CardDescription>
          </div>
          <Button variant="outline" size="sm" disabled={recalculate.isPending} onClick={() => recalculate.mutate()}>
            <RefreshCw className={recalculate.isPending ? 'animate-spin' : ''} />Пересчитать по истории
          </Button>
        </div>
        <div className="grid gap-2 sm:grid-cols-3">
          <div className="rounded-md border bg-muted/20 px-3 py-2"><div className="text-[11px] text-muted-foreground">Позиций АЗС × топливо</div><div className="font-semibold">{totals.count}</div></div>
          <div className="rounded-md border bg-muted/20 px-3 py-2"><div className="text-[11px] text-muted-foreground">Входящий объём</div><div className="font-semibold">{number.format(totals.liters)} л</div></div>
          <div className="rounded-md border bg-muted/20 px-3 py-2"><div className="text-[11px] text-muted-foreground">Стоимость остатка</div><div className="font-semibold">{compact.format(totals.value)} ₽</div></div>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <div className="max-h-[560px] overflow-auto">
          <Table className="text-xs">
            <TableHeader className="sticky top-0 z-10 bg-card">
              <TableRow>
                <TableHead>На дату</TableHead>
                <TableHead>АЗС</TableHead>
                <TableHead>Топливо</TableHead>
                <TableHead className="text-right">Остаток</TableHead>
                <TableHead className="text-right">Себестоимость</TableHead>
                <TableHead className="text-right">Стоимость</TableHead>
                <TableHead>Источник</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.id}>
                  <TableCell>{new Date(row.as_of).toLocaleString('ru-RU')}</TableCell>
                  <TableCell className="font-medium">{row.station_name || `АЗС №${row.station_code ?? '—'}`}</TableCell>
                  <TableCell>{row.fuel_name}</TableCell>
                  <TableCell className="text-right tabular-nums">{number.format(row.liters)} л</TableCell>
                  <TableCell className="text-right tabular-nums">{money.format(row.cost_per_liter)} ₽/л</TableCell>
                  <TableCell className="text-right tabular-nums">{money.format(row.value)} ₽</TableCell>
                  <TableCell><Badge variant="secondary">{row.source === 'auto' ? 'По истории' : 'Вручную'}</Badge></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  )
}
