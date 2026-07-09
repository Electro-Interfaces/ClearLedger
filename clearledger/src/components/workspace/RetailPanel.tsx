/**
 * Пункт «Частные лица» — розничное направление ЭЗС (ФЛ). Аналитика в разрезе
 * аккаунтов частных лиц. Внутренние табы: Обзор · Сегменты (RFM) · Экономика ·
 * Когорты · Гео. Данные — /api/retail/*. Телефоны псевдонимизированы (хеш-ID +
 * маска), сырой номер в панель не приходит.
 */
import { useMemo, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Command, CommandInput, CommandList, CommandEmpty, CommandGroup, CommandItem } from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Loader2, ShieldCheck, AlertTriangle, ArrowUp, ArrowDown, ChevronsUpDown, Search, Check } from 'lucide-react'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { useTabParams } from '@/hooks/useTabParams'
import {
  getRetailOverview, getRetailSegments, getRetailEconomics, getRetailGeo, getRetailCohorts,
  getRetailAccounts, getRetailDimensions, getRetailProfile, getRetailAccount,
  type RetailSegment, type RetailAccount,
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
const SEGMENTS = ['Чемпионы', 'Лояльные', 'Под риском', 'Новички', 'Случайные', 'Разовые', 'Уснувшие', 'Отток']
const fmtDate = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString('ru-RU') : '—')
function SegBadge({ seg }: { seg: string }) {
  return <span className="inline-flex items-center gap-1.5 whitespace-nowrap"><span className={`h-2 w-2 rounded-full ${segMeta(seg).dot}`} />{seg}</span>
}

