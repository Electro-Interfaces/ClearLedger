/**
 * «Экономика» (`econ`) — сколько компания заработала.
 *
 * До этого продукта пространство показывало правую половину отчёта: «Реализация»
 * отвечала, сколько продали и когда заплатят, «Бухгалтерия» — что лежит в регистре.
 * Куда уходят деньги и что осталось, не отвечал никто, хотя проводки для этого
 * приехали с первой выгрузкой.
 *
 * Три раздела по вопросу: «Результат» (отчёт о финансовых результатах и
 * рентабельность), «Расходы» (из чего сложились затраты), «Налоги» (сколько
 * начислено, уплачено и какая нагрузка).
 *
 * Числа считает бэкенд по ОБОРОТАМ счетов результата, а не по документам: внутренние
 * закрытия (90.09 ↔ 90.xx, 99 ↔ 90.09) в расчёт не идут, иначе выручка удваивается на
 * строке закрытия месяца. Фронт складывает только то, чего в ответе нет по природе.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Download, Printer } from 'lucide-react'

import { useCompany } from '@/contexts/CompanyContext'
import { useFilters, type Period } from '@/contexts/FilterContext'
import { useWorkspace, useWorkspaceSubView } from '@/contexts/WorkspaceContext'
import { QueryError } from '@/components/common/QueryError'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Card, CardContent } from '@/components/ui/card'
import { MetricTile } from '@/components/ui/metric-tile'
import { cn } from '@/lib/utils'
import {
  getExpenses, getPnl, getTaxes,
  type PnlTotals,
} from '@/services/booksService'
import { exportTable } from '@/services/booksExport'
import { Loading, NoCompany, TableCard, Th } from './OfficePanels'
import { useWorkspaceSections } from './workspaceSections'

const money = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const MONTHS = ['', 'январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль',
  'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь']

const monthLabel = (m: string) => {
  const [y, mm] = m.split('-')
  return `${MONTHS[Number(mm)] ?? mm} ${y}`
}

/** Кнопки выгрузки — те же, что в «Реализации»: Excel и PDF печатью браузера. */
function ExportButton({ onClick }: { onClick: () => void }) {
  const cls = 'inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs '
    + 'text-muted-foreground hover:bg-muted/50'
  return (
    <div className="inline-flex items-center gap-1 no-print">
      <button onClick={onClick} className={cls}><Download className="h-3.5 w-3.5" />Excel</button>
      <button onClick={() => window.print()} className={cls} title="Печать или сохранение в PDF">
        <Printer className="h-3.5 w-3.5" />PDF
      </button>
    </div>
  )
}

export function EconomyPanel() {
  const { coreMode } = useWorkspace()
  const sections = useWorkspaceSections()
  const items = sections.find((s) => s.mode === coreMode)?.items ?? []
  const [sub] = useWorkspaceSubView(items[0]?.key ?? '', items.map((i) => i.key))
  const { companyId } = useCompany()
  const { period } = useFilters()

  if (!companyId) return <NoCompany />
  if (!items.length) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        В этом разделе нет доступных вам экранов. Права выдаются в «Управлении».
      </div>
    )
  }

  const view = (() => {
    switch (sub) {
      case 'ec_dynamics':   return <EconDynamics companyId={companyId} period={period} />
      case 'ec_breakeven':  return <EconBreakeven companyId={companyId} period={period} />
      case 'ec_costs':      return <EconCosts companyId={companyId} period={period} view="structure" />
      case 'ec_costs_time': return <EconCosts companyId={companyId} period={period} view="months" />
      case 'ec_taxes':      return <EconTaxes companyId={companyId} period={period} view="list" />
      case 'ec_load':       return <EconTaxes companyId={companyId} period={period} view="load" />
      default:              return <EconPnl companyId={companyId} period={period} />
    }
  })()

  return (
    <div className="h-full flex flex-col">
      <ScrollArea className="flex-1 min-h-0">{view}</ScrollArea>
    </div>
  )
}

function usePnl(companyId: string, period: Period) {
  return useQuery({
    queryKey: ['books', 'pnl', companyId, period.from, period.to],
    queryFn: () => getPnl(companyId, period),
    enabled: !!companyId,
  })
}

