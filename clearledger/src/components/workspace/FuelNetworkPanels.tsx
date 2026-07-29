/**
 * Сетевые экраны «Топлива»: оборудование, актив, клиенты, приезды.
 *
 * Обычные разрезы отвечают, СКОЛЬКО сеть продала. Эти четыре — где она не
 * работает и где на самом деле лежат деньги (перенос приёмов ЭЗС-контура:
 * port-efficiency, silent-stations, ABC-XYZ, когорты клиентов, визиты).
 *
 * Четыре панели в одном файле намеренно: у них общий скоуп, общая вёрстка
 * таблиц и одна судьба — их правят вместе, разносить по файлам значит четыре
 * раза повторить один и тот же каркас.
 */
import { useMemo, useRef, useState, type ReactNode } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { AlertTriangle, CircleCheckBig, Gauge, Info, Loader2, TrendingUp } from 'lucide-react'
import {
  Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { Card, CardContent } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useCompany } from '@/contexts/CompanyContext'
import { useFilters } from '@/contexts/FilterContext'
import { useWorkspace, type CoreMode } from '@/contexts/WorkspaceContext'
import { workspaceModeForKey } from '@/config/workspaceMenus'
import { useLocations } from '@/hooks/useLocations'
import { scopeStationCodes } from '@/services/locationService'
import { cn } from '@/lib/utils'
import { fmtLiters, fmtMoney, fmtMoneyShort } from '@/services/analyticsService'
import { ExportButton } from './analytics/ExportButton'
import {
  getFuelAbcXyz, getFuelClients, getFuelPumps, getFuelSilent, getFuelVisits,
  type AbcDimension, type PumpLevel,
} from '@/services/fuelNetworkService'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })
const nf2 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 })
const pct = (v: number | null | undefined) => (v == null ? '—' : `${nf1.format(v)} %`)

/**
 * Область работы экрана из общего фильтра: точки и регионы → коды станций STS,
 * плюс выбранные виды нефтепродуктов.
 *
 * Вид топлива приходит отсюда, а не из локального селектора экрана: он выбран в
 * шапке рабочей области и обязан действовать одинаково на загрузку ТРК, ABC-XYZ,
 * когорты и приезды — иначе четыре экрана про одну сеть ответят по-разному.
 */
function useFuelScope(): { stationCodes?: number[]; fuelCodes?: number[]; key: string } {
  const { stationCode, locationIds, regionIds, fuelCodes } = useFilters()
  const locations = useLocations()
  const scope = useMemo(
    () => scopeStationCodes(locations, locationIds, regionIds),
    [locations, locationIds, regionIds],
  )
  const one = stationCode && stationCode !== 'all' ? Number(stationCode) : NaN
  const codes = Number.isFinite(one)
    ? (scope.length === 0 || scope.includes(one) ? [one] : [-1])
    : (scope.length ? scope : undefined)
  const fuels = fuelCodes.map(Number).filter(Number.isFinite)
  return {
    stationCodes: codes,
    fuelCodes: fuels.length ? fuels : undefined,
    key: `${stationCode ?? ''}|${scope.join(',')}|${fuels.join(',')}`,
  }
}

function Loading() {
  return <div className="flex justify-center py-16"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
}
function Empty({ text = 'Нет данных за период' }: { text?: string }) {
  return <div className="p-8 text-center text-sm text-muted-foreground">{text}</div>
}

function Metric({ label, value, hint, tone }: {
  label: string; value: string; hint?: string; tone?: 'danger' | 'success' | 'info'
}) {
  return (
    <div className="min-w-0 border-r border-border/70 px-4 py-3 last:border-r-0">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={cn('mt-1 truncate text-lg font-semibold tabular-nums',
        tone === 'danger' && 'text-rose-400',
        tone === 'success' && 'text-emerald-400',
        tone === 'info' && 'text-blue-400')}>{value}</div>
      {hint ? <div className="mt-0.5 truncate text-[11px] text-muted-foreground">{hint}</div> : null}
    </div>
  )
}

function Head({ title, hint, children, exportEl }: {
  title: string; hint: string; children?: ReactNode
  exportEl?: () => HTMLElement | null
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 className="text-base font-semibold">{title}</h2>
        <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>
      </div>
      <div className="flex items-center gap-2">
        {children}
        {exportEl && <ExportButton title={title} getEl={exportEl} />}
      </div>
    </div>
  )
}

