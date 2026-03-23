/**
 * Панель 3: Нормализованная база — детали выбранной смены.
 * Локальный тулбар с табами (Обзор/Резервуары/ТРК/Оплаты/ТТН) + кнопка «В 1С».
 */

import { useState } from 'react'
import { useWorkspace } from '@/contexts/WorkspaceContext'
import { useShiftReport, useReceipts } from '@/hooks/useFuel'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Loader2, Fuel, CreditCard, Truck, FileOutput, ClipboardList, BarChart3 } from 'lucide-react'
import { format } from 'date-fns'

type CoreTab = 'overview' | 'tanks' | 'pumps' | 'payments' | 'receipts'

const CORE_TABS: { key: CoreTab; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { key: 'overview', label: 'Обзор', icon: BarChart3 },
  { key: 'tanks', label: 'Резервуары', icon: Fuel },
  { key: 'pumps', label: 'ТРК', icon: Fuel },
  { key: 'payments', label: 'Оплаты', icon: CreditCard },
  { key: 'receipts', label: 'ТТН', icon: Truck },
]

function fmt(n: number): string {
  return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(n)
}

export function CorePanel({ hideHeader = false }: { hideHeader?: boolean }) {
  const [coreTab, setCoreTab] = useState<CoreTab>('overview')
  const { selectedStationId, selectedShiftNumber, addExportDoc, setActiveTab } = useWorkspace()

  const hasSelection = selectedStationId != null && selectedShiftNumber != null
  const { data: shift, isLoading } = useShiftReport(selectedStationId ?? 0, selectedShiftNumber ?? 0)
  const { data: receipts } = useReceipts(selectedStationId ?? 0, selectedShiftNumber ?? 0)

  function handlePrepareExport() {
    if (!shift) return
    const now = new Date().toISOString()
    addExportDoc({
      id: `retail-${shift.id}`,
      type: 'retail_sales',
      label: `Розн. продажи — Смена №${shift.shiftNumber} (${shift.stationName})`,
      sourceShift: shift.shiftNumber,
      stationId: shift.stationId,
      status: 'draft',
      createdAt: now,
    })
    if (receipts && receipts.length > 0) {
      receipts.forEach((r) => {
        addExportDoc({
          id: `receipt-${r.id}`,
          type: 'receipt',
          label: `Поступление ТТН ${r.ttn} — ${r.fuelName}`,
          sourceShift: shift.shiftNumber,
          stationId: shift.stationId,
          status: 'draft',
          createdAt: now,
        })
      })
    }
    setActiveTab('export')
  }

  if (!hasSelection) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-muted-foreground gap-3">
        <ClipboardList className="h-10 w-10 opacity-30" />
        <p className="text-sm">Выберите смену в левой панели</p>
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="flex justify-center items-center h-full">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (!shift) {
    return (
      <div className="flex justify-center items-center h-full text-muted-foreground">
        <p className="text-sm">Не удалось загрузить данные</p>
      </div>
    )
  }

  const showSection = (section: CoreTab) => coreTab === 'overview' || coreTab === section

  return (
    <div className="flex flex-col h-full">
      {/* Локальный тулбар — инфо о смене + кнопка */}
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-border/50">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-bold">
            №{shift.shiftNumber}
          </h2>
          <span className="text-xs text-muted-foreground">{shift.stationName}</span>
          <Badge variant={shift.status === 'open' ? 'default' : 'secondary'} className="text-[10px] h-5">
            {shift.status === 'open' ? 'Открыта' : 'Закрыта'}
          </Badge>
        </div>
        <Button size="sm" className="h-7 text-xs gap-1.5" onClick={handlePrepareExport}>
          <FileOutput className="h-3.5 w-3.5" />
          В 1С
        </Button>
      </div>

      {/* Табы навигации внутри панели */}
      <div className="flex items-center gap-0.5 px-2 py-1 border-b border-border/30 bg-card/20 overflow-x-auto">
        {CORE_TABS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => setCoreTab(key)}
            className={`flex items-center gap-1 px-2 py-1 rounded text-[11px] font-medium transition-colors whitespace-nowrap ${
              coreTab === key
                ? 'bg-primary/10 text-primary'
                : 'text-muted-foreground hover:text-foreground hover:bg-accent/50'
            }`}
          >
            <Icon className="h-3 w-3" />
            {label}
          </button>
        ))}
      </div>

      <ScrollArea className="flex-1">
        <div className="p-4 space-y-4">
          {/* KPI — всегда в обзоре */}
          {showSection('overview') && (
            <>
              <div className="grid grid-cols-3 gap-2">
                <Card className="bg-card/50">
                  <CardContent className="p-3">
                    <div className="flex items-center gap-2">
                      <Fuel className="h-4 w-4 text-amber-500 shrink-0" />
                      <div>
                        <p className="text-lg font-bold">{fmt(shift.totalSalesLiters)}</p>
                        <p className="text-[10px] text-muted-foreground">литров</p>
                      </div>
                    </div>
                  </CardContent>
                </Card>
                <Card className="bg-card/50">
                  <CardContent className="p-3">
                    <div className="flex items-center gap-2">
                      <CreditCard className="h-4 w-4 text-emerald-500 shrink-0" />
                      <div>
                        <p className="text-lg font-bold">{fmt(shift.totalSalesAmount)}</p>
                        <p className="text-[10px] text-muted-foreground">руб.</p>
                      </div>
                    </div>
                  </CardContent>
                </Card>
                <Card className="bg-card/50">
                  <CardContent className="p-3">
                    <div className="flex items-center gap-2">
                      <Truck className="h-4 w-4 text-blue-500 shrink-0" />
                      <div>
                        <p className="text-lg font-bold">{receipts?.length ?? 0}</p>
                        <p className="text-[10px] text-muted-foreground">ТТН</p>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              </div>

              {/* Info */}
              <div className="text-xs text-muted-foreground flex gap-4">
                <span>Оператор: <strong className="text-foreground">{shift.operator}</strong></span>
                <span>
                  {shift.openedAt ? format(new Date(shift.openedAt), 'dd.MM.yyyy HH:mm') : ''}
                  {shift.closedAt ? ` — ${format(new Date(shift.closedAt), 'HH:mm')}` : ''}
                </span>
              </div>
            </>
          )}

          {/* Резервуары */}
          {showSection('tanks') && shift.tanks.length > 0 && (
            <Card>
              <CardHeader className="py-2 px-3">
                <CardTitle className="text-xs font-semibold">Резервуары</CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <Table>
                  <TableHeader>
                    <TableRow className="text-[11px]">
                      <TableHead className="h-8 px-3">№</TableHead>
                      <TableHead className="h-8">Топливо</TableHead>
                      <TableHead className="h-8 text-right">Начало</TableHead>
                      <TableHead className="h-8 text-right">Конец</TableHead>
                      <TableHead className="h-8 text-right">Расход</TableHead>
                      <TableHead className="h-8 text-right">ρ</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {shift.tanks.map((t) => (
                      <TableRow key={t.tank_number} className="text-xs">
                        <TableCell className="py-1.5 px-3">{t.tank_number}</TableCell>
                        <TableCell className="py-1.5">{t.fuel_type}</TableCell>
                        <TableCell className="py-1.5 text-right">{fmt(t.volume_start)}</TableCell>
                        <TableCell className="py-1.5 text-right">{fmt(t.volume_end)}</TableCell>
                        <TableCell className="py-1.5 text-right font-medium">{fmt(t.sales)}</TableCell>
                        <TableCell className="py-1.5 text-right text-muted-foreground">{t.density}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          )}

          {/* Оплаты */}
          {showSection('payments') && (
            <Card>
              <CardHeader className="py-2 px-3">
                <CardTitle className="text-xs font-semibold">Оплаты</CardTitle>
              </CardHeader>
              <CardContent className="p-3 pt-0">
                <div className="grid grid-cols-4 gap-2 text-xs">
                  <div>
                    <p className="text-muted-foreground">Наличные</p>
                    <p className="font-semibold">{fmt(shift.payments.cash)} ₽</p>
                  </div>
                  <div>
                    <p className="text-muted-foreground">Карты</p>
                    <p className="font-semibold">{fmt(shift.payments.card)} ₽</p>
                  </div>
                  <div>
                    <p className="text-muted-foreground">Талоны</p>
                    <p className="font-semibold">{fmt(shift.payments.voucher)} ₽</p>
                  </div>
                  <div>
                    <p className="text-muted-foreground font-bold">Итого</p>
                    <p className="font-bold text-primary">{fmt(shift.payments.total)} ₽</p>
                  </div>
                </div>
              </CardContent>
            </Card>
          )}

          {/* ТРК */}
          {showSection('pumps') && shift.pumps.length > 0 && (
            <Card>
              <CardHeader className="py-2 px-3">
                <CardTitle className="text-xs font-semibold">ТРК (колонки)</CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <Table>
                  <TableHeader>
                    <TableRow className="text-[11px]">
                      <TableHead className="h-8 px-3">ТРК</TableHead>
                      <TableHead className="h-8">Топливо</TableHead>
                      <TableHead className="h-8 text-right">Объём, л</TableHead>
                      <TableHead className="h-8 text-right">Сумма, ₽</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {shift.pumps.map((p, i) => (
                      <TableRow key={i} className="text-xs">
                        <TableCell className="py-1.5 px-3">№{p.pump_number} ({p.nozzle})</TableCell>
                        <TableCell className="py-1.5">{p.fuel_type}</TableCell>
                        <TableCell className="py-1.5 text-right">{fmt(p.sales_volume)}</TableCell>
                        <TableCell className="py-1.5 text-right">{fmt(p.amount)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          )}

          {/* ТТН */}
          {showSection('receipts') && receipts && receipts.length > 0 && (
            <Card>
              <CardHeader className="py-2 px-3">
                <CardTitle className="text-xs font-semibold">Поступления (ТТН)</CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <Table>
                  <TableHeader>
                    <TableRow className="text-[11px]">
                      <TableHead className="h-8 px-3">ТТН</TableHead>
                      <TableHead className="h-8">Топливо</TableHead>
                      <TableHead className="h-8 text-right">Док, л</TableHead>
                      <TableHead className="h-8 text-right">Факт, л</TableHead>
                      <TableHead className="h-8 text-right">Δ</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {receipts.map((r) => (
                      <TableRow key={r.id} className="text-xs">
                        <TableCell className="py-1.5 px-3 font-medium">{r.ttn}</TableCell>
                        <TableCell className="py-1.5">{r.fuelName}</TableCell>
                        <TableCell className="py-1.5 text-right">{fmt(r.docVolumeLiters)}</TableCell>
                        <TableCell className="py-1.5 text-right">{fmt(r.factVolumeLiters)}</TableCell>
                        <TableCell className={`py-1.5 text-right font-medium ${Math.abs(r.diffVolume) > 10 ? 'text-destructive' : 'text-muted-foreground'}`}>
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
      </ScrollArea>
    </div>
  )
}
