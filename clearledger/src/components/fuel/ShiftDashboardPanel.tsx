/**
 * Дашборд бухгалтера по сменным отчётам — компактные таблицы-сводки (не россыпь карточек).
 * KPI-строка · реализация по топливу · выручка по оплате (раскрытие по топливу) ·
 * поступления ТТН · касса (движение + инкассация) · графики.
 * Данные — GET /api/fuel/shift-dashboard.
 */
import { useMemo, useState, Fragment } from 'react'
import { useQuery } from '@tanstack/react-query'
import { format } from 'date-fns'
import {
  Fuel, Banknote, CreditCard, Smartphone, Building2, Ticket, Truck,
  ChevronRight, Wallet, TrendingUp, TrendingDown, Minus,
  ClipboardCheck, AlertTriangle, Upload, CheckCircle2, Pencil,
} from 'lucide-react'
import {
  BarChart, Bar, PieChart, Pie, Cell, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer,
} from 'recharts'

import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { getFuelColor } from '@/utils/fuelColors'
import { getShiftDashboard, getFuelReadiness, type ShiftDashboardData } from '@/services/fuel/fuelMappingService'
import { useCompany } from '@/contexts/CompanyContext'
import { useFilters } from '@/contexts/FilterContext'
import { useLocations } from '@/hooks/useLocations'
import { useFuelKindFilter } from '@/hooks/useFuelKindFilter'
import { scopeStationCodes } from '@/services/locationService'
import { rechartsTooltipTheme } from '@/components/ui/chart-utils'

const rub = (v: number) => (v ?? 0).toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const rub0 = (v: number) => (v ?? 0).toLocaleString('ru-RU', { maximumFractionDigits: 0 })
const vol = (v: number) => (v ?? 0).toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const vol0 = (v: number) => (v ?? 0).toLocaleString('ru-RU', { maximumFractionDigits: 0 })
const fc = (name: string) => getFuelColor(name).hex

// Способы оплаты: порядок, иконка, цвет, только-объём (безнал без выручки в кассе)
const PAY_META: Record<string, { label: string; icon: typeof Banknote; color: string; volumeOnly: boolean }> = {
  cash: { label: 'Наличные', icon: Banknote, color: 'text-emerald-500', volumeOnly: false },
  card: { label: 'Банковские карты', icon: CreditCard, color: 'text-blue-500', volumeOnly: false },
  online: { label: 'Онлайн заказы', icon: Smartphone, color: 'text-purple-500', volumeOnly: true },
  corporate: { label: 'Корп. карты', icon: Building2, color: 'text-orange-500', volumeOnly: true },
  coupon: { label: 'Купоны на сдачу', icon: Ticket, color: 'text-amber-500', volumeOnly: true },
  voucher: { label: 'Талоны', icon: Ticket, color: 'text-amber-600', volumeOnly: true },
  fuel_card: { label: 'Топливные карты', icon: CreditCard, color: 'text-amber-500', volumeOnly: true },
  writeoff: { label: 'Тех. отпуск (прокачка, мерник)', icon: Fuel, color: 'text-muted-foreground', volumeOnly: true },
}
const PAY_ORDER = ['cash', 'card', 'fuel_card', 'corporate', 'online', 'coupon', 'voucher', 'writeoff']

const H3 = 'text-xs font-semibold uppercase tracking-wide text-muted-foreground'
const TH = 'py-1.5 text-[11px] font-medium text-muted-foreground'
const TD = 'py-1.5 tabular-nums'

