/**
 * Управленческие витрины энергопрофиля «Хозяйство» на РЕАЛЬНЫХ реестрах:
 * Энергозакупка (station_energy_periods + settlements role=energy) и
 * Аренда (settlements role=rent). Демо-витрины (сводка/выручка/тарифы/
 * дебиторка на DEMO_EZS) удалены — оставлен только реальный контур.
 */
import { useRef } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { ExportButton } from '@/components/workspace/analytics/ExportButton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { fmtN } from './balanceCalc'
import { usePaymentDisciplineSummary, useSettlementsDetail, useEnergyPeriodsSummary } from '@/hooks/useReferences'
import { ROLE_LABEL, PAYMENT_META, paidThroughLabel, type SettlementRole } from '@/types/settlement'


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
  // реализация (отпуск клиентам) для сравнения «закупка ↔ реализация»
  const hasSale = last12.some((p) => p.saleKwh != null)
  const sale12 = last12.reduce((a, p) => a + (p.saleKwh ?? 0), 0)
  const rev12 = last12.reduce((a, p) => a + (p.saleRevenue ?? 0), 0)
  // «сопоставимые» месяцы: обе стороны зрелые. Коридор выхода 50–110 % — потери ЭЗС
  // реально 0-20 %; выход > 110 % = реестр закупки за месяц ещё дозаполняется (лаг
  // 2-3 мес, «выход 3892 %» врал бы), выход < 50 % = реализация ещё не разогналась
  // (сессии грузятся с 01.2026). По несопоставимым месяцам выход и маржу не считаем.
  const settled = last12.filter((p) => p.saleKwh != null && p.kwh > 0
    && p.saleKwh <= p.kwh * 1.1 && p.saleKwh >= p.kwh * 0.5)
  const buyS = settled.reduce((a, p) => a + p.kwh, 0)
  const saleS = settled.reduce((a, p) => a + (p.saleKwh ?? 0), 0)
  const yield12 = buyS > 0 ? (saleS / buyS) * 100 : null
  const margin12 = settled.length
    ? settled.reduce((a, p) => a + ((p.saleRevenue ?? 0) - (p.costEst ?? 0)), 0)
    : null
  const maxBalKwh = Math.max(1, ...last12.map((p) => Math.max(p.kwh, p.saleKwh ?? 0)))
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

          {hasSale && (
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Kpi real label="Реализация за 12 мес, кВт·ч" value={fmtN(Math.round(sale12))} />
              <Kpi real label="Выход, сопоставимые мес" value={yield12 != null ? `${yield12.toFixed(1)} %` : '—'} />
              <Kpi real label="Выручка реализации за 12 мес, ₽" value={rev12 ? fmtN(Math.round(rev12)) : '—'} />
              <Kpi real label="Маржа, сопоставимые мес (оценка), ₽" value={margin12 != null ? fmtN(Math.round(margin12)) : '—'} />
            </div>
          )}

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
                  <TableCell className="text-right tabular-nums">
                    {p.tariffAvg != null
                      ? p.tariffAvg.toFixed(2)
                      : p.tariffEst != null
                        ? <>{p.tariffEst.toFixed(2)}<span className="ml-0.5 text-[9px] text-muted-foreground">оц.</span></>
                        : '—'}
                  </TableCell>
                  <TableCell className="text-right tabular-nums text-muted-foreground">{p.costEst != null ? fmtN(Math.round(p.costEst)) : '—'}</TableCell>
                </TableRow>
              ))}
            </TableBody></Table>
            <p className="text-xs text-muted-foreground/70">
              Стоимость — оценка: объём × входящий тариф месяца (для месяцев без тарифной сетки — средний тариф станции из реестра). Помесячные тарифы контрагент ведёт с июня 2026; за более ранние месяцы в колонке «Тариф ср.» показан оценочный тариф закупки (пометка «оц.») — средневзвешенный по объёму, тот же, что заложен в стоимость.
            </p>
          </CardContent></Card>

          {hasSale && (
            <Card><CardContent className="space-y-3 overflow-x-auto pt-5">
              <div className="flex flex-wrap items-center gap-2">
                <div className="text-sm font-medium">Закупка ↔ реализация по месяцам</div>
                <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground">
                  <span className="inline-block h-1.5 w-3 rounded-sm bg-primary/60" /> закупка
                  <span className="ml-2 inline-block h-1.5 w-3 rounded-sm bg-emerald-500/70" /> реализация
                </span>
              </div>
              <Table><TableHeader><TableRow>
                <TableHead>Месяц</TableHead>
                <TableHead className="w-[20%]"></TableHead>
                <TableHead className="text-right">Закуплено, кВт·ч</TableHead>
                <TableHead className="text-right">Реализация, кВт·ч</TableHead>
                <TableHead className="text-right">Выход</TableHead>
                <TableHead className="text-right">Стоимость закупки, ₽</TableHead>
                <TableHead className="text-right">Выручка, ₽</TableHead>
                <TableHead className="text-right">Маржа, ₽</TableHead>
              </TableRow></TableHeader><TableBody>
                {last12.map((p) => {
                  const yld = p.saleKwh != null && p.kwh > 0 ? (p.saleKwh / p.kwh) * 100 : null
                  const comparable = yld != null && yld >= 50 && yld <= 110
                  const buyIncomplete = yld != null && yld > 110   // реестр закупки за месяц ещё дозаполняется
                  const margin = comparable && p.saleRevenue != null && p.costEst != null ? p.saleRevenue - p.costEst : null
                  return (
                    <TableRow key={p.period}>
                      <TableCell className="font-medium whitespace-nowrap">{periodLabel(p.period)}</TableCell>
                      <TableCell>
                        <div className="space-y-1">
                          <div className="h-1.5 rounded-sm bg-primary/60" style={{ width: `${Math.max(2, (p.kwh / maxBalKwh) * 100)}%` }} />
                          <div className="h-1.5 rounded-sm bg-emerald-500/70" style={{ width: `${Math.max(2, ((p.saleKwh ?? 0) / maxBalKwh) * 100)}%` }} />
                        </div>
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {fmtN(Math.round(p.kwh))}
                        {buyIncomplete && <span className="ml-0.5 text-[9px] text-amber-600 dark:text-amber-400" title="реестр закупки за месяц ещё дозаполняется">неполн.</span>}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{p.saleKwh != null ? fmtN(Math.round(p.saleKwh)) : '—'}</TableCell>
                      <TableCell className="text-right tabular-nums text-muted-foreground">
                        {yld == null ? '—' : comparable
                          ? `${yld.toFixed(1)} %`
                          : <span title={buyIncomplete ? 'закупка в реестре за месяц ещё не заполнена — сравнение позже' : 'реализация за месяц ещё не набрала объём'}>н/д</span>}
                      </TableCell>
                      <TableCell className="text-right tabular-nums text-muted-foreground">{p.costEst != null ? fmtN(Math.round(p.costEst)) : '—'}</TableCell>
                      <TableCell className="text-right tabular-nums text-muted-foreground">{p.saleRevenue != null ? fmtN(Math.round(p.saleRevenue)) : '—'}</TableCell>
                      <TableCell className={`text-right tabular-nums ${margin == null ? 'text-muted-foreground' : margin >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}`}>{margin != null ? fmtN(Math.round(margin)) : (yld != null && !comparable ? 'н/д' : '—')}</TableCell>
                    </TableRow>
                  )
                })}
              </TableBody></Table>
              <p className="text-xs text-muted-foreground/70">
                Реализация — отпущенная клиентам энергия и выручка по зарядным сессиям (данные с 01.2026). Выход = реализация ÷ закупка: доля купленной энергии, дошедшая до клиента; разница — технологические потери сети и собственное потребление ЭЗС. Маржа = выручка − оценка стоимости закупки. Реестр закупки заполняется с лагом 2-3 мес: по месяцам, где реализация превышает закупку (метка «неполн.»), выход и маржа помечены «н/д» — сравнение появится после дозагрузки реестра.
              </p>
            </CardContent></Card>
          )}

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
