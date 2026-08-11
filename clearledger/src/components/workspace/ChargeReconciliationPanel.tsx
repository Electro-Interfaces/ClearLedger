/**
 * Пункт «Расхождения» — где данные о зарядках спорят с деньгами и энергией.
 *
 * Это самостоятельный вопрос анализа, а не приложение к платежам: отчёт о
 * выручке показывает, сколько начислено, а здесь видно, сколько из этого
 * подтверждено банком и сколько отпуска пришло из строк, которых физически не
 * могло быть (10 341 кВт·ч за 11 секунд).
 *
 * Три взгляда: причины расхождений (и строки под каждой), разрезы «где копится»
 * по семи измерениям и повторяемость по месяцам — она отличает разовый сбой от
 * неисправного оборудования.
 */
import { Fragment, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import { Loader2 } from 'lucide-react'
import { Kpi } from './analytics/Kpi'
import { PanelViewTabs } from './PanelViewTabs'
import { useTabParams } from '@/hooks/useTabParams'
import {
  getReconciliation, getReconciliationBy, getReconciliationRows,
  type ReconByRow, type ReconDim, type ReconRow, type ReconSummary,
} from '@/services/chargePaymentsService'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf2 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 })
const money = (v: number) => nf0.format(Math.round(v || 0)) + ' ₽'
const rub = (v: number) => nf2.format(v || 0) + ' ₽'
const kwh = (v: number) => nf0.format(v || 0) + ' кВт·ч'
const pct = (a: number, b: number) => (b ? Math.round((a / b) * 100) : 0)

function Loading() {
  return <div className="flex justify-center py-12"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
}
function Empty({ text }: { text: string }) {
  return <div className="p-6 text-sm text-muted-foreground text-center">{text}</div>
}

const DIMS: { k: ReconDim; label: string }[] = [
  { k: 'station', label: 'Станции' },
  { k: 'region', label: 'Регионы' },
  { k: 'month', label: 'Месяцы' },
  { k: 'connector', label: 'Разъёмы' },
  { k: 'charge_type', label: 'Канал запуска' },
  { k: 'client', label: 'Клиенты' },
  { k: 'card_status', label: 'Статус карты' },
]

// Платёжные расхождения: строка — операция эквайринга, а не сессия. У них
// «разрыв сессия − платёж» смысла не имеет, зато нужны холд и возврат.
const PAY_KINDS = new Set(['refund_full', 'hold_rule', 'receipt_no_txn', 'not_card'])