/** Строки отчёта в порядке формы 2 — от выручки к чистой прибыли. */
const PNL_LINES: { key: keyof PnlTotals; label: string; strong?: boolean; minus?: boolean }[] = [
  { key: 'revenue', label: 'Выручка с НДС' },
  { key: 'vat', label: 'НДС с продаж', minus: true },
  { key: 'net', label: 'Выручка без НДС', strong: true },
  { key: 'cogs', label: 'Себестоимость продаж', minus: true },
  { key: 'gross', label: 'Валовая прибыль', strong: true },
  { key: 'commercial', label: 'Коммерческие расходы', minus: true },
  { key: 'admin', label: 'Управленческие расходы', minus: true },
  { key: 'operating', label: 'Прибыль от продаж', strong: true },
  { key: 'otherIncome', label: 'Прочие доходы' },
  { key: 'otherExpense', label: 'Прочие расходы', minus: true },
  { key: 'beforeTax', label: 'Прибыль до налога', strong: true },
  { key: 'tax', label: 'Налог на прибыль', minus: true },
  { key: 'profit', label: 'Чистая прибыль', strong: true },
]

/**
 * Отчёт о финансовых результатах — единственный экран, отвечающий собственнику
 * целиком. Рядом с расчётной прибылью стоит то, что бухгалтерия закрыла на 84 счёт:
 * расхождение обычно означает незакрытый период, и это ответ, а не ошибка витрины.
 */
function EconPnl({ companyId, period }: { companyId: string; period: Period }) {
  const q = usePnl(companyId, period)
  if (q.isError) return <div className="p-4"><QueryError onRetry={() => q.refetch()} /></div>
  if (!q.data) return <Loading />
  const d = q.data
  const t = d.totals
  const diff = round2(t.profit - d.closedToRetained)

  return (
    <div className="p-4 space-y-4">
      <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
        <MetricTile label="Выручка без НДС" value={money.format(t.net) + ' ₽'}
          hint={`с НДС ${money.format(t.revenue)} ₽`} />
        <MetricTile label="Валовая прибыль" value={money.format(t.gross) + ' ₽'}
          hint={t.grossPct === null ? undefined : `${t.grossPct} % от выручки`} />
        <MetricTile label="Прибыль от продаж" value={money.format(t.operating) + ' ₽'}
          hint={t.operatingPct === null ? undefined : `${t.operatingPct} % от выручки`} />
        <MetricTile label="Чистая прибыль" value={money.format(t.profit) + ' ₽'}
          hint={t.profitPct === null ? undefined : `${t.profitPct} % от выручки`}
          tone={t.profit > 0 ? 'success' : 'danger'} />
      </div>

      <div className="flex justify-end">
        <ExportButton onClick={() => exportTable('Финансовый результат', [
          { header: 'Показатель', key: 'label', width: 34 },
          { header: 'Сумма', key: 'amount', width: 18, money: true },
        ], PNL_LINES.map((l) => ({ label: l.label, amount: t[l.key] as number })))} />
      </div>

      <TableCard note="Обороты счетов результата за период: 90 (продажи), 91 (прочее), 99 (налог)"
        head={<><Th>Показатель</Th><Th right>Сумма</Th><Th right>К выручке</Th></>}>
        {PNL_LINES.map((l) => {
          const v = t[l.key] as number
          return (
            <tr key={l.key} className={cn('border-b last:border-0',
              l.strong ? 'font-medium bg-muted/30' : '')}>
              <td className="px-3 py-1.5">
                {l.minus && <span className="text-muted-foreground mr-1">−</span>}
                {l.label}
              </td>
              <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
                {money.format(v)} ₽
              </td>
              <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
                {t.net ? `${((v / t.net) * 100).toFixed(1)} %` : '—'}
              </td>
            </tr>
          )
        })}
      </TableCard>

      <Card>
        <CardContent className="p-4 space-y-1">
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
            Сверка с бухгалтерией
          </div>
          <div className="text-sm">
            Закрыто на нераспределённую прибыль (84 счёт):{' '}
            <b className="tabular-nums">{money.format(d.closedToRetained)} ₽</b>
            {Math.abs(diff) > 1 && (
              <span className="text-muted-foreground">
                {' '}· расхождение с расчётом {money.format(diff)} ₽
              </span>
            )}
          </div>
          <p className="text-[11px] text-muted-foreground">
            Расхождение — обычно незакрытый период: реформация баланса делается в конце
            года, и прибыль текущих месяцев на 84 счёт ещё не перенесена. Если период
            закрыт, а разница осталась, это вопрос к бухгалтерии компании.
          </p>
        </CardContent>
      </Card>
    </div>
  )
}

