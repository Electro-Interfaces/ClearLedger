/**
 * «Касса и инкассация» (бухгалтерский раздел, ГИГ) — контур наличных из
 * money-секции сменных отчётов STS:
 *   • журнал инкассаций за период: сумма + «накоплено с прошлой инкассации»
 *     (Σ наличной выручки между инкассациями) — основание для РКО в 1С
 *     (в пакеты БП инкассация не выгружается: приёмник её не принимает);
 *   • выдачи наличных из кассы;
 *   • остатки касс по АЗС (последний снимок «по всей АЗС») + дни без
 *     инкассации — контроль накопления наличных на станциях.
 * «Выручка» money-секции = ВСЯ наличка ККТ (топливо + сопутка магазина).
 */
import { useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Banknote } from 'lucide-react'
import { ExportButton } from './analytics/ExportButton'
import { get } from '@/services/apiClient'

const nf = (n: number, d = 0) => new Intl.NumberFormat('ru-RU', { minimumFractionDigits: d, maximumFractionDigits: d }).format(n)
const fmtDT = (iso: string | null) => {
  if (!iso) return '—'
  const d = new Date(iso)
  const p = (x: number) => String(x).padStart(2, '0')
  return `${p(d.getDate())}.${p(d.getMonth() + 1)}.${d.getFullYear()} ${p(d.getHours())}:${p(d.getMinutes())}`
}

interface CashCollections {
  period: { from: string; to: string }
  kpis: { collected: number; collections: number; cashRevenue: number; payouts: number; networkBalance: number; stale7: number }
  journal: { date: string; station_code: number; station_name: string; shift_number: number; pos: number | null; amount: number; accrued_since_last: number; diff: number }[]
  payouts: { date: string; station_code: number; station_name: string; shift_number: number; amount: number }[]
  stations: { station_code: number; station_name: string; balance: number | null; balance_at: string | null; accrued_since_last: number; last_collection_at: string | null; last_collection_amount: number | null; days_since_collection: number | null }[]
}

function Kpi({ label, value, sub, accent }: { label: string; value: string; sub?: string; accent?: 'warn' | 'danger' }) {
  const tone = accent === 'danger' ? 'text-red-600 dark:text-red-400'
    : accent === 'warn' ? 'text-amber-600 dark:text-amber-400' : 'text-foreground'
  return (
    <Card><CardContent className="pt-4">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`mt-1 text-lg font-semibold tabular-nums ${tone}`}>{value}</div>
      {sub && <div className="text-[11px] text-muted-foreground/70">{sub}</div>}
    </CardContent></Card>
  )
}

