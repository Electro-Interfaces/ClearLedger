import { useParams, Link } from 'react-router-dom'
import { useShiftReport, useReceipts } from '@/hooks/useFuel'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { Loader2, ArrowLeft, Fuel, CreditCard, Truck } from 'lucide-react'
import { format } from 'date-fns'

function fmt(n: number): string {
  return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(n)
}

export function ShiftDetailPage() {
  const { stationId: sid, shiftNumber: sn } = useParams()
  const stationId = Number(sid)
  const shiftNumber = Number(sn)

  const { data: shift, isLoading, error } = useShiftReport(stationId, shiftNumber)
  const { data: receipts } = useReceipts(stationId, shiftNumber)

  if (isLoading) {
    return (
      <div className="flex justify-center py-16">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (error || !shift) {
    return (
      <div className="space-y-4">
        <Link to="/shifts" className="flex items-center gap-1 text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-4 w-4" /> К списку смен
        </Link>
        <p className="text-destructive">
          {error instanceof Error ? error.message : 'Не удалось загрузить отчёт'}
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-4">
        <Link to="/shifts" className="flex items-center gap-1 text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-4 w-4" /> Смены
        </Link>
        <h1 className="text-2xl font-bold">
          Смена №{shift.shiftNumber} — {shift.stationName}
        </h1>
        <Badge variant={shift.status === 'open' ? 'default' : 'secondary'}>
          {shift.status === 'open' ? 'Открыта' : 'Закрыта'}
        </Badge>
      </div>

      {/* Сводка */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-muted-foreground">Оператор</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-lg font-semibold">{shift.operator}</p>
            <p className="text-xs text-muted-foreground">
              {shift.openedAt ? format(new Date(shift.openedAt), 'dd.MM.yyyy HH:mm') : ''}
              {shift.closedAt ? ` — ${format(new Date(shift.closedAt), 'HH:mm')}` : ''}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-muted-foreground flex items-center gap-1">
              <Fuel className="h-4 w-4" /> Продажи
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">{fmt(shift.totalSalesLiters)} л</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-muted-foreground flex items-center gap-1">
              <CreditCard className="h-4 w-4" /> Выручка
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">{fmt(shift.totalSalesAmount)} ₽</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-muted-foreground flex items-center gap-1">
              <Truck className="h-4 w-4" /> Поступления
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">{receipts?.length ?? 0}</p>
          </CardContent>
        </Card>
      </div>

      {/* Резервуары */}
      {shift.tanks.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Резервуары</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Резервуар</TableHead>
                  <TableHead>Топливо</TableHead>
                  <TableHead className="text-right">Начало, л</TableHead>
                  <TableHead className="text-right">Конец, л</TableHead>
                  <TableHead className="text-right">Приход, л</TableHead>
                  <TableHead className="text-right">Расход, л</TableHead>
                  <TableHead className="text-right">Плотность</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {shift.tanks.map((t) => (
                  <TableRow key={t.tank_number}>
                    <TableCell>№{t.tank_number}</TableCell>
                    <TableCell>{t.fuel_type}</TableCell>
                    <TableCell className="text-right">{fmt(t.volume_start)}</TableCell>
                    <TableCell className="text-right">{fmt(t.volume_end)}</TableCell>
                    <TableCell className="text-right">{fmt(t.receipts)}</TableCell>
                    <TableCell className="text-right">{fmt(t.sales)}</TableCell>
                    <TableCell className="text-right">{t.density}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {/* ТРК */}
      {shift.pumps.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">ТРК (колонки)</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>ТРК</TableHead>
                  <TableHead>Пистолет</TableHead>
                  <TableHead>Топливо</TableHead>
                  <TableHead className="text-right">Объём, л</TableHead>
                  <TableHead className="text-right">Масса, кг</TableHead>
                  <TableHead className="text-right">Цена</TableHead>
                  <TableHead className="text-right">Сумма, ₽</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {shift.pumps.map((p, i) => (
                  <TableRow key={i}>
                    <TableCell>№{p.pump_number}</TableCell>
                    <TableCell>{p.nozzle}</TableCell>
                    <TableCell>{p.fuel_type}</TableCell>
                    <TableCell className="text-right">{fmt(p.sales_volume)}</TableCell>
                    <TableCell className="text-right">{fmt(p.sales_mass)}</TableCell>
                    <TableCell className="text-right">{fmt(p.price)}</TableCell>
                    <TableCell className="text-right">{fmt(p.amount)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {/* Оплаты */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Оплаты</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div>
              <p className="text-sm text-muted-foreground">Наличные</p>
              <p className="text-lg font-semibold">{fmt(shift.payments.cash)} ₽</p>
            </div>
            <div>
              <p className="text-sm text-muted-foreground">Карты</p>
              <p className="text-lg font-semibold">{fmt(shift.payments.card)} ₽</p>
            </div>
            <div>
              <p className="text-sm text-muted-foreground">Талоны</p>
              <p className="text-lg font-semibold">{fmt(shift.payments.voucher)} ₽</p>
            </div>
            <div>
              <p className="text-sm text-muted-foreground font-bold">Итого</p>
              <p className="text-lg font-bold">{fmt(shift.payments.total)} ₽</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Поступления (ТТН) */}
      {receipts && receipts.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Поступления (ТТН)</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>ТТН</TableHead>
                  <TableHead>Поставщик</TableHead>
                  <TableHead>Топливо</TableHead>
                  <TableHead className="text-right">Объём (док), л</TableHead>
                  <TableHead className="text-right">Масса (док), кг</TableHead>
                  <TableHead className="text-right">Объём (факт), л</TableHead>
                  <TableHead className="text-right">Расхождение, л</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {receipts.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell className="font-medium">{r.ttn}</TableCell>
                    <TableCell>{r.supplierName}</TableCell>
                    <TableCell>{r.fuelName}</TableCell>
                    <TableCell className="text-right">{fmt(r.docVolumeLiters)}</TableCell>
                    <TableCell className="text-right">{fmt(r.docMassKg)}</TableCell>
                    <TableCell className="text-right">{fmt(r.factVolumeLiters)}</TableCell>
                    <TableCell className={`text-right ${Math.abs(r.diffVolume) > 10 ? 'text-destructive font-bold' : ''}`}>
                      {r.diffVolume > 0 ? '+' : ''}{fmt(r.diffVolume)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

export default ShiftDetailPage