const round2 = (v: number) => Math.round(v * 100) / 100

/** Динамика результата по годам и месяцам плюс три рентабельности. */
function EconDynamics({ companyId, period }: { companyId: string; period: Period }) {
  const q = usePnl(companyId, period)
  if (q.isError) return <div className="p-4"><QueryError onRetry={() => q.refetch()} /></div>
  if (!q.data) return <Loading />
  const d = q.data
  const months = d.months.filter((m) => m.net || m.profit)
  const maxAbs = Math.max(...months.map((m) => Math.abs(m.profit)), 1)

  return (
    <div className="p-4 space-y-4">
      <Card>
        <CardContent className="p-4">
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground mb-3">
            Прибыль по месяцам — вверх прибыль, вниз убыток
          </div>
          <div className="flex items-center gap-1 overflow-x-auto" style={{ height: 190 }}>
            {months.map((m) => {
              const h = Math.max(1, (Math.abs(m.profit) / maxAbs) * 74)
              return (
                <div key={m.month} className="flex flex-col items-center min-w-[24px] flex-1"
                  title={`${monthLabel(m.month)}: выручка ${money.format(m.net)} ₽, `
                    + `прибыль ${money.format(m.profit)} ₽`}>
                  <div className="w-full flex flex-col justify-end" style={{ height: 76 }}>
                    {m.profit > 0 && (
                      <div className="w-full rounded-t bg-emerald-500/60" style={{ height: h }} />
                    )}
                  </div>
                  <div className="w-full" style={{ height: 76 }}>
                    {m.profit < 0 && (
                      <div className="w-full rounded-b bg-rose-500/60" style={{ height: h }} />
                    )}
                  </div>
                  <div className="text-[9px] text-muted-foreground rotate-45 origin-left h-6 whitespace-nowrap">
                    {m.month.slice(2)}
                  </div>
                </div>
              )
            })}
          </div>
        </CardContent>
      </Card>

      <div className="flex justify-end">
        <ExportButton onClick={() => exportTable('Динамика результата', [
          { header: 'Год', key: 'year', width: 8 },
          { header: 'Выручка без НДС', key: 'net', width: 18, money: true },
          { header: 'Валовая прибыль', key: 'gross', width: 18, money: true },
          { header: 'Прибыль от продаж', key: 'operating', width: 18, money: true },
          { header: 'Чистая прибыль', key: 'profit', width: 18, money: true },
          { header: 'Чистая, %', key: 'profitPct', width: 12 },
        ], d.years)} />
      </div>

      <TableCard note="По годам: выручка, три уровня прибыли и рентабельность"
        head={<><Th>Год</Th><Th right>Выручка</Th><Th right>Валовая</Th><Th right>От продаж</Th>
          <Th right>Чистая</Th><Th right>Валовая, %</Th><Th right>Чистая, %</Th></>}>
        {[...d.years].reverse().map((y) => (
          <tr key={y.year} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5 tabular-nums">{y.year}</td>
            <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
              {money.format(y.net)} ₽
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
              {money.format(y.gross)} ₽
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
              {money.format(y.operating)} ₽
            </td>
            <td className={cn('px-3 py-1.5 text-right tabular-nums whitespace-nowrap',
              y.profit >= 0 ? 'text-emerald-600 dark:text-emerald-400'
                : 'text-rose-600 dark:text-rose-400')}>
              {money.format(y.profit)} ₽
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
              {y.grossPct === null ? '—' : `${y.grossPct} %`}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
              {y.profitPct === null ? '—' : `${y.profitPct} %`}
            </td>
          </tr>
        ))}
      </TableCard>
    </div>
  )
}