export function AccountingCashPanel({ dateFrom, dateTo }: { dateFrom: string; dateTo: string }) {
  const rootRef = useRef<HTMLDivElement>(null)
  const { data, isLoading } = useQuery({
    queryKey: ['fuel-cash-collections', dateFrom, dateTo],
    queryFn: () => get<CashCollections>('/api/fuel/cash-collections', { date_from: dateFrom, date_to: dateTo }),
    staleTime: 60_000,
  })

  if (isLoading) return <div className="p-6 text-sm text-muted-foreground">Загрузка кассового контура…</div>
  if (!data || (data.journal.length === 0 && data.stations.length === 0)) {
    return <div className="p-6 text-sm text-muted-foreground">Нет данных money-секции — загрузите смены в канале «Сменные отчёты STS».</div>
  }
  const k = data.kpis
  const daysCls = (d: number | null, accrued: number) =>
    d == null ? 'text-muted-foreground'
      : d >= 14 && accrued > 0 ? 'text-red-600 dark:text-red-400 font-medium'
      : d >= 7 && accrued > 0 ? 'text-amber-600 dark:text-amber-400'
      : 'text-muted-foreground'

  return (
    <div ref={rootRef} className="space-y-5 p-6">
      <div className="flex flex-wrap items-center gap-2">
        <Banknote className="h-5 w-5 text-primary" />
        <h1 className="text-xl font-semibold">Касса и инкассация</h1>
        <Badge className="bg-emerald-500/15 text-[10px] text-emerald-600 dark:text-emerald-400">реальные данные</Badge>
        <ExportButton title="Касса и инкассация" subtitle={`${dateFrom} — ${dateTo}`} getEl={() => rootRef.current} />
      </div>
      <p className="max-w-3xl text-sm text-muted-foreground">
        Наличный контур из money-секции сменных отчётов. «Выручка» — вся наличка ККТ
        (топливо + сопутка). Инкассации в 1С оформляются РКО вручную — журнал ниже
        даёт основание (сумма + накоплено с прошлой инкассации).
      </p>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
        <Kpi label="Инкассировано за период" value={`${nf(k.collected)} ₽`} sub={`${k.collections} инкассаций`} />
        <Kpi label="Наличная выручка (ККТ)" value={`${nf(k.cashRevenue)} ₽`} sub="топливо + сопутка" />
        <Kpi label="Выдано наличными" value={`${nf(k.payouts)} ₽`} />
        <Kpi label="Остаток по сети" value={`${nf(k.networkBalance)} ₽`} sub="последние снимки касс АЗС" />
        <Kpi label="≥7 дней без инкассации" value={String(k.stale7)} accent={k.stale7 ? 'warn' : undefined} sub="с накоплением в кассе" />
        <Kpi label="Δ выручка − инкассация" value={`${nf(k.cashRevenue - k.collected)} ₽`} sub="накопление за период" />
      </div>

      {/* Остатки касс по АЗС */}
      <Card><CardContent className="space-y-3 pt-5">
        <div className="text-sm font-medium">Кассы по АЗС — остатки и дни без инкассации</div>
        <Table><TableHeader><TableRow>
          <TableHead>АЗС</TableHead>
          <TableHead className="text-right">Остаток кассы, ₽</TableHead>
          <TableHead className="text-right">Снимок</TableHead>
          <TableHead className="text-right">Накоплено с последней, ₽</TableHead>
          <TableHead className="text-right">Последняя инкассация</TableHead>
          <TableHead className="text-right">Сумма, ₽</TableHead>
          <TableHead className="text-right">Дней без инкассации</TableHead>
        </TableRow></TableHeader><TableBody>
          {data.stations.map((s) => (
            <TableRow key={s.station_code}>
              <TableCell className="font-medium">{s.station_name} ({s.station_code})</TableCell>
              <TableCell className={`text-right tabular-nums ${(s.balance ?? 0) < 0 ? 'text-red-600 dark:text-red-400' : ''}`}>
                {s.balance != null ? nf(s.balance, 2) : '—'}
              </TableCell>
              <TableCell className="text-right text-xs text-muted-foreground whitespace-nowrap">{fmtDT(s.balance_at)}</TableCell>
              <TableCell className="text-right tabular-nums">{nf(s.accrued_since_last, 2)}</TableCell>
              <TableCell className="text-right text-xs text-muted-foreground whitespace-nowrap">{fmtDT(s.last_collection_at)}</TableCell>
              <TableCell className="text-right tabular-nums text-muted-foreground">{s.last_collection_amount != null ? nf(s.last_collection_amount, 2) : '—'}</TableCell>
              <TableCell className={`text-right tabular-nums ${daysCls(s.days_since_collection, s.accrued_since_last)}`}>
                {s.days_since_collection ?? '—'}
              </TableCell>
            </TableRow>
          ))}
        </TableBody></Table>
        <p className="text-xs text-muted-foreground/70">
          Отрицательный остаток — аномалия учёта STS (проверить смену); жёлтый/красный — 7/14 дней
          без инкассации при ненулевом накоплении.
        </p>
      </CardContent></Card>

      {/* Журнал инкассаций */}
      <Card><CardContent className="space-y-3 pt-5">
        <div className="flex items-center gap-2">
          <div className="text-sm font-medium">Журнал инкассаций</div>
          <Badge variant="secondary" className="text-[10px]">{data.journal.length}</Badge>
          <span className="text-xs text-muted-foreground/70">основание для РКО (Дт 57.02 Кт 50.01)</span>
        </div>
        <div className="max-h-[420px] overflow-auto rounded-md border border-border/40">
          <Table><TableHeader className="sticky top-0 bg-card"><TableRow>
            <TableHead>Дата смены</TableHead>
            <TableHead>АЗС</TableHead>
            <TableHead className="text-right">Смена</TableHead>
            <TableHead className="text-right">Инкассировано, ₽</TableHead>
            <TableHead className="text-right">Накоплено с прошлой, ₽</TableHead>
            <TableHead className="text-right">Δ, ₽</TableHead>
          </TableRow></TableHeader><TableBody>
            {data.journal.map((j, i) => (
              <TableRow key={i}>
                <TableCell className="whitespace-nowrap font-mono text-xs">{fmtDT(j.date)}</TableCell>
                <TableCell>{j.station_name} ({j.station_code})</TableCell>
                <TableCell className="text-right tabular-nums text-muted-foreground">№{j.shift_number}</TableCell>
                <TableCell className="text-right tabular-nums font-medium">{nf(j.amount, 2)}</TableCell>
                <TableCell className="text-right tabular-nums text-muted-foreground">{nf(j.accrued_since_last, 2)}</TableCell>
                <TableCell className={`text-right tabular-nums ${Math.abs(j.diff) > 10000 ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground'}`}>
                  {nf(j.diff, 2)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody></Table>
        </div>
      </CardContent></Card>

      {/* Выдачи наличных */}
      {data.payouts.length > 0 && (
        <Card><CardContent className="space-y-3 pt-5">
          <div className="flex items-center gap-2">
            <div className="text-sm font-medium">Выдано наличными из кассы</div>
            <Badge variant="secondary" className="text-[10px]">{data.payouts.length}</Badge>
          </div>
          <Table><TableHeader><TableRow>
            <TableHead>Дата смены</TableHead><TableHead>АЗС</TableHead>
            <TableHead className="text-right">Смена</TableHead>
            <TableHead className="text-right">Сумма, ₽</TableHead>
          </TableRow></TableHeader><TableBody>
            {data.payouts.map((p, i) => (
              <TableRow key={i}>
                <TableCell className="whitespace-nowrap font-mono text-xs">{fmtDT(p.date)}</TableCell>
                <TableCell>{p.station_name} ({p.station_code})</TableCell>
                <TableCell className="text-right tabular-nums text-muted-foreground">№{p.shift_number}</TableCell>
                <TableCell className="text-right tabular-nums">{nf(p.amount, 2)}</TableCell>
              </TableRow>
            ))}
          </TableBody></Table>
        </CardContent></Card>
      )}
    </div>
  )
}
