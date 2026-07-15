/**
 * Журнал поступлений (ТТН) — как в TradePoint. Фильтры (Дата от/до · Номер ТТН ·
 * Нефтебаза · Номер смены) + таблица (Дата/ТТ/Смена/ТТН/Топливо/Объём/Масса/
 * Отклонение). Клик по строке → «Детали поступления». Display-only.
 */
import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { format } from 'date-fns'
import { ru } from 'date-fns/locale'
import { PackageOpen, Check, X, TrendingUp, TrendingDown, Minus, Pencil } from 'lucide-react'
import { toast } from 'sonner'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { cn } from '@/lib/utils'
import { getFuelColor } from '@/utils/fuelColors'
import { FuelBadge } from '@/components/common/FuelBadge'
import { useFuelName } from '@/hooks/useFuelName'
import {
  getLoadedReceipts, setReceiptStatus, bulkReceiptStatus,
  type LoadedReceipt, type ReceiptStatus,
} from '@/services/fuel/fuelMappingService'
import { ReceiptDetailsModal } from './ReceiptDetailsModal'

const STATUS_META: Record<string, { label: string; cls: string }> = {
  confirmed: { label: 'Принято', cls: 'border-emerald-400/50 text-emerald-300/80' },
  corrected: { label: 'Скорректировано', cls: 'border-sky-400/50 text-sky-300/80' },
  rejected: { label: 'Отклонено', cls: 'border-red-400/50 text-red-300/80' },
  pending: { label: 'Не проверено', cls: 'border-zinc-600 text-zinc-400' },
  new: { label: 'Не проверено', cls: 'border-zinc-600 text-zinc-400' },
}

