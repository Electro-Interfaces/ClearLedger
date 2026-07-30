/**
 * Раздел «Купоны» — журнал сдачи топливом (STS `/v1/coupons`).
 *
 * Купон выдают, когда клиенту не отпустили весь оплаченный объём: остаток —
 * долг сети перед ним. Поэтому раздел отвечает на два вопроса: сколько мы
 * должны прямо сейчас (активные и их остаток) и что залежалось (активные
 * старше недели — за ними, скорее всего, уже не придут).
 *
 * Форма — как в «Мониторе» (`prod.dataworker.ru/network/coupons`): сводка,
 * чипы-разрезы по состоянию и топливу, журнал строками. Своё: дата реализации
 * заполнена (взята из реализаций Ledger по номеру купона — STS её не отдаёт).
 */
import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Copy, Download, Loader2, Search, Ticket, X } from 'lucide-react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { FuelBadge } from '@/components/common/FuelBadge'
import { cn } from '@/lib/utils'
import { useResetOnScopeChange } from '@/hooks/useScopeReset'
import { useFuelKindFilter } from '@/hooks/useFuelKindFilter'
import { getCoupons, type CouponRow } from '@/services/fuel/couponsService'

const PAGE = 100
const ALL = '__all__'
const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })
const nf2 = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

function fmtDt(value: string | null): { date: string; time: string } | null {
  if (!value) return null
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return null
  return {
    date: d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit' }),
    time: d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }),
  }
}

/** Состояние купона: активный (долг), погашен, прочее. */
function stateClass(stateId: number | null) {
  if (stateId === 0) return 'border-emerald-500/40 bg-emerald-500/10 text-emerald-500'
  if (stateId === 2) return 'border-muted-foreground/40 bg-muted text-muted-foreground'
  return 'border-border bg-muted text-muted-foreground'
}

/** Остаток: положительный — долг перед клиентом, отрицательный — перебор отпуска. */
function restClass(value: number) {
  if (value < 0) return 'text-red-500'
  if (value === 0) return 'text-muted-foreground'
  return 'text-emerald-500'
}

function DateCell({ value }: { value: string | null }) {
  const d = fmtDt(value)
  if (!d) return <span className="text-muted-foreground">—</span>
  return (
    <div className="flex flex-col">
      <span className="font-mono">{d.date}</span>
      <span className="font-mono text-[10px] text-muted-foreground">{d.time}</span>
    </div>
  )
}