// ── Searchable combobox (поиск + фильтр по type-ahead) ──
interface Opt { value: string; label: string; keywords?: string }
function SearchableSelect({ value, onChange, options, placeholder, triggerWidth = 'w-[240px]' }: {
  value: string; onChange: (v: string) => void; options: Opt[]; placeholder: string; triggerWidth?: string
}) {
  const [open, setOpen] = useState(false)
  const cur = options.find((o) => o.value === value)
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button type="button" className={`inline-flex h-8 items-center justify-between gap-2 rounded-md border bg-background px-3 text-xs ${triggerWidth}`}>
          <span className="truncate">{cur ? cur.label : placeholder}</span>
          <ChevronsUpDown className="h-3.5 w-3.5 shrink-0 opacity-50" />
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-[340px] p-0" align="start">
        <Command>
          <CommandInput placeholder="Поиск…" className="text-xs" />
          <CommandList>
            <CommandEmpty>Ничего не найдено</CommandEmpty>
            <CommandGroup>
              {options.map((o) => (
                <CommandItem key={o.value} value={`${o.label} ${o.keywords ?? ''}`} className="text-xs"
                  onSelect={() => { onChange(o.value); setOpen(false) }}>
                  <Check className={`mr-2 h-3.5 w-3.5 ${value === o.value ? 'opacity-100' : 'opacity-0'}`} />
                  <span className="truncate">{o.label}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}

// ── Детальная карточка аккаунта (модалка) ──
function AccountDetailDialog({ companyId, dateFrom, dateTo, account, onClose }: TabProps & { account: string | null; onClose: () => void }) {
  const q = useQuery({
    enabled: !!account,
    queryKey: ['retail-acct-detail', companyId, dateFrom, dateTo, account],
    queryFn: () => getRetailAccount({ companyId, dateFrom, dateTo, account: account! }),
  })
  const d = q.data
  const maxStRev = Math.max(1, ...(d?.by_station ?? []).map((s) => s.revenue))
  const maxConn = Math.max(1, ...(d?.connectors ?? []).map((c) => c.sessions))
  const resTint = (r: string | null) => (r === 'Complete' ? 'text-emerald-400/80' : 'text-amber-400/80')
  return (
    <Dialog open={!!account} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-w-3xl max-h-[88vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-base">
            {d?.found && d.account ? <><span className="tabular-nums">{d.account.masked}</span><SegBadge seg={d.account.segment} /></> : 'Аккаунт'}
          </DialogTitle>
        </DialogHeader>
        {q.isLoading ? <Loading /> : !d || !d.found || !d.account ? <Empty text="Аккаунт не найден за период" /> : (
          <div className="space-y-4">
            <div className="grid grid-cols-3 gap-2 md:grid-cols-6">
              <Kpi label="Сессий" value={nf0.format(d.account.sessions)} />
              <Kpi label="Выручка" value={moneyK(d.account.revenue)} />
              <Kpi label="Ср. чек" value={money(d.account.avg_check)} />
              <Kpi label="Энергия" value={nf0.format(d.account.energy_kwh)} sub="кВтч" />
              <Kpi label="Станций" value={String(d.account.stations)} />
              <Kpi label="Успех" value={pct(d.account.success_pct)} />
            </div>
            <div className="text-[11px] text-muted-foreground">
              Первая {fmtDate(d.account.first_at)} · последняя {fmtDate(d.account.last_at)} · давность {d.account.recency_days ?? '—'} дн · ср. тариф {nf1.format(d.account.avg_tariff)} ₽/кВтч
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              <Widget title="Выручка по месяцам">
                <div data-chart><ResponsiveContainer width="100%" height={170}>
                  <BarChart data={(d.by_month ?? []).map((m) => ({ label: m.month.slice(5), revenue: m.revenue }))} margin={{ top: 6, right: 6, left: 4, bottom: 4 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="hsl(var(--border))" />
                    <XAxis dataKey="label" tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }} />
                    <YAxis tick={{ fontSize: 9, fill: 'hsl(var(--muted-foreground))' }} width={40} tickFormatter={(v) => moneyK(Number(v)).replace(' ₽', '')} />
                    <Tooltip cursor={{ fill: 'hsl(var(--muted) / 0.3)' }} formatter={(v) => [moneyK(Number(v)), 'Выручка']} />
                    <Bar dataKey="revenue" fill="hsl(217, 91%, 60%)" radius={[2, 2, 0, 0]} isAnimationActive={false} />
                  </BarChart>
                </ResponsiveContainer></div>
              </Widget>
              <Widget title="Когда заряжается — по часам">
                <div data-chart><ResponsiveContainer width="100%" height={170}>
                  <BarChart data={d.hourly ?? []} margin={{ top: 6, right: 6, left: 4, bottom: 4 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="hsl(var(--border))" />
                    <XAxis dataKey="hour" tick={{ fontSize: 9, fill: 'hsl(var(--muted-foreground))' }} interval={2} tickFormatter={(h) => String(h).padStart(2, '0')} />
                    <YAxis tick={{ fontSize: 9, fill: 'hsl(var(--muted-foreground))' }} width={28} />
                    <Tooltip cursor={{ fill: 'hsl(var(--muted) / 0.3)' }} labelFormatter={(h) => `${String(h).padStart(2, '0')}:00`} formatter={(v) => [`${nf0.format(Number(v))} сес`, 'Сессий']} />
                    <Bar dataKey="sessions" fill="hsl(152, 60%, 45%)" radius={[2, 2, 0, 0]} isAnimationActive={false} />
                  </BarChart>
                </ResponsiveContainer></div>
              </Widget>
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              <Widget title="Любимые станции">
                {(d.by_station ?? []).slice(0, 6).map((s) => (
                  <BarRow key={s.name + (s.number ?? '')} label={`${s.name}${s.number ? ` (${s.number})` : ''}`} value={moneyK(s.revenue)} frac={s.revenue / maxStRev} sub={`${nf0.format(s.sessions)} сес`} />
                ))}
              </Widget>
              <Widget title="Коннекторы">
                {(d.connectors ?? []).map((c) => (
                  <BarRow key={c.type} label={c.type} value={`${nf0.format(c.sessions)} сес`} frac={c.sessions / maxConn} />
                ))}
              </Widget>
            </div>
            <div className="space-y-1.5">
              <div className="text-[11px] uppercase tracking-wider text-muted-foreground">Последние сессии</div>
              <Card><CardContent className="p-0 overflow-x-auto">
                <table className="w-full text-xs">
                  <thead><tr className="border-b bg-muted/40 text-muted-foreground">
                    <th className="p-2 text-left font-medium">Дата</th><th className="p-2 text-left font-medium">Станция</th>
                    <th className="p-2 text-left font-medium">Коннектор</th><th className="p-2 text-right font-medium">кВтч</th>
                    <th className="p-2 text-right font-medium">Сумма</th><th className="p-2 text-left font-medium">Результат</th>
                  </tr></thead>
                  <tbody>
                    {(d.recent ?? []).map((s, i) => (
                      <tr key={i} className="border-b border-border/30">
                        <td className="p-2 tabular-nums text-muted-foreground">{s.started_at ? new Date(s.started_at).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—'}</td>
                        <td className="p-2 truncate max-w-[180px]">{s.station ?? '—'}</td>
                        <td className="p-2 text-muted-foreground">{s.connector ?? '—'}</td>
                        <td className="p-2 text-right tabular-nums">{nf1.format(s.energy_kwh)}</td>
                        <td className="p-2 text-right tabular-nums">{money(s.amount)}</td>
                        <td className={`p-2 ${resTint(s.result)}`}>{s.result ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </CardContent></Card>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

// ── Таб: Обзор ──
function RetailOverviewTab({ companyId, dateFrom, dateTo }: TabProps) {
  const p = { companyId, dateFrom, dateTo }
  const ov = useQuery({ queryKey: ['retail-ov', companyId, dateFrom, dateTo], queryFn: () => getRetailOverview(p) })
  const seg = useQuery({ queryKey: ['retail-seg', companyId, dateFrom, dateTo], queryFn: () => getRetailSegments(p) })
  const eco = useQuery({ queryKey: ['retail-eco', companyId, dateFrom, dateTo], queryFn: () => getRetailEconomics(p) })
  if (ov.isLoading) return <Loading />
  if (!ov.data) return <Empty text="Нет данных" />
  const t = ov.data.totals
  const segs = [...(seg.data?.segments ?? [])].sort((a, b) => b.revenue - a.revenue)  // бары по убыванию выручки
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
function RetailSegmentsTab({ companyId, dateFrom, dateTo, onDrill }: TabProps & { onDrill?: (seg: string) => void }) {
  const { data, isLoading } = useQuery({ queryKey: ['retail-seg', companyId, dateFrom, dateTo], queryFn: () => getRetailSegments({ companyId, dateFrom, dateTo }) })
  if (isLoading) return <Loading />
  if (!data || data.segments.length === 0) return <Empty text="Нет данных за период" />
  const segs = data.segments
  const totalAcc = data.totals.accounts || 1
  const maxRev = Math.max(1, ...segs.map((s) => s.revenue))
  return (
    <div className="space-y-3">
      <div className="text-xs text-muted-foreground">
        RFM: сегмент по давности последней сессии (R) и частоте (F); сумма (M) — для порядка. Всего аккаунтов: <b className="text-foreground">{nf0.format(totalAcc)}</b>. Клик по строке — <span className="text-primary/80">отбор аккаунтов сегмента</span> во вкладке «Аккаунты».
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
              <tr key={s.segment} onClick={() => onDrill?.(s.segment)} title={`Отобрать аккаунты: ${s.segment}`}
                className="group cursor-pointer border-b border-border/30 hover:bg-muted/30">
                <td className="p-2">
                  <span className="inline-flex items-center gap-2">
                    <span className={`h-2.5 w-2.5 rounded-full ${segMeta(s.segment).dot}`} />
                    <span className="font-medium">{s.segment}</span>
                    <span className="text-[10px] text-muted-foreground">{segMeta(s.segment).hint}</span>
                    <span className="text-[10px] text-primary/70 opacity-0 transition-opacity group-hover:opacity-100">отбор →</span>
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

// ── Таб: Аккаунты (реестр с фильтрами/отборами/сортировкой) ──
const ACC_COLS = [
  { key: 'sessions', label: 'Сессий' },
  { key: 'energy_kwh', label: 'кВтч' },
  { key: 'revenue', label: 'Выручка' },
  { key: 'avg_check', label: 'Ср. чек' },
  { key: 'stations', label: 'Станций' },
  { key: 'last_at', label: 'Последняя' },
]
function RetailAccountsTab({ companyId, dateFrom, dateTo, initialSegment }: TabProps & { initialSegment?: string | null }) {
  const [segment, setSegment] = useState(initialSegment || 'all')
  const [region, setRegion] = useState('all')
  const [station, setStation] = useState('all')
  const [minSessions, setMinSessions] = useState('')
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState<{ key: string; order: 'asc' | 'desc' }>({ key: 'revenue', order: 'desc' })
  const [detail, setDetail] = useState<string | null>(null)
  const p = { companyId, dateFrom, dateTo }
  const dims = useQuery({ queryKey: ['retail-dims', companyId, dateFrom, dateTo], queryFn: () => getRetailDimensions(p) })
  const regionOpts: Opt[] = useMemo(() => [{ value: 'all', label: 'Все регионы' },
    ...(dims.data?.regions ?? []).map((r) => ({ value: r.region, label: `${r.region} · ${r.accounts}` }))], [dims.data])
  const stationOpts: Opt[] = useMemo(() => [{ value: 'all', label: 'Все станции' },
    ...(dims.data?.stations ?? []).map((s) => ({ value: s.location_id, label: `${s.name}${s.number ? ` (${s.number})` : ''} · ${s.accounts}`, keywords: `${s.region ?? ''} ${s.number ?? ''}` }))], [dims.data])
  const q = useQuery({
    queryKey: ['retail-accts', companyId, dateFrom, dateTo, segment, region, station, minSessions, search, sort],
    queryFn: () => getRetailAccounts({
      ...p,
      segment: segment === 'all' ? undefined : segment,
      region: region === 'all' ? undefined : region,
      station: station === 'all' ? undefined : station,
      minSessions: minSessions ? Number(minSessions) : undefined,
      search: search || undefined, sort: sort.key, order: sort.order, limit: 200,
    }),
  })
  const toggle = (k: string) => setSort((s) => (s.key === k ? { key: k, order: s.order === 'desc' ? 'asc' : 'desc' } : { key: k, order: 'desc' }))
  const H = ({ c }: { c: { key: string; label: string } }) => {
    const on = sort.key === c.key
    const Ico = on ? (sort.order === 'asc' ? ArrowUp : ArrowDown) : ChevronsUpDown
    return (
      <th className="p-2 text-right font-medium">
        <button onClick={() => toggle(c.key)} title="Сортировать"
          className={`group inline-flex flex-row-reverse items-center gap-1 cursor-pointer hover:text-foreground ${on ? 'text-foreground' : ''}`}>
          <span className="whitespace-nowrap">{c.label}</span>
          <Ico className={`h-3 w-3 shrink-0 ${on ? 'text-primary' : 'opacity-30 group-hover:opacity-70'}`} />
        </button>
      </th>
    )
  }
  const rows = q.data?.accounts ?? []
  const t = q.data?.totals
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Select value={segment} onValueChange={setSegment}>
          <SelectTrigger className="h-8 w-[150px] text-xs"><SelectValue placeholder="Сегмент" /></SelectTrigger>
          <SelectContent><SelectItem value="all" className="text-xs">Все сегменты</SelectItem>{SEGMENTS.map((s) => <SelectItem key={s} value={s} className="text-xs">{s}</SelectItem>)}</SelectContent>
        </Select>
        <SearchableSelect value={region} onChange={setRegion} options={regionOpts} placeholder="Регион" triggerWidth="w-[200px]" />
        <SearchableSelect value={station} onChange={setStation} options={stationOpts} placeholder="Станция" triggerWidth="w-[220px]" />
        <input value={minSessions} onChange={(e) => setMinSessions(e.target.value.replace(/\D/g, ''))} placeholder="мин. сессий"
          className="h-8 w-[110px] rounded-md border bg-background px-2 text-xs" inputMode="numeric" />
        <div className="relative">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="поиск по номеру"
            className="h-8 w-[170px] rounded-md border bg-background pl-7 pr-2 text-xs" />
        </div>
      </div>
      {t && (
        <div className="text-xs text-muted-foreground">
          Найдено <b className="text-foreground">{nf0.format(t.accounts)}</b> аккаунтов · выручка {moneyK(t.revenue)} · ср. чек {money(t.avg_check)} · ARPA {money(t.arpa)}
          {q.data && q.data.total > q.data.returned ? ` · показаны первые ${q.data.returned}` : ''}
        </div>
      )}
      {q.isLoading ? <Loading /> : rows.length === 0 ? <Empty text="Нет аккаунтов под фильтр" /> : (
        <Card><CardContent className="p-0 overflow-x-auto">
          <table className="w-full text-xs">
            <thead><tr className="border-b bg-muted/40 text-muted-foreground">
              <th className="p-2 text-left font-medium">Аккаунт</th>
              <th className="p-2 text-left font-medium">Сегмент</th>
              {ACC_COLS.map((c) => <H key={c.key} c={c} />)}
            </tr></thead>
            <tbody>
              {rows.map((a: RetailAccount) => (
                <tr key={a.account} onClick={() => setDetail(a.account)} title="Открыть карточку аккаунта"
                  className="cursor-pointer border-b border-border/30 hover:bg-muted/30">
                  <td className="p-2 font-medium tabular-nums">{a.masked}</td>
                  <td className="p-2"><SegBadge seg={a.segment} /></td>
                  <td className="p-2 text-right tabular-nums">{nf0.format(a.sessions)}</td>
                  <td className="p-2 text-right tabular-nums text-muted-foreground">{nf0.format(a.energy_kwh)}</td>
                  <td className="p-2 text-right tabular-nums font-medium">{moneyK(a.revenue)}</td>
                  <td className="p-2 text-right tabular-nums text-muted-foreground">{money(a.avg_check)}</td>
                  <td className="p-2 text-right tabular-nums text-muted-foreground">{a.stations}</td>
                  <td className="p-2 text-right tabular-nums text-muted-foreground">{fmtDate(a.last_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent></Card>
      )}
      <AccountDetailDialog {...p} account={detail} onClose={() => setDetail(null)} />
    </div>
  )
}

// ── Таб: Станция/регион (профиль: клиенты + когда заряжаются) ──
function ChartBox({ data, xKey, color, tip }: { data: { sessions: number }[]; xKey: string; color: string; tip: (v: number) => [string, string] }) {
  return (
    <div data-chart>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data} margin={{ top: 8, right: 8, left: 4, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="hsl(var(--border))" />
          <XAxis dataKey={xKey} tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }} interval={xKey === 'hour' ? 1 : 0}
            tickFormatter={(v) => (xKey === 'hour' ? String(v).padStart(2, '0') : String(v))} />
          <YAxis tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }} width={34} />
          <Tooltip cursor={{ fill: 'hsl(var(--muted) / 0.3)' }}
            labelFormatter={(v) => (xKey === 'hour' ? `${String(v).padStart(2, '0')}:00` : String(v))}
            formatter={(v) => tip(Number(v))} />
          <Bar dataKey="sessions" fill={color} radius={[2, 2, 0, 0]} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
function RetailProfileTab({ companyId, dateFrom, dateTo }: TabProps) {
  const [mode, setMode] = useState<'station' | 'region'>('station')
  const [value, setValue] = useState('')
  const [detail, setDetail] = useState<string | null>(null)
  const p = { companyId, dateFrom, dateTo }
  const dims = useQuery({ queryKey: ['retail-dims', companyId, dateFrom, dateTo], queryFn: () => getRetailDimensions(p) })
  const stationOpts: Opt[] = useMemo(() => (dims.data?.stations ?? []).map((s) => ({
    value: s.location_id, label: `${s.name}${s.number ? ` (${s.number})` : ''} · ${s.accounts} акк`, keywords: `${s.region ?? ''} ${s.number ?? ''}` })), [dims.data])
  const regionOpts: Opt[] = useMemo(() => (dims.data?.regions ?? []).map((r) => ({
    value: r.region, label: `${r.region} · ${r.accounts} акк` })), [dims.data])
  const q = useQuery({
    enabled: !!value,
    queryKey: ['retail-profile', companyId, dateFrom, dateTo, mode, value],
    queryFn: () => getRetailProfile({ ...p, station: mode === 'station' ? value : undefined, region: mode === 'region' ? value : undefined }),
  })
  const d = q.data
  const tip = (v: number): [string, string] => [`${nf0.format(v)} сес`, 'Сессий']
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="inline-flex rounded-md border p-0.5">
          {(['station', 'region'] as const).map((m) => (
            <button key={m} onClick={() => { setMode(m); setValue('') }}
              className={`rounded px-3 py-1 text-xs transition-colors ${mode === m ? 'bg-primary/15 text-primary font-medium' : 'text-muted-foreground hover:text-foreground'}`}>
              {m === 'station' ? 'Станция' : 'Регион'}
            </button>
          ))}
        </div>
        <SearchableSelect value={value} onChange={setValue}
          options={mode === 'station' ? stationOpts : regionOpts}
          placeholder={mode === 'station' ? 'Выберите станцию…' : 'Выберите регион…'} triggerWidth="w-[320px]" />
      </div>
      {!value ? <Empty text="Выберите станцию или регион — увидите клиентов и профиль зарядок (часы, дни, средние)" />
        : q.isLoading ? <Loading />
          : !d || d.totals.sessions === 0 ? <Empty text="Нет сессий за период" />
            : (
              <>
                <div className="grid grid-cols-2 gap-2 md:grid-cols-3 lg:grid-cols-6">
                  <Kpi label="Аккаунтов" value={nf0.format(d.totals.accounts)} />
                  <Kpi label="Сессий" value={nf0.format(d.totals.sessions)} />
                  <Kpi label="Выручка" value={moneyK(d.totals.revenue)} />
                  <Kpi label="Ср. чек" value={money(d.totals.avg_check)} />
                  <Kpi label="Ср. кВтч/сес" value={nf1.format(d.totals.avg_kwh)} />
                  <Kpi label="Энергия" value={`${nf0.format(d.totals.energy_kwh)}`} sub="кВтч" />
                </div>
                <div className="grid gap-4 lg:grid-cols-2">
                  <Widget title="Когда заряжаются — по часам суток"><ChartBox data={d.hourly} xKey="hour" color="hsl(217, 91%, 60%)" tip={tip} /></Widget>
                  <Widget title="По дням недели"><ChartBox data={d.weekday} xKey="label" color="hsl(152, 60%, 45%)" tip={tip} /></Widget>
                </div>
                <div className="space-y-1.5">
                  <div className="text-[11px] uppercase tracking-wider text-muted-foreground">Топ клиентов · {d.scope.label}</div>
                  <Card><CardContent className="p-0 overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead><tr className="border-b bg-muted/40 text-muted-foreground">
                        <th className="p-2 text-left font-medium">Аккаунт</th><th className="p-2 text-left font-medium">Сегмент</th>
                        <th className="p-2 text-right font-medium">Сессий</th><th className="p-2 text-right font-medium">Выручка</th>
                        <th className="p-2 text-right font-medium">Ср. чек</th><th className="p-2 text-right font-medium">Последняя</th>
                      </tr></thead>
                      <tbody>
                        {d.top_accounts.map((a: RetailAccount) => (
                          <tr key={a.account} onClick={() => setDetail(a.account)} title="Открыть карточку аккаунта"
                            className="cursor-pointer border-b border-border/30 hover:bg-muted/30">
                            <td className="p-2 font-medium tabular-nums">{a.masked}</td>
                            <td className="p-2"><SegBadge seg={a.segment} /></td>
                            <td className="p-2 text-right tabular-nums">{nf0.format(a.sessions)}</td>
                            <td className="p-2 text-right tabular-nums font-medium">{moneyK(a.revenue)}</td>
                            <td className="p-2 text-right tabular-nums text-muted-foreground">{money(a.avg_check)}</td>
                            <td className="p-2 text-right tabular-nums text-muted-foreground">{fmtDate(a.last_at)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </CardContent></Card>
                </div>
              </>
            )}
      <AccountDetailDialog {...p} account={detail} onClose={() => setDetail(null)} />
    </div>
  )
}

const RETAIL_TABS: { k: string; label: string }[] = [
  { k: 'overview', label: 'Обзор' },
  { k: 'segments', label: 'Сегменты (RFM)' },
  { k: 'accounts', label: 'Аккаунты' },
  { k: 'profile', label: 'Станция/регион' },
  { k: 'economics', label: 'Экономика' },
  { k: 'cohorts', label: 'Когорты' },
  { k: 'geo', label: 'Гео' },
]

/** Контейнер пункта «Частные лица» с внутренними табами. */
export function RetailPanel({ companyId, dateFrom, dateTo }: TabProps) {
  const [t, patch] = useTabParams('retail', { sub: 'overview' })
  const [drillSeg, setDrillSeg] = useState<string | null>(null)
  const p: TabProps = { companyId, dateFrom, dateTo }
  const tab = useMemo(() => t.sub, [t.sub])
  const drill = (seg: string) => { setDrillSeg(seg); patch({ sub: 'accounts' }) }
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
        {tab === 'segments' && <RetailSegmentsTab {...p} onDrill={drill} />}
        {tab === 'accounts' && <RetailAccountsTab {...p} initialSegment={drillSeg} />}
        {tab === 'profile' && <RetailProfileTab {...p} />}
        {tab === 'economics' && <RetailEconomicsTab {...p} />}
        {tab === 'cohorts' && <RetailCohortsTab {...p} />}
        {tab === 'geo' && <RetailGeoTab {...p} />}
      </div>
    </div>
  )
}