/** Сегмент-переключатель — тот же вид, что у «Реализации». */
function Toggle<T extends string>({ value, onChange, opts, title }: {
  value: T; onChange: (v: T) => void; opts: { v: T; label: string }[]; title?: string
}) {
  return (
    <div className="inline-flex w-fit rounded-md border border-border p-0.5 gap-0.5" title={title}>
      {opts.map((o) => (
        <button key={o.v} type="button" onClick={() => onChange(o.v)}
          className={`px-2.5 py-0.5 text-xs rounded-[5px] transition-colors ${
            value === o.v ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'}`}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

function Th({ children, right }: { children: ReactNode; right?: boolean }) {
  return <th className={cn('p-2.5 font-medium', right ? 'text-right' : 'text-left')}>{children}</th>
}
function Td({ children, right, className }: { children: ReactNode; right?: boolean; className?: string }) {
  return <td className={cn('p-2.5', right && 'text-right tabular-nums', className)}>{children}</td>
}

// ═══════════════════════════════════════════════════════════════════════
// 1. Оборудование: ТРК и пистолеты
// ═══════════════════════════════════════════════════════════════════════

/**
 * Загрузка оборудования. Ключевая колонка — не выручка, а наливов в сутки:
 * абсолютные цифры зависят от размера АЗС, и без нормировки крупная станция
 * всегда выглядит эффективнее маленькой.
 */
export function FuelPumpsPanel({ companyId, dateFrom, dateTo }: {
  companyId: string; dateFrom: string; dateTo: string
}) {
  const [level, setLevel] = useState<PumpLevel>('nozzle')
  const scope = useFuelScope()
  const ref = useRef<HTMLDivElement>(null)
  const q = useQuery({
    queryKey: ['fuel-pumps', companyId, dateFrom, dateTo, level, scope.key],
    queryFn: () => getFuelPumps({ companyId, dateFrom, dateTo, level, stationCodes: scope.stationCodes, fuelCodes: scope.fuelCodes }),
    placeholderData: keepPreviousData,
  })
  const silentQ = useQuery({
    queryKey: ['fuel-silent', companyId, dateFrom, dateTo],
    queryFn: () => getFuelSilent({ companyId, dateFrom, dateTo }),
    placeholderData: keepPreviousData,
  })

  if (q.isLoading) return <Loading />
  if (q.error) return <div className="p-6 text-sm text-destructive">Не удалось получить загрузку оборудования: {String(q.error)}</div>
  const data = q.data
  if (!data) return null
  const t = data.totals
  const active = data.lines.filter((l) => !l.silent)
  const chart = active.slice(0, 20).map((l) => ({
    name: `${l.station_code}·${l.pos}${l.nozzle != null ? `/${l.nozzle}` : ''}`,
    v: l.fills_per_day,
  }))

  return (
    <div ref={ref} className="space-y-4 p-4">
      <Head title="Загрузка ТРК и пистолетов"
        hint="Наливов в сутки на единицу оборудования · простой · молчащие рукава"
        exportEl={() => ref.current}>
        <Toggle value={level} onChange={setLevel} title="Уровень детализации"
          opts={[{ v: 'nozzle', label: 'Пистолеты' }, { v: 'pos', label: 'ТРК' }]} />
      </Head>

      <Card className="gap-0 py-0">
        <CardContent className="grid grid-cols-2 p-0 md:grid-cols-3 xl:grid-cols-6">
          <Metric label={level === 'nozzle' ? 'Пистолетов' : 'ТРК'} value={nf0.format(t.units)}
            hint={`${t.stations} АЗС · ${data.days} дней`} />
          <Metric label="Работали" value={nf0.format(t.active)} tone="success"
            hint={`${pct(t.units ? t.active / t.units * 100 : 0)} парка`} />
          <Metric label="Молчали" value={nf0.format(t.silent)} tone={t.silent ? 'danger' : undefined}
            hint="ни одного налива за период" />
          <Metric label="Медиана" value={`${nf2.format(t.median_fills_per_day)}/сут`}
            hint="наливов в сутки на единицу" />
          <Metric label="Максимум" value={`${nf2.format(t.top_fills_per_day)}/сут`} tone="info"
            hint={t.median_fills_per_day
              ? `разброс ${nf1.format(t.top_fills_per_day / t.median_fills_per_day)}×` : undefined} />
          <Metric label="Выручка" value={`${fmtMoneyShort(t.amount)} ₽`}
            hint={`${fmtLiters(t.liters)} · ${nf0.format(t.fills)} наливов`} />
        </CardContent>
      </Card>

      {chart.length > 0 && (
        <Card>
          <CardContent className="pt-4">
            <div className="mb-2 text-sm font-medium">Топ-20 по загрузке</div>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={chart} margin={{ top: 4, right: 8, bottom: 4, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" opacity={0.2} vertical={false} />
                <XAxis dataKey="name" tick={{ fontSize: 10 }} interval={0} angle={-45} textAnchor="end" height={54} />
                <YAxis tick={{ fontSize: 10 }} width={38} />
                <Tooltip formatter={(v) => [`${nf2.format(Number(v ?? 0))} наливов/сут`, '']}
                  contentStyle={{ fontSize: 12 }} />
                <Bar dataKey="v" radius={[3, 3, 0, 0]}>
                  {chart.map((_, i) => <Cell key={i} fill="hsl(217 91% 60%)" />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}

      <Tabs defaultValue="all">
        <TabsList variant="line" className="h-9">
          <TabsTrigger value="all"><Gauge className="mr-1.5 h-3.5 w-3.5" />Все единицы</TabsTrigger>
          <TabsTrigger value="silent">
            <AlertTriangle className="mr-1.5 h-3.5 w-3.5" />Молчащие
            {silentQ.data ? <span className="ml-1 text-muted-foreground">{silentQ.data.counts.nozzles}</span> : null}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="all" className="mt-3">
          <Card className="gap-0 overflow-hidden py-0"><CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[900px] text-xs">
                <thead>
                  <tr className="border-b bg-muted/35 text-muted-foreground">
                    <Th>АЗС</Th><Th>ТРК</Th>{level === 'nozzle' && <Th>Пистолет</Th>}<Th>Топливо</Th>
                    <Th right>Наливов/сут</Th><Th right>Наливы</Th><Th right>Литры</Th>
                    <Th right>Выручка</Th><Th right>Ср. налив</Th>
                    <Th right>Дней без работы</Th><Th right>Доля АЗС</Th>
                  </tr>
                </thead>
                <tbody>
                  {data.lines.map((l, i) => (
                    <tr key={`${l.station_code}-${l.pos}-${l.nozzle}-${i}`}
                      className={cn('border-b border-border/50 hover:bg-muted/25', l.silent && 'opacity-60')}>
                      <Td>{l.station}</Td>
                      <Td>{l.pos ?? '—'}</Td>
                      {level === 'nozzle' && <Td>{l.nozzle ?? '—'}</Td>}
                      <Td className="text-muted-foreground">{l.fuel_name ?? (l.fuels > 1 ? `${l.fuels} вида` : '—')}</Td>
                      <Td right className={l.silent ? 'text-rose-400' : 'font-medium'}>{nf2.format(l.fills_per_day)}</Td>
                      <Td right>{nf0.format(l.fills)}</Td>
                      <Td right>{fmtLiters(l.liters)}</Td>
                      <Td right>{fmtMoney(l.amount)}</Td>
                      <Td right>{nf1.format(l.avg_fill)} л</Td>
                      <Td right className={l.idle_days > data.days / 2 ? 'text-amber-400' : ''}>{l.idle_days}</Td>
                      <Td right className="text-muted-foreground">{pct(l.station_share_pct)}</Td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent></Card>
        </TabsContent>

        <TabsContent value="silent" className="mt-3">
          {silentQ.data && (silentQ.data.counts.stations + silentQ.data.counts.pumps + silentQ.data.counts.nozzles) === 0 ? (
            <Card><CardContent className="flex items-center gap-3 py-6 text-sm">
              <CircleCheckBig className="h-4 w-4 text-emerald-400" />
              Всё оборудование сети отпускало топливо в этом периоде.
            </CardContent></Card>
          ) : (
            <Card className="gap-0 overflow-hidden py-0"><CardContent className="p-0">
              <div className="overflow-x-auto">
                <table className="w-full min-w-[720px] text-xs">
                  <thead>
                    <tr className="border-b bg-muted/35 text-muted-foreground">
                      <Th>Уровень</Th><Th>АЗС</Th><Th>ТРК</Th><Th>Пистолет</Th>
                      <Th right>Последний налив</Th><Th right>Дней простоя</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {[
                      ...(silentQ.data?.stations ?? []).map((r) => ({ ...r, kind: 'Станция' })),
                      ...(silentQ.data?.pumps ?? []).map((r) => ({ ...r, kind: 'ТРК' })),
                      ...(silentQ.data?.nozzles ?? []).map((r) => ({ ...r, kind: 'Пистолет' })),
                    ].map((r, i) => (
                      <tr key={i} className="border-b border-border/50 hover:bg-muted/25">
                        <Td className="text-muted-foreground">{r.kind}</Td>
                        <Td>{r.station}</Td><Td>{r.pos ?? '—'}</Td><Td>{r.nozzle ?? '—'}</Td>
                        <Td right>{r.last_at ? r.last_at.slice(0, 10) : 'никогда'}</Td>
                        <Td right className="text-amber-400">{r.days_idle ?? '—'}</Td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent></Card>
          )}
        </TabsContent>
      </Tabs>

      <div className="rounded-lg border border-dashed px-4 py-3 text-xs text-muted-foreground">
        «Наливов в сутки» считается на все сутки периода, включая простой: делить на
        рабочие дни значило бы спрятать сам простой. Молчащие единицы — те, что
        отпускали топливо раньше, но за период не сделали ни одной операции.
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════
// 2. ABC-XYZ и концентрация
// ═══════════════════════════════════════════════════════════════════════

const ABC_TONE: Record<string, string> = {
  A: 'text-emerald-400', B: 'text-blue-400', C: 'text-muted-foreground',
}

export function FuelAbcXyzPanel({ companyId, dateFrom, dateTo }: {
  companyId: string; dateFrom: string; dateTo: string
}) {
  const [dim, setDim] = useState<AbcDimension>('station_fuel')
  const [bucket, setBucket] = useState<'week' | 'month'>('week')
  const scope = useFuelScope()
  const ref = useRef<HTMLDivElement>(null)
  const q = useQuery({
    queryKey: ['fuel-abcxyz', companyId, dateFrom, dateTo, dim, bucket, scope.key],
    queryFn: () => getFuelAbcXyz({ companyId, dateFrom, dateTo, dimension: dim, bucket, stationCodes: scope.stationCodes, fuelCodes: scope.fuelCodes }),
    placeholderData: keepPreviousData,
  })

  if (q.isLoading) return <Loading />
  const data = q.data
  if (!data) return <Empty />
  const cells = ['A', 'B', 'C'].flatMap((a) => ['X', 'Y', 'Z'].map((x) => {
    const m = data.matrix.find((c) => c.cell === a + x)
    return { cell: a + x, count: m?.count ?? 0, share: m?.share_pct ?? 0, hint: m?.hint ?? '' }
  }))

  return (
    <div ref={ref} className="space-y-4 p-4">
      <Head title="ABC-XYZ и концентрация"
        hint="ABC — вклад в выручку, XYZ — стабильность спроса по бакетам периода"
        exportEl={() => ref.current}>
        <Toggle value={dim} onChange={setDim} title="Единица классификации"
          opts={[{ v: 'station_fuel', label: 'АЗС × топливо' }, { v: 'station', label: 'АЗС' }, { v: 'fuel', label: 'Топливо' }]} />
        <Toggle value={bucket} onChange={setBucket} title="Шаг для расчёта стабильности"
          opts={[{ v: 'week', label: 'Недели' }, { v: 'month', label: 'Месяцы' }]} />
      </Head>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,320px)_1fr]">
        <Card><CardContent className="pt-4">
          <div className="mb-2 text-sm font-medium">Матрица 3 × 3</div>
          <div className="grid grid-cols-3 gap-1.5">
            {cells.map((c) => (
              <div key={c.cell} title={c.hint}
                className={cn('rounded-md border px-2 py-2 text-center',
                  c.count ? 'bg-muted/40' : 'opacity-40')}>
                <div className={cn('text-xs font-semibold', ABC_TONE[c.cell[0]])}>{c.cell}</div>
                <div className="text-base font-semibold tabular-nums">{c.count}</div>
                <div className="text-[10px] text-muted-foreground">{nf1.format(c.share)} %</div>
              </div>
            ))}
          </div>
          <div className="mt-3 text-[11px] text-muted-foreground">
            Строки — вклад (A → C), столбцы — стабильность (X → Z). Наведите на клетку,
            чтобы прочитать, что с ней делать. Бакетов в расчёте: {data.buckets}.
          </div>
        </CardContent></Card>

        <Card><CardContent className="pt-4">
          <div className="mb-2 text-sm font-medium">Концентрация: квинтили позиций</div>
          <div className="space-y-1.5">
            {data.quintiles.map((qq) => (
              <div key={qq.quintile} className="flex items-center gap-2 text-xs">
                <span className="w-16 shrink-0 text-muted-foreground">{qq.quintile}-я 20 %</span>
                <div className="h-4 flex-1 overflow-hidden rounded bg-muted/40">
                  <div className="h-full rounded bg-blue-500/70" style={{ width: `${Math.min(100, qq.share_pct)}%` }} />
                </div>
                <span className="w-16 shrink-0 text-right tabular-nums">{nf1.format(qq.share_pct)} %</span>
                <span className="w-20 shrink-0 text-right text-muted-foreground">{qq.count} поз.</span>
              </div>
            ))}
          </div>
          <div className="mt-3 text-[11px] text-muted-foreground">
            Средняя по сети смешивает полюса: решения принимаются по верхушке и по хвосту.
          </div>
        </CardContent></Card>
      </div>

      <Card className="gap-0 overflow-hidden py-0"><CardContent className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[860px] text-xs">
            <thead>
              <tr className="border-b bg-muted/35 text-muted-foreground">
                <Th>Позиция</Th><Th>Класс</Th><Th right>Выручка</Th><Th right>Доля</Th>
                <Th right>Накопл.</Th><Th right>Литры</Th><Th right>Наливы</Th>
                <Th right>Карт</Th><Th right>Разброс (CV)</Th><Th>Что делать</Th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((i) => (
                <tr key={i.key} className="border-b border-border/50 hover:bg-muted/25">
                  <Td>{i.label}</Td>
                  <Td><span className={cn('font-semibold', ABC_TONE[i.abc])}>{i.abc}</span>
                    <span className="text-muted-foreground">{i.xyz}</span></Td>
                  <Td right>{fmtMoney(i.amount)}</Td>
                  <Td right>{pct(i.share_pct)}</Td>
                  <Td right className="text-muted-foreground">{pct(i.cum_share_pct)}</Td>
                  <Td right>{fmtLiters(i.liters)}</Td>
                  <Td right>{nf0.format(i.fills)}</Td>
                  <Td right>{nf0.format(i.cards)}</Td>
                  <Td right className={cn(i.cv != null && i.cv > 0.5 && 'text-amber-400')}>
                    {i.cv != null ? nf2.format(i.cv) : '—'}
                  </Td>
                  <Td className="max-w-[280px] truncate text-muted-foreground" >{i.hint}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent></Card>

      <div className="rounded-lg border border-dashed px-4 py-3 text-xs text-muted-foreground">
        Стабильность считается только по полным бакетам периода: неполная неделя на краю
        даёт половину обычной выручки и добавила бы разброс из ниоткуда. Нули внутри
        периода учитываются честно — не продавали неделю, это и есть рваный спрос.
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════
// 3. Клиенты: когорты и движение базы
// ═══════════════════════════════════════════════════════════════════════

export function FuelClientsPanel({ companyId, dateFrom, dateTo }: {
  companyId: string; dateFrom: string; dateTo: string
}) {
  const scope = useFuelScope()
  const ref = useRef<HTMLDivElement>(null)
  const q = useQuery({
    queryKey: ['fuel-clients', companyId, dateFrom, dateTo, scope.key],
    queryFn: () => getFuelClients({ companyId, dateFrom, dateTo, stationCodes: scope.stationCodes, fuelCodes: scope.fuelCodes }),
    placeholderData: keepPreviousData,
  })

  if (q.isLoading) return <Loading />
  const data = q.data
  if (!data) return <Empty />
  const m = data.movement
  const c = data.concentration

  return (
    <div ref={ref} className="space-y-4 p-4">
      <Head title="Клиенты: когорты и удержание"
        hint="По картам за период · наличные без карты в клиентские метрики не входят"
        exportEl={() => ref.current} />

      <Card className="gap-0 py-0">
        <CardContent className="grid grid-cols-2 p-0 md:grid-cols-3 xl:grid-cols-6">
          <Metric label="Активных карт" value={nf0.format(m.active)}
            hint={`${fmtMoneyShort(data.totals.amount)} ₽ · ${nf0.format(data.totals.fills)} покупок`} />
          <Metric label="Новые" value={nf0.format(m.new)} tone="success"
            hint={`${fmtMoneyShort(m.new_amount)} ₽ · первая покупка в периоде`} />
          <Metric label="Вернулись" value={nf0.format(m.returning)}
            hint={`${fmtMoneyShort(m.returning_amount)} ₽`} />
          <Metric label="Не вернулись" value={nf0.format(m.churned)} tone={m.churned ? 'danger' : undefined}
            hint={`были в ${m.prev_period.from.slice(5)}–${m.prev_period.to.slice(5)}`} />
          <Metric label="Удержание" value={pct(m.retention_pct)}
            tone={(m.retention_pct ?? 100) < 60 ? 'danger' : 'success'}
            hint={`из ${nf0.format(m.prev_active)} прошлого периода`} />
          <Metric label="Топ-10 % карт" value={pct(c.top10_pct)} tone="info"
            hint={`${nf0.format(c.cards_top10)} карт · верхний 1 % → ${pct(c.top1_pct)}`} />
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="gap-0 overflow-hidden py-0"><CardContent className="p-0">
          <div className="border-b px-4 py-2.5 text-sm font-medium">Когорты по частоте покупок</div>
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b bg-muted/35 text-muted-foreground">
                <Th>Когорта</Th><Th right>Карт</Th><Th right>Доля карт</Th>
                <Th right>Выручка</Th><Th right>Доля выручки</Th><Th right>На карту</Th>
              </tr>
            </thead>
            <tbody>
              {data.cohorts.map((co) => (
                <tr key={co.code} className="border-b border-border/50 hover:bg-muted/25">
                  <Td>{co.label}</Td>
                  <Td right>{nf0.format(co.cards)}</Td>
                  <Td right className="text-muted-foreground">{pct(co.cards_pct)}</Td>
                  <Td right>{fmtMoney(co.amount)}</Td>
                  <Td right className="font-medium">{pct(co.amount_pct)}</Td>
                  <Td right>{fmtMoney(co.avg_card)}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent></Card>

        <Card className="gap-0 overflow-hidden py-0"><CardContent className="p-0">
          <div className="border-b px-4 py-2.5 text-sm font-medium">Что берут: виды топлива</div>
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b bg-muted/35 text-muted-foreground">
                <Th>Топливо</Th><Th right>Карт</Th><Th right>Покупок</Th>
                <Th right>Выручка</Th><Th right>Доля</Th><Th right>Ср. чек</Th>
              </tr>
            </thead>
            <tbody>
              {data.by_fuel.map((f) => (
                <tr key={f.fuel_name} className="border-b border-border/50 hover:bg-muted/25">
                  <Td>{f.fuel_name}</Td>
                  <Td right>{nf0.format(f.cards)}</Td>
                  <Td right>{nf0.format(f.fills)}</Td>
                  <Td right>{fmtMoney(f.amount)}</Td>
                  <Td right className="font-medium">{pct(f.amount_pct)}</Td>
                  <Td right>{fmtMoney(f.avg_check)}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent></Card>

        <Card className="gap-0 overflow-hidden py-0"><CardContent className="p-0">
          <div className="border-b px-4 py-2.5 text-sm font-medium">Топ карт по обороту</div>
          <div className="max-h-[420px] overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-card">
                <tr className="border-b bg-muted/35 text-muted-foreground">
                  <Th>Карта</Th><Th right>Покупок</Th><Th right>Выручка</Th>
                  <Th right>Ср. чек</Th><Th right>АЗС</Th><Th right>Последняя</Th>
                </tr>
              </thead>
              <tbody>
                {data.top_cards.map((k) => (
                  <tr key={k.card} className="border-b border-border/50 hover:bg-muted/25">
                    <Td className="font-mono text-[11px]">
                      {k.card}{k.is_new && <span className="ml-1.5 text-[10px] text-emerald-400">новая</span>}
                    </Td>
                    <Td right>{nf0.format(k.fills)}</Td>
                    <Td right>{fmtMoney(k.amount)}</Td>
                    <Td right>{fmtMoney(k.avg_check)}</Td>
                    <Td right>{k.stations}</Td>
                    <Td right className="text-muted-foreground">{k.last_at ? k.last_at.slice(0, 10) : '—'}</Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent></Card>
      </div>

      <div className="rounded-lg border border-dashed px-4 py-3 text-xs text-muted-foreground">
        «Новая» — карта, у которой ПЕРВАЯ в истории покупка попала в период; иначе
        новичком выглядел бы любой, кто просто не заезжал полгода. Границы когорт
        привязаны к длине периода, поэтому концентрация (верхние 10 % по обороту)
        показана отдельно — она от границ не зависит.
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════
// 4. Визиты (приезды)
// ═══════════════════════════════════════════════════════════════════════

export function FuelVisitsPanel({ companyId, dateFrom, dateTo }: {
  companyId: string; dateFrom: string; dateTo: string
}) {
  const [gap, setGap] = useState<'5' | '10' | '20'>('10')
  const scope = useFuelScope()
  const ref = useRef<HTMLDivElement>(null)
  const q = useQuery({
    queryKey: ['fuel-visits', companyId, dateFrom, dateTo, gap, scope.key],
    queryFn: () => getFuelVisits({ companyId, dateFrom, dateTo, gapMin: Number(gap), stationCodes: scope.stationCodes, fuelCodes: scope.fuelCodes }),
    placeholderData: keepPreviousData,
  })

  if (q.isLoading) return <Loading />
  const data = q.data
  if (!data) return <Empty />
  const t = data.totals
  const lift = t.avg_fill_check ? (t.avg_visit_check / t.avg_fill_check - 1) * 100 : 0

  return (
    <div ref={ref} className="space-y-4 p-4">
      <Head title="Приезды (визиты)"
        hint="Соседние наливы одной карты на одной АЗС — это один приезд, а не несколько покупок"
        exportEl={() => ref.current}>
        <Toggle value={gap} onChange={setGap} title="Порог склейки наливов в один приезд"
          opts={[{ v: '5', label: '5 мин' }, { v: '10', label: '10 мин' }, { v: '20', label: '20 мин' }]} />
      </Head>

      <Card className="gap-0 py-0">
        <CardContent className="grid grid-cols-2 p-0 md:grid-cols-3 xl:grid-cols-6">
          <Metric label="Приездов" value={nf0.format(t.visits)}
            hint={`из ${nf0.format(t.fills)} наливов`} />
          <Metric label="Наливов на приезд" value={nf2.format(t.fills_per_visit)}
            hint={`составных приездов ${pct(t.multi_pct)}`} />
          <Metric label="Чек приезда" value={fmtMoney(t.avg_visit_check)} tone="info"
            hint={`по наливам ${fmtMoney(t.avg_fill_check)}`} />
          <Metric label="Разница" value={`+${nf1.format(lift)} %`} tone="success"
            hint="насколько занижен чек по наливам" />
          <Metric label="Объём приезда" value={`${nf1.format(t.avg_visit_liters)} л`}
            hint={fmtLiters(t.liters)} />
          <Metric label="Разных видов в приезде" value={nf0.format(t.multi_fuel_visits)}
            hint={`${pct(t.multi_fuel_pct)} приездов · бак + канистра`} />
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="gap-0 overflow-hidden py-0"><CardContent className="p-0">
          <div className="border-b px-4 py-2.5 text-sm font-medium">Сколько наливов в приезде</div>
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b bg-muted/35 text-muted-foreground">
                <Th>Наливов</Th><Th right>Приездов</Th><Th right>Доля</Th><Th right>Выручка</Th>
              </tr>
            </thead>
            <tbody>
              {data.distribution.map((d) => (
                <tr key={d.fills} className="border-b border-border/50 hover:bg-muted/25">
                  <Td>{d.fills}</Td>
                  <Td right>{nf0.format(d.visits)}</Td>
                  <Td right className="text-muted-foreground">{pct(d.share_pct)}</Td>
                  <Td right>{fmtMoney(d.amount)}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent></Card>

        <Card className="gap-0 overflow-hidden py-0"><CardContent className="p-0">
          <div className="border-b px-4 py-2.5 text-sm font-medium">Чек приезда по видам топлива</div>
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b bg-muted/35 text-muted-foreground">
                <Th>Топливо</Th><Th right>Приездов</Th><Th right>Чек приезда</Th>
                <Th right>Литров за приезд</Th><Th right>Выручка</Th>
              </tr>
            </thead>
            <tbody>
              {data.by_fuel.map((f) => (
                <tr key={f.fuel_name} className="border-b border-border/50 hover:bg-muted/25">
                  <Td>{f.fuel_name}</Td>
                  <Td right>{nf0.format(f.visits)}</Td>
                  <Td right className="font-medium">{fmtMoney(f.avg_visit_check)}</Td>
                  <Td right>{nf1.format(f.avg_visit_liters)} л</Td>
                  <Td right>{fmtMoney(f.amount)}</Td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="border-t px-4 py-2 text-[11px] text-muted-foreground">
            Только приезды с одним видом топлива: смешанные ({pct(t.multi_fuel_pct)}) в разрез
            не входят — их чек принадлежит сразу двум продуктам.
          </div>
        </CardContent></Card>

        <Card className="gap-0 overflow-hidden py-0"><CardContent className="p-0">
          <div className="border-b px-4 py-2.5 text-sm font-medium">По станциям</div>
          <div className="max-h-[420px] overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-card">
                <tr className="border-b bg-muted/35 text-muted-foreground">
                  <Th>АЗС</Th><Th right>Приездов</Th><Th right>Составных</Th>
                  <Th right>Чек приезда</Th><Th right>Выручка</Th>
                </tr>
              </thead>
              <tbody>
                {data.by_station.map((s) => (
                  <tr key={s.station_code} className="border-b border-border/50 hover:bg-muted/25">
                    <Td>{s.station}</Td>
                    <Td right>{nf0.format(s.visits)}</Td>
                    <Td right className="text-muted-foreground">{pct(s.multi_pct)}</Td>
                    <Td right>{fmtMoney(s.avg_visit_check)}</Td>
                    <Td right>{fmtMoney(s.amount)}</Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent></Card>
      </div>

      <div className="rounded-lg border border-dashed px-4 py-3 text-xs text-muted-foreground">
        Склейка идёт по карте и станции: наличные без карты остаются отдельными наливами —
        связать их с одним автомобилем нечем. Порог по умолчанию 10 минут: дольше на
        колонке не стоят, это уже следующий заезд.
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════
// 5. Инсайты для шапки «Обзора»
// ═══════════════════════════════════════════════════════════════════════

const TONE_STYLE = {
  warning: { border: 'border-amber-500/35 bg-amber-500/5', icon: AlertTriangle, color: 'text-amber-400' },
  success: { border: 'border-emerald-500/30 bg-emerald-500/5', icon: TrendingUp, color: 'text-emerald-400' },
  info: { border: 'border-blue-500/30 bg-blue-500/5', icon: Info, color: 'text-blue-400' },
} as const

/**
 * Полоса выводов над обзором: не «сколько заработали» (это KPI ниже), а что в
 * данных видно и требует решения. Каждый вывод ведёт на экран, где эта цифра
 * разбирается подробно.
 */
export function FuelInsightsBar({ companyId, dateFrom, dateTo }: {
  companyId: string; dateFrom: string; dateTo: string
}) {
  const { company } = useCompany()
  const { setCoreMode } = useWorkspace()
  // Вывод ведёт на пункт в ЕГО разделе: «Загрузка ТРК» живёт в «Сети», «Приезды» —
  // в «Аналитике», и без смены раздела ссылка открыла бы пустой экран.
  const open = (sub: string) => {
    const mode = workspaceModeForKey(sub)
    if (mode) setCoreMode(mode as CoreMode, sub)
  }
  const q = useQuery({
    queryKey: ['fuel-insights', companyId, dateFrom, dateTo],
    queryFn: () => getFuelInsightsSafe({ companyId, dateFrom, dateTo }),
    enabled: company.profileId === 'fuel',
    staleTime: 5 * 60_000,
  })
  const items = q.data?.insights ?? []
  if (!items.length) return null
  return (
    <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
      {items.map((i) => {
        const s = TONE_STYLE[i.tone] ?? TONE_STYLE.info
        const Icon = s.icon
        const clickable = !!i.link?.sub
        return (
          <div key={i.key}
            onClick={clickable ? () => open(i.link!.sub!) : undefined}
            className={cn('flex items-start gap-2.5 rounded-lg border px-3 py-2.5', s.border,
              clickable && 'cursor-pointer transition-colors hover:bg-muted/30')}>
            <Icon className={cn('mt-0.5 h-4 w-4 shrink-0', s.color)} />
            <div className="min-w-0">
              <div className="text-sm font-medium">{i.title}</div>
              <div className="mt-0.5 text-xs text-muted-foreground">{i.text}</div>
            </div>
          </div>
        )
      })}
    </div>
  )
}

/** Инсайты не должны ронять обзор: пустой список честнее пустого экрана. */
async function getFuelInsightsSafe(p: { companyId: string; dateFrom: string; dateTo: string }) {
  const { getFuelInsights } = await import('@/services/fuelNetworkService')
  try {
    return await getFuelInsights(p)
  } catch {
    return { period: { from: p.dateFrom, to: p.dateTo }, insights: [] }
  }
}
