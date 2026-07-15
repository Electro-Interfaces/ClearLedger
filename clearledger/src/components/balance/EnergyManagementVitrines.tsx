/**
 * Управленческие витрины энергопрофиля (демо на данных сети DEMO_EZS):
 * Сводка сети · Выручка и продажи · Тарифы · Дебиторка · Энергозакупка.
 * Модули рабочего стола (раздел «Управленческий»), подключаются через каталог.
 * Заменяются выборкой из L2/разрезов. uptime/утилизация — заглушки до телеметрии.
 */
import { useRef } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { ExportButton } from '@/components/workspace/analytics/ExportButton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import {
  DEMO_EZS, sumBuy, sumRelease, lossKwh, lossPct, overNorm, fmtN,
  supplierContract, tariffCheck, openClaimsCount, CONTRACT_STATUS_META,
} from './balanceCalc'
import { usePaymentDisciplineSummary, useSettlementsDetail, useEnergyPeriodsSummary } from '@/hooks/useReferences'
import { useLocations } from '@/hooks/useLocations'
import { m } from '@/components/locations/fleet/locationFleetService'
import { ROLE_LABEL, PAYMENT_META, paidThroughLabel, type SettlementRole } from '@/types/settlement'

const all = DEMO_EZS

/* ── Платёжная дисциплина (РЕАЛЬНЫЕ данные реестра «Энергоснабжение и аренда ЭЗС»).
   role задаёт контур: 'energy' (закупка) | 'rent' (аренда) | undefined (оба, для Дебиторки). ── */
function PaymentDisciplineBlock({ role }: { role?: SettlementRole }) {
  const q = usePaymentDisciplineSummary()
  const s = q.data
  if (!s || s.stationsCovered === 0) return null
  const rolesShown = (role ? [role] : (['energy', 'rent'] as SettlementRole[]))
    .map((r) => s.byRole.find((x) => x.role === r)).filter(Boolean) as typeof s.byRole
  const r0 = role ? s.byRole.find((x) => x.role === role) : undefined
  const cpUnpaid = role === 'rent' ? s.counterpartiesUnpaidRent : s.counterpartiesUnpaidEnergy
  const noContract = role === 'rent' ? s.stationsNoRent : s.stationsNoEnergy
  const title = role === 'energy' ? 'Договоры и оплаты энергоснабжения'
    : role === 'rent' ? 'Договоры/разрешения и оплаты аренды'
    : 'Платёжная дисциплина (реестр ЭЗС)'
  return (
    <Card><CardContent className="space-y-3 pt-5">
      <div className="flex items-center gap-2">
        <div className="text-sm font-medium">{title}</div>
        <Badge className="bg-emerald-500/15 text-[10px] text-emerald-600 dark:text-emerald-400">реальные данные</Badge>
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {role && r0 ? (
          <>
            <Kpi label="Записей по ЭЗС" value={fmtN(r0.total)} />
            <Kpi label="Оплачено" value={fmtN(r0.paid)} />
            <Kpi label="Не оплачено" value={String(r0.unpaid)} accent={r0.unpaid ? 'warn' : undefined} />
            <Kpi label="Контрагентов без оплат" value={String(cpUnpaid)} accent={cpUnpaid ? 'warn' : undefined} />
          </>
        ) : (
          <>
            <Kpi label="ЭЗС с данными" value={fmtN(s.stationsCovered)} />
            <Kpi label="Контрагенты без оплат (энерго)" value={String(s.counterpartiesUnpaidEnergy)} accent={s.counterpartiesUnpaidEnergy ? 'warn' : undefined} />
            <Kpi label="Контрагенты без оплат (аренда)" value={String(s.counterpartiesUnpaidRent)} accent={s.counterpartiesUnpaidRent ? 'warn' : undefined} />
            <Kpi label="ЭЗС без договора э/э" value={String(s.stationsNoEnergy)} accent={s.stationsNoEnergy ? 'warn' : undefined} />
          </>
        )}
      </div>
      {role && r0 && (
        <p className="text-xs text-muted-foreground/70">
          {role === 'rent' ? 'ЭЗС без договора/разрешения аренды' : 'ЭЗС без договора энергоснабжения'}: {noContract}.
          {' '}Особый порядок: {r0.special}{role === 'rent' ? ' (% от выручки / фикс / сервитут)' : ''}.
        </p>
      )}
      <Table><TableHeader><TableRow>
        <TableHead>Контур</TableHead><TableHead className="text-right">Всего</TableHead>
        <TableHead className="text-right">Оплачено</TableHead><TableHead className="text-right">Не оплачено</TableHead>
        <TableHead className="text-right">Особый порядок</TableHead><TableHead className="text-right">С проблемой</TableHead>
      </TableRow></TableHeader><TableBody>
        {rolesShown.map((r) => (
          <TableRow key={r.role}>
            <TableCell className="font-medium">{ROLE_LABEL[r.role as SettlementRole] ?? r.role}</TableCell>
            <TableCell className="text-right tabular-nums">{r.total}</TableCell>
            <TableCell className="text-right tabular-nums text-emerald-600 dark:text-emerald-400">{r.paid}</TableCell>
            <TableCell className="text-right tabular-nums text-red-600 dark:text-red-400">{r.unpaid}</TableCell>
            <TableCell className="text-right tabular-nums text-amber-600 dark:text-amber-400">{r.special}</TableCell>
            <TableCell className="text-right tabular-nums text-muted-foreground">{r.withProblem}</TableCell>
          </TableRow>
        ))}
      </TableBody></Table>
    </CardContent></Card>
  )
}

