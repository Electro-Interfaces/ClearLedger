/**
 * Пункт «Частные лица» — розничное направление ЭЗС (ФЛ). Аналитика в разрезе
 * аккаунтов частных лиц. Внутренние табы: Обзор · Сегменты (RFM) · Экономика ·
 * Когорты · Гео. Данные — /api/retail/*. Телефоны псевдонимизированы (хеш-ID +
 * маска), сырой номер в панель не приходит.
 */
import { useMemo, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import { Loader2, ShieldCheck, AlertTriangle } from 'lucide-react'
import { useTabParams } from '@/hooks/useTabParams'
import {
  getRetailOverview, getRetailSegments, getRetailEconomics, getRetailGeo, getRetailCohorts,
  type RetailSegment,
} from '@/services/retailService'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })
const money = (v: number) => nf0.format(Math.round(v || 0)) + ' ₽'
const moneyK = (v: number) => (Math.abs(v) >= 10000 ? nf1.format(v / 1000) + ' тыс' : nf0.format(v)) + ' ₽'
const pct = (v: number) => nf1.format(v) + '%'

function Loading() { return <div className="flex justify-center py-12"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div> }
function Empty({ text }: { text: string }) { return <div className="p-6 text-sm text-muted-foreground text-center">{text}</div> }

function Kpi({ label, value, sub, cls }: { label: string; value: string; sub?: string; cls?: string }) {
  return (
    <Card className="py-0">
      <CardContent className="p-3">
        <div className="text-[11px] uppercase tracking-wider text-muted-foreground">{label}</div>
        <div className={`text-lg font-semibold tabular-nums ${cls ?? ''}`}>{value}</div>
        {sub && <div className="text-[11px] text-muted-foreground mt-0.5">{sub}</div>}
      </CardContent>
    </Card>
  )
}
function Widget({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <div className="text-[11px] uppercase tracking-wider text-muted-foreground">{title}</div>
      <Card className="h-full"><CardContent className="space-y-2 p-3">{children}</CardContent></Card>
    </div>
  )
}
function BarRow({ label, value, frac, sub, tint }: { label: ReactNode; value: string; frac: number; sub?: string; tint?: string }) {
  return (
    <div className="space-y-0.5">
      <div className="flex justify-between gap-2 text-xs">
        <span className="truncate">{label}</span>
        <span className="whitespace-nowrap tabular-nums text-muted-foreground">{value}{sub ? ` · ${sub}` : ''}</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted"><div className={`h-full rounded-full ${tint ?? 'bg-primary/70'}`} style={{ width: `${Math.max(2, Math.min(100, frac * 100))}%` }} /></div>
    </div>
  )
}

interface TabProps { companyId: string; dateFrom: string; dateTo: string }

/* ── RFM-сегменты: семантика цвета (приглушённая, по палитре проекта) ── */
const SEG_META: Record<string, { dot: string; bar: string; hint: string }> = {
  'Чемпионы':   { dot: 'bg-emerald-400/80', bar: 'bg-emerald-400/70', hint: 'свежие + частые' },
  'Лояльные':   { dot: 'bg-emerald-300/70', bar: 'bg-emerald-300/60', hint: 'свежие, регулярные' },
  'Под риском': { dot: 'bg-amber-400/80',   bar: 'bg-amber-400/70',   hint: 'частые, но давно не были' },
  'Новички':    { dot: 'bg-blue-400/70',    bar: 'bg-blue-400/60',    hint: 'первая сессия недавно' },
  'Случайные':  { dot: 'bg-zinc-400/60',    bar: 'bg-zinc-400/50',    hint: 'редкие' },
  'Разовые':    { dot: 'bg-zinc-500/60',    bar: 'bg-zinc-500/50',    hint: 'одна сессия, давно' },
  'Уснувшие':   { dot: 'bg-amber-300/60',   bar: 'bg-amber-300/50',   hint: 'замолчали' },
  'Отток':      { dot: 'bg-red-400/70',     bar: 'bg-red-400/60',     hint: 'были частыми, ушли' },
}
const segMeta = (s: string) => SEG_META[s] ?? { dot: 'bg-zinc-400/60', bar: 'bg-zinc-400/50', hint: '' }