export function ShiftDashboardPanel() {
  const { companyId } = useCompany()
  const [compare, setCompare] = useState(false)
  /**
   * Контур — только из верхнего фильтра (CLAUDE.md, «Взаимодействие верхнего
   * фильтра и параметров таба», правила 1 и 3). Свои пресеты периода панель
   * держать не имеет права: шапка заявляла «1 июл — 31 июл», а дашборд считал
   * последние 30 дней от сегодня — и вдобавок по всей сети при выбранной
   * одной АЗС. Тот же дефект уже был закрыт в FuelOverviewPanel.
   */
  const { period } = useFilters()
  const { from, to } = period
  const locations = useLocations()
  const { locationIds, regionIds } = useFilters()
  const scopeCodes = useMemo(
    () => scopeStationCodes(locations, locationIds, regionIds),
    [locations, locationIds, regionIds],
  )
  const scopeKey = scopeCodes.join(',')
  const fk = useFuelKindFilter()
  const days = Math.round((new Date(to).getTime() - new Date(from).getTime()) / 86400000) + 1

  const { data, isLoading } = useQuery({
    queryKey: ['shift-dashboard', companyId, from, to, scopeKey, fk.key, compare],
    queryFn: () => getShiftDashboard(from, to, {
      compare,
      stations: scopeCodes.length ? scopeCodes.map(String) : undefined,
      fuelCodes: fk.fuelCodes,
    }),
  })

  return (
    <div className="space-y-5 p-4">
      {/* Период — отражение контура, не собственный выбор панели */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="rounded-lg border border-border bg-card px-3 py-1.5 text-xs">
          <span className="text-muted-foreground">Период:</span>{' '}
          {format(new Date(from), 'dd.MM.yyyy')} — {format(new Date(to), 'dd.MM.yyyy')}
          <span className="ml-2 text-muted-foreground">Дней: {days}</span>
          <span className="ml-2 text-muted-foreground">
            {scopeCodes.length ? `АЗС: ${scopeCodes.join(', ')}` : 'Вся сеть'}
          </span>
        </div>
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <input type="checkbox" checked={compare} onChange={(e) => setCompare(e.target.checked)} />
          Сравнить с пред. периодом
        </label>
      </div>

      {isLoading || !data ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Загрузка данных дашборда…</p>
      ) : (
        <>
          <KpiRow data={data} />
          <ReadinessBlock from={from} to={to} stations={scopeCodes} />
          <div className="grid gap-4 lg:grid-cols-2">
            <FuelTable data={data} />
            <PaymentTable data={data} />
          </div>
          <ReceiptsTable data={data} />
          <CashRow data={data} />
          <ChartsBlock data={data} />
        </>
      )}
    </div>
  )
}

/* ── KPI-строка ── */
function KpiRow({ data }: { data: ShiftDashboardData }) {
  const rev = data.financial.total_revenue
  const v = data.volume.total
  const avg = v > 0 ? rev / v : 0
  const t = data.trends
  const items = [
    { label: 'Выручка', value: `${rub0(rev)} ₽`, accent: 'text-foreground', trend: t?.revenue },
    { label: 'Объём реализации', value: `${vol0(v)} л`, accent: 'text-primary', trend: t?.volume },
    { label: 'Средняя цена', value: `${avg.toFixed(2)} ₽/л`, accent: 'text-foreground', trend: undefined },
    { label: 'Смен', value: String(data.operational.shifts_count), accent: 'text-foreground', trend: t?.shifts },
    { label: 'Поступило (факт)', value: `${vol0(data.receipts.total_fact)} л`, accent: 'text-emerald-600 dark:text-emerald-400', trend: undefined },
  ]
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
      {items.map((k) => (
        <div key={k.label} className="rounded-xl border border-border bg-card p-3">
          <div className="flex items-center gap-1 text-[11px] text-muted-foreground">{k.label}{k.trend && <TrendMini t={k.trend} />}</div>
          <div className={cn('mt-1 text-lg font-bold tabular-nums', k.accent)}>{k.value}</div>
        </div>
      ))}
    </div>
  )
}
function TrendMini({ t }: { t: { percent: number; direction: string } }) {
  const Icon = t.direction === 'up' ? TrendingUp : t.direction === 'down' ? TrendingDown : Minus
  const c = t.direction === 'up' ? 'text-emerald-500' : t.direction === 'down' ? 'text-red-500' : 'text-muted-foreground'
  return <span className={cn('ml-auto flex items-center gap-0.5 text-[10px]', c)}><Icon className="h-3 w-3" />{t.percent > 0 ? '+' : ''}{t.percent}%</span>
}