/**
 * Точка безубыточности. Деления затрат на постоянные и переменные в учёте нет, и
 * выдумывать его нельзя — поэтому берём приближение, честно названное на экране:
 * переменные это себестоимость продаж (растёт вместе с отгрузкой), постоянные —
 * коммерческие и управленческие расходы (не зависят от одной сделки).
 */
function EconBreakeven({ companyId, period }: { companyId: string; period: Period }) {
  const q = usePnl(companyId, period)
  if (q.isError) return <div className="p-4"><QueryError onRetry={() => q.refetch()} /></div>
  if (!q.data) return <Loading />
  const t = q.data.totals
  const fixed = t.commercial + t.admin
  const marginPct = t.net ? (t.net - t.cogs) / t.net : 0
  const point = marginPct > 0 ? fixed / marginPct : null
  const safety = point && t.net ? ((t.net - point) / t.net) * 100 : null

  return (
    <div className="p-4 space-y-4">
      <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
        <MetricTile label="Постоянные расходы" value={money.format(fixed) + ' ₽'}
          hint="коммерческие и управленческие за период" />
        <MetricTile label="Маржинальность" value={`${(marginPct * 100).toFixed(1)} %`}
          hint="доля, остающаяся после себестоимости" />
        <MetricTile label="Точка безубыточности"
          value={point === null ? '—' : money.format(point) + ' ₽'}
          hint="выручка без НДС, при которой прибыль от продаж равна нулю" />
        <MetricTile label="Запас прочности"
          value={safety === null ? '—' : `${safety.toFixed(1)} %`}
          hint={safety === null ? undefined
            : safety > 0 ? 'на столько может упасть выручка' : 'выручка ниже точки'}
          tone={safety !== null && safety > 0 ? 'success' : 'danger'} />
      </div>

      <Card>
        <CardContent className="p-4 space-y-2 text-sm">
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
            Как считается
          </div>
          <p>
            Выручка без НДС <b className="tabular-nums">{money.format(t.net)} ₽</b> минус
            себестоимость <b className="tabular-nums">{money.format(t.cogs)} ₽</b> даёт
            маржинальный доход <b className="tabular-nums">{money.format(t.net - t.cogs)} ₽</b>{' '}
            ({(marginPct * 100).toFixed(1)} % выручки). Постоянные расходы{' '}
            <b className="tabular-nums">{money.format(fixed)} ₽</b> делятся на эту долю —
            получается выручка, покрывающая расходы ровно в ноль.
          </p>
          <p className="text-[11px] text-muted-foreground">
            Деления затрат на постоянные и переменные в бухгалтерском учёте нет. Здесь
            принято приближение: переменные — себестоимость продаж (растёт вместе с
            отгрузкой), постоянные — коммерческие и управленческие расходы. Если часть
            коммерческих расходов у компании сдельная, точка сдвинется вниз.
          </p>
        </CardContent>
      </Card>
    </div>
  )
}