// ── Таб: Обзор ──
function RetailOverviewTab({ companyId, dateFrom, dateTo }: TabProps) {
  const p = { companyId, dateFrom, dateTo }
  const ov = useQuery({ queryKey: ['retail-ov', companyId, dateFrom, dateTo], queryFn: () => getRetailOverview(p) })
  const seg = useQuery({ queryKey: ['retail-seg', companyId, dateFrom, dateTo], queryFn: () => getRetailSegments(p) })
  const eco = useQuery({ queryKey: ['retail-eco', companyId, dateFrom, dateTo], queryFn: () => getRetailEconomics(p) })
  if (ov.isLoading) return <Loading />
  if (!ov.data) return <Empty text="Нет данных" />
  const t = ov.data.totals
  const segs = seg.data?.segments ?? []
  const maxSeg = Math.max(1, ...segs.map((s) => s.revenue))
  const pareto = eco.data?.pareto ?? []
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-2 md:grid-cols-3 lg:grid-cols-6">
        <Kpi label="Аккаунтов ФЛ" value={nf0.format(t.accounts)} sub={`${nf0.format(t.new_accounts)} новых за период`} />
        <Kpi label="Выручка" value={moneyK(t.revenue)} sub={`ср. тариф ${nf1.format(t.avg_tariff)} ₽/кВтч`} />
        <Kpi label="ARPA" value={money(t.arpa)} sub="доход на аккаунт" />
        <Kpi label="Ср. чек" value={money(t.avg_check)} sub={`${nf0.format(t.sessions)} сессий`} />
        <Kpi label="Сессий/аккаунт" value={nf1.format(t.avg_sessions)} sub="в среднем" />
        <Kpi label="Энергия" value={`${nf0.format(t.energy_kwh)}`} sub="кВтч за период" />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Widget title="Выручка по RFM-сегментам">
          {seg.isLoading ? <Loading /> : segs.length === 0 ? <Empty text="Нет данных" />
            : segs.map((s) => (
              <BarRow key={s.segment} tint={segMeta(s.segment).bar} frac={s.revenue / maxSeg}
                label={<span className="inline-flex items-center gap-1.5"><span className={`h-2 w-2 rounded-full ${segMeta(s.segment).dot}`} />{s.segment}</span>}
                value={moneyK(s.revenue)} sub={`${nf0.format(s.accounts)} акк · ${pct(s.revenue_pct)}`} />
            ))}
        </Widget>
        <Widget title="Концентрация выручки (Pareto)">
          {eco.isLoading ? <Loading /> : pareto.length === 0 ? <Empty text="Нет данных" />
            : (
              <>
                {pareto.map((r) => (
                  <BarRow key={r.top_pct} label={`Топ-${r.top_pct}% аккаунтов`} value={pct(r.revenue_pct)}
                    frac={r.revenue_pct / 100} sub={`${nf0.format(r.accounts)} акк`} />
                ))}
                <div className="border-t border-border/40 pt-1.5 text-[11px] text-muted-foreground">
                  Чем круче кривая — тем сильнее выручка держится на «тяжёлых» аккаунтах.
                </div>
              </>
            )}
        </Widget>
      </div>
    </div>
  )
}

