/**
 * «Экономика» (`econ`) — сколько компания заработала.
 *
 * До этого продукта пространство показывало правую половину отчёта: «Реализация»
 * отвечала, сколько продали и когда заплатят, «Бухгалтерия» — что лежит в регистре.
 * Куда уходят деньги и что осталось, не отвечал никто, хотя проводки для этого
 * приехали с первой выгрузкой.
 *
 * Три раздела по вопросу: «Результат» (как образуется прибыль, отчёт, доходы,
 * динамика, безубыточность), «Расходы» (за что платим), «Налоги» (сколько отдаём).
 *
 * Числа считает бэкенд по ОБОРОТАМ счетов результата, а не по документам, и
 * двусторонне (возврат обратной записью вычитается). Фронт складывает только то,
 * чего в ответе нет по природе: свёртку месяцев в кварталы и годы и сравнение
 * периодов между собой.
 */
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { useCompany } from '@/contexts/CompanyContext'
import { useFilters, type Period } from '@/contexts/FilterContext'
import { useWorkspace, useWorkspaceSubView } from '@/contexts/WorkspaceContext'
import { QueryError } from '@/components/common/QueryError'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Card, CardContent } from '@/components/ui/card'
import { MetricTile } from '@/components/ui/metric-tile'
import { cn } from '@/lib/utils'
import {
  getCostBridge, getExpenses, getPnl, getPnlEntries, getRevenue, getTaxes,
  type PnlData, type PnlTotals,
} from '@/services/booksService'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { exportTable } from '@/services/booksExport'
import { Loading, NoCompany, TableCard, Th } from './OfficePanels'
import { ProductHelpPanel } from './ProductHelpPanel'
import { ECONOMY_HELP_SLICES } from './helpSlices'
import {
  ECON_RESULT_MENU, ECON_COSTS_MENU, ECON_TAXES_MENU,
} from '@/config/workspaceMenus'
import { useWorkspaceSections } from './workspaceSections'
import { ExportButton, Tabs, money, money2, monthLabel, num } from './officeShared'

/** Все пункты продукта — по ним статья находит подпись экрана и кнопку перехода. */
const ECON_MENU_FOR_HELP = [...ECON_RESULT_MENU, ...ECON_COSTS_MENU, ...ECON_TAXES_MENU]

const modeForHelpKey = (key: string): string =>
  ECON_COSTS_MENU.some((m) => m.key === key) ? 'econ_costs'
  : ECON_TAXES_MENU.some((m) => m.key === key) ? 'econ_taxes'
  : 'econ_result'


/* ── Периоды сравнения (та же арифметика, что в «Реализации») ─────────────── */

const isDate = (iso: string | undefined | null): iso is string =>
  !!iso && /^\d{4}-\d{2}-\d{2}$/.test(iso)

