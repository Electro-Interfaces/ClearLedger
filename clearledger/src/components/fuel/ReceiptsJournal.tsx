/**
 * Журнал поступлений (ТТН) — как в TradePoint. Фильтры (Дата от/до · Номер ТТН ·
 * Нефтебаза · Номер смены) + таблица (Дата/ТТ/Смена/ТТН/Топливо/Объём/Масса/
 * Отклонение). Клик по строке → «Детали поступления». Display-only.
 */
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { format } from 'date-fns'
import { ru } from 'date-fns/locale'
import { PackageOpen } from 'lucide-react'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { cn } from '@/lib/utils'
import { FuelBadge } from '@/components/common/FuelBadge'
import { useFuelName } from '@/hooks/useFuelName'
import { getLoadedReceipts, type LoadedReceipt } from '@/services/fuel/fuelMappingService'
import { ReceiptDetailsModal } from './ReceiptDetailsModal'

const todayStr = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export function ReceiptsJournal() {
  const { data } = useQuery({
    queryKey: ['fuel-receipts-journal'],
    queryFn: getLoadedReceipts,
  })
  const receipts = data ?? []
  const fuelName = useFuelName()

  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState(todayStr())
  const [ttn, setTtn] = useState('')
  const [base, setBase] = useState('all')
  const [shift, setShift] = useState('')
  const [openReceipt, setOpenReceipt] = useState<LoadedReceipt | null>(null)

  const bases = useMemo(() => {
    const s = new Set<string>()
    for (const r of receipts) if (r.supplier) s.add(r.supplier)
    return [...s].sort()
  }, [receipts])

  const rdt = (r: LoadedReceipt) => r.received_at || r.created_at

  const filtered = useMemo(() => {
    let list = receipts
    if (ttn.trim()) list = list.filter((r) => r.ttn.toLowerCase().includes(ttn.toLowerCase().trim()))
    if (base !== 'all') list = list.filter((r) => (r.supplier || '') === base)
    if (shift.trim()) list = list.filter((r) => String(r.shift_number ?? '') === shift.trim())
    if (dateFrom || dateTo) {
      const from = dateFrom ? new Date(dateFrom + 'T00:00:00') : null
      const to = dateTo ? new Date(dateTo + 'T23:59:59') : null
      list = list.filter((r) => {
        const d = new Date(rdt(r))
        if (from && d < from) return false
        if (to && d > to) return false
        return true
      })
    }
    return [...list].sort((a, b) => new Date(rdt(b)).getTime() - new Date(rdt(a)).getTime())
  }, [receipts, ttn, base, shift, dateFrom, dateTo])

  const clear = () => { setDateFrom(''); setDateTo(todayStr()); setTtn(''); setBase('all'); setShift('') }

  return (
    <div className="space-y-4">
      {/* Фильтры */}
      <Card className="py-3">
        <CardContent className="pt-0 pb-0">
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">Дата от</Label>
              <Input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className="h-8" />
            </div>
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">Дата до</Label>
              <Input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} className="h-8" />
            </div>
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">Номер ТТН</Label>
              <Input type="text" placeholder="Введите номер" value={ttn} onChange={(e) => setTtn(e.target.value)} className="h-8" />
            </div>
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">Нефтебаза</Label>
              <Select value={base} onValueChange={setBase}>
                <SelectTrigger className="h-8"><SelectValue placeholder="Все" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Все</SelectItem>
                  {bases.map((b) => <SelectItem key={b} value={b}>{b}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">Номер смены</Label>
              <Input type="number" placeholder="Введите номер" value={shift} onChange={(e) => setShift(e.target.value)} className="h-8" />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Журнал */}
      <Card className="py-3 gap-2">
        <CardHeader className="pb-0">
          <CardTitle className="text-sm flex items-center gap-1.5">
            <PackageOpen className="h-3.5 w-3.5 text-muted-foreground" />
            Журнал поступлений
            <span className="text-xs text-muted-foreground font-normal ml-2 tabular-nums">{filtered.length}</span>
            <button onClick={clear} className="ml-auto text-xs text-muted-foreground hover:text-foreground">Сбросить фильтры</button>
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-0 pb-3">
          <div className="grid grid-cols-[150px_60px_80px_90px_1fr_120px_120px_130px] gap-3 px-3 pb-2 text-[10px] font-semibold text-muted-foreground/70 uppercase tracking-wide">
            <span>Дата и время</span><span>ТТ</span><span>Смена</span><span>ТТН</span><span>Топливо</span>
            <span className="text-right">Объём (л)</span><span className="text-right">Масса (кг)</span><span className="text-right">Отклонение (кг)</span>
          </div>
          <div className="max-h-[460px] overflow-y-auto space-y-1 pr-1">
            {filtered.length === 0 ? (
              <p className="text-sm text-muted-foreground py-8 text-center">Нет поступлений по фильтру</p>
            ) : filtered.map((r) => {
              const massDiff = r.diff_mass ?? ((r.fact_mass_kg || 0) - (r.doc_mass_kg || 0))
              return (
                <div key={r.id} onClick={() => setOpenReceipt(r)}
                  className="grid grid-cols-[150px_60px_80px_90px_1fr_120px_120px_130px] gap-3 items-center px-3 py-2.5 text-xs bg-di-surface-low rounded-xl hover:bg-di-surface-high transition-colors cursor-pointer">
                  <span className="text-muted-foreground tabular-nums">{format(new Date(rdt(r)), 'dd.MM.yyyy HH:mm', { locale: ru })}</span>
                  <span className="text-foreground/80">{r.station_code}</span>
                  <span className="text-foreground/80">{r.shift_number ?? '—'}</span>
                  <span className="font-mono text-foreground/80">{r.ttn}</span>
                  <FuelBadge fuel={fuelName(r.fuel_code, r.fuel_name)} />
                  <span className="text-right tabular-nums text-foreground/80">{(r.doc_volume_liters || 0).toFixed(2)}</span>
                  <span className="text-right tabular-nums text-foreground/80">{(r.doc_mass_kg || 0).toFixed(2)}</span>
                  <span className={cn('text-right tabular-nums font-medium', massDiff > 0 ? 'text-emerald-500' : massDiff < 0 ? 'text-red-500' : 'text-muted-foreground')}>
                    {massDiff > 0 ? '+' : ''}{massDiff.toFixed(2)}
                  </span>
                </div>
              )
            })}
          </div>
        </CardContent>
      </Card>

      <ReceiptDetailsModal receipt={openReceipt} open={openReceipt !== null} onClose={() => setOpenReceipt(null)} />
    </div>
  )
}