const todayStr = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export function ReceiptsJournal({ stationFilter = null, onClearStation }: {
  stationFilter?: number | null
  onClearStation?: () => void
} = {}) {
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
    if (stationFilter != null) list = list.filter((r) => r.station_code === stationFilter)
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
  }, [receipts, stationFilter, ttn, base, shift, dateFrom, dateTo])

  const stationName = useMemo(
    () => (stationFilter == null ? null : receipts.find((r) => r.station_code === stationFilter)?.station_name ?? `АЗС №${stationFilter}`),
    [receipts, stationFilter])

  const clear = () => { setDateFrom(''); setDateTo(todayStr()); setTtn(''); setBase('all'); setShift(''); setFuelFilter(null); setOnlyCorrected(false); onClearStation?.() }

  const [fuelFilter, setFuelFilter] = useState<number | null>(null)
  const [onlyCorrected, setOnlyCorrected] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)
  const qc = useQueryClient()
  const corrCount = useMemo(() => filtered.filter((r) => r.has_corrections).length, [filtered])

  // KPI по видам топлива (по отфильтрованному журналу, без учёта клика по KPI).
  const byFuel = useMemo(() => {
    const map = new Map<number, { code: number; name: string; count: number; doc: number; fact: number; diff: number }>()
    for (const r of filtered) {
      const code = r.fuel_code ?? -1
      const e = map.get(code) ?? { code, name: fuelName(r.fuel_code, r.fuel_name), count: 0, doc: 0, fact: 0, diff: 0 }
      e.count += 1
      e.doc += r.doc_volume_liters || 0
      e.fact += r.fact_volume_liters || 0
      e.diff += r.diff_volume ?? ((r.fact_volume_liters || 0) - (r.doc_volume_liters || 0))
      map.set(code, e)
    }
    return [...map.values()].sort((a, b) => b.doc - a.doc)
  }, [filtered, fuelName])

  const shown = useMemo(() => {
    let list = fuelFilter == null ? filtered : filtered.filter((r) => (r.fuel_code ?? -1) === fuelFilter)
    if (onlyCorrected) list = list.filter((r) => r.has_corrections)
    return list
  }, [filtered, fuelFilter, onlyCorrected])

  const toggleSel = (id: string) => setSelected((s) => {
    const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n
  })
  const applyStatus = async (status: ReceiptStatus, ids: string[]) => {
    if (!ids.length) return
    setBusy(true)
    try {
      if (ids.length === 1) await setReceiptStatus(ids[0], status)
      else await bulkReceiptStatus(ids, status)
      await qc.invalidateQueries({ queryKey: ['fuel-receipts-journal'] })
      setSelected(new Set())
      toast.success(status === 'confirmed' ? 'Приёмка подтверждена' : status === 'rejected' ? 'Приёмка отклонена' : 'Статус обновлён')
    } catch { toast.error('Не удалось обновить статус') } finally { setBusy(false) }
  }

  return (
    <div className="space-y-4">
      {/* KPI по видам топлива (клик = фильтр) */}
      {byFuel.length > 0 && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
          {byFuel.map((f) => {
            const active = fuelFilter === f.code
            const D = f.diff > 0.01 ? TrendingUp : f.diff < -0.01 ? TrendingDown : Minus
            return (
              <button key={f.code} onClick={() => setFuelFilter(active ? null : f.code)}
                className={cn('rounded-xl border p-3 text-left transition-colors', active ? 'border-primary bg-primary/10' : 'border-border bg-card hover:bg-accent/40')}>
                <div className="flex items-center gap-1.5 text-sm">
                  <span className="h-2.5 w-2.5 rounded-full" style={{ background: getFuelColor(f.name).hex }} />
                  <span className="font-medium">{f.name}</span>
                  <span className="ml-auto text-xs text-muted-foreground">{f.count} ТТН</span>
                </div>
                <div className="mt-1.5 space-y-0.5 text-xs">
                  <div className="flex justify-between"><span className="text-muted-foreground">DOC:</span><span className="font-semibold tabular-nums">{f.doc.toFixed(0)} л</span></div>
                  <div className="flex justify-between"><span className="text-muted-foreground">FACT:</span><span className="tabular-nums text-primary">{f.fact.toFixed(0)} л</span></div>
                  <div className={cn('flex justify-between border-t border-border/60 pt-0.5', f.diff > 0.01 ? 'text-emerald-500' : f.diff < -0.01 ? 'text-red-500' : 'text-muted-foreground')}>
                    <span>Разн:</span><span className="flex items-center gap-0.5 tabular-nums"><D className="h-3 w-3" />{f.diff > 0 ? '+' : ''}{f.diff.toFixed(0)} л</span>
                  </div>
                </div>
              </button>
            )
          })}
        </div>
      )}

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
          <CardTitle className="text-sm flex flex-wrap items-center gap-1.5">
            <PackageOpen className="h-3.5 w-3.5 text-muted-foreground" />
            Журнал поступлений
            <span className="text-xs text-muted-foreground font-normal ml-2 tabular-nums">{shown.length}</span>
            {stationFilter != null && (
              <button onClick={() => onClearStation?.()}
                className="inline-flex items-center gap-1 rounded-md bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary hover:bg-primary/20">
                {stationName}<X className="h-3 w-3" />
              </button>
            )}
            {selected.size > 0 && (
              <span className="ml-3 flex items-center gap-1.5">
                <span className="text-xs text-muted-foreground">Выбрано {selected.size}:</span>
                <Button size="sm" className="h-6 gap-1 text-xs" disabled={busy} onClick={() => applyStatus('confirmed', [...selected])}><Check className="h-3 w-3" />Принять</Button>
                <Button size="sm" variant="outline" className="h-6 gap-1 text-xs text-red-400" disabled={busy} onClick={() => applyStatus('rejected', [...selected])}><X className="h-3 w-3" />Отклонить</Button>
              </span>
            )}
            <button onClick={() => setOnlyCorrected((v) => !v)} disabled={corrCount === 0}
              className={cn('ml-auto inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs transition-colors disabled:opacity-50',
                onlyCorrected ? 'border-amber-400 bg-amber-100 text-amber-700 dark:bg-amber-400/15 dark:text-amber-300' : 'border-border text-muted-foreground hover:bg-accent/40')}>
              <Pencil className="h-3 w-3" />Только изменённые{corrCount > 0 ? ` (${corrCount})` : ''}
            </button>
            <button onClick={clear} className="text-xs text-muted-foreground hover:text-foreground">Сбросить фильтры</button>
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-0 pb-3">
          {/* Фикс. колонки журнала на мобиле распирали раздел — скролл внутри
              карточки; w-0+min-w-full гасит проброс min-content вверх */}
          <div className="overflow-x-auto w-0 min-w-full">
          <div className="min-w-[880px]">
          <div className="grid grid-cols-[28px_130px_50px_56px_88px_1fr_92px_92px_100px_120px] gap-2 px-3 pb-2 text-[10px] font-semibold text-muted-foreground/70 uppercase tracking-wide">
            <span></span><span>Дата</span><span>ТТ</span><span>Смена</span><span>ТТН</span><span>Топливо</span>
            <span className="text-right">Объём л</span><span className="text-right">Масса кг</span><span className="text-right">Откл. кг</span><span>Приёмка</span>
          </div>
          <div className="max-h-[460px] overflow-y-auto space-y-1 pr-1">
            {shown.length === 0 ? (
              <p className="text-sm text-muted-foreground py-8 text-center">Нет поступлений по фильтру</p>
            ) : shown.map((r) => {
              const massDiff = r.diff_mass ?? ((r.fact_mass_kg || 0) - (r.doc_mass_kg || 0))
              const st = STATUS_META[r.status] ?? STATUS_META.pending
              return (
                <div key={r.id} onClick={() => setOpenReceipt(r)}
                  className={cn('grid grid-cols-[28px_130px_50px_56px_88px_1fr_92px_92px_100px_120px] gap-2 items-center px-3 py-2.5 text-xs bg-di-surface-low rounded-xl hover:bg-di-surface-high transition-colors cursor-pointer',
                    r.has_corrections && 'border-l-2 border-l-amber-400 bg-amber-50/60 dark:bg-amber-400/[0.06]')}>
                  <input type="checkbox" checked={selected.has(r.id)} onChange={() => toggleSel(r.id)} onClick={(e) => e.stopPropagation()} className="cursor-pointer" />
                  <span className="text-muted-foreground tabular-nums">{format(new Date(rdt(r)), 'dd.MM HH:mm', { locale: ru })}</span>
                  <span className="text-foreground/80">{r.station_code}</span>
                  <span className="text-foreground/80">{r.shift_number ?? '—'}</span>
                  <span className="font-mono text-foreground/80 inline-flex items-center gap-1">
                    {r.ttn}
                    {r.has_corrections && <Pencil className="h-3 w-3 shrink-0 text-amber-500" aria-label="Внесена корректировка" />}
                  </span>
                  <FuelBadge fuel={fuelName(r.fuel_code, r.fuel_name)} />
                  <span className="text-right tabular-nums text-foreground/80">{(r.doc_volume_liters || 0).toFixed(2)}</span>
                  <span className="text-right tabular-nums text-foreground/80">{(r.doc_mass_kg || 0).toFixed(2)}</span>
                  <span className={cn('text-right tabular-nums font-medium', massDiff > 0 ? 'text-emerald-500' : massDiff < 0 ? 'text-red-500' : 'text-muted-foreground')}>
                    {massDiff > 0 ? '+' : ''}{massDiff.toFixed(2)}
                  </span>
                  <Badge variant="outline" className={cn('w-fit text-[10px]', st.cls)}>{st.label}</Badge>
                </div>
              )
            })}
          </div>
          </div>
          </div>
        </CardContent>
      </Card>

      <ReceiptDetailsModal receipt={openReceipt} open={openReceipt !== null} onClose={() => setOpenReceipt(null)} />
    </div>
  )
}