function ReadinessStat({ label, value, cls, icon: Icon }: {
  label: string; value: number; cls?: string; icon?: typeof AlertTriangle
}) {
  return (
    <div className="flex items-center justify-between text-xs">
      <span className="flex items-center gap-1 text-muted-foreground">{Icon && <Icon className={cn('h-3 w-3', cls)} />}{label}</span>
      <span className={cn('font-semibold tabular-nums', cls)}>{value}</span>
    </div>
  )
}

/* ── Готовность к 1С ── */
function ReadinessBlock({ from, to, stations }: { from: string; to: string; stations: number[] }) {
  const { companyId } = useCompany()
  const { data: r } = useQuery({
    queryKey: ['fuel-readiness', companyId, from, to, stations.join(',')],
    queryFn: () => getFuelReadiness(from, to, {
      stations: stations.length ? stations.map(String) : undefined,
    }),
  })
  if (!r) return null
  const rc = r.receipts
  const pk = r.packets
  return (
    <Card>
      <CardContent className="pt-4">
        <div className="mb-3 flex items-center gap-2"><ClipboardCheck className="h-4 w-4 text-primary" /><h3 className={H3}>Готовность к 1С</h3></div>
        <div className="grid gap-3 md:grid-cols-3">
          <div className="space-y-1.5 rounded-lg border border-border bg-background p-3">
            <div className="flex items-center gap-1.5 text-sm font-medium"><Fuel className="h-3.5 w-3.5 text-blue-500" />Смены</div>
            <ReadinessStat label="Всего" value={r.shifts.total} />
            <ReadinessStat label="С корректировкой" value={r.shifts.corrected} cls={r.shifts.corrected > 0 ? 'text-amber-600 dark:text-amber-400' : ''} icon={r.shifts.corrected > 0 ? Pencil : undefined} />
          </div>
          <div className="space-y-1.5 rounded-lg border border-border bg-background p-3">
            <div className="flex items-center gap-1.5 text-sm font-medium"><Truck className="h-3.5 w-3.5 text-emerald-500" />Приёмка ТТН</div>
            <ReadinessStat label="Всего" value={rc.total} />
            <ReadinessStat label="Не проверено" value={rc.pending} cls={rc.pending > 0 ? 'text-amber-600 dark:text-amber-400' : ''} icon={rc.pending > 0 ? AlertTriangle : undefined} />
            <ReadinessStat label="Принято" value={rc.confirmed} cls={rc.confirmed > 0 ? 'text-emerald-600 dark:text-emerald-400' : ''} />
            <ReadinessStat label="Отклонено" value={rc.rejected} cls={rc.rejected > 0 ? 'text-red-500' : ''} />
            <ReadinessStat label="С корректировкой" value={rc.with_corrections} cls={rc.with_corrections > 0 ? 'text-amber-600 dark:text-amber-400' : ''} icon={rc.with_corrections > 0 ? Pencil : undefined} />
          </div>
          <div className="space-y-1.5 rounded-lg border border-border bg-background p-3">
            <div className="flex items-center gap-1.5 text-sm font-medium"><Upload className="h-3.5 w-3.5 text-primary" />Выгрузка в 1С</div>
            <ReadinessStat label="Готово к отправке" value={pk.draft} cls={pk.draft > 0 ? 'text-blue-600 dark:text-blue-400' : ''} />
            <ReadinessStat label="В пути" value={pk.in_flight} />
            <ReadinessStat label="Загружено" value={pk.acked} cls={pk.acked > 0 ? 'text-emerald-600 dark:text-emerald-400' : ''} icon={pk.acked > 0 ? CheckCircle2 : undefined} />
            <ReadinessStat label="Отклонено 1С" value={pk.rejected} cls={pk.rejected > 0 ? 'text-red-500' : ''} />
          </div>
        </div>
        {(rc.pending > 0 || pk.rejected > 0) && (
          <p className="mt-2 flex items-center gap-1.5 text-[11px] text-amber-600 dark:text-amber-400">
            <AlertTriangle className="h-3 w-3 shrink-0" />
            {rc.pending > 0 ? `${rc.pending} ТТН ждут проверки приёмки. ` : ''}
            {pk.rejected > 0 ? `${pk.rejected} пакетов отклонены 1С — требуется разбор.` : ''}
          </p>
        )}
      </CardContent>
    </Card>
  )
}