function Head({ title, subtitle, real, exportEl }: {
  title: string; subtitle: string; real?: boolean
  /** Корневой элемент витрины для экспорта Excel/PDF (кнопка — только на реальных данных). */
  exportEl?: () => HTMLElement | null
}) {
  return (
    <div>
      <div className="flex items-center gap-2">
        <h1 className="text-xl font-semibold">{title}</h1>
        {real
          ? <Badge className="bg-emerald-500/15 text-[10px] text-emerald-600 dark:text-emerald-400">реальные данные</Badge>
          : <Badge variant="secondary" className="text-[10px]">демо-данные</Badge>}
        {exportEl && real && <ExportButton title={title} getEl={exportEl} />}
      </div>
      <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{subtitle}</p>
    </div>
  )
}
function Kpi({ label, value, accent, real }: { label: string; value: string; accent?: 'warn' | 'danger'; real?: boolean }) {
  const tone = accent === 'danger' ? 'text-red-600 dark:text-red-400' : accent === 'warn' ? 'text-amber-600 dark:text-amber-400' : 'text-foreground'
  return (
    <Card><CardContent className="pt-4">
      <div className="flex items-center gap-1 text-xs text-muted-foreground">
        <span>{label}</span>
        {real && <span className="rounded bg-emerald-500/15 px-1 text-[9px] font-medium text-emerald-600 dark:text-emerald-400">факт</span>}
      </div>
      <div className={`mt-1 text-lg font-semibold tabular-nums ${tone}`}>{value}</div>
    </CardContent></Card>
  )
}
const rate = (rub: number, kwh: number) => (kwh > 0 ? (rub / kwh).toFixed(2) : '—')

/* ── Структура парка по регионам (РЕАЛЬНЫЕ данные: точки обслуживания компании). ── */
function RegionParkStructure() {
  const locations = useLocations()
  if (!locations.length) return null
  const byRegion = new Map<string, { count: number; power: number }>()
  for (const l of locations) {
    const region = (m(l, 'federalSubject') as string) || '— не указан'
    const e = byRegion.get(region) ?? { count: 0, power: 0 }
    e.count += 1
    e.power += Number(m(l, 'maxPowerKw')) || 0
    byRegion.set(region, e)
  }
  const all = [...byRegion.entries()].sort((a, b) => b[1].count - a[1].count)
  const rows = all.slice(0, 15)
  const restCount = all.slice(15).reduce((a, [, e]) => a + e.count, 0)
  const restRegions = all.length - rows.length
  const totalPower = all.reduce((a, [, e]) => a + e.power, 0)
  return (
    <Card><CardContent className="space-y-3 overflow-x-auto pt-5">
      <div className="flex items-center gap-2">
        <div className="text-sm font-medium">Структура парка по регионам</div>
        <Badge className="bg-emerald-500/15 text-[10px] text-emerald-600 dark:text-emerald-400">реальные данные</Badge>
        <span className="text-xs text-muted-foreground/70">{locations.length} ЭЗС · {all.length} регионов · Σ {fmtN(totalPower)} кВт</span>
      </div>
      <Table><TableHeader><TableRow>
        <TableHead>Регион</TableHead><TableHead className="text-right">ЭЗС, шт</TableHead>
        <TableHead className="text-right">Σ мощность, кВт</TableHead><TableHead className="text-right">средняя, кВт</TableHead>
      </TableRow></TableHeader><TableBody>
        {rows.map(([region, e]) => (
          <TableRow key={region}>
            <TableCell className="font-medium">{region}</TableCell>
            <TableCell className="text-right tabular-nums">{e.count}</TableCell>
            <TableCell className="text-right tabular-nums text-muted-foreground">{fmtN(e.power)}</TableCell>
            <TableCell className="text-right tabular-nums text-muted-foreground">{e.count ? Math.round(e.power / e.count) : 0}</TableCell>
          </TableRow>
        ))}
      </TableBody></Table>
      {restRegions > 0 && (
        <p className="text-xs text-muted-foreground/70">…и ещё {restRegions} регионов ({restCount} ЭЗС).</p>
      )}
    </CardContent></Card>
  )
}

