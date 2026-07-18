/**
 * Сменные отчёты — список загруженных смен с фильтрами.
 * Клик → модальное окно с деталями смены (5 вкладок).
 */

import { useState, useMemo } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { getAllLoadedDocs } from '@/services/channelSyncService'
import type { ShiftRecord } from '@/services/fuel/types'
import { ShiftDetailModal } from '@/components/shift-reports/ShiftDetailModal'
import {
  Clock, CheckCircle, Filter, ChevronDown, ChevronRight, FileText,
} from 'lucide-react'
import { format } from 'date-fns'
import { ru } from 'date-fns/locale'

function formatDT(d: string) {
  return format(new Date(d), 'dd.MM.yyyy HH:mm', { locale: ru })
}

function getStatusBadge(status: 'open' | 'closed') {
  if (status === 'open') {
    return (
      <Badge className="bg-emerald-500/10 text-green-600 dark:text-green-400 border-green-500 flex items-center gap-1">
        <Clock className="w-3 h-3" />
        Открыта
      </Badge>
    )
  }
  return (
    <Badge className="bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-500 flex items-center gap-1">
      <CheckCircle className="w-3 h-3" />
      Закрыта
    </Badge>
  )
}

export function ShiftReportsPage() {
  const docs = getAllLoadedDocs().filter((d) => d.docType === 'shift_report')
  const shifts: ShiftRecord[] = docs.map((d) => d.data as ShiftRecord).filter(Boolean)

  const [filtersOpen, setFiltersOpen] = useState(true)
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [statusFilter, setStatusFilter] = useState<'all' | 'open' | 'closed'>('all')
  const [shiftNumberFilter, setShiftNumberFilter] = useState('')
  const [selectedShift, setSelectedShift] = useState<ShiftRecord | null>(null)

  const filtered = useMemo(() => {
    let result = [...shifts]

    if (dateFrom) {
      const from = new Date(dateFrom)
      result = result.filter((s) => new Date(s.openedAt) >= from)
    }
    if (dateTo) {
      const to = new Date(dateTo + 'T23:59:59')
      result = result.filter((s) => new Date(s.openedAt) <= to)
    }
    if (statusFilter !== 'all') {
      result = result.filter((s) => s.status === statusFilter)
    }
    if (shiftNumberFilter) {
      const num = Number(shiftNumberFilter)
      result = result.filter((s) => s.shiftNumber === num)
    }

    return result.sort((a, b) => b.shiftNumber - a.shiftNumber)
  }, [shifts, dateFrom, dateTo, statusFilter, shiftNumberFilter])

  function handleReset() {
    setDateFrom('')
    setDateTo('')
    setStatusFilter('all')
    setShiftNumberFilter('')
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">Сменные отчёты</h1>
        <Badge variant="secondary" className="text-xs">{shifts.length} загружено</Badge>
      </div>

      {/* Фильтры */}
      <Card>
        <Collapsible open={filtersOpen} onOpenChange={setFiltersOpen}>
          <CollapsibleTrigger asChild>
            <div className="flex items-center justify-between p-3 cursor-pointer hover:bg-accent/30 transition-colors">
              <div className="flex items-center gap-2">
                <Filter className="h-4 w-4 text-muted-foreground" />
                <span className="text-sm font-medium">Фильтры</span>
              </div>
              <div className="flex items-center gap-2">
                <Button variant="outline" size="sm" className="h-7 text-xs" onClick={(e) => { e.stopPropagation(); handleReset() }}>
                  Очистить
                </Button>
                {filtersOpen ? <ChevronDown className="h-4 w-4 text-muted-foreground" /> : <ChevronRight className="h-4 w-4 text-muted-foreground" />}
              </div>
            </div>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <div className="p-3 border-t border-border/40">
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                <div>
                  <Label className="text-xs text-muted-foreground">Дата от</Label>
                  <Input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className="mt-1 h-8 text-sm" />
                </div>
                <div>
                  <Label className="text-xs text-muted-foreground">Дата до</Label>
                  <Input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} className="mt-1 h-8 text-sm" />
                </div>
                <div>
                  <Label className="text-xs text-muted-foreground">Статус</Label>
                  <Select value={statusFilter} onValueChange={(v) => setStatusFilter(v as any)}>
                    <SelectTrigger className="mt-1 h-8 text-sm"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">Все</SelectItem>
                      <SelectItem value="open">Открыта</SelectItem>
                      <SelectItem value="closed">Закрыта</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label className="text-xs text-muted-foreground">Номер смены</Label>
                  <Input type="number" value={shiftNumberFilter} onChange={(e) => setShiftNumberFilter(e.target.value)}
                    placeholder="Введите номер" className="mt-1 h-8 text-sm" />
                </div>
              </div>
            </div>
          </CollapsibleContent>
        </Collapsible>
      </Card>

      {/* Таблица смен */}
      {filtered.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12 gap-3">
            <FileText className="h-10 w-10 text-muted-foreground/30" />
            <p className="text-sm text-muted-foreground">Смены не найдены</p>
            <p className="text-xs text-muted-foreground">Измените фильтры или загрузите данные через обработку</p>
          </CardContent>
        </Card>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-sm">
            <thead className="bg-secondary/80">
              <tr>
                <th className="px-4 py-3 text-left font-medium">ТТ</th>
                <th className="px-4 py-3 text-left font-medium">СМЕНА №</th>
                <th className="px-4 py-3 text-left font-medium">ОТКРЫТА</th>
                <th className="px-4 py-3 text-left font-medium">ЗАКРЫТА</th>
                <th className="px-4 py-3 text-right font-medium">ОБЪЁМ, л</th>
                <th className="px-4 py-3 text-right font-medium">СУММА, ₽</th>
                <th className="px-4 py-3 text-center font-medium">СТАТУС</th>
              </tr>
            </thead>
            <tbody className="bg-card">
              {filtered.map((shift) => (
                <tr
                  key={shift.id}
                  className="border-b border-border hover:bg-secondary/50 transition-colors cursor-pointer"
                  onClick={() => setSelectedShift(shift)}
                >
                  <td className="px-4 py-3">{shift.stationName}</td>
                  <td className="px-4 py-3">
                    <span className="font-semibold text-base">#{shift.shiftNumber}</span>
                  </td>
                  <td className="px-4 py-3">{formatDT(shift.openedAt)}</td>
                  <td className="px-4 py-3">{shift.closedAt ? formatDT(shift.closedAt) : '—'}</td>
                  <td className="px-4 py-3 text-right font-medium">{shift.totalVolumeLiters.toFixed(0)}</td>
                  <td className="px-4 py-3 text-right font-medium">
                    {shift.totalAmount.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </td>
                  <td className="px-4 py-3 text-center">{getStatusBadge(shift.status)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Модал деталей */}
      <ShiftDetailModal
        shift={selectedShift}
        onClose={() => setSelectedShift(null)}
      />
    </div>
  )
}

export default ShiftReportsPage