/* ── Реализация по топливу ── */
function FuelTable({ data }: { data: ShiftDashboardData }) {
  const rows = data.volume.by_fuel
  return (
    <Card>
      <CardContent className="pt-4">
        <div className="mb-2 flex items-center gap-2"><Fuel className="h-4 w-4 text-blue-500" /><h3 className={H3}>Реализация по топливу</h3></div>
        <div className="overflow-x-auto"><table className="w-full min-w-[440px] text-sm">
          <thead><tr className="border-b border-border/60">
            <th className={cn(TH, 'text-left')}>Топливо</th>
            <th className={cn(TH, 'text-right')}>Объём, л</th>
            <th className={cn(TH, 'text-right')}>Выручка, ₽</th>
            <th className={cn(TH, 'text-right')}>Доля</th>
          </tr></thead>
          <tbody>
            {rows.map((f) => (
              <tr key={f.fuel_code} className="border-b border-border/30">
                <td className="py-1.5"><span className="mr-1.5 inline-block h-2.5 w-2.5 rounded-full align-middle" style={{ background: fc(f.fuel_name) }} />{f.fuel_name}</td>
                <td className={cn(TD, 'text-right text-primary')}>{vol(f.volume)}</td>
                <td className={cn(TD, 'text-right')}>{rub(f.revenue)}</td>
                <td className={cn(TD, 'text-right text-muted-foreground')}>{f.percent.toFixed(1)}%</td>
              </tr>
            ))}
          </tbody>
          <tfoot><tr className="border-t-2 border-border font-semibold">
            <td className="py-1.5">ИТОГО</td>
            <td className={cn(TD, 'text-right text-primary')}>{vol(data.volume.total)}</td>
            <td className={cn(TD, 'text-right')}>{rub(data.financial.total_revenue)}</td>
            <td className={cn(TD, 'text-right text-muted-foreground')}>100%</td>
          </tr></tfoot>
        </table></div>
      </CardContent>
    </Card>
  )
}

/* ── Выручка по оплате (раскрытие по топливу) ── */
function PaymentTable({ data }: { data: ShiftDashboardData }) {
  const [open, setOpen] = useState<Set<string>>(new Set())
  const pd = data.financial.payment_details
  const totalRev = data.financial.total_revenue
  const rows = PAY_ORDER.filter((k) => pd[k] && (pd[k].revenue > 0 || pd[k].volume > 0))
  const totalVol = rows.reduce((s, k) => s + pd[k].volume, 0)
  const toggle = (k: string) => setOpen((s) => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n })

  return (
    <Card>
      <CardContent className="pt-4">
        <div className="mb-2 flex items-center gap-2"><Wallet className="h-4 w-4 text-emerald-500" /><h3 className={H3}>Выручка по способам оплаты</h3></div>
        <div className="overflow-x-auto"><table className="w-full min-w-[440px] text-sm">
          <thead><tr className="border-b border-border/60">
            <th className={cn(TH, 'text-left')}>Способ</th>
            <th className={cn(TH, 'text-right')}>Выручка, ₽</th>
            <th className={cn(TH, 'text-right')}>Объём, л</th>
            <th className={cn(TH, 'text-right')}>Доля</th>
          </tr></thead>
          <tbody>
            {rows.map((k) => {
              const d = pd[k]
              const meta = PAY_META[k] ?? { label: k, icon: CreditCard, color: 'text-muted-foreground', volumeOnly: false }
              const Icon = meta.icon
              const share = meta.volumeOnly ? (totalVol > 0 ? d.volume / totalVol * 100 : 0) : (totalRev > 0 ? d.revenue / totalRev * 100 : 0)
              const isOpen = open.has(k)
              return (
                <Fragment key={k}>
                  <tr onClick={() => toggle(k)} className="cursor-pointer border-b border-border/30 hover:bg-accent/40">
                    <td className="py-1.5">
                      <span className="inline-flex items-center gap-1.5">
                        <ChevronRight className={cn('h-3 w-3 text-muted-foreground transition-transform', isOpen && 'rotate-90')} />
                        <Icon className={cn('h-3.5 w-3.5', meta.color)} />{meta.label}
                      </span>
                    </td>
                    <td className={cn(TD, 'text-right')}>{meta.volumeOnly ? '—' : rub(d.revenue)}</td>
                    <td className={cn(TD, 'text-right text-primary')}>{vol(d.volume)}</td>
                    <td className={cn(TD, 'text-right text-muted-foreground')}>{share.toFixed(1)}%</td>
                  </tr>
                  {isOpen && d.by_fuel.map((bf) => (
                    <tr key={`${k}-${bf.fuel_code}`} className="border-b border-border/20 bg-muted/20 text-xs">
                      <td className="py-1 pl-8"><span className="mr-1.5 inline-block h-2 w-2 rounded-full align-middle" style={{ background: fc(bf.fuel_name) }} />{bf.fuel_name}</td>
                      <td className={cn(TD, 'text-right')}>{meta.volumeOnly ? '—' : rub(bf.revenue)}</td>
                      <td className={cn(TD, 'text-right text-primary')}>{vol(bf.volume)}</td>
                      <td />
                    </tr>
                  ))}
                </Fragment>
              )
            })}
          </tbody>
          <tfoot><tr className="border-t-2 border-border font-semibold">
            <td className="py-1.5">ИТОГО</td>
            <td className={cn(TD, 'text-right')}>{rub(totalRev)}</td>
            <td className={cn(TD, 'text-right text-primary')}>{vol(totalVol)}</td>
            <td className={cn(TD, 'text-right text-muted-foreground')}>100%</td>
          </tr></tfoot>
        </table></div>
        <p className="mt-1.5 text-[10px] text-muted-foreground">Безнал (топл./корп. карты, онлайн, талоны) — только объём отпуска; выручка учитывается вне кассы.</p>
      </CardContent>
    </Card>
  )
}