/* ── Структура парка по производителям и мощности (РЕАЛЬНЫЕ данные точек). Мощность ЭЗС
   определяет ценовой сегмент (медленные/быстрые/ультрабыстрые), поэтому блок — в «Тарифах». ── */
function ManufacturerParkStructure() {
  const locations = useLocations()
  if (!locations.length) return null
  const byMfr = new Map<string, { count: number; power: number }>()
  let slow = 0, fast = 0, ultra = 0, unknownP = 0
  for (const l of locations) {
    const mfr = (m(l, 'manufacturer') as string) || '— не указан'
    const p = Number(m(l, 'maxPowerKw')) || 0
    const e = byMfr.get(mfr) ?? { count: 0, power: 0 }
    e.count += 1; e.power += p
    byMfr.set(mfr, e)
    if (!p) unknownP += 1
    else if (p < 50) slow += 1
    else if (p < 150) fast += 1
    else ultra += 1
  }
  const ranked = [...byMfr.entries()].sort((a, b) => b[1].count - a[1].count)
  const rows = ranked.slice(0, 12)
  const restMfr = ranked.length - rows.length
  const restCount = ranked.slice(12).reduce((a, [, e]) => a + e.count, 0)
  return (
    <Card><CardContent className="space-y-3 overflow-x-auto pt-5">
      <div className="flex items-center gap-2">
        <div className="text-sm font-medium">Структура парка: производители и мощность</div>
        <Badge className="bg-emerald-500/15 text-[10px] text-emerald-600 dark:text-emerald-400">реальные данные</Badge>
        <span className="text-xs text-muted-foreground/70">{locations.length} ЭЗС · {ranked.length} производителей</span>
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="Медленные, <50 кВт" value={fmtN(slow)} />
        <Kpi label="Быстрые, 50–149 кВт" value={fmtN(fast)} />
        <Kpi label="Ультрабыстрые, ≥150 кВт" value={fmtN(ultra)} />
        <Kpi label="Мощность не указана" value={fmtN(unknownP)} accent={unknownP ? 'warn' : undefined} />
      </div>
      <Table><TableHeader><TableRow>
        <TableHead>Производитель</TableHead><TableHead className="text-right">ЭЗС, шт</TableHead>
        <TableHead className="text-right">Σ мощность, кВт</TableHead><TableHead className="text-right">средняя, кВт</TableHead>
      </TableRow></TableHeader><TableBody>
        {rows.map(([mfr, e]) => (
          <TableRow key={mfr}>
            <TableCell className="font-medium">{mfr}</TableCell>
            <TableCell className="text-right tabular-nums">{e.count}</TableCell>
            <TableCell className="text-right tabular-nums text-muted-foreground">{fmtN(e.power)}</TableCell>
            <TableCell className="text-right tabular-nums text-muted-foreground">{e.count ? Math.round(e.power / e.count) : 0}</TableCell>
          </TableRow>
        ))}
      </TableBody></Table>
      {restMfr > 0 && (
        <p className="text-xs text-muted-foreground/70">…и ещё {restMfr} производителей ({restCount} ЭЗС).</p>
      )}
    </CardContent></Card>
  )
}