/** Структура затрат: счёт затрат и то, откуда затрата пришла. */
function EconCosts({ companyId, period, view }: {
  companyId: string; period: Period; view: 'structure' | 'months'
}) {
  const q = useQuery({
    queryKey: ['books', 'expenses', companyId, period.from, period.to],
    queryFn: () => getExpenses(companyId, period),
    enabled: !!companyId,
  })
  const [open, setOpen] = useState<string | null>(null)

  if (q.isError) return <div className="p-4"><QueryError onRetry={() => q.refetch()} /></div>
  if (!q.data) return <Loading />
  const d = q.data
  if (!d.total) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        За выбранный период затрат в учёте нет.
      </div>
    )
  }

  if (view === 'months') {
    const max = Math.max(...d.months.map((m) => m.amount), 1)
    return (
      <div className="p-4 space-y-4">
        <Card>
          <CardContent className="p-4">
            <div className="text-[11px] uppercase tracking-wider text-muted-foreground mb-3">
              Затраты помесячно — всего {money.format(d.total)} ₽
            </div>
            <div className="flex items-end gap-1 overflow-x-auto" style={{ height: 160 }}>
              {d.months.map((m) => (
                <div key={m.month} className="flex flex-col items-center gap-1 min-w-[26px] flex-1"
                  title={`${monthLabel(m.month)}: ${money.format(m.amount)} ₽`}>
                  <div className="w-full rounded-t bg-primary/60"
                    style={{ height: `${Math.max(2, (m.amount / max) * 120)}px` }} />
                  <div className="text-[9px] text-muted-foreground rotate-45 origin-left h-6 whitespace-nowrap">
                    {m.month.slice(2)}
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
        <TableCard note="Месяц: сколько затрат признано в учёте"
          head={<><Th>Месяц</Th><Th right>Затраты</Th><Th right>Доля</Th></>}>
          {[...d.months].reverse().map((m) => (
            <tr key={m.month} className="border-b last:border-0 hover:bg-muted/40">
              <td className="px-3 py-1.5">{monthLabel(m.month)}</td>
              <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
                {money.format(m.amount)} ₽
              </td>
              <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
                {((m.amount / d.total) * 100).toFixed(1)} %
              </td>
            </tr>
          ))}
        </TableCard>
      </div>
    )
  }

  return (
    <div className="p-4 space-y-4">
      <div className="grid gap-3 grid-cols-3">
        {d.accounts.slice(0, 3).map((a) => (
          <MetricTile key={a.account} label={a.name ?? a.account}
            value={money.format(a.amount) + ' ₽'}
            hint={`счёт ${a.account} · ${((a.amount / d.total) * 100).toFixed(1)} % затрат`} />
        ))}
      </div>

      <div className="flex justify-end">
        <ExportButton onClick={() => exportTable('Структура затрат', [
          { header: 'Счёт затрат', key: 'account', width: 12 },
          { header: 'Наименование', key: 'accountName', width: 40 },
          { header: 'Источник', key: 'source', width: 12 },
          { header: 'Что это', key: 'sourceName', width: 40 },
          { header: 'Сумма', key: 'amount', width: 18, money: true },
        ], d.rows)} />
      </div>

      <TableCard
        note="Счёт затрат раскрывается источником: поставщик, зарплата, взносы, амортизация"
        head={<><Th>Счёт</Th><Th>Статья</Th><Th right>Сумма</Th><Th right>Доля</Th></>}>
        {d.accounts.map((a) => [
          <tr key={a.account} className="border-b hover:bg-muted/40">
            <td className="px-3 py-1.5 tabular-nums">
              <button onClick={() => setOpen(open === a.account ? null : a.account)}
                className="hover:text-primary hover:underline">{a.account}</button>
            </td>
            <td className="px-3 py-1.5">{a.name ?? '—'}</td>
            <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap font-medium">
              {money.format(a.amount)} ₽
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
              {((a.amount / d.total) * 100).toFixed(1)} %
            </td>
          </tr>,
          ...(open === a.account ? a.sources.map((src) => (
            <tr key={`${a.account}-${src.source}`} className="border-b last:border-0 bg-muted/20">
              <td className="px-3 py-1 text-[11px] text-muted-foreground tabular-nums">
                ← {src.source}
              </td>
              <td className="px-3 py-1 text-[11px] text-muted-foreground">
                {src.sourceName ?? '—'}
              </td>
              <td className="px-3 py-1 text-right tabular-nums text-muted-foreground whitespace-nowrap">
                {money.format(src.amount)} ₽
              </td>
              <td className="px-3 py-1 text-right text-[11px] text-muted-foreground">
                {src.entries} проводок
              </td>
            </tr>
          )) : []),
        ])}
      </TableCard>
    </div>
  )
}

/** Налоги и взносы: начислено, уплачено, задолженность и нагрузка. */
function EconTaxes({ companyId, period, view }: {
  companyId: string; period: Period; view: 'list' | 'load'
}) {
  const q = useQuery({
    queryKey: ['books', 'taxes', companyId, period.from, period.to],
    queryFn: () => getTaxes(companyId, period),
    enabled: !!companyId,
  })

  if (q.isError) return <div className="p-4"><QueryError onRetry={() => q.refetch()} /></div>
  if (!q.data) return <Loading />
  const d = q.data

  if (view === 'load') {
    const max = Math.max(...d.months.map((m) => Math.max(m.accrued, m.paid)), 1)
    return (
      <div className="p-4 space-y-4">
        <div className="grid gap-3 grid-cols-3">
          <MetricTile label="Уплачено налогов" value={money.format(d.paid) + ' ₽'}
            hint="деньгами с расчётного счёта" />
          <MetricTile label="Нагрузка на выручку"
            value={d.loadPct === null ? '—' : `${d.loadPct} %`}
            hint={`от выручки без НДС ${money.format(d.revenueNet)} ₽`} />
          <MetricTile label="Начислено по регистру" value={money.format(d.accrued) + ' ₽'}
            hint={d.accruedPct === null ? undefined : `${d.accruedPct} % — это не нагрузка`} />
        </div>

        <p className="text-[11px] text-muted-foreground">
          Нагрузка считается от УПЛАЧЕННОГО — так её определяет и налоговая служба.
          Начисленный оборот по счетам 68 и 69 для этого не годится: кредит 68.02 несёт
          весь НДС с продаж, тогда как в бюджет уходит разница с вычетами по покупкам.
        </p>

        <Card>
          <CardContent className="p-4">
            <div className="text-[11px] uppercase tracking-wider text-muted-foreground mb-3">
              Помесячно: начислено (сверху) и уплачено (снизу)
            </div>
            <div className="flex items-center gap-1 overflow-x-auto" style={{ height: 190 }}>
              {d.months.map((m) => (
                <div key={m.month} className="flex flex-col items-center min-w-[24px] flex-1"
                  title={`${monthLabel(m.month)}: начислено ${money.format(m.accrued)} ₽, `
                    + `уплачено ${money.format(m.paid)} ₽`}>
                  <div className="w-full flex flex-col justify-end" style={{ height: 76 }}>
                    <div className="w-full rounded-t bg-primary/50"
                      style={{ height: `${Math.max(1, (m.accrued / max) * 74)}px` }} />
                  </div>
                  <div className="w-full" style={{ height: 76 }}>
                    <div className="w-full rounded-b bg-emerald-500/60"
                      style={{ height: `${Math.max(1, (m.paid / max) * 74)}px` }} />
                  </div>
                  <div className="text-[9px] text-muted-foreground rotate-45 origin-left h-6 whitespace-nowrap">
                    {m.month.slice(2)}
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="p-4 space-y-4">
      <div className="grid gap-3 grid-cols-3">
        <MetricTile label="Начислено" value={money.format(d.accrued) + ' ₽'} />
        <MetricTile label="Уплачено" value={money.format(d.paid) + ' ₽'} />
        <MetricTile label="Разница" value={money.format(d.accrued - d.paid) + ' ₽'}
          hint="не задолженность: часть НДС закрывается вычетами, а не деньгами" />
      </div>

      <div className="flex justify-end">
        <ExportButton onClick={() => exportTable('Налоги и взносы', [
          { header: 'Счёт', key: 'account', width: 12 },
          { header: 'Налог', key: 'name', width: 40 },
          { header: 'Начислено', key: 'accrued', width: 18, money: true },
          { header: 'Уплачено', key: 'paid', width: 18, money: true },
          { header: 'Разница', key: 'rest', width: 18, money: true },
        ], d.rows)} />
      </div>

      <TableCard note="Начислено — кредит счетов 68 и 69; уплачено — их дебет в корреспонденции с деньгами"
        head={<><Th>Счёт</Th><Th>Налог или взнос</Th><Th right>Начислено</Th>
          <Th right>Уплачено</Th><Th right>Разница</Th></>}>
        {d.rows.map((r) => (
          <tr key={r.account} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5 tabular-nums">{r.account}</td>
            <td className="px-3 py-1.5 max-w-[360px] truncate" title={r.name}>{r.name}</td>
            <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
              {money.format(r.accrued)} ₽
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
              {money.format(r.paid)} ₽
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground whitespace-nowrap">
              {money.format(r.rest)} ₽
            </td>
          </tr>
        ))}
      </TableCard>
    </div>
  )
}