/* ── Поступления по ТТН ── */
function ReceiptsTable({ data }: { data: ShiftDashboardData }) {
  const r = data.receipts
  if (r.ttn_count === 0) return null
  const diffCls = (v: number) => v > 0.5 ? 'text-emerald-600 dark:text-emerald-400' : v < -0.5 ? 'text-red-500' : 'text-muted-foreground'
  return (
    <Card>
      <CardContent className="pt-4">
        <div className="mb-2 flex items-center gap-2"><Truck className="h-4 w-4 text-emerald-500" /><h3 className={H3}>Поступления по ТТН</h3><span className="text-xs text-muted-foreground">{r.ttn_count} ТТН</span></div>
        <div className="overflow-x-auto"><table className="w-full min-w-[440px] text-sm">
          <thead><tr className="border-b border-border/60">
            <th className={cn(TH, 'text-left')}>Топливо</th>
            <th className={cn(TH, 'text-right')}>ТТН</th>
            <th className={cn(TH, 'text-right')}>Документ, л</th>
            <th className={cn(TH, 'text-right')}>Факт, л</th>
            <th className={cn(TH, 'text-right')}>Разница</th>
          </tr></thead>
          <tbody>
            {r.by_fuel.map((f) => (
              <tr key={f.fuel_code} className="border-b border-border/30">
                <td className="py-1.5"><span className="mr-1.5 inline-block h-2.5 w-2.5 rounded-full align-middle" style={{ background: fc(f.fuel_name) }} />{f.fuel_name}</td>
                <td className={cn(TD, 'text-right text-muted-foreground')}>{f.ttn_count}</td>
                <td className={cn(TD, 'text-right')}>{vol(f.doc_volume)}</td>
                <td className={cn(TD, 'text-right text-primary')}>{vol(f.fact_volume)}</td>
                <td className={cn(TD, 'text-right', diffCls(f.diff))}>{f.diff > 0 ? '+' : ''}{vol(f.diff)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot><tr className="border-t-2 border-border font-semibold">
            <td className="py-1.5">ИТОГО</td>
            <td className={cn(TD, 'text-right text-muted-foreground')}>{r.ttn_count}</td>
            <td className={cn(TD, 'text-right')}>{vol(r.total_doc)}</td>
            <td className={cn(TD, 'text-right text-primary')}>{vol(r.total_fact)}</td>
            <td className={cn(TD, 'text-right', diffCls(r.total_diff))}>{r.total_diff > 0 ? '+' : ''}{vol(r.total_diff)}</td>
          </tr></tfoot>
        </table></div>
      </CardContent>
    </Card>
  )
}

/* ── Касса: движение наличных + инкассация ── */
function CashRow({ data }: { data: ShiftDashboardData }) {
  const c = data.cash_flow
  const co = data.cashout
  if (c.operations_count === 0 && c.income === 0 && co.count === 0) return null
  const items = [
    { label: 'Наличная выручка', value: `${rub0(c.income)} ₽`, cls: 'text-emerald-600 dark:text-emerald-400', sub: 'money-секция ККТ' },
    { label: 'Расход (в т.ч. инкассация)', value: `${rub0(c.expense)} ₽`, cls: 'text-red-500', sub: '' },
    { label: 'Δ за период', value: `${c.calculated > 0 ? '+' : ''}${rub0(c.calculated)} ₽`, cls: 'text-foreground', sub: 'приход − расход' },
    { label: 'Инкассация', value: `${rub0(co.total)} ₽`, cls: 'text-foreground', sub: `${co.count} шт.` },
    // Остаток — снимок STS, а не расчёт. Прежняя плитка «Разница» была зашита
    // в ноль на бэкенде и всегда рапортовала «сходится».
    { label: 'Остаток кассы', value: `${rub0(c.closing)} ₽`, cls: 'text-foreground', sub: 'снимок на конец последней смены' },
  ]
  return (
    <Card>
      <CardContent className="pt-4">
        <div className="mb-2 flex items-center gap-2"><Banknote className="h-4 w-4 text-emerald-500" /><h3 className={H3}>Касса — движение наличных и инкассация</h3></div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-5">
          {items.map((k) => (
            <div key={k.label} className="rounded-lg border border-border bg-background p-2.5">
              <div className="text-[11px] text-muted-foreground">{k.label}</div>
              <div className={cn('mt-0.5 text-base font-bold tabular-nums', k.cls)}>{k.value}</div>
              {k.sub && <div className="text-[10px] text-muted-foreground">{k.sub}</div>}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

/* ── Графики ── */
function ChartsBlock({ data }: { data: ShiftDashboardData }) {
  const daily = useMemo(() => data.charts.daily.map((d) => ({ ...d, label: format(new Date(d.date), 'dd.MM') })), [data])
  const payPie = useMemo(() => Object.entries(data.financial.payment_details)
    .filter(([, v]) => v.revenue > 0)
    .map(([k, v]) => ({ name: PAY_META[k]?.label ?? k, value: v.revenue })), [data])

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <Card><CardContent className="pt-4">
        <div className="mb-2 text-sm font-medium">Выручка по дням</div>
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={daily}>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
            <XAxis dataKey="label" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `${Math.round(v / 1000)}к`} />
            <Tooltip {...rechartsTooltipTheme} formatter={(v) => `${rub(Number(v))} ₽`} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Bar dataKey="cash" stackId="r" name="Наличные" fill="#22c55e" />
            <Bar dataKey="card" stackId="r" name="Карты" fill="#3b82f6" />
            <Bar dataKey="online" stackId="r" name="Онлайн" fill="#8b5cf6" />
            <Bar dataKey="corporate" stackId="r" name="Корп." fill="#f97316" />
            <Bar dataKey="coupon" stackId="r" name="Купоны" fill="#eab308" radius={[3, 3, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </CardContent></Card>

      <Card><CardContent className="pt-4">
        <div className="mb-2 text-sm font-medium">Структура выручки по оплате</div>
        <ResponsiveContainer width="100%" height={220}>
          <PieChart>
            <Pie data={payPie} dataKey="value" nameKey="name" innerRadius={45} outerRadius={80} paddingAngle={2}>
              {payPie.map((_, i) => <Cell key={i} fill={['#22c55e', '#3b82f6', '#8b5cf6', '#f97316', '#eab308', '#f59e0b'][i % 6]} />)}
            </Pie>
            <Tooltip {...rechartsTooltipTheme} formatter={(v) => `${rub(Number(v))} ₽`} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
          </PieChart>
        </ResponsiveContainer>
      </CardContent></Card>
    </div>
  )
}