/* ── Сводка сети ── */
export function NetworkOverviewVitrine() {
  const revenue = all.reduce((a, s) => a + sumRelease(s).rub, 0)
  const kwh = all.reduce((a, s) => a + sumRelease(s).kwh, 0)
  const buyKwh = all.reduce((a, s) => a + sumBuy(s).kwh, 0)
  const lossTot = all.reduce((a, s) => a + lossKwh(s), 0)
  const lossPctNet = buyKwh ? (lossTot / buyKwh) * 100 : 0
  const over = all.filter(overNorm).length
  const claims = openClaimsCount(all)
  const receivable = all.reduce((a, s) => a + s.unpaid.rub, 0)
  const uptime = 98.2, util = 41 // заглушки до телеметрии
  const top = [...all].sort((a, b) => sumRelease(b).rub - sumRelease(a).rub).slice(0, 5)
  const networkSize = useLocations().length // реальный размер парка ЭЗС (точки обслуживания компании)
  return (
    <div className="space-y-5 px-6 py-6">
      <Head title="Сводка сети ЭЗС" subtitle="Единый кокпит сети: размер парка и платёжная дисциплина — реальные данные (помечены «факт»); выручка, потери, доступность, утилизация — демо до подключения телеметрии." />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-8">
        <Kpi label="ЭЗС в сети" value={fmtN(networkSize)} real />
        <Kpi label="Выручка, ₽" value={fmtN(revenue)} />
        <Kpi label="Отпуск, кВт·ч" value={fmtN(kwh)} />
        <Kpi label="% потерь" value={`${lossPctNet.toFixed(1)}%`} accent={lossPctNet > 2 ? 'warn' : undefined} />
        <Kpi label="Uptime, %" value={uptime.toFixed(1)} accent={uptime < 98 ? 'warn' : undefined} />
        <Kpi label="Утилизация, %" value={String(util)} />
        <Kpi label="ЭЗС вне нормы" value={String(over)} accent={over ? 'danger' : undefined} />
        <Kpi label="Открытых обращений" value={String(claims)} accent={claims ? 'danger' : undefined} />
      </div>
      <Card><CardContent className="pt-5">
        <div className="mb-3 text-sm font-medium">Топ-5 ЭЗС по выручке</div>
        <Table><TableHeader><TableRow>
          <TableHead>ЭЗС</TableHead><TableHead className="text-right">Выручка, ₽</TableHead>
          <TableHead className="text-right">кВт·ч</TableHead><TableHead className="text-center">% потерь</TableHead>
        </TableRow></TableHeader><TableBody>
          {top.map((s) => (
            <TableRow key={s.id}>
              <TableCell className="font-medium">{s.name}</TableCell>
              <TableCell className="text-right tabular-nums">{fmtN(sumRelease(s).rub)}</TableCell>
              <TableCell className="text-right tabular-nums text-muted-foreground">{fmtN(sumRelease(s).kwh)}</TableCell>
              <TableCell className="text-center">
                <Badge variant="secondary" className={`text-[10px] ${overNorm(s) ? 'bg-red-500/15 text-red-600 dark:text-red-400' : 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'}`}>{lossPct(s).toFixed(1)}%</Badge>
              </TableCell>
            </TableRow>
          ))}
        </TableBody></Table>
      </CardContent></Card>
      <PaymentDisciplineBlock />
      <p className="text-xs text-muted-foreground/70">Дебиторка к доплате (холд&lt;факт): {fmtN(receivable)} ₽. Uptime/утилизация — заглушка до телеметрии ПК/ПУ.</p>
    </div>
  )
}

/* ── Выручка и продажи ── */
export function RevenueVitrine() {
  const revenue = all.reduce((a, s) => a + sumRelease(s).rub, 0)
  const kwh = all.reduce((a, s) => a + sumRelease(s).kwh, 0)
  const sessions = all.reduce((a, s) => a + tariffCheck(s).sessions, 0)
  const byRegion = new Map<string, { rub: number; kwh: number; ul: number; fl: number }>()
  for (const s of all) {
    const e = byRegion.get(s.region) ?? { rub: 0, kwh: 0, ul: 0, fl: 0 }
    e.rub += sumRelease(s).rub; e.kwh += sumRelease(s).kwh
    e.ul += s.release.ul?.kwh ?? 0; e.fl += s.release.fl?.kwh ?? 0
    byRegion.set(s.region, e)
  }
  return (
    <div className="space-y-5 px-6 py-6">
      <Head title="Выручка и продажи" subtitle="Выручка и кВт·ч в разрезе региона и категорий (ЮЛ/ФЛ), средний чек сессии." />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="Выручка с НДС, ₽" value={fmtN(revenue)} />
        <Kpi label="Выручка без НДС (22%), ₽" value={fmtN(revenue / 1.22)} />
        <Kpi label="Отпуск, кВт·ч" value={fmtN(kwh)} />
        <Kpi label="Средний чек сессии, ₽" value={fmtN(sessions ? revenue / sessions : 0)} />
      </div>
      <Card><CardContent className="overflow-x-auto pt-5">
        <Table><TableHeader><TableRow>
          <TableHead>Регион</TableHead><TableHead className="text-right">Выручка, ₽</TableHead>
          <TableHead className="text-right">кВт·ч</TableHead><TableHead className="text-right">ЮЛ, кВт·ч</TableHead>
          <TableHead className="text-right">ФЛ, кВт·ч</TableHead><TableHead className="text-right">₽/кВт·ч</TableHead>
        </TableRow></TableHeader><TableBody>
          {[...byRegion.entries()].sort((a, b) => b[1].rub - a[1].rub).map(([region, e]) => (
            <TableRow key={region}>
              <TableCell className="font-medium">{region}</TableCell>
              <TableCell className="text-right tabular-nums">{fmtN(e.rub)}</TableCell>
              <TableCell className="text-right tabular-nums text-muted-foreground">{fmtN(e.kwh)}</TableCell>
              <TableCell className="text-right tabular-nums text-muted-foreground">{fmtN(e.ul)}</TableCell>
              <TableCell className="text-right tabular-nums text-muted-foreground">{fmtN(e.fl)}</TableCell>
              <TableCell className="text-right tabular-nums">{rate(e.rub, e.kwh)}</TableCell>
            </TableRow>
          ))}
        </TableBody></Table>
      </CardContent></Card>
      <RegionParkStructure />
    </div>
  )
}