/** Сами строки, из которых сложилась причина: сессии либо операции эквайринга. */
function ReconRows({ kind, rows, total }: { kind: string; rows: ReconRow[]; total: number }) {
  const pay = PAY_KINDS.has(kind)
  return (
    <div className="overflow-x-auto border-t">
      <div className="px-2 py-1.5 text-[11px] text-muted-foreground">
        {rows.length < total
          ? `Показаны ${nf0.format(rows.length)} строк из ${nf0.format(total)} — самые крупные`
          : `Все ${nf0.format(total)} строк`}
      </div>
      <table className="w-full text-xs">
        <thead><tr className="border-y bg-muted/30 text-muted-foreground">
          <th className="p-2 text-left font-medium">Дата</th>
          <th className="p-2 text-left font-medium">Станция</th>
          <th className="p-2 text-left font-medium">Сессия</th>
          <th className="p-2 text-right font-medium">кВт·ч</th>
          {kind === 'impossible' && <th className="p-2 text-right font-medium">Мощность</th>}
          <th className="p-2 text-right font-medium">Начислено</th>
          {pay && <th className="p-2 text-right font-medium">Холд</th>}
          {pay && <th className="p-2 text-right font-medium">Возврат</th>}
          <th className="p-2 text-right font-medium">Списано</th>
          {!pay && <th className="p-2 text-right font-medium">Разрыв</th>}
          <th className="p-2 text-left font-medium">Чек</th>
        </tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className="border-b last:border-0">
              <td className="p-2 whitespace-nowrap">{r.at ? new Date(r.at).toLocaleDateString('ru-RU') : '—'}</td>
              <td className="p-2 max-w-[220px] truncate">{r.station ?? '—'}</td>
              <td className="p-2 font-mono text-muted-foreground">{r.session ?? '—'}</td>
              <td className="p-2 text-right tabular-nums">{nf2.format(r.energy)}</td>
              {kind === 'impossible' && (
                <td className="p-2 text-right tabular-nums text-amber-600 dark:text-amber-400">
                  {r.powerKw != null ? `${nf0.format(r.powerKw)} кВт` : '—'}
                </td>
              )}
              <td className="p-2 text-right tabular-nums">{rub(r.amount)}</td>
              {pay && <td className="p-2 text-right tabular-nums text-muted-foreground">{r.hold ? rub(r.hold) : '—'}</td>}
              {pay && <td className="p-2 text-right tabular-nums text-amber-600 dark:text-amber-400">{r.refund ? rub(r.refund) : '—'}</td>}
              <td className="p-2 text-right tabular-nums">{rub(r.paid)}</td>
              {!pay && (
                <td className={`p-2 text-right tabular-nums ${Math.abs(r.gap) > 1 ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground'}`}>
                  {rub(r.gap)}
                </td>
              )}
              <td className="p-2">{r.receipt ? 'есть' : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

interface Props { companyId: string; dateFrom: string; dateTo: string }

export function ChargeReconciliationPanel({ companyId, dateFrom, dateTo }: Props) {
  const [t0, patch] = useTabParams('cs_recon', { by: 'station' })
  const by = (DIMS.some((d) => d.k === t0.by) ? t0.by : 'station') as ReconDim
  const [kind, setKind] = useState<string | null>(null)

  const sum = useQuery<ReconSummary>({
    queryKey: ['recon-sum', companyId, dateFrom, dateTo],
    queryFn: () => getReconciliation({ companyId, dateFrom, dateTo }),
    enabled: !!companyId,
  })
  const dim = useQuery<ReconByRow[]>({
    queryKey: ['recon-by', companyId, dateFrom, dateTo, by],
    queryFn: () => getReconciliationBy({ companyId, dateFrom, dateTo, by, limit: 60 }),
    enabled: !!companyId,
  })
  const rows = useQuery<ReconRow[]>({
    queryKey: ['recon-rows', companyId, dateFrom, dateTo, kind],
    queryFn: () => getReconciliationRows({ companyId, dateFrom, dateTo, kind: kind! }),
    enabled: !!companyId && !!kind,
  })

  if (sum.isLoading) return <Loading />
  if (!sum.data || !sum.data.totals.sessions) return <Empty text="За период сессий нет" />
  const t = sum.data.totals

  return (
    <div className="p-4 space-y-4">
      {/* Деньги и энергия рядом: расходятся оба показателя, а не только выручка. */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Kpi label="Начислено рознице" value={money(t.retail_amount)}
             sub={`${nf0.format(t.sessions)} сессий · корпоратив ${money(t.corp_amount)} по договору`} />
        <Kpi label="Списано банком" value={money(t.paid)}
             sub={t.retail_amount ? `${pct(t.paid, t.retail_amount)} % от начисленного рознице` : undefined} />
        <Kpi label="Разрыв в деньгах" value={money(t.gap)}
             sub={t.retail_amount ? `${pct(Math.abs(t.gap), t.retail_amount)} % розничных начислений` : undefined} />
        <Kpi label="Отпуск под вопросом" value={kwh(t.bad_energy_kwh)}
             sub={t.energy_kwh ? `${pct(t.bad_energy_kwh, t.energy_kwh)} % от ${kwh(t.energy_kwh)}` : undefined} />
      </div>

      {/* ── Причины ── */}
      <div className="space-y-2">
        <div className="text-xs text-muted-foreground">
          Из чего складывается расхождение. Клик по строке открывает сами сессии.
          Сверяется только розница: у юрлиц постоплата по договору, эквайринга по их
          сессиям нет — но битые строки завышают счёт и им, это видно в разрезе по клиентам.
        </div>
        <Card><CardContent className="p-0 overflow-x-auto">
          <table className="w-full text-xs">
            <thead><tr className="border-b bg-muted/40 text-muted-foreground">
              <th className="p-2 text-left font-medium">Причина</th>
              <th className="p-2 text-right font-medium">Строк</th>
              <th className="p-2 text-right font-medium">Начислено</th>
              <th className="p-2 text-right font-medium">Списано</th>
              <th className="p-2 text-right font-medium">Разрыв</th>
            </tr></thead>
            <tbody>
              {sum.data.kinds.map((k) => (
                <Fragment key={k.key}>
                  <tr onClick={() => k.count && setKind(kind === k.key ? null : k.key)}
                      className={`border-b last:border-0 ${k.count ? 'cursor-pointer hover:bg-muted/30' : ''} ${kind === k.key ? 'bg-muted/40' : ''}`}>
                    <td className="p-2">
                      <div className="font-medium">{k.label}</div>
                      <div className="text-muted-foreground">{k.hint}</div>
                    </td>
                    <td className={`p-2 text-right tabular-nums ${k.count ? '' : 'text-muted-foreground'}`}>{nf0.format(k.count)}</td>
                    <td className="p-2 text-right tabular-nums text-muted-foreground">{money(k.amount)}</td>
                    <td className="p-2 text-right tabular-nums text-muted-foreground">{money(k.paid)}</td>
                    <td className={`p-2 text-right tabular-nums ${Math.abs(k.gap) > 1 ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground'}`}>
                      {k.gap ? money(k.gap) : '—'}
                    </td>
                  </tr>
                  {/* Строки — прямо под своей причиной: иначе они уезжают под всю
                      таблицу и клик выглядит как «ничего не произошло». */}
                  {kind === k.key && (
                    <tr className="border-b last:border-0 bg-muted/10">
                      <td colSpan={5} className="p-0">
                        {rows.isLoading ? <Loading /> : !rows.data?.length ? <Empty text="Строк нет" /> : (
                          <ReconRows kind={k.key} rows={rows.data} total={k.count} />
                        )}
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </CardContent></Card>
      </div>

      {/* ── Разрезы «где копится» ── */}
      <div className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="text-xs text-muted-foreground">
            Где копятся расхождения. Повторяющиеся из месяца в месяц отмечены
            «хроника» — это оборудование, а не правка данных.
          </div>
          <PanelViewTabs tabs={DIMS.map((d) => ({ k: d.k, label: d.label }))}
            value={by} onChange={(k) => patch({ by: k })} label={null}
            ariaLabel="Разрез расхождений" />
        </div>
        {dim.isLoading ? <Loading /> : !dim.data?.length ? (
          <Empty text="В этом разрезе расхождений нет" />
        ) : (
          <Card><CardContent className="p-0 overflow-x-auto">
            <table className="w-full text-xs">
              <thead><tr className="border-b bg-muted/40 text-muted-foreground">
                <th className="p-2 text-left font-medium">{DIMS.find((d) => d.k === by)?.label}</th>
                {by === 'station' && <th className="p-2 text-left font-medium">Повторяемость</th>}
                <th className="p-2 text-right font-medium">Разрыв ₽</th>
                <th className="p-2 text-right font-medium">Доля</th>
                <th className="p-2 text-right font-medium">Отпуск под вопросом</th>
                <th className="p-2 text-right font-medium">Битых</th>
                <th className="p-2 text-right font-medium">Недоплат</th>
                <th className="p-2 text-right font-medium">Без чека</th>
                <th className="p-2 text-right font-medium">Сессий</th>
              </tr></thead>
              <tbody>
                {[...dim.data].sort((a, b) =>
                  (b.chronic ? 1 : 0) - (a.chronic ? 1 : 0)
                  || Math.abs(b.gap) - Math.abs(a.gap)).map((r) => (
                  <tr key={r.label} className="border-b last:border-0">
                    <td className="p-2 max-w-[240px] truncate" title={r.label}>{r.label}</td>
                    {by === 'station' && (
                      <td className="p-2 whitespace-nowrap">
                        {r.badMonths ? (
                          <span className={r.chronic ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground'}>
                            {r.badMonths} из {r.months} мес{r.chronic ? ' · хроника' : ''}
                          </span>
                        ) : <span className="text-muted-foreground/60">—</span>}
                      </td>
                    )}
                    <td className="p-2 text-right tabular-nums text-amber-600 dark:text-amber-400">{money(r.gap)}</td>
                    <td className="p-2 text-right tabular-nums text-muted-foreground">{r.gapPct} %</td>
                    <td className={`p-2 text-right tabular-nums ${
                      r.impossibleEnergy ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground/60'}`}>
                      {r.impossibleEnergy
                        ? `${kwh(r.impossibleEnergy)} · ${r.impossibleEnergyPct} %`
                        : '—'}
                    </td>
                    <td className={`p-2 text-right tabular-nums ${r.impossible ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground/60'}`}>
                      {r.impossible || '—'}
                    </td>
                    <td className="p-2 text-right tabular-nums text-muted-foreground">{r.underpaid || '—'}</td>
                    <td className="p-2 text-right tabular-nums text-muted-foreground">{r.noReceipt || '—'}</td>
                    <td className="p-2 text-right tabular-nums text-muted-foreground">{nf0.format(r.sessions)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent></Card>
        )}
      </div>
    </div>
  )
}