// ── Таб: Сегменты (RFM) ──
function RetailSegmentsTab({ companyId, dateFrom, dateTo }: TabProps) {
  const { data, isLoading } = useQuery({ queryKey: ['retail-seg', companyId, dateFrom, dateTo], queryFn: () => getRetailSegments({ companyId, dateFrom, dateTo }) })
  if (isLoading) return <Loading />
  if (!data || data.segments.length === 0) return <Empty text="Нет данных за период" />
  const segs = data.segments
  const totalAcc = data.totals.accounts || 1
  const maxRev = Math.max(1, ...segs.map((s) => s.revenue))
  return (
    <div className="space-y-3">
      <div className="text-xs text-muted-foreground">
        RFM: сегмент по давности последней сессии (R) и частоте (F); сумма (M) — для порядка. Всего аккаунтов: <b className="text-foreground">{nf0.format(totalAcc)}</b>.
      </div>
      <Card><CardContent className="p-0 overflow-x-auto">
        <table className="w-full text-xs">
          <thead><tr className="border-b bg-muted/40 text-muted-foreground">
            <th className="p-2 text-left font-medium">Сегмент</th>
            <th className="p-2 text-right font-medium">Аккаунтов</th>
            <th className="p-2 text-right font-medium">Доля базы</th>
            <th className="p-2 text-right font-medium">Сессий</th>
            <th className="p-2 text-right font-medium">Выручка</th>
            <th className="p-2 text-left font-medium w-[180px]">Доля выручки</th>
            <th className="p-2 text-right font-medium">Ср. чек</th>
          </tr></thead>
          <tbody>
            {segs.map((s: RetailSegment) => (
              <tr key={s.segment} className="border-b border-border/30 hover:bg-muted/30">
                <td className="p-2">
                  <span className="inline-flex items-center gap-2">
                    <span className={`h-2.5 w-2.5 rounded-full ${segMeta(s.segment).dot}`} />
                    <span className="font-medium">{s.segment}</span>
                    <span className="text-[10px] text-muted-foreground">{segMeta(s.segment).hint}</span>
                  </span>
                </td>
                <td className="p-2 text-right tabular-nums">{nf0.format(s.accounts)}</td>
                <td className="p-2 text-right tabular-nums text-muted-foreground">{pct(s.accounts / totalAcc * 100)}</td>
                <td className="p-2 text-right tabular-nums text-muted-foreground">{nf0.format(s.sessions)}</td>
                <td className="p-2 text-right tabular-nums font-medium">{moneyK(s.revenue)}</td>
                <td className="p-2">
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted"><div className={`h-full rounded-full ${segMeta(s.segment).bar}`} style={{ width: `${Math.max(2, s.revenue / maxRev * 100)}%` }} /></div>
                    <span className="w-10 text-right tabular-nums text-[11px] text-muted-foreground">{pct(s.revenue_pct)}</span>
                  </div>
                </td>
                <td className="p-2 text-right tabular-nums text-muted-foreground">{money(s.avg_check)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent></Card>
    </div>
  )
}

// ── Таб: Экономика (Pareto + распределение) ──
function RetailEconomicsTab({ companyId, dateFrom, dateTo }: TabProps) {
  const { data, isLoading } = useQuery({ queryKey: ['retail-eco', companyId, dateFrom, dateTo], queryFn: () => getRetailEconomics({ companyId, dateFrom, dateTo }) })
  if (isLoading) return <Loading />
  if (!data || data.totals.accounts === 0) return <Empty text="Нет данных за период" />
  const maxBucketRev = Math.max(1, ...data.session_buckets.map((b) => b.revenue))
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
        <Kpi label="Аккаунтов" value={nf0.format(data.totals.accounts)} />
        <Kpi label="Выручка" value={moneyK(data.totals.revenue)} />
        <Kpi label="ARPA" value={money(data.totals.arpa)} sub="доход на аккаунт" />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Widget title="Концентрация: топ-X% аккаунтов → % выручки">
          {data.pareto.map((r) => (
            <BarRow key={r.top_pct} label={`Топ-${r.top_pct}%`} value={pct(r.revenue_pct)} frac={r.revenue_pct / 100} sub={`${nf0.format(r.accounts)} акк`} />
          ))}
        </Widget>
        <Widget title="Распределение по числу сессий на аккаунт">
          {data.session_buckets.map((b) => (
            <BarRow key={b.bucket} label={`${b.bucket} сес.`} value={moneyK(b.revenue)} frac={b.revenue / maxBucketRev}
              sub={`${nf0.format(b.accounts)} акк (${pct(b.accounts_pct)}) · ${pct(b.revenue_pct)} выр.`} />
          ))}
        </Widget>
      </div>
    </div>
  )
}

// ── Таб: Гео (мобильность + регионы, нормализованный слой L2) ──
const isOrphan = (label: string) => label === 'без привязки' || label.startsWith('—')
function RetailGeoTab({ companyId, dateFrom, dateTo }: TabProps) {
  const { data, isLoading } = useQuery({ queryKey: ['retail-geo', companyId, dateFrom, dateTo], queryFn: () => getRetailGeo({ companyId, dateFrom, dateTo }) })
  if (isLoading) return <Loading />
  if (!data || data.totals.accounts === 0) return <Empty text="Нет данных за период" />
  const cov = data.coverage
  const maxMob = Math.max(1, ...data.mobility.map((m) => m.accounts))
  const maxReg = Math.max(1, ...data.regions.map((r) => r.revenue))
  const mono = data.mobility.find((m) => m.bucket === '1 объект')?.accounts ?? 0
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        <Kpi label="Аккаунтов" value={nf0.format(data.totals.accounts)} />
        <Kpi label="Объектов L2 на аккаунт" value={nf1.format(data.avg_stations)} sub="среди привязанных" />
        <Kpi label="Моно-объект" value={pct(mono / data.totals.accounts * 100)} sub="один объект L2" />
        <Kpi label="Привязано к L2" value={pct(cov.resolved_pct)} sub={`${nf0.format(cov.sessions_orphan)} сессий-сирот`} cls={cov.resolved_pct < 90 ? 'text-amber-400/90' : undefined} />
      </div>
      {cov.orphan_revenue_pct > 0.5 && (
        <div className="flex items-start gap-2 rounded-md border border-amber-400/40 bg-amber-400/5 px-3 py-2 text-xs text-amber-300/90">
          <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
          <span>
            <b>{pct(cov.orphan_revenue_pct)}</b> выручки ({moneyK(cov.revenue_orphan)}) — на сессиях <b>без привязки к объекту L2</b> (station_code не сматчен на <span className="whitespace-nowrap">service_locations</span>). Станции и регионы по ним не атрибутированы — это разрыв нормализации, а не поведение клиентов.
          </span>
        </div>
      )}
      <div className="grid gap-4 lg:grid-cols-2">
        <Widget title="Мобильность: сколько объектов L2 посещает аккаунт">
          {data.mobility.map((m) => (
            <BarRow key={m.bucket} label={<span className={isOrphan(m.bucket) ? 'text-amber-300/80' : undefined}>{m.bucket}</span>}
              tint={isOrphan(m.bucket) ? 'bg-amber-400/50' : undefined}
              value={`${nf0.format(m.accounts)} акк`} frac={m.accounts / maxMob} sub={`${pct(m.accounts_pct)} · ${moneyK(m.revenue)}`} />
          ))}
        </Widget>
        <Widget title="Топ-регионы розницы (канон L2) по выручке">
          {data.regions.length === 0 ? <Empty text="Нет данных" />
            : data.regions.slice(0, 12).map((r) => (
              <BarRow key={r.region} label={<span className={isOrphan(r.region) ? 'text-amber-300/80' : undefined}>{r.region}</span>}
                tint={isOrphan(r.region) ? 'bg-amber-400/50' : undefined}
                value={moneyK(r.revenue)} frac={r.revenue / maxReg} sub={`${nf0.format(r.accounts)} акк`} />
            ))}
        </Widget>
      </div>
    </div>
  )
}

// ── Таб: Когорты (retention-матрица) ──
function retColor(p: number): string {
  // Приглушённый emerald с прозрачностью ∝ удержанию (0..100%).
  const a = Math.max(0, Math.min(1, p / 100))
  return `rgba(52, 211, 153, ${(0.08 + a * 0.5).toFixed(3)})`
}
function RetailCohortsTab({ companyId }: TabProps) {
  const { data, isLoading } = useQuery({ queryKey: ['retail-coh', companyId], queryFn: () => getRetailCohorts({ companyId, months: 12 }) })
  if (isLoading) return <Loading />
  if (!data || data.cohorts.length === 0) return <Empty text="Недостаточно истории для когорт" />
  const cols = Array.from({ length: data.max_offset + 1 }, (_, i) => i)
  return (
    <div className="space-y-3">
      <div className="text-xs text-muted-foreground">
        Удержание по когортам месяца первой сессии (вся история). Ячейка M<sub>n</sub> — доля аккаунтов когорты, активных через n месяцев.
      </div>
      <Card><CardContent className="p-0 overflow-x-auto">
        <table className="text-xs">
          <thead><tr className="border-b bg-muted/40 text-muted-foreground">
            <th className="p-2 text-left font-medium sticky left-0 bg-muted/40">Когорта</th>
            <th className="p-2 text-right font-medium">Размер</th>
            {cols.map((c) => <th key={c} className="p-2 text-right font-medium w-14">M{c}</th>)}
          </tr></thead>
          <tbody>
            {data.cohorts.map((row) => {
              const byOff = new Map(row.retention.map((r) => [r.offset, r]))
              return (
                <tr key={row.cohort} className="border-b border-border/20">
                  <td className="p-2 text-left font-medium sticky left-0 bg-card">{row.cohort}</td>
                  <td className="p-2 text-right tabular-nums text-muted-foreground">{nf0.format(row.size)}</td>
                  {cols.map((c) => {
                    const r = byOff.get(c)
                    if (!r) return <td key={c} className="p-2" />
                    return (
                      <td key={c} className="p-2 text-right tabular-nums" style={{ backgroundColor: retColor(r.pct) }} title={`${nf0.format(r.count)} акк`}>
                        {nf0.format(r.pct)}%
                      </td>
                    )
                  })}
                </tr>
              )
            })}
          </tbody>
        </table>
      </CardContent></Card>
    </div>
  )
}

const RETAIL_TABS: { k: string; label: string }[] = [
  { k: 'overview', label: 'Обзор' },
  { k: 'segments', label: 'Сегменты (RFM)' },
  { k: 'economics', label: 'Экономика' },
  { k: 'cohorts', label: 'Когорты' },
  { k: 'geo', label: 'Гео' },
]

/** Контейнер пункта «Частные лица» с внутренними табами. */
export function RetailPanel({ companyId, dateFrom, dateTo }: TabProps) {
  const [t, patch] = useTabParams('retail', { sub: 'overview' })
  const p: TabProps = { companyId, dateFrom, dateTo }
  const tab = useMemo(() => t.sub, [t.sub])
  return (
    <div>
      <div className="flex items-center gap-3 border-b border-border px-4">
        <span className="inline-flex items-center gap-1 text-[11px] rounded-md border border-primary/40 px-2 py-0.5 text-primary/80 shrink-0 my-2" title="Телефоны маскированы, аккаунт = псевдоним">
          <ShieldCheck className="h-3 w-3" />ФЛ · псевдонимы
        </span>
        <div className="flex items-stretch gap-0.5 overflow-x-auto">
          {RETAIL_TABS.map((x) => {
            const on = tab === x.k
            return (
              <button key={x.k} type="button" onClick={() => patch({ sub: x.k })}
                className={`whitespace-nowrap border-b-2 -mb-px px-3 py-2.5 text-[13px] transition-colors ${on ? 'border-primary text-primary font-medium' : 'border-transparent text-muted-foreground hover:text-foreground hover:border-border'}`}>
                {x.label}
              </button>
            )
          })}
        </div>
      </div>
      <div className="p-4">
        {tab === 'overview' && <RetailOverviewTab {...p} />}
        {tab === 'segments' && <RetailSegmentsTab {...p} />}
        {tab === 'economics' && <RetailEconomicsTab {...p} />}
        {tab === 'cohorts' && <RetailCohortsTab {...p} />}
        {tab === 'geo' && <RetailGeoTab {...p} />}
      </div>
    </div>
  )
}