/* ── Тарифы и ценообразование ── */
export function TariffsVitrine() {
  const ulRub = all.reduce((a, s) => a + (s.release.ul?.rub ?? 0), 0), ulKwh = all.reduce((a, s) => a + (s.release.ul?.kwh ?? 0), 0)
  const flRub = all.reduce((a, s) => a + (s.release.fl?.rub ?? 0), 0), flKwh = all.reduce((a, s) => a + (s.release.fl?.kwh ?? 0), 0)
  const violations = all.filter((s) => { const t = tariffCheck(s); return t.rateMismatch > 0 || t.noCategory > 0 }).length
  const offTariff = all.reduce((a, s) => a + tariffCheck(s).noCategory, 0)
  const rows = [...all].map((s) => ({ s, t: tariffCheck(s) })).sort((a, b) => (b.t.rateMismatch + b.t.noCategory) - (a.t.rateMismatch + a.t.noCategory)).slice(0, 14)
  return (
    <div className="space-y-5 px-6 py-6">
      <Head title="Тарифы и ценообразование" subtitle="Тарифы по категориям, контроль соответствия НПА (ТЗ §4.3.2), станции с нарушениями." />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="Средний тариф ЮЛ, ₽/кВт·ч" value={rate(ulRub, ulKwh)} />
        <Kpi label="Средний тариф ФЛ, ₽/кВт·ч" value={rate(flRub, flKwh)} />
        <Kpi label="ЭЗС с нарушением НПА" value={String(violations)} accent={violations ? 'danger' : undefined} />
        <Kpi label="Сессий вне тарифа" value={fmtN(offTariff)} accent={offTariff ? 'warn' : undefined} />
      </div>
      <Card><CardContent className="overflow-x-auto pt-5">
        <Table><TableHeader><TableRow>
          <TableHead>ЭЗС</TableHead><TableHead className="text-right">Тариф ЮЛ</TableHead>
          <TableHead className="text-right">Тариф ФЛ</TableHead><TableHead className="text-center">Соответствие НПА</TableHead>
        </TableRow></TableHeader><TableBody>
          {rows.map(({ s, t }) => {
            const ok = t.rateMismatch === 0 && t.noCategory === 0
            return (
              <TableRow key={s.id}>
                <TableCell className="font-medium">{s.name}</TableCell>
                <TableCell className="text-right tabular-nums">{rate(s.release.ul?.rub ?? 0, s.release.ul?.kwh ?? 0)}</TableCell>
                <TableCell className="text-right tabular-nums">{rate(s.release.fl?.rub ?? 0, s.release.fl?.kwh ?? 0)}</TableCell>
                <TableCell className="text-center">
                  <Badge variant="secondary" className={`text-[10px] ${ok ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400' : 'bg-red-500/15 text-red-600 dark:text-red-400'}`}>
                    {ok ? 'по НПА' : `нарушений: ${t.rateMismatch + t.noCategory}`}
                  </Badge>
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody></Table>
      </CardContent></Card>
      <ManufacturerParkStructure />
    </div>
  )
}

/* ── Детализация по ЭЗС (РЕАЛЬНЫЕ строки реестра): станция × контрагент × договор × оплата ── */
function SettlementDetailTable({ role }: { role: SettlementRole }) {
  const q = useSettlementsDetail(role)
  const rows = q.data ?? []
  if (q.isLoading) return <Card><CardContent className="pt-5 text-sm text-muted-foreground">Загрузка детализации…</CardContent></Card>
  if (!rows.length) return null
  return (
    <Card><CardContent className="pt-5">
      <div className="mb-3 flex items-center gap-2">
        <div className="text-sm font-medium">
          {role === 'rent' ? 'Аренда по ЭЗС — детализация' : 'Энергоснабжение по ЭЗС — детализация'}
        </div>
        <Badge className="bg-emerald-500/15 text-[10px] text-emerald-600 dark:text-emerald-400">реальные данные · {rows.length}</Badge>
      </div>
      <div className="max-h-[480px] overflow-auto rounded-md border border-border/40">
        <Table><TableHeader className="sticky top-0 bg-card"><TableRow>
          <TableHead>ЭЗС</TableHead>
          <TableHead>{role === 'rent' ? 'Арендодатель' : 'Поставщик э/э'}</TableHead>
          <TableHead>{role === 'rent' ? 'Договор / разрешение' : 'Договор'}</TableHead>
          {role === 'rent' && <TableHead className="text-right">Плата, ₽/мес</TableHead>}
          {role === 'rent' && <TableHead className="text-right">Срок до</TableHead>}
          {role === 'energy' && <TableHead className="text-right">Тариф ср., ₽/кВт·ч</TableHead>}
          <TableHead>Оплата</TableHead>
          <TableHead>Комментарий</TableHead>
        </TableRow></TableHeader><TableBody>
          {rows.map((r) => {
            const meta = PAYMENT_META[r.paymentStatus]
            const contractCell = r.contractNumber || (r.basis && r.basis !== 'договор' ? r.basis : '—')
            const amount = r.amountGross ?? r.amountNet
            const avgTariff = typeof r.extra?.avgTariff === 'number' ? r.extra.avgTariff : null
            const expired = !!(r.contractEnd && r.contractEnd < new Date().toISOString().slice(0, 10))
            return (
              <TableRow key={`${r.locationId}-${r.role}`}>
                <TableCell className="font-medium whitespace-nowrap">
                  {r.buNumber ? `№${r.buNumber}` : (r.stationCode || '—')}
                  {r.stationName && <span className="ml-1 text-xs text-muted-foreground">{r.stationName.length > 38 ? r.stationName.slice(0, 38) + '…' : r.stationName}</span>}
                </TableCell>
                <TableCell className="text-muted-foreground">{r.counterpartyName || '—'}</TableCell>
                <TableCell className="text-xs text-muted-foreground">{contractCell}</TableCell>
                {role === 'rent' && (
                  <TableCell className="text-right tabular-nums">
                    {amount != null ? fmtN(Math.round(amount)) : '—'}
                    {amount != null && r.amountGross == null && <span className="ml-0.5 text-[9px] text-muted-foreground">без НДС</span>}
                  </TableCell>
                )}
                {role === 'rent' && (
                  <TableCell className={`text-right text-xs tabular-nums whitespace-nowrap ${expired ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground'}`}>
                    {r.contractEnd ? r.contractEnd.split('-').reverse().join('.') : '—'}
                  </TableCell>
                )}
                {role === 'energy' && (
                  <TableCell className="text-right tabular-nums">{avgTariff != null ? avgTariff.toFixed(2) : '—'}</TableCell>
                )}
                <TableCell><span className={`whitespace-nowrap rounded px-1.5 py-0.5 text-[10px] font-medium ${meta.cls}`}>{paidThroughLabel(r)}</span></TableCell>
                <TableCell className="max-w-[280px] text-xs text-muted-foreground">{r.comment || ''}</TableCell>
              </TableRow>
            )
          })}
        </TableBody></Table>
      </div>
    </CardContent></Card>
  )
}

/* ── Дебиторка и взаиморасчёты ── */
export function ReceivablesVitrine() {
  const hold = all.reduce((a, s) => a + s.unpaid.rub, 0)
  const payable = all.reduce((a, s) => a + supplierContract(s).debt, 0)
  const renegotiating = all.filter((s) => { const c = supplierContract(s).status; return c === 'amending' || c === 'terminating' }).length
  const rows = [...all].map((s) => ({ s, c: supplierContract(s) }))
    .sort((a, b) => (b.s.unpaid.rub + b.c.debt) - (a.s.unpaid.rub + a.c.debt)).slice(0, 14)
  return (
    <div className="space-y-5 px-6 py-6">
      <Head title="Дебиторка и взаиморасчёты" subtitle="Холд<факт (дебиторка ЮЛ/ФЛ), сальдо с поставщиками э/э и арендодателями, договорная работа." />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        <Kpi label="Холд < факт (дебиторка), ₽" value={fmtN(hold)} accent={hold ? 'warn' : undefined} />
        <Kpi label="Задолженность поставщикам, ₽" value={fmtN(payable)} accent={payable ? 'warn' : undefined} />
        <Kpi label="Договоров в пересмотре/расторжении" value={String(renegotiating)} accent={renegotiating ? 'warn' : undefined} />
      </div>
      <PaymentDisciplineBlock />
      <Card><CardContent className="overflow-x-auto pt-5">
        <Table><TableHeader><TableRow>
          <TableHead>ЭЗС</TableHead><TableHead className="text-right">Холд&lt;факт, ₽</TableHead>
          <TableHead>Поставщик</TableHead><TableHead className="text-right">Сальдо (долг), ₽</TableHead>
          <TableHead className="text-center">Договор</TableHead>
        </TableRow></TableHeader><TableBody>
          {rows.map(({ s, c }) => (
            <TableRow key={s.id}>
              <TableCell className="font-medium">{s.name}</TableCell>
              <TableCell className="text-right tabular-nums">{fmtN(s.unpaid.rub)}</TableCell>
              <TableCell className="text-muted-foreground">{c.supplier}</TableCell>
              <TableCell className="text-right tabular-nums">{fmtN(c.debt)}</TableCell>
              <TableCell className="text-center">
                <Badge variant="secondary" className={`text-[10px] ${CONTRACT_STATUS_META[c.status].cls}`}>{CONTRACT_STATUS_META[c.status].label}</Badge>
              </TableCell>
            </TableRow>
          ))}
        </TableBody></Table>
      </CardContent></Card>
    </div>
  )
}

/* ── Энергозакупка (РЕАЛЬНЫЕ данные: объёмы входящей э/э из «Сводной» реестра,
   тарифы из «Тарифы Электроэнергия_Входящие»; стоимость — оценка объём×тариф). ── */
const MONTH_SHORT = ['', 'янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']
function periodLabel(iso: string): string {
  const [y, m] = iso.split('-')
  return `${MONTH_SHORT[Number(m)] || m} ${y.slice(2)}`
}

export function ProcurementVitrine() {
  const rootRef = useRef<HTMLDivElement>(null)
  const q = useEnergyPeriodsSummary(24)
  const s = q.data
  const series = s?.series ?? []
  const last12 = series.slice(-12)
  const kwh12 = last12.reduce((a, p) => a + p.kwh, 0)
  const cost12 = last12.reduce((a, p) => a + (p.costEst ?? 0), 0)
  const lastTariff = [...series].reverse().find((p) => p.tariffAvg != null)
  const maxKwh = Math.max(1, ...last12.map((p) => p.kwh))
  return (
    <div ref={rootRef} className="space-y-5 px-6 py-6">
      <Head
        real={!!s && series.length > 0}
        title="Энергозакупка"
        subtitle="Входящая электроэнергия по сети: объёмы, которые выставляют контрагенты (помесячно из реестра), входящие тарифы и оценка стоимости закупки."
        exportEl={() => rootRef.current}
      />
      {q.isLoading && <p className="text-sm text-muted-foreground">Загрузка данных энергозакупки…</p>}
      {!!s && series.length > 0 && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Kpi real label="Входящая э/э за 12 мес, кВт·ч" value={fmtN(Math.round(kwh12))} />
            <Kpi real label="Оценка стоимости за 12 мес, ₽" value={cost12 ? fmtN(Math.round(cost12)) : '—'} />
            <Kpi real label={`Средний входящий тариф${lastTariff ? ` (${periodLabel(lastTariff.period)})` : ''}, ₽/кВт·ч`} value={lastTariff?.tariffAvg != null ? lastTariff.tariffAvg.toFixed(2) : '—'} />
            <Kpi real label="ЭЗС с объёмами / с тарифом" value={`${s.stationsWithVolumes} / ${s.stationsWithTariff}`} />
          </div>

          <Card><CardContent className="space-y-3 pt-5">
            <div className="flex items-center gap-2">
              <div className="text-sm font-medium">Входящая э/э по месяцам</div>
              <span className="text-xs text-muted-foreground/70">
                последние 12 мес · всего в реестре {fmtN(Math.round(s.totalKwh))} кВт·ч с 09.2022
              </span>
            </div>
            <Table><TableHeader><TableRow>
              <TableHead>Месяц</TableHead>
              <TableHead className="w-[34%]"></TableHead>
              <TableHead className="text-right">Объём, кВт·ч</TableHead>
              <TableHead className="text-right">ЭЗС</TableHead>
              <TableHead className="text-right">Тариф ср., ₽/кВт·ч</TableHead>
              <TableHead className="text-right">Стоимость (оценка), ₽</TableHead>
            </TableRow></TableHeader><TableBody>
              {last12.map((p) => (
                <TableRow key={p.period}>
                  <TableCell className="font-medium whitespace-nowrap">{periodLabel(p.period)}</TableCell>
                  <TableCell>
                    <div className="h-2 rounded-sm bg-primary/70" style={{ width: `${Math.max(2, (p.kwh / maxKwh) * 100)}%` }} />
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{fmtN(Math.round(p.kwh))}</TableCell>
                  <TableCell className="text-right tabular-nums text-muted-foreground">{p.stations}</TableCell>
                  <TableCell className="text-right tabular-nums">{p.tariffAvg != null ? p.tariffAvg.toFixed(2) : '—'}</TableCell>
                  <TableCell className="text-right tabular-nums text-muted-foreground">{p.costEst != null ? fmtN(Math.round(p.costEst)) : '—'}</TableCell>
                </TableRow>
              ))}
            </TableBody></Table>
            <p className="text-xs text-muted-foreground/70">
              Стоимость — оценка: объём × входящий тариф месяца (для месяцев без тарифной сетки — средний тариф станции из реестра). Помесячные тарифы контрагент ведёт с июня 2026.
            </p>
          </CardContent></Card>

          {s.suppliers.length > 0 && (
            <Card><CardContent className="space-y-3 overflow-x-auto pt-5">
              <div className="flex items-center gap-2">
                <div className="text-sm font-medium">Поставщики э/э</div>
                <Badge className="bg-emerald-500/15 text-[10px] text-emerald-600 dark:text-emerald-400">реальные данные</Badge>
                <span className="text-xs text-muted-foreground/70">объёмы за окно 24 мес · по договорам энергоснабжения</span>
              </div>
              <Table><TableHeader><TableRow>
                <TableHead>Поставщик э/э</TableHead><TableHead>ИНН</TableHead>
                <TableHead className="text-right">ЭЗС</TableHead>
                <TableHead className="text-right">Объём, кВт·ч</TableHead>
                <TableHead className="text-right">Тариф средневзв., ₽/кВт·ч</TableHead>
                <TableHead className="text-right">Не оплачено, ЭЗС</TableHead>
              </TableRow></TableHeader><TableBody>
                {s.suppliers.map((r) => (
                  <TableRow key={r.name}>
                    <TableCell className="font-medium">{r.name}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{r.inn || '—'}</TableCell>
                    <TableCell className="text-right tabular-nums">{r.stations}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmtN(Math.round(r.kwh))}</TableCell>
                    <TableCell className="text-right tabular-nums">{r.tariffAvg != null ? r.tariffAvg.toFixed(2) : '—'}</TableCell>
                    <TableCell className={`text-right tabular-nums ${r.unpaid ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground'}`}>{r.unpaid || ''}</TableCell>
                  </TableRow>
                ))}
              </TableBody></Table>
            </CardContent></Card>
          )}
        </>
      )}
      <PaymentDisciplineBlock role="energy" />
      <SettlementDetailTable role="energy" />
    </div>
  )
}

/* ── Аренда (земля/площадки ЭЗС) — отдельный управленческий модуль.
   Суммы постоянной части и сроки — из реестра «ЭЗС_Договоры_Аренда» (актуальный)
   и «Сводной». ── */
export function RentVitrine() {
  const rootRef = useRef<HTMLDivElement>(null)
  const q = useSettlementsDetail('rent')
  const rows = q.data ?? []
  const withAmount = rows.filter((r) => (r.amountGross ?? r.amountNet) != null)
  const monthlyGross = withAmount.reduce((a, r) => a + (r.amountGross ?? r.amountNet ?? 0), 0)
  const monthlyNet = withAmount.reduce((a, r) => a + (r.amountNet ?? 0), 0)
  const now = new Date()
  const in90 = new Date(now.getTime() + 90 * 864e5).toISOString().slice(0, 10)
  const today = now.toISOString().slice(0, 10)
  const expiring = rows.filter((r) => r.contractEnd && r.contractEnd >= today && r.contractEnd <= in90).length
  const expired = rows.filter((r) => r.contractEnd && r.contractEnd < today).length
  return (
    <div ref={rootRef} className="space-y-5 px-6 py-6">
      <Head
        real={rows.length > 0}
        title="Аренда (земля и площадки ЭЗС)"
        subtitle="Договоры и разрешения на размещение ЭЗС, арендодатели (в т.ч. муниципалитеты), постоянная часть арендной платы, сроки договоров, статус оплаты «оплачено по», особый порядок (% от выручки / фикс / сервитут)."
        exportEl={() => rootRef.current}
      />
      {rows.length > 0 && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Kpi real label="Постоянная часть, ₽/мес (с НДС)" value={fmtN(Math.round(monthlyGross))} />
          <Kpi real label="в т.ч. без НДС, ₽/мес" value={monthlyNet ? fmtN(Math.round(monthlyNet)) : '—'} />
          <Kpi real label="Договоров с суммой" value={`${withAmount.length} из ${rows.length}`} />
          <Kpi real label="Истекают за 90 дней / истекли" value={`${expiring} / ${expired}`}
               accent={expiring + expired ? 'warn' : undefined} />
        </div>
      )}
      <PaymentDisciplineBlock role="rent" />
      <SettlementDetailTable role="rent" />
    </div>
  )
}