export function CouponsPanel({ companyId, dateFrom, dateTo }: {
  companyId: string; dateFrom: string; dateTo: string
}) {
  const [search, setSearch] = useState('')
  const [station, setStation] = useState(ALL)
  const [states, setStates] = useState<Set<string>>(new Set())
  const [fuels, setFuels] = useState<Set<string>>(new Set())
  const [page, setPage] = useState(0)
  const [detail, setDetail] = useState<CouponRow | null>(null)
  useResetOnScopeChange(() => { setSearch(''); setPage(0) })

  const fk = useFuelKindFilter()
  const query = useQuery({
    queryKey: ['fuel-coupons', companyId, dateFrom, dateTo],
    queryFn: () => getCoupons(dateFrom, dateTo),
    staleTime: 60_000,
  })

  const all = useMemo(() => query.data?.coupons ?? [], [query.data])
  const stats = query.data?.stats as import('@/services/fuel/couponsService').CouponsStats | undefined

  const stationOptions = useMemo(() => {
    const map = new Map<string, string>()
    all.forEach((c) => { if (c.station_code != null) map.set(String(c.station_code), c.station_name) })
    return [...map.entries()].sort((a, b) => Number(a[0]) - Number(b[0]))
  }, [all])
  // Вид нефтепродукта из шапки рабочей области — тот же контур, что и у соседних
  // экранов: раздел не имеет права показывать топливо вне выбранного разреза.
  const scopedByKind = useMemo(() => {
    const codes = fk.fuelCodes
    if (!codes?.length) return all
    return all.filter((c) => c.fuel_code != null && codes.includes(c.fuel_code))
  }, [all, fk.fuelCodes])

  const filtered = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase('ru')
    return scopedByKind.filter((c) => {
      if (station !== ALL && String(c.station_code) !== station) return false
      if (states.size > 0 && !states.has(c.state_name)) return false
      if (fuels.size > 0 && !(c.fuel_name && fuels.has(c.fuel_name))) return false
      if (!needle) return true
      return [c.number, c.station_name, c.fuel_name, c.author, c.comment]
        .some((v) => v?.toLocaleLowerCase('ru').includes(needle))
    })
  }, [scopedByKind, search, station, states, fuels])

  useEffect(() => { setPage(0) }, [search, station, states, fuels, dateFrom, dateTo, fk.key])

  // Разрез по топливу — остаток долга: именно он, а не число купонов, решает,
  // сколько литров сеть ещё должна отпустить.
  const byFuel = useMemo(() => {
    const acc = new Map<string, { count: number; rest: number }>()
    for (const c of scopedByKind) {
      const key = c.fuel_name ?? '—'
      const e = acc.get(key) ?? { count: 0, rest: 0 }
      e.count += 1
      e.rest += c.rest_qty
      acc.set(key, e)
    }
    return [...acc.entries()].sort((a, b) => b[1].rest - a[1].rest)
  }, [scopedByKind])

  const byState = useMemo(() => {
    const acc = new Map<string, number>()
    for (const c of scopedByKind) acc.set(c.state_name, (acc.get(c.state_name) ?? 0) + 1)
    return [...acc.entries()].sort((a, b) => b[1] - a[1])
  }, [scopedByKind])

  const pages = Math.max(1, Math.ceil(filtered.length / PAGE))
  const current = Math.min(page, pages - 1)
  const visible = filtered.slice(current * PAGE, (current + 1) * PAGE)
  const hasFilters = station !== ALL || states.size > 0 || fuels.size > 0 || !!search

  const toggle = (set: (fn: (s: Set<string>) => Set<string>) => void) => (value: string) => set((s) => {
    const n = new Set(s)
    if (n.has(value)) n.delete(value)
    else n.add(value)
    return n
  })
  const toggleState = toggle(setStates)
  const toggleFuel = toggle(setFuels)
  const resetAll = () => { setStation(ALL); setStates(new Set()); setFuels(new Set()); setSearch('') }

  async function exportXlsx() {
    const XLSX = await import('xlsx')
    const sheet = filtered.map((c) => ({
      'АЗС': c.station_name,
      'Номер купона': c.number,
      'Выдан': fmtDt(c.dt) ? `${fmtDt(c.dt)!.date} ${fmtDt(c.dt)!.time}` : '',
      'Реализован': fmtDt(c.redeemed_at) ? `${fmtDt(c.redeemed_at)!.date} ${fmtDt(c.redeemed_at)!.time}` : '',
      'Топливо': c.fuel_name ?? '',
      'Цена, ₽/л': c.price || '',
      'Выдано, л': c.qty_total,
      'Использовано, л': c.qty_used,
      'Остаток, л': c.rest_qty,
      'Остаток, ₽': c.rest_summ,
      'Состояние': c.state_name,
      'Тип': c.type_name ?? '',
      'Автор': c.author ?? '',
      'Комментарий': c.comment ?? '',
      'Смена': c.shift ?? '',
      'Операция': c.opernum ?? '',
    }))
    const wb = XLSX.utils.book_new()
    XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(sheet), 'Купоны')
    XLSX.writeFile(wb, `kupony_${dateFrom}_${dateTo}.xlsx`)
  }

  const summary: [string, string, string?][] = stats ? [
    ['Выдано', nf0.format(stats.issued), `${nf0.format(Math.round(stats.issued_liters))} л`],
    ['Отоварено', nf0.format(stats.used), `${nf0.format(Math.round(stats.used_liters))} л`],
    ['Активные', nf0.format(stats.active), `${nf1.format(stats.active_liters)} л`],
    ['Долг по активным', `${nf0.format(Math.round(stats.active_amount))} ₽`, 'остаток к отпуску'],
    ['Залежались', nf0.format(stats.stale), `активные старше ${stats.stale_days} дн.`],
  ] : []

  return (
    <div className="space-y-3 p-3">
      <section className="rounded-lg border border-border bg-card">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border px-4 py-3">
          <div>
            <h2 className="flex items-center gap-2 text-sm font-semibold">
              <Ticket className="h-4 w-4 text-primary" />
              Купоны — сдача топливом
            </h2>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Остаток активного купона — долг сети перед клиентом. Строка открывает карточку.
            </p>
          </div>
          <Button variant="outline" size="sm" className="h-8 text-xs" disabled={filtered.length === 0} onClick={() => void exportXlsx()}>
            <Download className="mr-1.5 h-3.5 w-3.5" />Экспорт
          </Button>
        </div>

        {query.data?.warning && (
          <div className="border-b border-amber-500/30 bg-amber-500/5 px-4 py-2 text-xs text-amber-500">
            {query.data.warning}
          </div>
        )}

        {stats && (
          <div className="grid grid-cols-2 divide-x divide-y divide-border sm:grid-cols-3 lg:grid-cols-5 lg:divide-y-0">
            {summary.map(([label, value, hint]) => (
              <div key={label} className="px-4 py-3">
                <div className="text-[11px] text-muted-foreground">{label}</div>
                <div className="mt-0.5 text-sm font-semibold tabular-nums">{value}</div>
                {hint && <div className="mt-0.5 text-[11px] text-muted-foreground">{hint}</div>}
              </div>
            ))}
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2 border-t border-border px-3 py-2">
          <div className="relative min-w-52 flex-1 sm:max-w-72">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Поиск купона"
              placeholder="Номер купона, АЗС, автор…" className="h-8 pl-8 text-xs" />
          </div>
          <Select value={station} onValueChange={setStation}>
            <SelectTrigger aria-label="АЗС" className="h-8 w-44 text-xs"><SelectValue placeholder="Все АЗС" /></SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>Все АЗС</SelectItem>
              {stationOptions.map(([code, name]) => <SelectItem key={code} value={code}>{name}</SelectItem>)}
            </SelectContent>
          </Select>
          {hasFilters && (
            <Button variant="ghost" size="sm" className="h-8 px-2 text-xs" onClick={resetAll}>
              <X className="mr-1.5 h-3.5 w-3.5" />Сбросить
            </Button>
          )}
          {query.isFetching && (
            <span className="flex items-center gap-1.5 text-xs text-muted-foreground" aria-live="polite">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />Обновление
            </span>
          )}
        </div>

        {/* Разрезы чипами: состояние отвечает «сколько ещё должны», топливо —
            «чем именно». Цифра на чипе топлива — остаток, а не число купонов. */}
        {(byState.length > 0 || byFuel.length > 0) && (
          <div className="flex flex-wrap items-center gap-1.5 border-t border-border px-3 py-2">
            {byState.map(([name, count]) => (
              <button key={name} type="button" aria-pressed={states.has(name)} onClick={() => toggleState(name)}
                className={cn('rounded-lg border px-2.5 py-1 text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                  states.has(name) ? 'border-primary/60 bg-primary/10 font-medium text-primary'
                    : 'border-border bg-card/50 text-muted-foreground hover:bg-muted/40 hover:text-foreground')}>
                {name} <span className="tabular-nums">{nf0.format(count)}</span>
              </button>
            ))}
            <span className="mx-1 h-4 w-px bg-border" aria-hidden />
            {byFuel.map(([name, agg]) => (
              <button key={name} type="button" aria-pressed={fuels.has(name)} onClick={() => toggleFuel(name)}
                className={cn('rounded-lg border px-2.5 py-1 text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                  fuels.has(name) ? 'border-primary/60 bg-primary/10 font-medium text-primary'
                    : 'border-border bg-card/50 text-muted-foreground hover:bg-muted/40 hover:text-foreground')}
                title={`${nf0.format(agg.count)} купонов`}>
                {name} <span className="tabular-nums">{nf1.format(agg.rest)} л</span>
              </button>
            ))}
          </div>
        )}
      </section>

      <section className="overflow-hidden rounded-lg border border-border bg-card">
        {query.isLoading ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-9 w-full" />)}
          </div>
        ) : query.error ? (
          <div className="p-8 text-center text-sm text-red-400">Не удалось получить купоны из STS.</div>
        ) : visible.length === 0 ? (
          <div className="p-10 text-center">
            <Ticket className="mx-auto h-8 w-8 text-muted-foreground" />
            <div className="mt-2 text-sm font-medium">Купонов по выбранным условиям нет</div>
            <p className="mt-1 text-xs text-muted-foreground">Проверьте период, АЗС и вид топлива в шапке рабочей области.</p>
          </div>
        ) : (
          <Table className="text-xs">
            <TableHeader className="bg-muted/40">
              <TableRow>
                <TableHead className="h-9">АЗС</TableHead>
                <TableHead className="h-9">Номер</TableHead>
                <TableHead className="h-9">Выдан</TableHead>
                <TableHead className="h-9">Реализован</TableHead>
                <TableHead className="h-9">Топливо</TableHead>
                <TableHead className="h-9 text-right">Цена</TableHead>
                <TableHead className="h-9 text-right">Остаток, л</TableHead>
                <TableHead className="h-9 text-right">Остаток, ₽</TableHead>
                <TableHead className="h-9">Состояние</TableHead>
                <TableHead className="h-9">Тип</TableHead>
                <TableHead className="h-9">Автор</TableHead>
                <TableHead className="h-9">Смена</TableHead>
                <TableHead className="h-9 w-10" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {visible.map((c) => (
                <TableRow
                  key={`${c.station_code}-${c.number}-${c.dt}`}
                  tabIndex={0}
                  aria-haspopup="dialog"
                  className="cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                  onClick={() => setDetail(c)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setDetail(c) }
                  }}
                >
                  <TableCell className="max-w-40 truncate font-medium">{c.station_name}</TableCell>
                  <TableCell className="font-mono">
                    {c.number}
                    {c.state_id === 0 && c.qty_used === 0 && (
                      <div className="text-[10px] text-amber-500">не использован</div>
                    )}
                  </TableCell>
                  <TableCell><DateCell value={c.dt} /></TableCell>
                  <TableCell><DateCell value={c.redeemed_at} /></TableCell>
                  <TableCell>
                    {c.fuel_name && !/руб/i.test(c.fuel_name)
                      ? <FuelBadge fuel={c.fuel_name} />
                      : <span className="text-muted-foreground">{c.fuel_name ?? '—'}</span>}
                    {c.qty_used > 0 && (
                      <div className="text-[10px] text-muted-foreground">исп. {nf1.format(c.qty_used)} л</div>
                    )}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{c.price > 0 ? `${nf2.format(c.price)} ₽` : '—'}</TableCell>
                  <TableCell className={cn('text-right font-medium tabular-nums', restClass(c.rest_qty))}>
                    {nf1.format(c.rest_qty)} л
                    <div className="text-[10px] font-normal text-muted-foreground">из {nf1.format(c.qty_total)} л</div>
                  </TableCell>
                  <TableCell className={cn('text-right font-medium tabular-nums', restClass(c.rest_summ))}>
                    {nf2.format(c.rest_summ)} ₽
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline" className={cn('text-[10px]', stateClass(c.state_id))}>{c.state_name}</Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground">{c.type_name ?? '—'}</TableCell>
                  <TableCell className="max-w-28 truncate text-muted-foreground">{c.author ?? '—'}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {c.shift != null ? `№${c.shift}` : '—'}
                    {c.opernum != null && <div className="text-[10px]">операция №{c.opernum}</div>}
                  </TableCell>
                  <TableCell>
                    <Button
                      variant="ghost" size="sm" className="h-7 w-7 p-0"
                      aria-label={`Скопировать номер купона ${c.number}`}
                      onClick={(e) => {
                        e.stopPropagation() // копирование не должно открывать карточку
                        void navigator.clipboard.writeText(c.number)
                        toast.success(`Номер купона ${c.number} скопирован`)
                      }}
                    >
                      <Copy className="h-3.5 w-3.5" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </section>

      {filtered.length > 0 && (
        <div className="flex items-center justify-between px-1 text-xs text-muted-foreground">
          <span>
            {nf0.format(current * PAGE + 1)}–{nf0.format(Math.min((current + 1) * PAGE, filtered.length))} из {nf0.format(filtered.length)}
          </span>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" className="h-7 text-xs" disabled={current === 0} onClick={() => setPage((v) => Math.max(0, v - 1))}>Назад</Button>
            <span className="tabular-nums">{current + 1} / {pages}</span>
            <Button variant="outline" size="sm" className="h-7 text-xs" disabled={current + 1 >= pages} onClick={() => setPage((v) => v + 1)}>Далее</Button>
          </div>
        </div>
      )}

      <Dialog open={!!detail} onOpenChange={(open) => !open && setDetail(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <div className="flex flex-wrap items-center gap-2">
              <DialogTitle>Купон № {detail?.number}</DialogTitle>
              {detail && <Badge variant="outline" className={stateClass(detail.state_id)}>{detail.state_name}</Badge>}
            </div>
            <DialogDescription>
              {detail?.station_name}{fmtDt(detail?.dt ?? null) ? ` · выдан ${fmtDt(detail!.dt)!.date} ${fmtDt(detail!.dt)!.time}` : ''}
            </DialogDescription>
          </DialogHeader>
          {detail && (
            <div className="grid grid-cols-1 gap-0 text-sm">
              {([
                ['Топливо', detail.fuel_name ?? '—'],
                ['Цена', detail.price > 0 ? `${nf2.format(detail.price)} ₽/л` : '—'],
                ['Выдано', `${nf1.format(detail.qty_total)} л · ${nf2.format(detail.summ_total)} ₽`],
                ['Использовано', `${nf1.format(detail.qty_used)} л · ${nf2.format(detail.summ_used)} ₽`],
                ['Остаток', `${nf1.format(detail.rest_qty)} л · ${nf2.format(detail.rest_summ)} ₽`],
                ['Реализован', fmtDt(detail.redeemed_at) ? `${fmtDt(detail.redeemed_at)!.date} ${fmtDt(detail.redeemed_at)!.time}` : '—'],
                ['Тип', detail.type_name ?? '—'],
                ['Автор', detail.author ?? '—'],
                ['Комментарий', detail.comment ?? '—'],
                ['Смена · операция', `${detail.shift ?? '—'} · ${detail.opernum ?? '—'}`],
                ['Рабочее место', detail.pos ?? '—'],
              ] as [string, string | number][]).map(([k, v]) => (
                <div key={k} className="flex items-center justify-between gap-4 border-b border-border/60 py-1.5">
                  <span className="text-muted-foreground">{k}:</span>
                  <span className="text-right font-mono">{v}</span>
                </div>
              ))}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