const shiftDays = (iso: string, days: number) => {
  if (!isDate(iso)) return iso ?? ''
  const d = new Date(`${iso}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}

const shiftYears = (iso: string, years: number) => {
  if (!isDate(iso)) return iso ?? ''
  const d = new Date(`${iso}T00:00:00Z`)
  d.setUTCFullYear(d.getUTCFullYear() + years)
  return d.toISOString().slice(0, 10)
}

const lengthDays = (p: Period) =>
  isDate(p.from) && isDate(p.to)
    ? Math.round((Date.parse(p.to) - Date.parse(p.from)) / 86400000) + 1
    : 0

const prevPeriod = (p: Period): Period => {
  const len = lengthDays(p)
  if (!len) return p
  return { from: shiftDays(p.from, -len), to: shiftDays(p.to, -len) }
}

const yearAgo = (p: Period): Period => ({
  from: shiftYears(p.from, -1), to: shiftYears(p.to, -1),
})

const periodLabel = (p: Period) => `${p.from} — ${p.to}`

/* ── Общие мелочи ────────────────────────────────────────────────────────── */

/**
 * Изменение к базе. Процент не печатается на малых базах: «рост в восемь раз» с
 * 30 до 240 тысяч — это не рост, а эффект знаменателя (правило малых чисел из
 * практики статистики).
 */
function Delta({ now, was, min = 10000 }: { now: number; was: number; min?: number }) {
  if (!was || Math.abs(was) < min) {
    return <span className="text-muted-foreground text-xs">база мала</span>
  }
  const pct = ((now - was) / Math.abs(was)) * 100
  const up = pct >= 0
  return (
    <span className={cn('tabular-nums',
      up ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400')}>
      {up ? '+' : ''}{pct.toFixed(1)} %
    </span>
  )
}

/** Пустое состояние: ноль в отчёте и отсутствие данных — разные ответы. */
function NoData({ salesEntries }: { salesEntries?: number }) {
  return (
    <div className="p-6 text-sm text-muted-foreground space-y-2">
      <p>За выбранный период оборотов по счетам результата нет.</p>
      {salesEntries === 0 && (
        <p>
          Проводок по счёту 90 не найдено вовсе. Если продажи в этом периоде были,
          значит в плане счетов компании они учитываются под другими кодами — отчёт
          построен на типовых 90, 91 и 99.
        </p>
      )}
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

  // Помощь — общий компонент пространства: тот же свод «Инфо», суженный до продукта.
  if (coreMode === 'econ_help') {
    return (
      <ProductHelpPanel companyId={companyId} section={sub} appCode="econ"
        slices={ECONOMY_HELP_SLICES} menu={ECON_MENU_FOR_HELP} modeForKey={modeForHelpKey} />
    )
  }

  const view = (() => {
    switch (sub) {
      case 'ec_pnl':        return <EconPnl companyId={companyId} period={period} />
      case 'ec_income':     return <EconIncome companyId={companyId} period={period} />
      case 'ec_dynamics':   return <EconDynamics companyId={companyId} period={period} />
      case 'ec_breakeven':  return <EconBreakeven companyId={companyId} period={period} />
      case 'ec_items':      return <EconCosts companyId={companyId} period={period} view="items" />
      case 'ec_costs':      return <EconCosts companyId={companyId} period={period} view="structure" />
      case 'ec_costs_time': return <EconCosts companyId={companyId} period={period} view="months" />
      case 'ec_bridge_cost': return <EconCostBridge companyId={companyId} period={period} />
      case 'ec_taxes':      return <EconTaxes companyId={companyId} period={period} view="list" />
      case 'ec_load':       return <EconTaxes companyId={companyId} period={period} view="load" />
      default:              return <EconBridge companyId={companyId} period={period} />
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

/* ────────────────────────────────────────────────────────────── */
/*                    Как образуется результат                    */
/* ────────────────────────────────────────────────────────────── */

/** Шаги моста: что вычитается из выручки и какие итоги стоят опорами. */
const BRIDGE: { key: keyof PnlTotals; label: string; kind: 'start' | 'minus' | 'plus' | 'total' }[] = [
  { key: 'net', label: 'Выручка без НДС', kind: 'start' },
  { key: 'cogsTotal', label: 'Себестоимость', kind: 'minus' },
  { key: 'gross', label: 'Валовая прибыль', kind: 'total' },
  { key: 'commercial', label: 'Коммерческие', kind: 'minus' },
  { key: 'admin', label: 'Управленческие', kind: 'minus' },
  { key: 'operating', label: 'Прибыль от продаж', kind: 'total' },
  { key: 'otherIncome', label: 'Прочие доходы', kind: 'plus' },
  { key: 'otherExpense', label: 'Прочие расходы', kind: 'minus' },
  { key: 'interest', label: 'Проценты', kind: 'minus' },
  { key: 'tax', label: 'Налог', kind: 'minus' },
  { key: 'profit', label: 'Чистая прибыль', kind: 'total' },
]

/**
 * Мост прибыли — ответ на «непонятно, как образуется результат»: не список строк, а
 * путь от выручки к тому, что осталось.
 *
 * Переключатель «₽ / % от выручки» обязателен, а не украшение: при рентабельности
 * 2,9 % последний столбец в рублях составляет три сотых высоты первого и физически
 * не виден. Разрыв оси не используем — он ломает сопоставимость площадей.
 */
function EconBridge({ companyId, period }: { companyId: string; period: Period }) {
  const q = usePnl(companyId, period)
  const [mode, setMode] = useState<'money' | 'pct'>('money')

  if (q.isError) return <div className="p-4"><QueryError onRetry={() => q.refetch()} /></div>
  if (!q.data) return <Loading />
  const d = q.data
  const t = d.totals
  if (!t.net && !t.revenue) return <NoData salesEntries={d.salesEntries} />

  const base = t.net || 1
  const val = (k: keyof PnlTotals) => (t[k] as number) ?? 0
  const shown = BRIDGE.filter((b) => b.kind === 'start' || b.kind === 'total' || val(b.key))
  const max = Math.max(...shown.map((b) => Math.abs(val(b.key))), 1)

  // Накопленный уровень: столбик вычитаемой статьи «висит» от предыдущего итога.
  let level = 0
  const bars = shown.map((b) => {
    const v = val(b.key)
    if (b.kind === 'start' || b.kind === 'total') {
      level = v
      return { ...b, value: v, from: 0, to: v }
    }
    const from = level
    level = b.kind === 'minus' ? level - v : level + v
    return { ...b, value: v, from: Math.min(from, level), to: Math.max(from, level) }
  })

  const fmt = (v: number) => mode === 'money'
    ? `${money.format(v)} ₽`
    : `${((v / base) * 100).toFixed(1)} %`

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <Tabs value={mode} onChange={setMode} items={[
          { key: 'money' as const, label: 'В рублях' },
          { key: 'pct' as const, label: 'В % от выручки' },
        ]} />
        <ExportButton onClick={() => exportTable('Образование результата', [
          { header: 'Шаг', key: 'label', width: 30 },
          { header: 'Сумма', key: 'value', width: 18, money: true },
          { header: 'Доля от выручки, %', key: 'pct', width: 18 },
        ], bars.map((b) => ({ label: b.label, value: b.value,
                              pct: Number(((b.value / base) * 100).toFixed(1)) })))} />
      </div>

      <Card>
        <CardContent className="p-4">
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground mb-4">
            От выручки к прибыли — {periodLabel(period)}
          </div>
          <div className="flex items-end gap-2 overflow-x-auto pb-2" style={{ height: 300 }}>
            {bars.map((b) => {
              const h = Math.max(2, ((b.to - b.from) / max) * 200)
              const bottom = (Math.max(0, b.from) / max) * 200
              return (
                <div key={b.key} className="flex flex-col items-center gap-1 min-w-[76px] flex-1">
                  <div className="text-[11px] tabular-nums whitespace-nowrap">{fmt(b.value)}</div>
                  <div className="relative w-full" style={{ height: 210 }}>
                    <div className={cn('absolute w-full rounded-sm',
                      b.kind === 'total' ? 'bg-primary/70'
                      : b.kind === 'minus' ? 'bg-rose-500/60'
                      : 'bg-emerald-500/60')}
                      style={{ height: h, bottom }} />
                  </div>
                  <div className="text-[10px] text-center text-muted-foreground leading-tight">
                    {b.label}
                  </div>
                </div>
              )
            })}
          </div>
          <p className="text-[11px] text-muted-foreground pt-2">
            Синие столбцы — итоги, красные вычитаются, зелёные добавляются. При
            рентабельности {t.profitPct ?? '—'} % последний столбец в рублях почти не виден —
            для этого рядом режим «в % от выручки».
            {d.adminInCogs && ' Управленческие расходы у компании закрываются через '
              + 'себестоимость (директ-костинг выключен), поэтому в отчёте они выделены '
              + 'отдельной строкой, а не спрятаны внутри неё.'}
          </p>
        </CardContent>
      </Card>
    </div>
  )
}

/* ────────────────────────────────────────────────────────────── */
/*                     Отчёт о результате                         */
/* ────────────────────────────────────────────────────────────── */

const PNL_LINES: { key: keyof PnlTotals; label: string; strong?: boolean; minus?: boolean }[] = [
  { key: 'revenue', label: 'Выручка с НДС' },
  { key: 'vat', label: 'НДС с продаж', minus: true },
  { key: 'excise', label: 'Акцизы и пошлины', minus: true },
  { key: 'net', label: 'Выручка без НДС', strong: true },
  { key: 'cogs', label: 'Себестоимость товаров и продукции', minus: true },
  { key: 'cogsOther', label: 'Прочая себестоимость', minus: true },
  { key: 'gross', label: 'Валовая прибыль', strong: true },
  { key: 'commercial', label: 'Коммерческие расходы', minus: true },
  { key: 'admin', label: 'Управленческие расходы', minus: true },
  { key: 'operating', label: 'Прибыль от продаж', strong: true },
  { key: 'otherIncome', label: 'Прочие доходы' },
  { key: 'otherExpense', label: 'Прочие расходы', minus: true },
  { key: 'interest', label: 'Проценты к уплате', minus: true },
  { key: 'beforeTax', label: 'Прибыль до налога', strong: true },
  { key: 'tax', label: 'Налог на прибыль', minus: true },
  { key: 'profit', label: 'Чистая прибыль', strong: true },
]

/**
 * Отчёт с колонками сравнения. Прошлый период и тот же период годом раньше стоят
 * рядом со своей строкой — вертикальный и горизонтальный анализ разом, и это дешевле
 * любого графика.
 */
/** Строки, за которыми стоит однозначная пара счетов (см. PNL_DRILL на бэкенде). */
const DRILLABLE = new Set<keyof PnlTotals>(['revenue', 'vat', 'cogs', 'cogsOther',
  'commercial', 'admin', 'otherIncome', 'otherExpense', 'interest', 'tax'])

function EconPnl({ companyId, period }: { companyId: string; period: Period }) {
  const q = usePnl(companyId, period)
  const [base, setBase] = useState<'prev' | 'year'>('prev')
  const [drill, setDrill] = useState<string | null>(null)
  const other = base === 'prev' ? prevPeriod(period) : yearAgo(period)
  const b = usePnl(companyId, other)

  if (q.isError || b.isError) {
    return (
      <div className="p-4">
        <QueryError onRetry={() => { q.refetch(); b.refetch() }} />
      </div>
    )
  }
  if (!q.data) return <Loading />
  const d = q.data
  const t = d.totals
  if (!t.net && !t.revenue) return <NoData salesEntries={d.salesEntries} />
  const bt = b.data?.totals
  const diff = Math.round((t.profit - d.closedToRetained) * 100) / 100

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

      <div className="flex items-center justify-between gap-3 flex-wrap">
        <Tabs value={base} onChange={setBase} items={[
          { key: 'prev' as const, label: 'Против предыдущего периода' },
          { key: 'year' as const, label: 'Против прошлого года' },
        ]} />
        <ExportButton onClick={() => exportTable('Отчёт о результате', [
          { header: 'Показатель', key: 'label', width: 36 },
          { header: 'Сумма', key: 'amount', width: 18, money: true },
          { header: 'Доля от выручки, %', key: 'share', width: 18 },
          { header: 'База сравнения', key: 'was', width: 18, money: true },
        ], PNL_LINES.map((l) => ({
          label: l.label,
          // Вычитаемые строки выгружаются со знаком: в Excel столбец должен
          // складываться во что-то осмысленное, а не быть набором модулей.
          amount: l.minus ? -(t[l.key] as number) : (t[l.key] as number),
          share: t.net ? Number((((t[l.key] as number) / t.net) * 100).toFixed(1)) : null,
          was: bt ? (l.minus ? -(bt[l.key] as number) : (bt[l.key] as number)) : null,
        })))} />
      </div>

      <TableCard note={`Обороты счетов результата за период. База сравнения — ${periodLabel(other)}`}
        head={<><Th>Показатель</Th><Th right>Сумма</Th><Th right>К выручке</Th>
          <Th right>База</Th><Th right>Изменение</Th></>}>
        {PNL_LINES.map((l) => {
          const v = t[l.key] as number
          const wv = bt ? (bt[l.key] as number) : null
          return (
            <tr key={l.key} className={cn('border-b last:border-0',
              l.strong ? 'font-medium bg-muted/30' : '')}>
              <td className="px-3 py-1.5">
                {l.minus && <span className="text-muted-foreground mr-1">−</span>}
                {/* Строка раскрывается до проводок: цифра, которую нельзя проверить,
                    остаётся предметом веры, а не разбора. */}
                {DRILLABLE.has(l.key) ? (
                  <button onClick={() => setDrill(l.key)}
                    className="text-left hover:text-primary hover:underline">{l.label}</button>
                ) : l.label}
              </td>
              <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
                {money.format(v)} ₽
              </td>
              <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
                {t.net ? `${((v / t.net) * 100).toFixed(1)} %` : '—'}
              </td>
              <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground whitespace-nowrap">
                {wv === null ? (b.isLoading ? '…' : '—') : `${money.format(wv)} ₽`}
              </td>
              <td className="px-3 py-1.5 text-right">
                {wv === null ? '' : <Delta now={v} was={wv} />}
              </td>
            </tr>
          )
        })}
      </TableCard>

      {drill && (
        <PnlEntriesWindow companyId={companyId} period={period} line={drill}
          onClose={() => setDrill(null)} />
      )}

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
            Расхождение объясняется одной из трёх причин: период ещё не закрыт
            (реформация баланса делается в конце года), на 99 счёте есть обороты помимо
            налога и закрытия продаж, либо часть операций учтена на нетиповых счетах.
            Первая причина — обычная и не требует действий.
          </p>
        </CardContent>
      </Card>
    </div>
  )
}

/* ────────────────────────────────────────────────────────────── */
/*                          Доходы                                */
/* ────────────────────────────────────────────────────────────── */

/**
 * Доходная часть отдельным экраном.
 *
 * Выручка и прочие доходы НИКОГДА не в одной строке: прочие неповторяемы и не
 * управляются теми же рычагами (списание кредиторки, страховое возмещение, проценты
 * банка). Смешав их, получаешь рентабельность, которую нельзя ни спрогнозировать, ни
 * воспроизвести. В плане счетов это ровно граница 90 и 91.
 *
 * Структура выручки берётся из «Реализации» — того же источника, что и её экраны:
 * два ответа на один вопрос в соседних продуктах разошлись бы в первую же правку.
 */
function EconIncome({ companyId, period }: { companyId: string; period: Period }) {
  const q = usePnl(companyId, period)
  const r = useQuery({
    queryKey: ['books', 'revenue', companyId, 'all', period.from, period.to],
    queryFn: () => getRevenue(companyId, 'all', { top: 500, from: period.from, to: period.to }),
    enabled: !!companyId,
  })

  if (q.isError) return <div className="p-4"><QueryError onRetry={() => q.refetch()} /></div>
  if (!q.data) return <Loading />
  const d = q.data
  const t = d.totals
  if (!t.net && !t.revenue) return <NoData salesEntries={d.salesEntries} />

  const totalIncome = t.net + t.otherIncome
  const kinds = r.data?.byKind ?? { goods: 0, service: 0 }
  const kindsSum = kinds.goods + kinds.service
  const clients = r.data?.topClients ?? []
  const top5 = clients.slice(0, 5).reduce((s, c) => s + c.amount, 0)
  const clientsTotal = clients.reduce((s, c) => s + c.amount, 0) || 1

  return (
    <div className="p-4 space-y-4">
      <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
        <MetricTile label="Выручка без НДС" value={money.format(t.net) + ' ₽'}
          hint="доход от обычной деятельности" />
        <MetricTile label="Прочие доходы" value={money.format(t.otherIncome) + ' ₽'}
          hint={totalIncome ? `${((t.otherIncome / totalIncome) * 100).toFixed(1)} % всех доходов`
            : undefined} />
        <MetricTile label="НДС в цене" value={money.format(t.vat) + ' ₽'}
          hint="собирается в пользу бюджета, доходом не является" />
        <MetricTile label="Доля топ-5 покупателей"
          value={clients.length ? `${((top5 / clientsTotal) * 100).toFixed(1)} %` : '—'}
          hint={`покупателей за период: ${num.format(clients.length)}`}
          tone={clients.length && top5 / clientsTotal > 0.7 ? 'danger' : undefined} />
      </div>

      <p className="text-[11px] text-muted-foreground">
        Выручка и прочие доходы стоят порознь намеренно: прочие (списание кредиторской
        задолженности, страховое возмещение, проценты банка) не повторяются и не
        управляются теми же рычагами. Смешав их, получаешь рентабельность, которую
        нельзя ни спрогнозировать, ни воспроизвести.
      </p>

      {kindsSum > 0 && (
        <Card>
          <CardContent className="p-4 space-y-2">
            <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
              Из чего выручка — по строкам документов
            </div>
            <div className="flex h-3 rounded overflow-hidden">
              <div className="bg-primary/70" style={{ width: `${(kinds.goods / kindsSum) * 100}%` }} />
              <div className="bg-amber-500/70" style={{ width: `${(kinds.service / kindsSum) * 100}%` }} />
            </div>
            <div className="flex gap-4 text-sm">
              <span>Товары <b className="tabular-nums">{money.format(kinds.goods)} ₽</b>
                <span className="ml-1 text-muted-foreground tabular-nums">
                  {((kinds.goods / kindsSum) * 100).toFixed(1)} %
                </span></span>
              <span>Услуги <b className="tabular-nums">{money.format(kinds.service)} ₽</b>
                <span className="ml-1 text-muted-foreground tabular-nums">
                  {((kinds.service / kindsSum) * 100).toFixed(1)} %
                </span></span>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="flex justify-end">
        <ExportButton onClick={() => exportTable('Доходы по покупателям', [
          { header: 'Покупатель', key: 'name', width: 44 },
          { header: 'ИНН', key: 'inn', width: 14 },
          { header: 'Выручка с НДС', key: 'amount', width: 18, money: true },
          { header: 'Документов', key: 'docs', width: 12 },
        ], clients)} />
      </div>

      <TableCard
        note="Кто принёс выручку за период. Концентрация — главный риск проектных поставок"
        head={<><Th>Покупатель</Th><Th right>Выручка</Th><Th right>Доля</Th>
          <Th right>Документов</Th></>}>
        {clients.length === 0 ? (
          <tr><td colSpan={4} className="px-3 py-3 text-sm text-muted-foreground">
            {r.isLoading ? 'Загружаем…' : 'За период продаж не было'}
          </td></tr>
        ) : clients.slice(0, 30).map((c) => (
          <tr key={c.id ?? c.name} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5 max-w-[360px] truncate" title={c.name}>{c.name}</td>
            <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
              {money.format(c.amount)} ₽
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
              {((c.amount / clientsTotal) * 100).toFixed(1)} %
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">{c.docs}</td>
          </tr>
        ))}
      </TableCard>
    </div>
  )
}

/* ────────────────────────────────────────────────────────────── */
/*                  Динамика и рентабельность                     */
/* ────────────────────────────────────────────────────────────── */

type Grain = 'month' | 'quarter' | 'year' | 'roll12'

const GRAIN_TABS: { key: Grain; label: string }[] = [
  { key: 'month', label: 'Месяц' },
  { key: 'quarter', label: 'Квартал' },
  { key: 'year', label: 'Год' },
  { key: 'roll12', label: 'Скользящие 12' },
]

/** Строка свёрнутого ряда: подпись периода плюс те же показатели отчёта. */
type FoldedRow = { label: string } & Record<string, number>

/** Свёртка помесячных строк отчёта в выбранный разрез. */
function foldMonths(months: PnlData['months'], grain: Grain): FoldedRow[] {
  const sum = (rows: PnlData['months']) => {
    const keys: (keyof PnlTotals)[] = ['revenue', 'vat', 'excise', 'cogs', 'cogsOther',
      'commercial', 'admin', 'otherIncome', 'otherExpense', 'interest', 'tax']
    const acc: Record<string, number> = {}
    for (const k of keys) acc[k] = rows.reduce((s, r) => s + ((r as any)[k] ?? 0), 0)
    acc.net = acc.revenue - acc.vat - acc.excise
    acc.cogsTotal = acc.cogs + acc.cogsOther
    acc.gross = acc.net - acc.cogsTotal
    acc.operating = acc.gross - acc.commercial - acc.admin
    acc.beforeTax = acc.operating + acc.otherIncome - acc.otherExpense - acc.interest
    acc.profit = acc.beforeTax - acc.tax
    return acc
  }

  if (grain === 'roll12') {
    // Скользящие 12 месяцев: сезонность снимается полностью, тренд виден без
    // календарных скачков. Первые одиннадцать точек неполные — их не показываем.
    return months.map((_, i) => (i < 11 ? null : {
      label: monthLabel(months[i].month),
      ...sum(months.slice(i - 11, i + 1)),
    })).filter(Boolean) as FoldedRow[]
  }

  const key = (m: string) =>
    grain === 'year' ? m.slice(0, 4)
    : grain === 'quarter' ? `${m.slice(0, 4)} · ${Math.ceil(Number(m.slice(5, 7)) / 3)} кв.`
    : monthLabel(m)
  const by = new Map<string, PnlData['months']>()
  for (const m of months) {
    const k = key(m.month)
    by.set(k, [...(by.get(k) ?? []), m])
  }
  return [...by.entries()].map(([label, rows]) => ({ label, ...sum(rows) }) as FoldedRow)
}

function EconDynamics({ companyId, period }: { companyId: string; period: Period }) {
  const q = usePnl(companyId, period)
  const [grain, setGrain] = useState<Grain>('month')
  const rows = useMemo(() => foldMonths(q.data?.months ?? [], grain), [q.data, grain])

  if (q.isError) return <div className="p-4"><QueryError onRetry={() => q.refetch()} /></div>
  if (!q.data) return <Loading />
  if (!q.data.months.length) return <NoData salesEntries={q.data.salesEntries} />

  const maxAbs = Math.max(...rows.map((r) => Math.abs(r.profit)), 1)
  const single = rows.length < 2

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <Tabs value={grain} onChange={setGrain} items={GRAIN_TABS} />
        <ExportButton onClick={() => exportTable('Динамика результата', [
          { header: 'Период', key: 'label', width: 18 },
          { header: 'Выручка без НДС', key: 'net', width: 18, money: true },
          { header: 'Валовая прибыль', key: 'gross', width: 18, money: true },
          { header: 'Прибыль от продаж', key: 'operating', width: 18, money: true },
          { header: 'Чистая прибыль', key: 'profit', width: 18, money: true },
        ], rows)} />
      </div>

      {single && (
        <p className="text-[11px] text-muted-foreground">
          В выбранном периоде один интервал — динамику смотреть не на чем. Расширьте
          период в фильтре рабочей области или возьмите более мелкий разрез.
        </p>
      )}

      <Card>
        <CardContent className="p-4">
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground mb-3">
            Прибыль по периодам — вверх прибыль, вниз убыток
          </div>
          <div className="flex items-center gap-1 overflow-x-auto" style={{ height: 200 }}>
            {rows.map((r) => {
              const h = Math.max(1, (Math.abs(r.profit) / maxAbs) * 74)
              return (
                <div key={r.label} className="flex flex-col items-center min-w-[30px] flex-1"
                  title={`${r.label}: выручка ${money.format(r.net)} ₽, прибыль ${money.format(r.profit)} ₽`}>
                  <div className="w-full flex flex-col justify-end" style={{ height: 76 }}>
                    {r.profit > 0 && (
                      <div className="w-full rounded-t bg-emerald-500/60" style={{ height: h }} />
                    )}
                  </div>
                  <div className="w-full" style={{ height: 76 }}>
                    {r.profit < 0 && (
                      <div className="w-full rounded-b bg-rose-500/60" style={{ height: h }} />
                    )}
                  </div>
                  <div className="text-[9px] text-muted-foreground rotate-45 origin-left h-8 whitespace-nowrap">
                    {r.label}
                  </div>
                </div>
              )
            })}
          </div>
        </CardContent>
      </Card>

      <TableCard
        note={grain === 'roll12'
          ? 'Скользящие 12 месяцев: каждая строка — сумма года, заканчивающегося этим месяцем. Сезонность снята, но реакция на изменения запаздывает до года'
          : 'Выручка, три уровня прибыли и рентабельность'}
        head={<><Th>Период</Th><Th right>Выручка</Th><Th right>Валовая</Th><Th right>От продаж</Th>
          <Th right>Чистая</Th><Th right>Валовая, %</Th><Th right>Чистая, %</Th></>}>
        {[...rows].reverse().map((r) => (
          <tr key={r.label} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5">{r.label}</td>
            <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
              {money.format(r.net)} ₽
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
              {money.format(r.gross)} ₽
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
              {money.format(r.operating)} ₽
            </td>
            <td className={cn('px-3 py-1.5 text-right tabular-nums whitespace-nowrap',
              r.profit >= 0 ? 'text-emerald-600 dark:text-emerald-400'
                : 'text-rose-600 dark:text-rose-400')}>
              {money.format(r.profit)} ₽
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
              {r.net ? `${((r.gross / r.net) * 100).toFixed(1)} %` : '—'}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
              {r.net ? `${((r.profit / r.net) * 100).toFixed(1)} %` : '—'}
            </td>
          </tr>
        ))}
      </TableCard>
    </div>
  )
}

/* ────────────────────────────────────────────────────────────── */
/*                   Точка безубыточности                         */
/* ────────────────────────────────────────────────────────────── */

/**
 * Безубыточность считается диапазоном, а не одним числом.
 *
 * Деления затрат на постоянные и переменные в бухгалтерском учёте нет. Классификация
 * по счёту (account analysis) — единственный метод, дающий объяснимый результат, но
 * при рентабельности около 3 % переклассификация ОДНОЙ статьи двигает точку на
 * десятки процентов. Поэтому показываем две границы: осторожную (постоянными считаем
 * и коммерческие, и управленческие) и мягкую (только управленческие).
 *
 * Статистику здесь не применяем сознательно: на данных пилота структура затрат
 * менялась режимами (зарплата исчезла и заменилась услугами управляющего), и
 * регрессия измерила бы смену эпох, а не поведение затрат.
 */
function EconBreakeven({ companyId, period }: { companyId: string; period: Period }) {
  const q = usePnl(companyId, period)
  if (q.isError) return <div className="p-4"><QueryError onRetry={() => q.refetch()} /></div>
  if (!q.data) return <Loading />
  const t = q.data.totals
  if (!t.net) return <NoData salesEntries={q.data.salesEntries} />

  const marginPct = (t.net - t.cogsTotal) / t.net
  const fixedHigh = t.commercial + t.admin
  const fixedLow = t.admin
  const point = (f: number) => (marginPct > 0 ? f / marginPct : null)
  const high = point(fixedHigh)
  const low = point(fixedLow)
  const safety = high !== null ? ((t.net - high) / t.net) * 100 : null
  // Операционный рычаг: во сколько раз прибыль чувствительнее выручки. Показываем не
  // числом «25», а тем, что оно означает: падение выручки на 1/DOL обнуляет прибыль.
  const dol = t.operating > 0 ? (t.net - t.cogsTotal) / t.operating : null

  const noSplit = fixedHigh === 0

  return (
    <div className="p-4 space-y-4">
      {noSplit ? (
        <div className="p-2 text-sm text-muted-foreground">
          В периоде нет ни коммерческих, ни управленческих расходов — постоянную часть
          выделить не из чего, и точка безубыточности не считается. Так бывает, когда
          все затраты закрываются через себестоимость: разрез появится, как только в
          отчёте будут строки 2210 или 2220.
        </div>
      ) : (
        <>
          <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
            <MetricTile label="Маржинальность" value={`${(marginPct * 100).toFixed(1)} %`}
              hint="доля выручки, остающаяся после себестоимости" />
            <MetricTile label="Постоянные расходы" value={money.format(fixedHigh) + ' ₽'}
              hint="коммерческие и управленческие за период" />
            <MetricTile label="Точка безубыточности"
              value={high === null ? '—' : money.format(high) + ' ₽'}
              hint={low === null || low === high ? 'выручка, при которой прибыль равна нулю'
                : `мягкая оценка ${money.format(low)} ₽`} />
            <MetricTile label="Запас прочности"
              value={safety === null ? '—' : `${safety.toFixed(1)} %`}
              hint={safety === null ? undefined
                : safety > 0 ? 'на столько может упасть выручка' : 'выручка ниже точки'}
              tone={safety !== null && safety > 0 ? 'success' : 'danger'} />
          </div>

          <Card>
            <CardContent className="p-4 space-y-2 text-sm">
              <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
                Как считается и почему это диапазон
              </div>
              <p>
                Выручка без НДС <b className="tabular-nums">{money.format(t.net)} ₽</b> минус
                себестоимость <b className="tabular-nums">{money.format(t.cogsTotal)} ₽</b> даёт
                маржинальный доход{' '}
                <b className="tabular-nums">{money.format(t.net - t.cogsTotal)} ₽</b>{' '}
                ({(marginPct * 100).toFixed(1)} % выручки). Постоянные расходы делятся на эту
                долю — получается выручка, покрывающая расходы ровно в ноль.
              </p>
              {dol !== null && (
                <p>
                  Операционный рычаг: падение выручки на{' '}
                  <b className="tabular-nums">{(100 / dol).toFixed(1)} %</b> обнуляет прибыль
                  от продаж. Чем ниже рентабельность, тем короче этот запас.
                </p>
              )}
              <p className="text-[11px] text-muted-foreground">
                Точка показана диапазоном намеренно: деления затрат на постоянные и
                переменные в учёте нет. Осторожная оценка считает постоянными и
                коммерческие, и управленческие расходы, мягкая — только управленческие.
                При рентабельности около трёх процентов переклассификация одной статьи
                двигает точку на десятки процентов, поэтому одно число здесь было бы
                обманом точности.
              </p>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}

/* ────────────────────────────────────────────────────────────── */
/*                          Расходы                               */
/* ────────────────────────────────────────────────────────────── */

/**
 * Статьи затрат — из субконто оборотов, а не из имени корреспондирующего счёта.
 * По счёту ответ на «за что платим» звучит как «поставщику», и аренда, транспорт,
 * связь и зарплата не различаются.
 *
 * Классификация постоянные/переменные сделана по СМЫСЛУ статьи, а не статистикой:
 * на данных пилота структура затрат менялась режимами, и корреляция измерила бы
 * смену эпох. Правило видно на экране, его можно оспорить глазами.
 */
const FIXED_ITEMS = ['оплата труда', 'страховые взносы', 'аренда', 'услуги управляющего',
  'услуги банк', 'связь', 'взносы в фсс', 'амортизац']
const VARIABLE_ITEMS = ['транспорт', 'материал', 'брак', 'комисси', 'доставка']

function costBehavior(item: string): 'fixed' | 'variable' | 'unknown' {
  const s = item.toLowerCase()
  if (FIXED_ITEMS.some((k) => s.includes(k))) return 'fixed'
  if (VARIABLE_ITEMS.some((k) => s.includes(k))) return 'variable'
  return 'unknown'
}

const BEHAVIOR_LABEL: Record<string, string> = {
  fixed: 'постоянные', variable: 'переменные', unknown: 'не размечены',
}

function EconCosts({ companyId, period, view }: {
  companyId: string; period: Period; view: 'items' | 'structure' | 'months'
}) {
  const q = useQuery({
    queryKey: ['books', 'expenses', companyId, period.from, period.to],
    queryFn: () => getExpenses(companyId, period),
    enabled: !!companyId,
  })
  const [open, setOpen] = useState<string | null>(null)
  const [grain, setGrain] = useState<'month' | 'quarter' | 'year'>('month')

  if (q.isError) return <div className="p-4"><QueryError onRetry={() => q.refetch()} /></div>
  if (!q.data) return <Loading />
  const d = q.data
  if (!d.total && !d.itemsTotal) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        За выбранный период затрат в учёте нет.
      </div>
    )
  }

  if (view === 'items') {
    const groups = (['fixed', 'variable', 'unknown'] as const).map((k) => {
      const part = d.items.filter((i) => costBehavior(i.item) === k)
      return { key: k, count: part.length, amount: part.reduce((s, i) => s + i.amount, 0) }
    })
    return (
      <div className="p-4 space-y-4">
        <div className="grid gap-3 grid-cols-3">
          {groups.map((g) => (
            <MetricTile key={g.key} label={BEHAVIOR_LABEL[g.key]}
              value={money.format(g.amount) + ' ₽'}
              hint={`${num.format(g.count)} статей · `
                + `${d.itemsTotal ? ((g.amount / d.itemsTotal) * 100).toFixed(1) : '0'} % затрат`} />
          ))}
        </div>

        <p className="text-[11px] text-muted-foreground">
          Разметка сделана по смыслу статьи, а не статистикой: структура затрат у
          компании менялась режимами (зарплата уступила место услугам управляющего), и
          регрессия измерила бы смену эпох, а не поведение затрат. Статьи, которых нет
          в правиле, честно стоят как «не размечены», а не отнесены к постоянным.
        </p>

        <div className="flex justify-end">
          <ExportButton onClick={() => exportTable('Затраты по статьям', [
            { header: 'Статья', key: 'item', width: 40 },
            { header: 'Счёт', key: 'account', width: 10 },
            { header: 'Поведение', key: 'behavior', width: 16 },
            { header: 'Сумма', key: 'amount', width: 18, money: true },
            { header: 'Месяцев с оборотом', key: 'months', width: 18 },
          ], d.items.map((i) => ({ ...i, behavior: BEHAVIOR_LABEL[costBehavior(i.item)] })))} />
        </div>

        <TableCard note={`${num.format(d.items.length)} статей на ${money.format(d.itemsTotal)} ₽`}
          head={<><Th>Статья</Th><Th>Счёт</Th><Th>Поведение</Th><Th right>Сумма</Th>
            <Th right>Доля</Th><Th right>Месяцев</Th></>}>
          {d.items.map((i) => {
            const b = costBehavior(i.item)
            return (
              <tr key={`${i.account}-${i.item}`} className="border-b last:border-0 hover:bg-muted/40">
                <td className="px-3 py-1.5 max-w-[340px] truncate" title={i.item}>{i.item}</td>
                <td className="px-3 py-1.5 tabular-nums text-muted-foreground">{i.account}</td>
                <td className="px-3 py-1.5">
                  <span className={cn('rounded px-1.5 py-0.5 text-[11px]',
                    b === 'fixed' ? 'bg-amber-500/15 text-amber-600 dark:text-amber-400'
                    : b === 'variable' ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'
                    : 'bg-muted text-muted-foreground')}>{BEHAVIOR_LABEL[b]}</span>
                </td>
                <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
                  {money.format(i.amount)} ₽
                </td>
                <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
                  {d.itemsTotal ? `${((i.amount / d.itemsTotal) * 100).toFixed(1)} %` : '—'}
                </td>
                <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
                  {i.months}
                </td>
              </tr>
            )
          })}
        </TableCard>
      </div>
    )
  }

  if (view === 'months') {
    const key = (m: string) =>
      grain === 'year' ? m.slice(0, 4)
      : grain === 'quarter' ? `${m.slice(0, 4)} · ${Math.ceil(Number(m.slice(5, 7)) / 3)} кв.`
      : monthLabel(m)
    const by = new Map<string, number>()
    for (const m of d.months) by.set(key(m.month), (by.get(key(m.month)) ?? 0) + m.amount)
    const rows = [...by.entries()].map(([label, amount]) => ({ label, amount }))
    const max = Math.max(...rows.map((r) => r.amount), 1)

    return (
      <div className="p-4 space-y-4">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <Tabs value={grain} onChange={setGrain} items={[
            { key: 'month' as const, label: 'Месяц' },
            { key: 'quarter' as const, label: 'Квартал' },
            { key: 'year' as const, label: 'Год' },
          ]} />
          <ExportButton onClick={() => exportTable('Затраты по периодам', [
            { header: 'Период', key: 'label', width: 18 },
            { header: 'Затраты', key: 'amount', width: 18, money: true },
          ], rows)} />
        </div>
        <Card>
          <CardContent className="p-4">
            <div className="text-[11px] uppercase tracking-wider text-muted-foreground mb-3">
              Затраты по периодам — всего {money.format(d.total)} ₽
            </div>
            <div className="flex items-end gap-1 overflow-x-auto" style={{ height: 170 }}>
              {rows.map((r) => (
                <div key={r.label} className="flex flex-col items-center gap-1 min-w-[30px] flex-1"
                  title={`${r.label}: ${money.format(r.amount)} ₽`}>
                  <div className="w-full rounded-t bg-primary/60"
                    style={{ height: `${Math.max(2, (r.amount / max) * 120)}px` }} />
                  <div className="text-[9px] text-muted-foreground rotate-45 origin-left h-8 whitespace-nowrap">
                    {r.label}
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
        <TableCard note="Период: сколько затрат признано в учёте"
          head={<><Th>Период</Th><Th right>Затраты</Th><Th right>Доля</Th></>}>
          {[...rows].reverse().map((r) => (
            <tr key={r.label} className="border-b last:border-0 hover:bg-muted/40">
              <td className="px-3 py-1.5">{r.label}</td>
              <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
                {money.format(r.amount)} ₽
              </td>
              <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
                {d.total ? `${((r.amount / d.total) * 100).toFixed(1)} %` : '—'}
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
            hint={`счёт ${a.account} · ${((a.amount / (d.total || 1)) * 100).toFixed(1)} % затрат`} />
        ))}
      </div>

      <p className="text-[11px] text-muted-foreground">
        Здесь затраты в момент НАЧИСЛЕНИЯ на счетах учёта. В отчёте о результате они
        появляются в момент СПИСАНИЯ на 90 и 91, поэтому суммы совпадают только когда
        всё начисленное закрыто в том же периоде. Взаимные переносы между затратными
        счетами исключены — иначе одна затрата считалась бы дважды.
      </p>

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
              {d.total ? `${((a.amount / d.total) * 100).toFixed(1)} %` : '—'}
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

/* ────────────────────────────────────────────────────────────── */
/*                           Налоги                               */
/* ────────────────────────────────────────────────────────────── */

/**
 * Налоги разведены по смыслу, а не свалены в один список.
 *
 * Налог на прибыль — строка отчёта о результате. НДС — транзит: не расход компании,
 * он собирается с покупателя и уходит в бюджет. НДФЛ — удержание у работника,
 * компания только агент. Страховые взносы — часть затрат на персонал, они уже сидят
 * в себестоимости и управленческих расходах. Соседство этих четырёх в одной таблице
 * читается как «всё это съедает прибыль», что неверно для трёх из них.
 */
function EconTaxes({ companyId, period, view }: {
  companyId: string; period: Period; view: 'list' | 'load'
}) {
  const q = useQuery({
    queryKey: ['books', 'taxes', companyId, period.from, period.to],
    queryFn: () => getTaxes(companyId, period),
    enabled: !!companyId,
  })
  const [grain, setGrain] = useState<'month' | 'quarter' | 'year'>('month')

  if (q.isError) return <div className="p-4"><QueryError onRetry={() => q.refetch()} /></div>
  if (!q.data) return <Loading />
  const d = q.data
  if (!d.accrued && !d.paid) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        За выбранный период начислений и уплат по счетам 68 и 69 нет.
      </div>
    )
  }
  const g = d.groups

  if (view === 'load') {
    const key = (m: string) =>
      grain === 'year' ? m.slice(0, 4)
      : grain === 'quarter' ? `${m.slice(0, 4)} · ${Math.ceil(Number(m.slice(5, 7)) / 3)} кв.`
      : monthLabel(m)
    const by = new Map<string, { accrued: number; paid: number }>()
    for (const m of d.months) {
      const k = key(m.month)
      const cur = by.get(k) ?? { accrued: 0, paid: 0 }
      by.set(k, { accrued: cur.accrued + m.accrued, paid: cur.paid + m.paid })
    }
    const rows = [...by.entries()].map(([label, v]) => ({ label, ...v }))
    const max = Math.max(...rows.map((r) => Math.max(r.accrued, r.paid)), 1)

    return (
      <div className="p-4 space-y-4">
        <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
          <MetricTile label="Уплачено налогов" value={money.format(d.paid) + ' ₽'}
            hint="деньгами с расчётного счёта" />
          <MetricTile label="Нагрузка на выручку"
            value={d.loadPct === null ? '—' : `${d.loadPct} %`}
            hint={`методика ФНС: уплачено / выручка без НДС (${money.format(d.revenueNet)} ₽)`} />
          <MetricTile label="Эффективная ставка"
            value={d.etrPct === null ? '—' : `${d.etrPct} %`}
            hint={d.etrPct === null ? 'считается только при прибыли до налога'
              : 'налог на прибыль / прибыль до налога'} />
          <MetricTile label="Начислено всего" value={money.format(d.accrued) + ' ₽'}
            hint="включая НДС — он транзитный и нагрузкой не является" />
        </div>

        <p className="text-[11px] text-muted-foreground">
          Нагрузка считается от УПЛАЧЕННОГО — так её определяет и налоговая служба
          (уплаченные налоги к выручке без НДС). Начисленный оборот по счетам 68 и 69
          для этого не годится: кредит НДС несёт весь налог с продаж, тогда как в бюджет
          уходит разница с вычетами по покупкам. Переносы на единый налоговый счёт из
          расчёта исключены — иначе один и тот же налог считается дважды.
        </p>

        <div className="flex items-center justify-between gap-3 flex-wrap">
          <Tabs value={grain} onChange={setGrain} items={[
            { key: 'month' as const, label: 'Месяц' },
            { key: 'quarter' as const, label: 'Квартал' },
            { key: 'year' as const, label: 'Год' },
          ]} />
          <ExportButton onClick={() => exportTable('Налоги по периодам', [
            { header: 'Период', key: 'label', width: 18 },
            { header: 'Начислено', key: 'accrued', width: 18, money: true },
            { header: 'Уплачено', key: 'paid', width: 18, money: true },
          ], rows)} />
        </div>

        <Card>
          <CardContent className="p-4">
            <div className="text-[11px] uppercase tracking-wider text-muted-foreground mb-3">
              Начислено (сверху) и уплачено (снизу)
            </div>
            <div className="flex items-center gap-1 overflow-x-auto" style={{ height: 200 }}>
              {rows.map((r) => (
                <div key={r.label} className="flex flex-col items-center min-w-[30px] flex-1"
                  title={`${r.label}: начислено ${money.format(r.accrued)} ₽, уплачено ${money.format(r.paid)} ₽`}>
                  <div className="w-full flex flex-col justify-end" style={{ height: 76 }}>
                    <div className="w-full rounded-t bg-primary/50"
                      style={{ height: `${Math.max(1, (r.accrued / max) * 74)}px` }} />
                  </div>
                  <div className="w-full" style={{ height: 76 }}>
                    <div className="w-full rounded-b bg-emerald-500/60"
                      style={{ height: `${Math.max(1, (r.paid / max) * 74)}px` }} />
                  </div>
                  <div className="text-[9px] text-muted-foreground rotate-45 origin-left h-8 whitespace-nowrap">
                    {r.label}
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
      <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
        <MetricTile label="Налог на прибыль" value={money.format(g.profitTax) + ' ₽'}
          hint="строка отчёта о результате" />
        <MetricTile label="НДС" value={money.format(g.vat) + ' ₽'}
          hint="транзитный: собирается с покупателя, расходом не является" />
        <MetricTile label="Страховые взносы" value={money.format(g.contributions) + ' ₽'}
          hint="часть затрат на персонал, уже внутри расходов" />
        <MetricTile label="НДФЛ" value={money.format(g.ndfl) + ' ₽'}
          hint="удержание у работника, компания — агент" />
      </div>

      <p className="text-[11px] text-muted-foreground">
        Четыре суммы выше — про разное, и складывать их в «налоговую нагрузку» нельзя.
        Прибыль компании уменьшает только первая. НДС проходит транзитом, НДФЛ
        удерживается у работника, взносы уже посчитаны в расходах на персонал.
      </p>

      <div className="flex justify-end">
        <ExportButton onClick={() => exportTable('Налоги и взносы', [
          { header: 'Счёт', key: 'account', width: 12 },
          { header: 'Налог', key: 'name', width: 44 },
          { header: 'Начислено', key: 'accrued', width: 18, money: true },
          { header: 'Проводок', key: 'entries', width: 12 },
        ], d.rows)} />
      </div>

      <TableCard
        note="Начислено — кредит счетов 68 и 69 за вычетом переносов между ними и возвратов из бюджета"
        head={<><Th>Счёт</Th><Th>Налог или взнос</Th><Th right>Начислено</Th><Th right>Проводок</Th></>}>
        {d.rows.map((r) => (
          <tr key={r.account} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5 tabular-nums">{r.account}</td>
            <td className="px-3 py-1.5 max-w-[380px] truncate" title={r.name}>{r.name}</td>
            <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
              {money2.format(r.accrued)} ₽
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
              {r.entries}
            </td>
          </tr>
        ))}
      </TableCard>

      <Card>
        <CardContent className="p-4 text-sm space-y-1">
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
            Уплачено деньгами
          </div>
          <div>
            <b className="tabular-nums">{money.format(d.paid)} ₽</b> ушло с расчётного
            счёта в бюджет за период.
          </div>
          <p className="text-[11px] text-muted-foreground">
            С 2023 года платежи идут одной суммой на единый налоговый счёт, поэтому
            разложить уплату по видам налогов из проводок нельзя — это делает уже
            налоговая служба по декларациям. Разница между начисленным и уплаченным
            долгом не является: часть НДС закрывается вычетами, а не деньгами.
          </p>
        </CardContent>
      </Card>
    </div>
  )
}

/**
 * Проводки строки отчёта — окном поверх экрана, как принято в пространстве.
 *
 * Сумма окна обязана совпадать со строкой: если разошлась, ошибка в правиле разбора,
 * а не в данных. Поэтому итог показан прямо в шапке.
 */
function PnlEntriesWindow({ companyId, period, line, onClose }: {
  companyId: string; period: Period; line: string; onClose: () => void
}) {
  const q = useQuery({
    queryKey: ['books', 'pnl-entries', companyId, line, period.from, period.to],
    queryFn: () => getPnlEntries(companyId, line, period),
  })
  const d = q.data

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-5xl max-h-[85vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="text-base">
            {d?.label ?? 'Проводки'}
            {d && (
              <span className="ml-2 font-normal text-muted-foreground tabular-nums">
                {money.format(d.total)} ₽ · {num.format(d.count)} проводок
              </span>
            )}
          </DialogTitle>
        </DialogHeader>
        {q.isError && <QueryError onRetry={() => q.refetch()} />}
        {!d ? <Loading /> : (
          <div className="flex-1 min-h-0 overflow-y-auto pr-1">
            {d.shown < d.count && (
              <p className="text-[11px] text-muted-foreground pb-2">
                Показаны {num.format(d.shown)} последних из {num.format(d.count)} — итог в
                шапке посчитан по всем.
              </p>
            )}
            <TableCard head={<><Th>Дата</Th><Th>Дт</Th><Th>Кт</Th><Th right>Сумма</Th>
              <Th>Документ</Th></>}>
              {d.rows.map((r, i) => (
                <tr key={i} className="border-b last:border-0 hover:bg-muted/40">
                  <td className="px-3 py-1.5 tabular-nums whitespace-nowrap">{r.date}</td>
                  <td className="px-3 py-1.5 tabular-nums">{r.accountDt ?? '—'}</td>
                  <td className="px-3 py-1.5 tabular-nums">{r.accountKt ?? '—'}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
                    {money2.format(r.amount)} ₽
                  </td>
                  <td className="px-3 py-1.5 max-w-[380px] truncate"
                    title={`${r.docKind ?? ''} ${r.docTitle ?? ''} ${r.content ?? ''}`.trim()}>
                    <span className="text-muted-foreground">{r.docKind ?? ''}</span>{' '}
                    {r.docTitle ?? r.content ?? '—'}
                  </td>
                </tr>
              ))}
            </TableCard>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

/**
 * Мост «затраты → отчёт».
 *
 * Раздел «Расходы» считает затраты в момент НАЧИСЛЕНИЯ на счетах учёта, отчёт — в
 * момент СПИСАНИЯ на 90 и 91. Совпадают они только когда всё начисленное закрыто в
 * том же периоде; разница — это остаток на затратных счетах (у 20 — незавершённое
 * производство, у 44 — расходы, распределяемые на будущие периоды). Без этой таблицы
 * два числа выглядят как ошибка одного из них.
 */
function EconCostBridge({ companyId, period }: { companyId: string; period: Period }) {
  const q = useQuery({
    queryKey: ['books', 'cost-bridge', companyId, period.from, period.to],
    queryFn: () => getCostBridge(companyId, period),
    enabled: !!companyId,
  })

  if (q.isError) return <div className="p-4"><QueryError onRetry={() => q.refetch()} /></div>
  if (!q.data) return <Loading />
  const d = q.data
  if (!d.accrued && !d.written) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        За выбранный период оборотов по затратным счетам нет.
      </div>
    )
  }
  const gap = Math.round((d.written - d.inPnl) * 100) / 100

  return (
    <div className="p-4 space-y-4">
      <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
        <MetricTile label="Начислено затрат" value={money.format(d.accrued) + ' ₽'}
          hint="пришло на счета учёта извне: поставщики, зарплата, взносы" />
        <MetricTile label="Списано в результат" value={money.format(d.written) + ' ₽'}
          hint="ушло на счета 90 и 91 — это и есть расходы отчёта" />
        <MetricTile label="Осталось на счетах" value={money.format(d.rest) + ' ₽'}
          hint="незавершёнка и расходы, распределяемые на будущие периоды" />
        <MetricTile label="В отчёте о результате" value={money.format(d.inPnl) + ' ₽'}
          hint={Math.abs(gap) < 1 ? 'сходится со списанным'
            : `расхождение со списанным ${money.format(gap)} ₽`}
          tone={Math.abs(gap) < 1 ? 'success' : undefined} />
      </div>

      <p className="text-[11px] text-muted-foreground">
        Затраты попадают в отчёт не тогда, когда начислены, а когда списаны на счета
        продаж и прочих операций. Поэтому «Структура затрат» и строки «Коммерческие» и
        «Управленческие» в отчёте совпадают только при полном закрытии периода. Разница
        — это остаток на затратных счетах, а не потеря данных.
      </p>

      <div className="flex justify-end">
        <ExportButton onClick={() => exportTable('Затраты и отчёт', [
          { header: 'Счёт', key: 'account', width: 12 },
          { header: 'Наименование', key: 'name', width: 40 },
          { header: 'Начислено', key: 'accrued', width: 18, money: true },
          { header: 'Списано в результат', key: 'written', width: 20, money: true },
          { header: 'Перенесено на другие счета', key: 'moved', width: 24, money: true },
          { header: 'Остаток', key: 'rest', width: 18, money: true },
        ], d.rows)} />
      </div>

      <TableCard note="По каждому затратному счёту: пришло, ушло в результат, осталось"
        head={<><Th>Счёт</Th><Th>Наименование</Th><Th right>Начислено</Th>
          <Th right>Списано</Th><Th right>Перенесено</Th><Th right>Остаток</Th></>}>
        {d.rows.map((r) => (
          <tr key={r.account} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5 tabular-nums">{r.account}</td>
            <td className="px-3 py-1.5 max-w-[320px] truncate" title={r.name ?? ''}>
              {r.name ?? '—'}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
              {money.format(r.accrued)} ₽
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
              {money.format(r.written)} ₽
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground whitespace-nowrap">
              {r.moved ? `${money.format(r.moved)} ₽` : '—'}
            </td>
            <td className={cn('px-3 py-1.5 text-right tabular-nums whitespace-nowrap',
              Math.abs(r.rest) > 1 ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground')}>
              {money.format(r.rest)} ₽
            </td>
          </tr>
        ))}
      </TableCard>
    </div>
  )
}
