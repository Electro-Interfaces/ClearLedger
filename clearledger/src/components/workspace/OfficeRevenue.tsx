/**
 * «Реализация» (`revenue`) — что компания без объектов продала.
 *
 * Состав согласован МАГом 13.08.2026 и идёт по ВОПРОСУ, а не по виду строки:
 * «Продажи» (сколько продали и как это менялось), «Покупатели» (кому),
 * «Что продаём» (что), «Документы» (какими бумагами). Товар против услуги —
 * разрез ВНУТРИ экрана: до этого были два раздела с одинаковым набором пунктов,
 * и общей выручки компании не показывал ни один из них.
 *
 * Отдельный файл от `OfficePanels` (там осталась «Бухгалтерия»): тот правится в
 * соседней сессии, и две записи в один файл кончаются потерянной правкой. Окна
 * карточек — контрагента и позиции — берутся оттуда же, а не копируются: карточка
 * одна на пространство, из какого бы экрана её ни открыли.
 *
 * Числа приходят посчитанными с бэкенда (`/api/books/revenue`). Фронт складывает
 * только то, чего в ответе нет по природе: сравнение двух ответов между собой
 * (период к периоду) и накопленную долю для ABC.
 */
import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
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
  getArAging, getAssortment, getAttention, getBacklog, getCashflow, getCashflowItems,
  getCashForecast, getCollectionCurve,
  getConcentration, getContractSales, getDeals, getDocsAll, getPaymentTerms,
  getRevenue, getRevenueCheck, getRevenueQuality, getStock, getSuppliers,
  type DocRow, type RevKind,
} from '@/services/booksService'
import { exportTable } from '@/services/booksExport'
import { DocumentWindow } from '@/components/books/DocumentWindow'
import {
  CounterpartyWindow, Loading, NoCompany, NomenclatureWindow, TableCard, Th,
} from './OfficePanels'
import { useWorkspaceSections } from './workspaceSections'
import {
  ExportButton, SearchInput, Tabs, money, monthLabel, num, qty,
} from './officeShared'
import { ProductHelpPanel } from './ProductHelpPanel'
import { REVENUE_HELP_SLICES } from './helpSlices'
import {
  REV_SALES_MENU, REV_CLIENTS_MENU, REV_ITEMS_MENU, REV_DOCS_MENU,
  REV_MONEY_MENU, REV_STOCK_MENU,
} from '@/config/workspaceMenus'


/** Полный список, а не топ-15: экран разреза и есть его реестр. */
const FULL = 500

/* ── Периоды сравнения ───────────────────────────────────────────────────── */
// Дата хранится строкой ISO, и сравнение периодов — единственное место, где её
// приходится считать. Считаем ЦЕЛИКОМ в UTC (`Z`, `setUTC*`, `toISOString`): смесь
// локальной полуночи с `toISOString()` в московском поясе уводит каждую границу на
// день назад, и «август» превращается в «31 июля — 30 августа». Проверка —
// `scripts/period-check.mjs`.

/** Пустая или битая дата в фильтре роняла `toISOString()` белым экраном. */
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

/** Предыдущий период той же длины — «месяц к месяцу». */
const prevPeriod = (p: Period): Period => {
  const len = lengthDays(p)
  if (!len) return p            // период не задан — сравнивать не с чем
  return { from: shiftDays(p.from, -len), to: shiftDays(p.to, -len) }
}

/** Тот же период годом раньше — «год к году», с ним сравнивают сезонный бизнес. */
const yearAgo = (p: Period): Period => ({
  from: shiftYears(p.from, -1), to: shiftYears(p.to, -1),
})

const periodLabel = (p: Period) => `${p.from} — ${p.to}`

/* ── Общие мелочи ────────────────────────────────────────────────────────── */

const KIND_TABS: { key: RevKind; label: string }[] = [
  { key: 'all', label: 'Всё' },
  { key: 'goods', label: 'Товары' },
  { key: 'service', label: 'Услуги' },
]

/**
 * Фильтр «сумма от / до». Стоит рядом с поиском во всех реестрах: вопрос «покажи
 * сделки крупнее миллиона» задают чаще, чем ищут конкретное имя, а до этого его
 * приходилось решать выгрузкой в Excel и фильтром уже там.
 */
function AmountRange({ from, to, onChange }: {
  from: string; to: string; onChange: (from: string, to: string) => void
}) {
  const cls = 'h-8 w-28 rounded-md border bg-background px-2.5 text-sm tabular-nums'
  return (
    <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
      <span>сумма</span>
      <input value={from} onChange={(e) => onChange(e.target.value, to)}
        placeholder="от" inputMode="numeric" className={cls}
        aria-label="Сумма от" />
      <input value={to} onChange={(e) => onChange(from, e.target.value)}
        placeholder="до" inputMode="numeric" className={cls}
        aria-label="Сумма до" />
    </div>
  )
}

/** Пустая строка = граница не задана; мусор в поле = граница не задана (не ноль). */
const inRange = (v: number, from: string, to: string) => {
  const a = Number(from.replace(/\s/g, '').replace(',', '.'))
  const b = Number(to.replace(/\s/g, '').replace(',', '.'))
  if (from.trim() && Number.isFinite(a) && v < a) return false
  if (to.trim() && Number.isFinite(b) && v > b) return false
  return true
}

/** Сколько дней назад была последняя покупка — им меряются молчащие. */
const daysSince = (iso: string | null) =>
  iso ? Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 86400000)) : null

/**
 * Изменение к прошлому периоду. Рост с нуля процентом не выражается — показываем
 * «был ноль», иначе экран рисует «+∞ %» и в него перестают смотреть.
 */
function Delta({ now, was }: { now: number; was: number }) {
  if (!was) return <span className="text-muted-foreground">{now ? 'было пусто' : '—'}</span>
  const pct = ((now - was) / Math.abs(was)) * 100
  const up = pct >= 0
  return (
    <span className={cn('tabular-nums', up ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400')}>
      {up ? '+' : ''}{pct.toFixed(1)} %
    </span>
  )
}

/** Полоска доли внутри строки таблицы — вместо колонки процентов и глазомера. */
function Share({ value, of }: { value: number; of: number }) {
  const pct = of ? (value / of) * 100 : 0
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 rounded bg-muted overflow-hidden">
        <div className="h-full bg-primary/60" style={{ width: `${Math.min(100, pct)}%` }} />
      </div>
      <span className="tabular-nums text-muted-foreground w-12 text-right">{pct.toFixed(1)}%</span>
    </div>
  )
}

/**
 * Столбики помесячно — один и тот же график в «Обзоре» и «Динамике».
 *
 * Ряд достраивается нулями: месяц без продаж должен выглядеть провалом, а не
 * исчезать. Пропущенный столбец делает разрыв невидимым, и график читается как
 * непрерывная работа.
 */
function MonthBars({ months, height = 128 }: {
  months: { month: string; amount: number; docs: number }[]; height?: number
}) {
  months = fillMonths(months)
  const max = Math.max(...months.map((m) => m.amount), 1)
  if (!months.length) {
    return (
      <div className="py-6 text-center text-sm text-muted-foreground">
        За выбранный период документов нет
      </div>
    )
  }
  return (
    /* Высота столбца — в пикселях: проценты внутри flex без своей высоты
       разворачиваются в ноль, и график становится пустой полосой. */
    <div className="flex items-end gap-1 overflow-x-auto" style={{ height: height + 32 }}>
      {months.map((m) => (
        <div key={m.month} className="flex flex-col items-center gap-1 min-w-[26px] flex-1"
          title={`${monthLabel(m.month)}: ${money.format(m.amount)} ₽, документов ${m.docs}`}>
          <div className="w-full rounded-t bg-primary/70"
            style={{ height: `${Math.max(2, (m.amount / max) * height)}px` }} />
          <div className="text-[9px] text-muted-foreground rotate-45 origin-left h-6 whitespace-nowrap">
            {m.month.slice(2)}
          </div>
        </div>
      ))}
    </div>
  )
}

/* ── Данные ──────────────────────────────────────────────────────────────── */

function useRevenue(companyId: string, kind: RevKind, period?: Period) {
  return useQuery({
    queryKey: ['books', 'revenue', companyId, kind, period?.from, period?.to],
    queryFn: () => getRevenue(companyId, kind, { top: FULL, from: period?.from, to: period?.to }),
    enabled: !!companyId,
  })
}

/** Достроить помесячный ряд нулями между первым и последним месяцем. */
function fillMonths<T extends { month: string }>(rows: T[]): T[] {
  if (rows.length < 2) return rows
  const out: T[] = []
  const [fy, fm] = rows[0].month.split('-').map(Number)
  const [ly, lm] = rows[rows.length - 1].month.split('-').map(Number)
  const by = new Map(rows.map((r) => [r.month, r]))
  for (let y = fy, m = fm; y < ly || (y === ly && m <= lm); m === 12 ? (y++, m = 1) : m++) {
    const key = `${y}-${String(m).padStart(2, '0')}`
    out.push(by.get(key) ?? ({ month: key, amount: 0, docs: 0 } as unknown as T))
  }
  return out
}

/** Ключ покупателя: ссылка на карточку, а имя — только когда ссылки нет. */
const clientKey = (c: { id: string | null; name: string }) => c.id ?? c.name

/* ────────────────────────────────────────────────────────────── */
/*                            Панель                              */
/* ────────────────────────────────────────────────────────────── */

/**
 * Все пункты продукта одним списком — по ним статья помощи находит подпись экрана и
 * строит кнопку перехода. Раздел, которому пункт принадлежит, считает `modeForHelpKey`:
 * без него кнопка «открыть экран» вела бы в первый раздел.
 */
const REV_MENU_FOR_HELP = [
  ...REV_SALES_MENU, ...REV_CLIENTS_MENU, ...REV_ITEMS_MENU, ...REV_DOCS_MENU,
  ...REV_MONEY_MENU, ...REV_STOCK_MENU,
]

const modeForHelpKey = (key: string): string =>
  REV_CLIENTS_MENU.some((m) => m.key === key) ? 'rev_buyers'
  : REV_ITEMS_MENU.some((m) => m.key === key) ? 'rev_catalog'
  : REV_DOCS_MENU.some((m) => m.key === key) ? 'rev_papers'
  : REV_MONEY_MENU.some((m) => m.key === key) ? 'rev_money'
  : REV_STOCK_MENU.some((m) => m.key === key) ? 'rev_stock'
  : 'rev_sales'

/** Разрез задаётся пунктом там, где он и есть предмет пункта. */
const FIXED_KIND: Record<string, RevKind> = {
  rev_nomen: 'goods',
  rev_svc: 'service',
  rev_abc_items: 'goods',
  rev_margin: 'goods',
}

/** Экраны, у которых своя ручка и разрез над ними не имеет смысла. */
const NO_KIND = ['rev_invoices', 'rev_funnel', 'rev_recon', 'rev_abc', 'rev_abc_items',
  'rev_margin', 'rev_terms', 'rev_cashflow', 'rev_contracts', 'rev_stock', 'rev_suppliers',
  'rev_prices', 'rev_quality', 'rev_deals', 'rev_conc', 'rev_aging', 'rev_collect',
  'rev_backlog', 'rev_forecast', 'rev_cfitems', 'rev_attention']

export function RevenuePanel() {
  const { coreMode } = useWorkspace()
  const sections = useWorkspaceSections()
  const items = sections.find((s) => s.mode === coreMode)?.items ?? []
  const [sub] = useWorkspaceSubView(items[0]?.key ?? '', items.map((i) => i.key))
  const { companyId } = useCompany()
  const { period } = useFilters()
  // Разрез живёт в АДРЕСЕ: человек выбрал «услуги» и ходит с этим взглядом по
  // разделам, ссылкой делится, возврат из другого продукта его не сбрасывает.
  const [params, setParams] = useSearchParams()
  const kind = (['all', 'goods', 'service'].includes(params.get('kind') ?? '')
    ? params.get('kind') : 'all') as RevKind
  const setKind = (v: RevKind) => setParams((prev) => {
    const next = new URLSearchParams(prev)
    if (v === 'all') next.delete('kind')
    else next.set('kind', v)
    return next
  }, { replace: true })
  const shown = FIXED_KIND[sub] ?? kind

  if (!companyId) return <NoCompany />
  // Роль могла закрыть ВСЕ пункты раздела. Тогда `sub` пуст, и `switch` уходил в
  // ветку по умолчанию — раздел «Покупатели» без прав показывал «Обзор» с выручкой
  // компании. Рельса такой раздел прячет, но прямой адрес открывался.
  if (!items.length) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        В этом разделе нет доступных вам экранов. Права выдаются в «Управлении».
      </div>
    )
  }

  // Помощь — общий компонент пространства: тот же свод «Инфо», суженный до продукта.
  // Своей копии этого экрана не заводим, иначе она разойдётся с подсказкой рельсы.
  if (coreMode === 'rev_help') {
    return (
      <ProductHelpPanel companyId={companyId} section={sub} appCode="revenue"
        slices={REVENUE_HELP_SLICES} menu={REV_MENU_FOR_HELP} modeForKey={modeForHelpKey} />
    )
  }

  const view = (() => {
    switch (sub) {
      case 'rev_trend':      return <RevTrend companyId={companyId} kind={shown} />
      case 'rev_compare':    return <RevCompare companyId={companyId} kind={shown} period={period} />
      case 'rev_slices':     return <RevSlices companyId={companyId} kind={shown} period={period} />
      case 'rev_clients':    return <RevClients companyId={companyId} kind={shown} period={period} />
      case 'rev_abc':        return <RevAbc companyId={companyId} period={period} of="clients" />
      case 'rev_churn':      return <RevChurn companyId={companyId} kind={shown} period={period} />
      case 'rev_nomen':      return <RevItems companyId={companyId} kind="goods" period={period} title="Номенклатура" />
      case 'rev_svc':        return <RevItems companyId={companyId} kind="service" period={period} title="Услуги" />
      case 'rev_abc_items':  return <RevAbc companyId={companyId} period={period} of="items" />
      case 'rev_sale_docs':  return <RevSaleDocs companyId={companyId} kind={shown} period={period} />
      case 'rev_invoices':   return <RevInvoices companyId={companyId} period={period} />
      case 'rev_funnel':     return <RevFunnel companyId={companyId} period={period} />
      case 'rev_recon':      return <RevRecon companyId={companyId} />
      case 'rev_margin':     return <RevMargin companyId={companyId} period={period} />
      case 'rev_terms':      return <RevTerms companyId={companyId} period={period} />
      case 'rev_cashflow':   return <RevCashflow companyId={companyId} />
      case 'rev_contracts':  return <RevContracts companyId={companyId} period={period} />
      case 'rev_stock':      return <RevStock companyId={companyId} />
      case 'rev_suppliers':  return <RevSuppliers companyId={companyId} period={period} view="list" />
      case 'rev_prices':     return <RevSuppliers companyId={companyId} period={period} view="prices" />
      case 'rev_quality':    return <RevQuality companyId={companyId} />
      case 'rev_deals':      return <RevDeals companyId={companyId} period={period} />
      case 'rev_conc':       return <RevConcentration companyId={companyId} />
      case 'rev_aging':      return <RevAging companyId={companyId} />
      case 'rev_collect':    return <RevCollection companyId={companyId} />
      case 'rev_forecast':   return <RevForecast companyId={companyId} />
      case 'rev_cfitems':    return <RevCashflowItems companyId={companyId} period={period} />
      case 'rev_attention':  return <RevAttention companyId={companyId} period={period} />
      case 'rev_backlog':    return <RevBacklog companyId={companyId} />
      default:               return <RevOverview companyId={companyId} kind={shown} period={period} />
    }
  })()

  return (
    <div className="h-full flex flex-col">
      {/* Разрез не показываем там, где он предмет пункта («Номенклатура» — это уже
          товары) и где вопрос не про строки документа (счета, воронка). */}
      {!FIXED_KIND[sub] && !NO_KIND.includes(sub) && (
        <div className="px-4 pt-3">
          <Tabs value={kind} onChange={setKind} items={KIND_TABS} />
        </div>
      )}
      <ScrollArea className="flex-1 min-h-0">{view}</ScrollArea>
    </div>
  )
}

/* ────────────────────────────────────────────────────────────── */
/*                        Продажи                                 */
/* ────────────────────────────────────────────────────────────── */

/**
 * Обзор отвечает на вопрос «как идут дела», а не «сколько всего»: каждая цифра
 * стоит рядом с такой же за прошлый период той же длины. Без сравнения число
 * «22,1 млн» не говорит ничего — непонятно, много это или провал.
 */
function RevOverview({ companyId, kind, period }: {
  companyId: string; kind: RevKind; period: Period
}) {
  const cur = useRevenue(companyId, kind, period)
  const prev = useRevenue(companyId, kind, prevPeriod(period))
  const [card, setCard] = useState<string | null>(null)

  if (cur.isError) return <div className="p-4"><QueryError onRetry={() => cur.refetch()} /></div>
  if (!cur.data) return <Loading />
  const d = cur.data
  const p = prev.data
  const avg = d.docs ? d.total / d.docs : 0
  const avgPrev = p && p.docs ? p.total / p.docs : 0
  const kinds = d.byKind ?? { goods: 0, service: 0 }
  const kindsTotal = kinds.goods + kinds.service

  return (
    <div className="p-4 space-y-4">
      <div className="flex justify-end">
        <ExportButton onClick={() => exportTable('Обзор реализации', [
          { header: 'Показатель', key: 'label', width: 30 },
          { header: 'Период', key: 'now', width: 18, money: true },
          { header: 'Прошлый период', key: 'was', width: 18, money: true },
        ], [
          { label: 'Оборот с НДС', now: d.total, was: p?.total ?? null },
          { label: 'Оборот без НДС', now: d.net, was: p?.net ?? null },
          { label: 'Документов', now: d.docs, was: p?.docs ?? null },
          { label: 'Покупателей', now: d.clients, was: p?.clients ?? null },
          { label: 'НДС', now: d.vat, was: p?.vat ?? null },
        ])} />
      </div>

      <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
        <MetricTile label="Оборот с НДС" value={money.format(d.total) + ' ₽'}
          hint={`без НДС ${money.format(d.net)} ₽`} />
        <MetricTile label="Документов" value={num.format(d.docs)}
          hint={`средний ${money.format(avg)} ₽`} />
        <MetricTile label="Покупателей" value={num.format(d.clients)} />
        <MetricTile label="НДС" value={money.format(d.vat) + ' ₽'} />
      </div>

      <Card>
        <CardContent className="p-4 space-y-3">
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
            К прошлому периоду ({periodLabel(prevPeriod(period))})
          </div>
          {prev.isError ? (
            <QueryError onRetry={() => prev.refetch()} />
          ) : !p ? <div className="text-sm text-muted-foreground">Считаем…</div> : (
            <table className="w-full text-sm">
              <tbody>
                {[
                  { label: 'Оборот', now: d.total, was: p.total, fmt: money },
                  { label: 'Документов', now: d.docs, was: p.docs, fmt: num },
                  { label: 'Средний документ', now: avg, was: avgPrev, fmt: money },
                  { label: 'Покупателей', now: d.clients, was: p.clients, fmt: num },
                ].map((r) => (
                  <tr key={r.label} className="border-b last:border-0">
                    <td className="py-1.5 text-muted-foreground">{r.label}</td>
                    <td className="py-1.5 text-right tabular-nums">{r.fmt.format(r.now)}</td>
                    <td className="py-1.5 text-right tabular-nums text-muted-foreground w-32">
                      было {r.fmt.format(r.was)}
                    </td>
                    <td className="py-1.5 text-right w-24"><Delta now={r.now} was={r.was} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>

      {kind === 'all' && kindsTotal > 0 && (
        <Card>
          <CardContent className="p-4 space-y-2">
            <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
              Товары и услуги — по строкам документов
            </div>
            <div className="flex h-3 rounded overflow-hidden">
              <div className="bg-primary/70" style={{ width: `${(kinds.goods / kindsTotal) * 100}%` }} />
              <div className="bg-amber-500/70" style={{ width: `${(kinds.service / kindsTotal) * 100}%` }} />
            </div>
            <div className="flex gap-4 text-sm">
              <span>Товары <b className="tabular-nums">{money.format(kinds.goods)} ₽</b>
                <span className="ml-1 text-muted-foreground tabular-nums">
                  {((kinds.goods / kindsTotal) * 100).toFixed(1)}%
                </span></span>
              <span>Услуги <b className="tabular-nums">{money.format(kinds.service)} ₽</b>
                <span className="ml-1 text-muted-foreground tabular-nums">
                  {((kinds.service / kindsTotal) * 100).toFixed(1)}%
                </span></span>
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent className="p-4">
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground mb-3">
            Помесячно за период
          </div>
          <MonthBars months={d.months} />
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <TableCard note="Пять покупателей с наибольшим оборотом за период"
          head={<><Th>Покупатель</Th><Th right>Оборот</Th><Th right>Доля</Th></>}>
          {d.topClients.slice(0, 5).map((c) => (
            <tr key={clientKey(c)} className="border-b last:border-0 hover:bg-muted/40">
              <td className="px-3 py-1.5 max-w-[260px] truncate" title={c.name}>
                {c.id ? (
                  <button onClick={() => setCard(c.id)}
                    className="text-left hover:text-primary hover:underline">{c.name}</button>
                ) : c.name}
              </td>
              <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
                {money.format(c.amount)} ₽
              </td>
              <td className="px-3 py-1.5"><Share value={c.amount} of={d.total} /></td>
            </tr>
          ))}
        </TableCard>
        <TableCard note="Пять позиций с наибольшей суммой за период"
          head={<><Th>Позиция</Th><Th right>Сумма</Th><Th right>Доля</Th></>}>
          {d.topItems.slice(0, 5).map((it) => (
            <tr key={it.code ?? it.name} className="border-b last:border-0 hover:bg-muted/40">
              <td className="px-3 py-1.5 max-w-[260px] truncate" title={it.name}>{it.name}</td>
              <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
                {money.format(it.amount)} ₽
              </td>
              <td className="px-3 py-1.5"><Share value={it.amount} of={d.total} /></td>
            </tr>
          ))}
        </TableCard>
      </div>

      {card && <CounterpartyWindow companyId={companyId} id={card} onClose={() => setCard(null)} />}
    </div>
  )
}

/**
 * Динамика — вся история месяцами, независимо от фильтра периода: тренд на отрезке
 * в один месяц не виден, а именно за ним сюда и приходят. Год к году считается по
 * тем же месяцам предыдущего года, а не по «прошлым 12 месяцам»: у сезонного
 * бизнеса второе сравнение бессмысленно.
 */
function RevTrend({ companyId, kind }: { companyId: string; kind: RevKind }) {
  const q = useRevenue(companyId, kind)   // без периода — вся история
  const years = useMemo(() => {
    const by = new Map<string, { amount: number; docs: number }>()
    for (const m of q.data?.months ?? []) {
      const y = m.month.slice(0, 4)
      const cell = by.get(y) ?? { amount: 0, docs: 0 }
      cell.amount += m.amount
      cell.docs += m.docs
      by.set(y, cell)
    }
    return [...by.entries()].sort(([a], [b]) => a.localeCompare(b))
      .map(([year, v], i, arr) => {
        const was = i > 0 ? arr[i - 1][1].amount : 0
        return { year, ...v, was }
      })
  }, [q.data])

  if (q.isError) return <div className="p-4"><QueryError onRetry={() => q.refetch()} /></div>
  if (!q.data) return <Loading />
  const months = q.data.months

  return (
    <div className="p-4 space-y-4">
      <Card>
        <CardContent className="p-4">
          <div className="flex items-center justify-between mb-3">
            <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
              Вся история помесячно — {months.length} мес.
            </div>
            <ExportButton onClick={() => exportTable('Динамика реализации', [
              { header: 'Месяц', key: 'month', width: 18 },
              { header: 'Оборот', key: 'amount', width: 16, money: true },
              { header: 'Документов', key: 'docs', width: 12 },
            ], months.map((m) => ({ month: monthLabel(m.month), amount: m.amount, docs: m.docs })))} />
          </div>
          <MonthBars months={months} height={160} />
        </CardContent>
      </Card>

      <TableCard note="Год к году: сравнение с тем же показателем предыдущего года"
        head={<><Th>Год</Th><Th right>Оборот</Th><Th right>Документов</Th>
          <Th right>Средний документ</Th><Th right>К прошлому году</Th></>}>
        {years.map((y) => (
          <tr key={y.year} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5 tabular-nums">{y.year}</td>
            <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
              {money.format(y.amount)} ₽
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">{y.docs}</td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
              {money.format(y.docs ? y.amount / y.docs : 0)} ₽
            </td>
            <td className="px-3 py-1.5 text-right"><Delta now={y.amount} was={y.was} /></td>
          </tr>
        ))}
      </TableCard>

      <TableCard note="Месяц к тому же месяцу прошлого года"
        head={<><Th>Месяц</Th><Th right>Оборот</Th><Th right>Год назад</Th><Th right>YoY</Th></>}>
        {[...months].reverse().map((m) => {
          const prevYear = months.find((x) => x.month === `${Number(m.month.slice(0, 4)) - 1}-${m.month.slice(5)}`)
          return (
            <tr key={m.month} className="border-b last:border-0 hover:bg-muted/40">
              <td className="px-3 py-1.5">{monthLabel(m.month)}</td>
              <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
                {money.format(m.amount)} ₽
              </td>
              <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground whitespace-nowrap">
                {prevYear ? `${money.format(prevYear.amount)} ₽` : '—'}
              </td>
              <td className="px-3 py-1.5 text-right">
                <Delta now={m.amount} was={prevYear?.amount ?? 0} />
              </td>
            </tr>
          )
        })}
      </TableCard>
    </div>
  )
}

/**
 * Сравнение периодов: слева период рабочей области, справа — с чем сравниваем.
 * Два готовых варианта («предыдущий» и «год назад») закрывают почти все случаи;
 * произвольный второй период потребовал бы второго календаря в шапке, а он там
 * один на всё пространство.
 */
function RevCompare({ companyId, kind, period }: {
  companyId: string; kind: RevKind; period: Period
}) {
  const [base, setBase] = useState<'prev' | 'year'>('prev')
  const other = base === 'prev' ? prevPeriod(period) : yearAgo(period)
  const a = useRevenue(companyId, kind, period)
  const b = useRevenue(companyId, kind, other)

  // Ошибку обязаны показать оба запроса: раньше падение второго оставляло экран
  // в «Загрузка…» навсегда, без кнопки «Повторить».
  if (a.isError || b.isError) {
    return <div className="p-4"><QueryError onRetry={() => { a.refetch(); b.refetch() }} /></div>
  }
  if (!a.data || !b.data) return <Loading />

  const rows = [
    { label: 'Оборот с НДС', now: a.data.total, was: b.data.total, fmt: money },
    { label: 'Оборот без НДС', now: a.data.net, was: b.data.net, fmt: money },
    { label: 'НДС', now: a.data.vat, was: b.data.vat, fmt: money },
    { label: 'Документов', now: a.data.docs, was: b.data.docs, fmt: num },
    { label: 'Покупателей', now: a.data.clients, was: b.data.clients, fmt: num },
    {
      label: 'Средний документ',
      now: a.data.docs ? a.data.total / a.data.docs : 0,
      was: b.data.docs ? b.data.total / b.data.docs : 0, fmt: money,
    },
  ]

  // Покупатели обоих периодов рядом: где вырос, где просел, кого не стало.
  const byClient = new Map<string, { name: string; now: number; was: number }>()
  for (const c of a.data.topClients) {
    byClient.set(clientKey(c), { name: c.name, now: c.amount, was: 0 })
  }
  for (const c of b.data.topClients) {
    const k = clientKey(c)
    const cell = byClient.get(k) ?? { name: c.name, now: 0, was: 0 }
    cell.was = c.amount
    byClient.set(k, cell)
  }
  const clients = [...byClient.values()].sort((x, y) => (y.now - y.was) - (x.now - x.was))

  // Сопоставимая база: только те покупатели, что были в ОБОИХ периодах. Отделяет
  // «мы выросли» от «пришёл один большой проект» — для компании с проектными
  // поставками это разные новости, а общий итог их смешивает.
  const both = clients.filter((c) => c.now > 0 && c.was > 0)
  const lflNow = both.reduce((sum, c) => sum + c.now, 0)
  const lflWas = both.reduce((sum, c) => sum + c.was, 0)
  const arrived = clients.filter((c) => c.now > 0 && c.was === 0)
  const left = clients.filter((c) => c.now === 0 && c.was > 0)

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <Tabs value={base} onChange={setBase} items={[
          { key: 'prev' as const, label: 'Предыдущий период' },
          { key: 'year' as const, label: 'Год назад' },
        ]} />
        <div className="flex items-center gap-3">
          <div className="text-xs text-muted-foreground tabular-nums">
            {periodLabel(period)} · против · {periodLabel(other)}
          </div>
          <ExportButton onClick={() => exportTable('Сравнение периодов', [
            { header: 'Показатель', key: 'label', width: 30 },
            { header: periodLabel(period), key: 'now', width: 20, money: true },
            { header: periodLabel(other), key: 'was', width: 20, money: true },
          ], rows.map((r) => ({ label: r.label, now: r.now, was: r.was })))} />
        </div>
      </div>

      <TableCard head={<><Th>Показатель</Th><Th right>{periodLabel(period)}</Th>
        <Th right>{periodLabel(other)}</Th><Th right>Изменение</Th></>}>
        {rows.map((r) => (
          <tr key={r.label} className="border-b last:border-0">
            <td className="px-3 py-1.5">{r.label}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{r.fmt.format(r.now)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
              {r.fmt.format(r.was)}
            </td>
            <td className="px-3 py-1.5 text-right"><Delta now={r.now} was={r.was} /></td>
          </tr>
        ))}
      </TableCard>

      <Card>
        <CardContent className="p-4 space-y-2">
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
            Сопоставимая база — покупатели, которые были в обоих периодах
          </div>
          <table className="w-full text-sm">
            <tbody>
              <tr className="border-b">
                <td className="py-1.5 text-muted-foreground">
                  Сопоставимые ({num.format(both.length)} покупателей)
                </td>
                <td className="py-1.5 text-right tabular-nums">{money.format(lflNow)} ₽</td>
                <td className="py-1.5 text-right tabular-nums text-muted-foreground w-32">
                  было {money.format(lflWas)} ₽
                </td>
                <td className="py-1.5 text-right w-24"><Delta now={lflNow} was={lflWas} /></td>
              </tr>
              <tr className="border-b">
                <td className="py-1.5 text-muted-foreground">
                  Пришли впервые ({num.format(arrived.length)})
                </td>
                <td className="py-1.5 text-right tabular-nums">
                  {money.format(arrived.reduce((sum, c) => sum + c.now, 0))} ₽
                </td>
                <td colSpan={2} className="py-1.5 text-right text-[11px] text-muted-foreground">
                  весь этот оборот — прирост, но не повторяемый
                </td>
              </tr>
              <tr>
                <td className="py-1.5 text-muted-foreground">
                  Перестали покупать ({num.format(left.length)})
                </td>
                <td className="py-1.5 text-right tabular-nums text-muted-foreground">
                  {money.format(left.reduce((sum, c) => sum + c.was, 0))} ₽
                </td>
                <td colSpan={2} className="py-1.5 text-right text-[11px] text-muted-foreground">
                  столько выручки ушло вместе с ними
                </td>
              </tr>
            </tbody>
          </table>
          <p className="text-[11px] text-muted-foreground">
            Сопоставимая база отвечает на вопрос, выросли ли мы на своих клиентах.
            Общий итог его смешивает: один пришедший проект способен перекрыть падение
            по всем остальным, и рост будет выглядеть как успех работы с базой.
          </p>
        </CardContent>
      </Card>

      <TableCard note="Покупатели обоих периодов — отсортированы по приросту оборота"
        head={<><Th>Покупатель</Th><Th right>Период</Th><Th right>Сравнение</Th>
          <Th right>Разница</Th></>}>
        {clients.map((c) => (
          <tr key={c.name} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5 max-w-[360px] truncate" title={c.name}>{c.name}</td>
            <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
              {money.format(c.now)} ₽
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground whitespace-nowrap">
              {money.format(c.was)} ₽
            </td>
            <td className={cn('px-3 py-1.5 text-right tabular-nums whitespace-nowrap',
              c.now - c.was >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400')}>
              {c.now - c.was >= 0 ? '+' : ''}{money.format(c.now - c.was)} ₽
            </td>
          </tr>
        ))}
      </TableCard>
    </div>
  )
}

/** Одно и то же множество документов, свёрнутое по выбранному измерению. */
type SliceDim = 'month' | 'quarter' | 'year' | 'client' | 'item'

const DIM_TABS: { key: SliceDim; label: string }[] = [
  { key: 'month', label: 'По месяцам' },
  { key: 'quarter', label: 'По кварталам' },
  { key: 'year', label: 'По годам' },
  { key: 'client', label: 'По покупателям' },
  { key: 'item', label: 'По позициям' },
]

function RevSlices({ companyId, kind, period }: {
  companyId: string; kind: RevKind; period: Period
}) {
  const [dim, setDim] = useState<SliceDim>('month')
  const q = useRevenue(companyId, kind, period)

  const rows = useMemo(() => {
    const d = q.data
    if (!d) return []
    if (dim === 'client') {
      return d.topClients.map((c) => ({ label: c.name, amount: c.amount, count: c.docs }))
    }
    if (dim === 'item') {
      return d.topItems.map((i) => ({ label: i.name, amount: i.amount, count: null }))
    }
    const key = (m: string) =>
      dim === 'year' ? m.slice(0, 4)
      : dim === 'quarter' ? `${m.slice(0, 4)} · ${Math.ceil(Number(m.slice(5, 7)) / 3)} кв.`
      : monthLabel(m)
    const by = new Map<string, { amount: number; count: number }>()
    for (const m of d.months) {
      const cell = by.get(key(m.month)) ?? { amount: 0, count: 0 }
      cell.amount += m.amount
      cell.count += m.docs
      by.set(key(m.month), cell)
    }
    return [...by.entries()].map(([label, v]) => ({ label, amount: v.amount, count: v.count }))
  }, [q.data, dim])

  if (q.isError) return <div className="p-4"><QueryError onRetry={() => q.refetch()} /></div>
  if (!q.data) return <Loading />
  // Доли считаются от суммы ПОКАЗАННЫХ строк, а не от итога документов: у позиций
  // сумма собирается по строкам, и чужой знаменатель давал доли, не дающие ста.
  const shownTotal = rows.reduce((s, r) => s + r.amount, 0)
  const total = shownTotal || 1

  return (
    <div className="p-4 space-y-3">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <Tabs value={dim} onChange={setDim} items={DIM_TABS} />
        <ExportButton onClick={() => exportTable('Разрез реализации', [
          { header: 'Разрез', key: 'label', width: 42 },
          { header: 'Оборот', key: 'amount', width: 16, money: true },
          { header: 'Документов', key: 'count', width: 12 },
        ], rows)} />
      </div>
      <TableCard
        note={`${rows.length} строк · итог ${money.format(shownTotal)} ₽`
          + (dim === 'item' && Math.abs(shownTotal - q.data.total) > 1
            ? ` · сумма документов ${money.format(q.data.total)} ₽: позиции считаются по`
              + ' строкам, а документ — по шапке, и у части документов они разошлись'
            : '')}
        head={<><Th>Разрез</Th><Th right>Документов</Th><Th right>Оборот</Th><Th right>Доля</Th></>}>
        {rows.map((r) => (
          <tr key={r.label} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5 max-w-[420px] truncate" title={r.label}>{r.label}</td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
              {r.count ?? '—'}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
              {money.format(r.amount)} ₽
            </td>
            <td className="px-3 py-1.5"><Share value={r.amount} of={total} /></td>
          </tr>
        ))}
      </TableCard>
    </div>
  )
}

/* ────────────────────────────────────────────────────────────── */
/*                       Покупатели                               */
/* ────────────────────────────────────────────────────────────── */

/**
 * Реестр покупателей. Строка ведёт в КАРТОЧКУ контрагента — то же юрлицо, о котором
 * пространство знает всё: реквизиты, договоры, долг, что покупает. Кнопкой становится
 * только сведённый со справочником (`id`): у части документов ИНН не приезжает вовсе,
 * карточки у них нет, и ссылка вела бы в пустоту.
 *
 * «Молчит» — дней с последней покупки. Молчащий покупатель из реестра не исчезает и
 * выглядит как активный: оборот у него есть, просто накоплен полгода назад. Отсюда
 * колонка и отбор «молчат 90+ дней» — это и есть «молчащие покупатели» второй волны.
 */
function RevClients({ companyId, kind, period }: {
  companyId: string; kind: RevKind; period: Period
}) {
  const q = useRevenue(companyId, kind, period)
  const [card, setCard] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [amount, setAmount] = useState({ from: '', to: '' })
  const [silent, setSilent] = useState(false)

  if (q.isError) return <div className="p-4"><QueryError onRetry={() => q.refetch()} /></div>
  if (!q.data) return <Loading />
  const d = q.data
  const found = d.topClients.filter((c) =>
    (!search || c.name.toLowerCase().includes(search.toLowerCase()) || (c.inn ?? '').includes(search))
    && inRange(c.amount, amount.from, amount.to)
    && (!silent || (daysSince(c.last) ?? 0) > 90))
  const unlinked = d.topClients.filter((c) => !c.id).length

  return (
    <div className="p-4 space-y-3">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3 flex-wrap">
          <SearchInput value={search} onChange={setSearch}
            placeholder="Покупатель или ИНН" label="Поиск по покупателю или ИНН" />
          <AmountRange from={amount.from} to={amount.to}
            onChange={(from, to) => setAmount({ from, to })} />
          <Tabs value={silent ? 'silent' : 'all'} onChange={(v) => setSilent(v === 'silent')}
            items={[{ key: 'all', label: 'Все' }, { key: 'silent', label: 'Молчат 90+ дней' }]} />
        </div>
        <ExportButton onClick={() => exportTable('Покупатели', [
          { header: 'Покупатель', key: 'name', width: 42 },
          { header: 'ИНН', key: 'inn', width: 14 },
          { header: 'Документов', key: 'docs', width: 12 },
          { header: 'Оборот', key: 'amount', width: 16, money: true },
          { header: 'Первая покупка', key: 'first', width: 14 },
          { header: 'Последняя покупка', key: 'last', width: 16 },
        ], found)} />
      </div>
      <TableCard
        note={`${num.format(found.length)} из ${num.format(d.clients)} — по обороту за период`
          + (unlinked ? ` · ${unlinked} без карточки в справочнике` : '')}
        head={<>
          <Th>Покупатель</Th><Th>ИНН</Th><Th right>Документов</Th>
          <Th right>Оборот</Th><Th right>Доля</Th><Th>Последняя</Th><Th right>Молчит</Th>
        </>}>
        {found.map((c) => {
          const days = daysSince(c.last)
          return (
            <tr key={clientKey(c)} className="border-b last:border-0 hover:bg-muted/40">
              <td className="px-3 py-1.5 max-w-[300px] truncate" title={c.name}>
                {c.id ? (
                  <button onClick={() => setCard(c.id)}
                    className="text-left hover:text-primary hover:underline">{c.name}</button>
                ) : c.name}
              </td>
              <td className="px-3 py-1.5 tabular-nums text-muted-foreground">{c.inn ?? '—'}</td>
              <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">{c.docs}</td>
              <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
                {money.format(c.amount)} ₽
              </td>
              <td className="px-3 py-1.5"><Share value={c.amount} of={d.total || 1} /></td>
              <td className="px-3 py-1.5 tabular-nums text-muted-foreground whitespace-nowrap">
                {c.last ?? '—'}
              </td>
              <td className={cn('px-3 py-1.5 text-right tabular-nums whitespace-nowrap',
                days !== null && days > 180 ? 'text-rose-600 dark:text-rose-400'
                : days !== null && days > 90 ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground')}>
                {days === null ? '—' : `${num.format(days)} дн.`}
              </td>
            </tr>
          )
        })}
      </TableCard>
      {card && <CounterpartyWindow companyId={companyId} id={card} onClose={() => setCard(null)} />}
    </div>
  )
}

/* ── ABC × частота ──────────────────────────────────────────────────────── */

const FREQ: { key: 'once' | 'few' | 'regular'; label: string; hint: string }[] = [
  { key: 'regular', label: 'Регулярные', hint: 'покупали 6+ месяцев' },
  { key: 'few', label: 'Эпизодические', hint: '2–5 месяцев' },
  { key: 'once', label: 'Разовые', hint: 'один месяц' },
]

const CELL_HINT: Record<string, string> = {
  'A/regular': 'Ядро: большой оборот и постоянные покупки — на этом компания и держится.',
  'A/few': 'Крупные, но приходят наездами — вопрос, чем занят промежуток.',
  'A/once': 'Крупная разовая сделка. Выручка была, повторяемости нет — на неё нельзя планировать.',
  'B/regular': 'Крепкий середняк с постоянными покупками — опора выручки.',
  'B/few': 'Середняк наездами — потенциал роста, если сделать регулярным.',
  'B/once': 'Разовый середняк — проверить, была ли попытка вернуть.',
  'C/regular': 'Малый оборот, но ходят постоянно — устойчивая мелочь.',
  'C/few': 'Малые и редкие — наблюдать.',
  'C/once': 'Хвост из разовых — основная масса строк; ими меряется, насколько бизнес проектный.',
}

/**
 * ABC × частота покупок: вклад в оборот против того, повторяются ли покупки.
 *
 * Второй осью задумывался классический XYZ (стабильность спроса, канон пространства
 * — та же формула, что у сети ЭЗС). На данных офисной компании он молчит: 153 позиции
 * из 201 продавались ровно в ОДНОМ месяце, 23 покупателя из 43 покупали один раз, и
 * 95 % строк получали «мало данных». Это не дефект расчёта, а профиль бизнеса —
 * поставки проектные. Поэтому осью стала ЧАСТОТА, а разброс (CV и класс XYZ) остался
 * колонкой там, где ряд действительно есть.
 *
 * Главный ответ экрана на таких данных: какая доля выручки держится на разовых
 * сделках. Клетка матрицы — отбор: нажали «A · Разовые» — остались крупные разовые.
 */
function RevAbc({ companyId, period, of }: {
  companyId: string; period: Period; of: 'clients' | 'items'
}) {
  const q = useQuery({
    // Ключ по ТОМУ ЖЕ значению, что уходит в запрос: раньше «ABC товаров» и «Маржа»
    // тянули один и тот же тяжёлый ответ под разными ключами ('items' и 'item').
    queryKey: ['books', 'assortment', companyId, of === 'clients' ? 'client' : 'item',
               period.from, period.to],
    queryFn: () => getAssortment(companyId, of === 'clients' ? 'client' : 'item', period),
    enabled: !!companyId,
  })
  const [cell, setCell] = useState<string | null>(null)
  const [card, setCard] = useState<string | null>(null)

  const rows = useMemo(() => {
    const src = (q.data?.rows ?? []).map((r) => ({ ...r, value: r.amount ?? r.soldAmount ?? 0 }))
    const total = src.reduce((s, r) => s + r.value, 0) || 1
    let acc = 0
    return src.map((r) => {
      acc += r.value
      const cum = (acc / total) * 100
      return { ...r, share: (r.value / total) * 100, cum, abc: cum <= 80 ? 'A' : cum <= 95 ? 'B' : 'C' }
    })
  }, [q.data])

  if (q.isError) return <div className="p-4"><QueryError onRetry={() => q.refetch()} /></div>
  if (!q.data) return <Loading />

  const what = of === 'clients' ? 'покупателей' : 'позиций'
  if (!rows.length) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        За выбранный период продаж нет — разбирать по вкладу и повторяемости нечего.
      </div>
    )
  }
  const total = rows.reduce((s, r) => s + r.value, 0) || 1
  const shown = cell ? rows.filter((r) => `${r.abc}/${r.freq}` === cell) : rows
  const once = rows.filter((r) => r.freq === 'once')
  const onceSum = once.reduce((s, r) => s + r.value, 0)

  return (
    <div className="p-4 space-y-4">
      <div className="grid gap-3 grid-cols-3">
        {FREQ.map((f) => {
          const part = rows.filter((r) => r.freq === f.key)
          const sum = part.reduce((s, r) => s + r.value, 0)
          return (
            <MetricTile key={f.key} label={f.label}
              value={`${num.format(part.length)} ${what}`}
              hint={`${money.format(sum)} ₽ · ${((sum / total) * 100).toFixed(1)}% оборота · ${f.hint}`} />
          )
        })}
      </div>

      <Card>
        <CardContent className="p-4 space-y-2 overflow-x-auto">
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
            Вклад в оборот × частота покупок — клетка отбирает строки
          </div>
          <table className="text-sm">
            <thead className="text-[11px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="px-2 py-1 text-left font-normal" />
                {FREQ.map((f) => (
                  <th key={f.key} className="px-2 py-1 text-left font-normal">
                    {f.label} <span className="normal-case opacity-70">· {f.hint}</span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(['A', 'B', 'C'] as const).map((abc) => (
                <tr key={abc}>
                  <td className="px-2 py-1 text-muted-foreground">{abc}</td>
                  {FREQ.map((f) => {
                    const part = rows.filter((r) => r.abc === abc && r.freq === f.key)
                    const sum = part.reduce((s, r) => s + r.value, 0)
                    const key = `${abc}/${f.key}`
                    return (
                      <td key={key} className="px-1 py-1">
                        <button disabled={!part.length} onClick={() => setCell(cell === key ? null : key)}
                          title={CELL_HINT[key] ?? ''}
                          className={cn('w-44 rounded-md border px-2 py-1.5 text-left',
                            !part.length ? 'opacity-40'
                            : cell === key ? 'border-primary bg-primary/10'
                            : 'hover:bg-muted/50')}>
                          <div className="tabular-nums">{part.length}</div>
                          <div className="text-[11px] text-muted-foreground tabular-nums">
                            {money.format(sum)} ₽ · {((sum / total) * 100).toFixed(1)}%
                          </div>
                        </button>
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-[11px] text-muted-foreground">
            {cell
              ? CELL_HINT[cell]
              : `A — первые 80 % оборота, B — следующие 15 %, C — остальные 5 %. `
                + `На разовые приходится ${((onceSum / total) * 100).toFixed(1)} % оборота: `
                + `настолько бизнес зависит от неповторяющихся сделок.`}
          </p>
        </CardContent>
      </Card>

      <div className="flex justify-end">
        <ExportButton onClick={() => exportTable(
          of === 'clients' ? 'ABC покупателей' : 'ABC товаров', [
            { header: 'Группа', key: 'group', width: 10 },
            { header: of === 'clients' ? 'Покупатель' : 'Позиция', key: 'name', width: 44 },
            { header: 'Оборот', key: 'value', width: 16, money: true },
            { header: 'Доля, %', key: 'share', width: 10 },
            { header: 'Накоплено, %', key: 'cum', width: 12 },
            { header: 'Месяцев с покупкой', key: 'saleMonths', width: 16 },
            { header: 'Разброс (CV)', key: 'cv', width: 12 },
            { header: 'Тренд, %', key: 'trendPct', width: 10 },
          ], shown.map((r) => ({ ...r, group: `${r.abc} · ${FREQ.find((f) => f.key === r.freq)?.label}` })))} />
      </div>

      <TableCard
        note={cell
          ? `Отбор ${cell.replace('/', ' · ')}: ${num.format(shown.length)} ${what}`
          : `${num.format(rows.length)} ${what} по убыванию вклада в оборот`}
        head={<><Th>Группа</Th><Th>{of === 'clients' ? 'Покупатель' : 'Позиция'}</Th>
          <Th right>Оборот</Th><Th right>Доля</Th><Th right>Накоплено</Th>
          <Th right>Месяцев</Th><Th right>Разброс</Th><Th right>Тренд</Th></>}>
        {shown.map((r) => (
          <tr key={r.key} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5 whitespace-nowrap">
              <span className={cn('rounded px-1.5 py-0.5 text-[11px] font-medium',
                r.abc === 'A' ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'
                : r.abc === 'B' ? 'bg-amber-500/15 text-amber-600 dark:text-amber-400'
                : 'bg-muted text-muted-foreground')}>{r.abc}</span>
              <span className="ml-1.5 text-[11px] text-muted-foreground">
                {r.freq === 'once' ? 'разовый' : r.freq === 'few' ? 'эпизод.' : 'регуляр.'}
              </span>
            </td>
            <td className="px-3 py-1.5 max-w-[340px] truncate" title={r.name}>
              {of === 'clients' && r.id ? (
                <button onClick={() => setCard(r.id!)}
                  className="text-left hover:text-primary hover:underline">{r.name}</button>
              ) : of === 'items' && r.code ? (
                <button onClick={() => setCard(r.code!)}
                  className="text-left hover:text-primary hover:underline">{r.name}</button>
              ) : r.name}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
              {money.format(r.value)} ₽
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
              {r.share.toFixed(1)}%
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
              {r.cum.toFixed(1)}%
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
              {r.saleMonths}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground"
              title={r.cv === null ? 'ряда для расчёта не хватает' : `класс ${r.xyz}`}>
              {r.cv === null ? '—' : `${r.cv.toFixed(2)} · ${r.xyz}`}
            </td>
            <td className={cn('px-3 py-1.5 text-right tabular-nums',
              r.trend === 'up' ? 'text-emerald-600 dark:text-emerald-400'
              : r.trend === 'down' ? 'text-rose-600 dark:text-rose-400' : 'text-muted-foreground')}>
              {r.trendPct === null ? '—' : `${r.trendPct > 0 ? '+' : ''}${r.trendPct.toFixed(0)}%`}
            </td>
          </tr>
        ))}
      </TableCard>
      {card && of === 'clients' && (
        <CounterpartyWindow companyId={companyId} id={card} onClose={() => setCard(null)} />
      )}
      {card && of === 'items' && (
        <NomenclatureWindow companyId={companyId} code={card} onClose={() => setCard(null)} />
      )}
    </div>
  )
}

/**
 * Новые и ушедшие. «Новый» здесь — тот, кто НИКОГДА раньше не покупал, а не «не
 * покупал в прошлом месяце»: для этого берётся вся история до начала периода
 * отдельным запросом. Иначе постоянный клиент с редкими закупками каждый раз
 * попадал бы в новые, и цифра ничего не значила бы.
 */
function RevChurn({ companyId, kind, period }: {
  companyId: string; kind: RevKind; period: Period
}) {
  const prev = prevPeriod(period)
  const cur = useRevenue(companyId, kind, period)
  const before = useRevenue(companyId, kind, { from: '', to: shiftDays(period.from, -1) })
  const prevQ = useRevenue(companyId, kind, prev)
  const [card, setCard] = useState<string | null>(null)

  if (cur.isError || before.isError || prevQ.isError) {
    return (
      <div className="p-4">
        <QueryError onRetry={() => { cur.refetch(); before.refetch(); prevQ.refetch() }} />
      </div>
    )
  }
  if (!cur.data || !before.data || !prevQ.data) return <Loading />

  const beforeKeys = new Set(before.data.topClients.map(clientKey))
  const prevKeys = new Set(prevQ.data.topClients.map(clientKey))
  const curKeys = new Set(cur.data.topClients.map(clientKey))

  const fresh = cur.data.topClients.filter((c) => !beforeKeys.has(clientKey(c)))
  const back = cur.data.topClients.filter((c) =>
    beforeKeys.has(clientKey(c)) && !prevKeys.has(clientKey(c)))
  const gone = prevQ.data.topClients.filter((c) => !curKeys.has(clientKey(c)))

  const list = (title: string, note: string, rows: typeof fresh) => (
    <TableCard note={`${title}: ${num.format(rows.length)} — ${note}`}
      head={<><Th>Покупатель</Th><Th>ИНН</Th><Th right>Документов</Th><Th right>Оборот</Th></>}>
      {rows.length === 0 ? (
        <tr><td colSpan={4} className="px-3 py-3 text-sm text-muted-foreground">Никого</td></tr>
      ) : rows.map((c) => (
        <tr key={clientKey(c)} className="border-b last:border-0 hover:bg-muted/40">
          <td className="px-3 py-1.5 max-w-[320px] truncate" title={c.name}>
            {c.id ? (
              <button onClick={() => setCard(c.id)}
                className="text-left hover:text-primary hover:underline">{c.name}</button>
            ) : c.name}
          </td>
          <td className="px-3 py-1.5 tabular-nums text-muted-foreground">{c.inn ?? '—'}</td>
          <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">{c.docs}</td>
          <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
            {money.format(c.amount)} ₽
          </td>
        </tr>
      ))}
    </TableCard>
  )

  return (
    <div className="p-4 space-y-4">
      <div className="grid gap-3 grid-cols-3">
        <MetricTile label="Новые" value={num.format(fresh.length)}
          hint={`${money.format(fresh.reduce((s, c) => s + c.amount, 0))} ₽ за период`} />
        <MetricTile label="Вернулись" value={num.format(back.length)}
          hint="покупали раньше, но не в прошлом периоде" />
        <MetricTile label="Ушедшие" value={num.format(gone.length)}
          hint={`покупали в ${periodLabel(prev)}, сейчас нет`} />
      </div>
      <div className="flex justify-end">
        <ExportButton onClick={() => exportTable('Новые и ушедшие', [
          { header: 'Группа', key: 'group', width: 16 },
          { header: 'Покупатель', key: 'name', width: 44 },
          { header: 'ИНН', key: 'inn', width: 14 },
          { header: 'Оборот', key: 'amount', width: 18, money: true },
          { header: 'Документов', key: 'docs', width: 12 },
        ], [
          ...fresh.map((c) => ({ ...c, group: 'новые' })),
          ...back.map((c) => ({ ...c, group: 'вернулись' })),
          ...gone.map((c) => ({ ...c, group: 'ушедшие' })),
        ])} />
      </div>

      {list('Новые', 'первая покупка в истории компании', fresh)}
      {list('Вернулись', 'были в истории, пропустили прошлый период', back)}
      {list('Ушедшие', 'были в прошлом периоде, в этом не покупали', gone)}
      {card && <CounterpartyWindow companyId={companyId} id={card} onClose={() => setCard(null)} />}
    </div>
  )
}

/* ────────────────────────────────────────────────────────────── */
/*                      Что продаём                               */
/* ────────────────────────────────────────────────────────────── */

function RevItems({ companyId, kind, period, title }: {
  companyId: string; kind: RevKind; period: Period; title: string
}) {
  const q = useRevenue(companyId, kind, period)
  const [card, setCard] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [amount, setAmount] = useState({ from: '', to: '' })

  if (q.isError) return <div className="p-4"><QueryError onRetry={() => q.refetch()} /></div>
  if (!q.data) return <Loading />
  const found = q.data.topItems.filter((i) =>
    (!search || i.name.toLowerCase().includes(search.toLowerCase())
      || (i.code ?? '').toLowerCase().includes(search.toLowerCase()))
    && inRange(i.amount, amount.from, amount.to))

  return (
    <div className="p-4 space-y-3">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3 flex-wrap">
          <SearchInput value={search} onChange={setSearch}
            placeholder="Наименование или код" label="Поиск по наименованию или коду" />
          <AmountRange from={amount.from} to={amount.to}
            onChange={(from, to) => setAmount({ from, to })} />
        </div>
        <ExportButton onClick={() => exportTable(title, [
          { header: 'Код', key: 'code', width: 14 },
          { header: 'Наименование', key: 'name', width: 48 },
          { header: 'Количество', key: 'qty', width: 12 },
          { header: 'Сумма', key: 'amount', width: 16, money: true },
        ], found)} />
      </div>
      <TableCard
        note={`${title} — ${num.format(found.length)} позиций, `
          + `${money.format(found.reduce((sum, i) => sum + i.amount, 0))} ₽`
          + (found.length !== q.data.topItems.length
            ? ` (всего ${num.format(q.data.topItems.length)} на ${money.format(q.data.total)} ₽)` : '')}
        head={<><Th>{title}</Th><Th right>Количество</Th><Th right>Сумма</Th><Th right>Доля</Th></>}>
        {found.map((it) => (
          <tr key={it.code ?? it.name} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5 max-w-[420px] truncate" title={it.name}>
              {it.code ? (
                <button onClick={() => setCard(it.code)}
                  className="text-left hover:text-primary hover:underline">{it.name}</button>
              ) : it.name}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
              {it.qty ? qty.format(it.qty) : '—'}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
              {money.format(it.amount)} ₽
            </td>
            <td className="px-3 py-1.5"><Share value={it.amount} of={q.data.total || 1} /></td>
          </tr>
        ))}
      </TableCard>
      {card && <NomenclatureWindow companyId={companyId} code={card} onClose={() => setCard(null)} />}
    </div>
  )
}

/* ────────────────────────────────────────────────────────────── */
/*                       Документы                                */
/* ────────────────────────────────────────────────────────────── */

/**
 * Документы вида за период — ЦЕЛИКОМ, а не первой страницей.
 *
 * Все три экрана, которые этим пользуются, считают по строкам итоги (суммы счетов,
 * конверсию воронки, отбор по сумме). Пока документов меньше пятисот, разницы нет;
 * дальше первая страница молча занижала бы каждую цифру.
 */
function useDocs(companyId: string, docType: string, period: Period, lineKind?: string) {
  return useQuery({
    queryKey: ['books', 'docs-all', companyId, docType, lineKind, period.from, period.to],
    queryFn: () => getDocsAll(companyId, docType, { from: period.from, to: period.to }, lineKind),
    enabled: !!companyId,
  })
}

function RevSaleDocs({ companyId, kind, period }: {
  companyId: string; kind: RevKind; period: Period
}) {
  const q = useDocs(companyId, 'sale', period, kind === 'all' ? undefined : kind)
  const [card, setCard] = useState<string | null>(null)
  const [docId, setDocId] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [amount, setAmount] = useState({ from: '', to: '' })

  if (q.isError) return <div className="p-4"><QueryError onRetry={() => q.refetch()} /></div>
  if (!q.data) return <Loading />
  const rows = q.data.rows.filter((r) =>
    (!search || r.counterparty.toLowerCase().includes(search.toLowerCase())
      || r.number.toLowerCase().includes(search.toLowerCase()))
    && inRange(r.amount, amount.from, amount.to))

  return (
    <div className="p-4 space-y-3">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3 flex-wrap">
          <SearchInput value={search} onChange={setSearch}
            placeholder="Контрагент или номер" label="Поиск по контрагенту или номеру документа" />
          <AmountRange from={amount.from} to={amount.to}
            onChange={(from, to) => setAmount({ from, to })} />
        </div>
        <ExportButton onClick={() => exportTable('Реализации', [
          { header: 'Дата', key: 'date', width: 12 },
          { header: 'Номер', key: 'number', width: 16 },
          { header: 'Контрагент', key: 'counterparty', width: 42 },
          { header: 'Сумма', key: 'amount', width: 16, money: true },
          { header: 'НДС', key: 'vat', width: 14, money: true },
        ], rows)} />
      </div>
      <TableCard
        note={`Документы реализации: ${num.format(rows.length)} из ${num.format(q.data.total)}`}
        head={<>
          <Th>Дата</Th><Th>Номер</Th><Th>Контрагент</Th>
          <Th right>Сумма</Th><Th right>НДС</Th><Th right>Строк</Th>
        </>}>
        {rows.map((r) => (
          <tr key={r.id} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5 tabular-nums whitespace-nowrap">{r.date}</td>
            <td className="px-3 py-1.5 tabular-nums">
              {/* Номер — вход в сам документ: строки и проводки. */}
              <button onClick={() => setDocId(r.id)}
                className="hover:text-primary hover:underline">{r.number}</button>
            </td>
            <td className="px-3 py-1.5 max-w-[320px] truncate" title={r.counterparty}>
              {r.counterpartyId ? (
                <button onClick={() => setCard(r.counterpartyId)}
                  className="text-left hover:text-primary hover:underline">{r.counterparty}</button>
              ) : r.counterparty}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums">{money.format(r.amount)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
              {money.format(r.vat)}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">{r.lines}</td>
          </tr>
        ))}
      </TableCard>
      {card && <CounterpartyWindow companyId={companyId} id={card} onClose={() => setCard(null)} />}
      {docId && <DocumentWindow companyId={companyId} docId={docId} onClose={() => setDocId(null)} />}
    </div>
  )
}

/**
 * Счета покупателю. Оплата приезжает из регистра «Оплата счетов» (`paid` в ответе):
 * связь «счёт ↔ платёж» есть только там — по суммам и датам её не восстановить.
 */
function RevInvoices({ companyId, period }: { companyId: string; period: Period }) {
  const q = useDocs(companyId, 'invoice_out', period)
  const [onlyDebt, setOnlyDebt] = useState(false)
  const [amount, setAmount] = useState({ from: '', to: '' })
  const [card, setCard] = useState<string | null>(null)
  const [docId, setDocId] = useState<string | null>(null)

  if (q.isError) return <div className="p-4"><QueryError onRetry={() => q.refetch()} /></div>
  if (!q.data) return <Loading />

  // «Оплата неизвестна» и «не оплачен» — разные ответы. Регистр «Оплата счетов»
  // покрывает часть счетов; у остальных данных нет, и записывать их в долг нельзя.
  const known = q.data.rows.filter((r) => r.paid !== null)
  const unknown = q.data.rows.length - known.length
  const rows = q.data.rows.filter((r) =>
    (!onlyDebt || (r.paid !== null && r.amount - r.paid > 0.01))
    && inRange(r.amount, amount.from, amount.to))
  const billed = q.data.rows.reduce((s, r) => s + r.amount, 0)
  const billedKnown = known.reduce((s, r) => s + r.amount, 0)
  const paid = known.reduce((s, r) => s + (r.paid ?? 0), 0)

  return (
    <div className="p-4 space-y-3">
      <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
        <MetricTile label="Выставлено" value={money.format(billed) + ' ₽'}
          hint={`${num.format(q.data.rows.length)} счетов`} />
        <MetricTile label="Оплачено" value={money.format(paid) + ' ₽'}
          hint={billedKnown ? `${((paid / billedKnown) * 100).toFixed(1)}% от счетов с известной оплатой` : '—'} />
        <MetricTile label="Не оплачено" value={money.format(billedKnown - paid) + ' ₽'}
          hint={`по ${num.format(known.length)} счетам, где оплата известна`} />
        <MetricTile label="Оплата неизвестна" value={num.format(unknown)}
          hint="нет записи в регистре «Оплата счетов»"
          tone={unknown ? 'danger' : undefined} />
      </div>
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3 flex-wrap">
          <Tabs value={onlyDebt ? 'debt' : 'all'} onChange={(v) => setOnlyDebt(v === 'debt')}
            items={[{ key: 'all', label: 'Все счета' }, { key: 'debt', label: 'Только неоплаченные' }]} />
          <AmountRange from={amount.from} to={amount.to}
            onChange={(from, to) => setAmount({ from, to })} />
        </div>
        <ExportButton onClick={() => exportTable('Счета покупателю', [
          { header: 'Дата', key: 'date', width: 12 },
          { header: 'Номер', key: 'number', width: 16 },
          { header: 'Покупатель', key: 'counterparty', width: 42 },
          { header: 'Сумма', key: 'amount', width: 16, money: true },
          { header: 'Оплачено', key: 'paid', width: 16, money: true },
        ], rows)} />
      </div>
      <TableCard note={`${num.format(rows.length)} счетов за период`
        + (unknown ? ` · у ${num.format(unknown)} оплата неизвестна: регистр «Оплата счетов» их не свёл` : '')}
        head={<>
          <Th>Дата</Th><Th>Номер</Th><Th>Покупатель</Th>
          <Th right>Сумма</Th><Th right>Оплачено</Th><Th right>Остаток</Th>
        </>}>
        {rows.map((r) => {
          const rest = r.paid === null ? null : r.amount - r.paid
          return (
            <tr key={r.id} className="border-b last:border-0 hover:bg-muted/40">
              <td className="px-3 py-1.5 tabular-nums whitespace-nowrap">{r.date}</td>
              <td className="px-3 py-1.5 tabular-nums">
                <button onClick={() => setDocId(r.id)}
                  className="hover:text-primary hover:underline">{r.number}</button>
              </td>
              <td className="px-3 py-1.5 max-w-[320px] truncate" title={r.counterparty}>
                {r.counterpartyId ? (
                  <button onClick={() => setCard(r.counterpartyId)}
                    className="text-left hover:text-primary hover:underline">{r.counterparty}</button>
                ) : r.counterparty}
              </td>
              <td className="px-3 py-1.5 text-right tabular-nums">{money.format(r.amount)}</td>
              <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
                {r.paid === null ? '—' : money.format(r.paid)}
              </td>
              <td className={cn('px-3 py-1.5 text-right tabular-nums',
                rest !== null && rest > 0.01 ? 'text-rose-600 dark:text-rose-400' : 'text-muted-foreground')}>
                {rest === null ? 'нет данных' : money.format(rest)}
              </td>
            </tr>
          )
        })}
      </TableCard>
      {card && <CounterpartyWindow companyId={companyId} id={card} onClose={() => setCard(null)} />}
      {docId && <DocumentWindow companyId={companyId} docId={docId} onClose={() => setDocId(null)} />}
    </div>
  )
}

/**
 * Воронка «счёт → отгрузка → оплата».
 *
 * Ради чего экран: у пилота счетов покупателю выставлено втрое больше, чем отгружено,
 * и до этого экрана разрыв не был виден нигде.
 *
 * ⚠ Ссылки «счёт → реализация» в данных НЕТ: 1С связывает их документом-основанием,
 * которого выгрузка не несёт. Поэтому стадии сопоставляются по периоду, а не по
 * конкретной сделке — экран отвечает «сколько выставили, отгрузили и получили за
 * месяц», а не «этот счёт закрыт этой накладной».
 */
function RevFunnel({ companyId, period }: { companyId: string; period: Period }) {
  const inv = useDocs(companyId, 'invoice_out', period)
  const sale = useDocs(companyId, 'sale', period)

  const months = useMemo(() => {
    const by = new Map<string, { billed: number; shipped: number; paid: number; unknown: number }>()
    const cell = (m: string) => {
      const c = by.get(m) ?? { billed: 0, shipped: 0, paid: 0, unknown: 0 }
      by.set(m, c)
      return c
    }
    for (const r of inv.data?.rows ?? []) {
      const c = cell(r.date.slice(0, 7))
      c.billed += r.amount
      // Только известная оплата: отсутствие записи в регистре это не ноль.
      c.paid += r.paid ?? 0
      if (r.paid === null) c.unknown += r.amount
    }
    for (const r of sale.data?.rows ?? []) cell(r.date.slice(0, 7)).shipped += r.amount
    return [...by.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([month, v]) => ({ month, ...v }))
  }, [inv.data, sale.data])

  if (inv.isError || sale.isError) {
    return (
      <div className="p-4">
        <QueryError onRetry={() => { inv.refetch(); sale.refetch() }} />
      </div>
    )
  }
  if (!inv.data || !sale.data) return <Loading />

  const billed = months.reduce((s, m) => s + m.billed, 0)
  const shipped = months.reduce((s, m) => s + m.shipped, 0)
  const paid = months.reduce((s, m) => s + m.paid, 0)
  const stages: { label: string; value: number; note: string }[] = [
    { label: 'Выставлено счетов', value: billed, note: `${num.format(inv.data.rows.length)} документов` },
    { label: 'Отгружено', value: shipped, note: `${num.format(sale.data.rows.length)} реализаций` },
    {
      label: 'Оплачено по счетам', value: paid,
      note: `известно по ${num.format(inv.data.rows.filter((r) => r.paid !== null).length)}`
        + ` счетам из ${num.format(inv.data.rows.length)}`,
    },
  ]
  const max = Math.max(billed, shipped, paid, 1)

  return (
    <div className="p-4 space-y-4">
      <Card>
        <CardContent className="p-4 space-y-3">
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
            Стадии за период — {periodLabel(period)}
          </div>
          {stages.map((s) => (
            <div key={s.label} className="space-y-1">
              <div className="flex justify-between text-sm">
                <span>{s.label} <span className="text-muted-foreground text-xs">· {s.note}</span></span>
                <span className="tabular-nums">
                  {money.format(s.value)} ₽
                  <span className="ml-2 text-muted-foreground">
                    {((s.value / max) * 100).toFixed(0)}%
                  </span>
                </span>
              </div>
              <div className="h-2.5 rounded bg-muted overflow-hidden">
                <div className="h-full bg-primary/60" style={{ width: `${(s.value / max) * 100}%` }} />
              </div>
            </div>
          ))}
          <p className="text-[11px] text-muted-foreground pt-1">
            Стадии сопоставлены по периоду: ссылки «счёт → реализация» выгрузка 1С не
            несёт, документ-основание в ней не заполнено. Оплата считается только по
            счетам, которые регистр «Оплата счетов» свёл с платежами — у остальных её
            не «ноль», а неизвестно, и в долг они не записываются.
          </p>
        </CardContent>
      </Card>

      <div className="flex justify-end">
        <ExportButton onClick={() => exportTable('Воронка', [
          { header: 'Месяц', key: 'month', width: 12 },
          { header: 'Счета', key: 'billed', width: 18, money: true },
          { header: 'Реализации', key: 'shipped', width: 18, money: true },
          { header: 'Оплачено', key: 'paid', width: 18, money: true },
        ], months)} />
      </div>

      <TableCard note="Помесячно: выставили, отгрузили, получили"
        head={<><Th>Месяц</Th><Th right>Счета</Th><Th right>Реализации</Th>
          <Th right>Оплачено</Th><Th right>Отгружено / выставлено</Th></>}>
        {months.map((m) => (
          <tr key={m.month} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5">{monthLabel(m.month)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
              {money.format(m.billed)} ₽
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
              {money.format(m.shipped)} ₽
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground whitespace-nowrap">
              {money.format(m.paid)} ₽
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
              {m.billed ? `${((m.shipped / m.billed) * 100).toFixed(0)}%` : '—'}
            </td>
          </tr>
        ))}
      </TableCard>

      <UnpaidInvoices rows={inv.data.rows} companyId={companyId} />
    </div>
  )
}

/** Неоплаченные счета — то, ради чего в воронку и приходят. */
function UnpaidInvoices({ rows, companyId }: { rows: DocRow[]; companyId: string }) {
  const [card, setCard] = useState<string | null>(null)
  const today = new Date().toISOString().slice(0, 10)
  // Только счета с ИЗВЕСТНОЙ оплатой: без записи в регистре «не оплачен» — догадка,
  // а список для звонков из догадок не составляют.
  const unpaid = rows
    .filter((r) => r.paid !== null)
    .map((r) => ({ ...r, rest: r.amount - (r.paid ?? 0) }))
    .filter((r) => r.rest > 0.01)
    .sort((a, b) => b.rest - a.rest)
  const unknown = rows.filter((r) => r.paid === null).length

  return (
    <>
      <TableCard note={`Счета без полной оплаты: ${num.format(unpaid.length)} на `
        + `${money.format(unpaid.reduce((s, r) => s + r.rest, 0))} ₽`
        + (unknown ? ` · ещё у ${num.format(unknown)} оплата неизвестна` : '')}
        head={<><Th>Дата</Th><Th>Номер</Th><Th>Покупатель</Th>
          <Th right>Сумма</Th><Th right>Не оплачено</Th><Th right>Дней</Th></>}>
        {unpaid.length === 0 ? (
          <tr><td colSpan={6} className="px-3 py-3 text-sm text-muted-foreground">
            Среди счетов с известной оплатой неоплаченных нет
          </td></tr>
        ) : unpaid.map((r) => (
          <tr key={r.id} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5 tabular-nums whitespace-nowrap">{r.date}</td>
            <td className="px-3 py-1.5 tabular-nums">{r.number}</td>
            <td className="px-3 py-1.5 max-w-[320px] truncate" title={r.counterparty}>
              {r.counterpartyId ? (
                <button onClick={() => setCard(r.counterpartyId)}
                  className="text-left hover:text-primary hover:underline">{r.counterparty}</button>
              ) : r.counterparty}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums">{money.format(r.amount)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums text-rose-600 dark:text-rose-400">
              {money.format(r.rest)}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
              {Math.max(0, Math.round((Date.parse(today) - Date.parse(r.date)) / 86400000))}
            </td>
          </tr>
        ))}
      </TableCard>
      {card && <CounterpartyWindow companyId={companyId} id={card} onClose={() => setCard(null)} />}
    </>
  )
}

/* ────────────────────────────────────────────────────────────── */
/*                    Маржа и сверка                              */
/* ────────────────────────────────────────────────────────────── */

/**
 * Маржа по позициям: цена продажи против цены закупки того же кода номенклатуры.
 *
 * Себестоимость берётся из строк ПОСТУПЛЕНИЙ, а не из 90.02.1: в регистре она
 * свёрнута по счёту, и разложить её обратно по позициям нечем. Способ приблизительный
 * — средневзвешенная цена закупки за период, без партий и FIFO, — поэтому итог рядом
 * сверяется с 90.02.1: расхождение видно, а не спрятано.
 *
 * Позиции, которых компания не закупала (услуги, работы, товар со старых остатков),
 * попадают в отдельный счётчик: у них себестоимости нет вовсе, и молча считать её
 * нулём значило бы показать маржу 100 %.
 */
function RevMargin({ companyId, period }: { companyId: string; period: Period }) {
  const q = useQuery({
    queryKey: ['books', 'assortment', companyId, 'item', period.from, period.to],
    queryFn: () => getAssortment(companyId, 'item', period),
    enabled: !!companyId,
  })
  const [search, setSearch] = useState('')
  const [amount, setAmount] = useState({ from: '', to: '' })
  const [onlyKnown, setOnlyKnown] = useState(true)
  const [card, setCard] = useState<string | null>(null)

  const rows = useMemo(() => (q.data?.rows ?? []).map((r) => {
    const soldQty = r.soldQty ?? 0
    // Маржа считается БЕЗ НДС: на 90.02.1 себестоимость лежит без налога, и с
    // суммами «как в документе» сверка расходилась ровно на ставку — первый прогон
    // дал 112 % регистра. Выручка с НДС остаётся на других экранах: там она сходится
    // с 90.01.1, где налог сидит внутри.
    const sold = r.soldNet ?? r.soldAmount ?? 0
    const boughtQty = r.boughtQty ?? 0
    const bought = r.boughtNet ?? r.boughtAmount ?? 0
    // Средняя цена — сумма / количество, а не среднее из цен строк: строка на сто
    // штук весит столько же, сколько строка на одну, и «среднее из средних» врёт.
    const avgSale = soldQty ? sold / soldQty : 0
    const avgBuy = boughtQty ? bought / boughtQty : 0
    // Себестоимость неизвестна и когда закупки не было, и когда в строке продажи нет
    // количества: `avgBuy × 0` давало ноль и «маржу 100 %», а позиция при этом
    // попадала в итог «с известной закупкой» и раздувала его.
    const cost = avgBuy && soldQty ? avgBuy * soldQty : null
    return {
      ...r, sold, soldQty, avgSale, avgBuy,
      cost,
      margin: cost === null ? null : sold - cost,
      marginPct: cost === null || !sold ? null : ((sold - cost) / sold) * 100,
      markupPct: avgBuy ? (avgSale / avgBuy - 1) * 100 : null,
    }
  }), [q.data])

  if (q.isError) return <div className="p-4"><QueryError onRetry={() => q.refetch()} /></div>
  if (!q.data) return <Loading />

  const shown = rows.filter((r) =>
    (!search || r.name.toLowerCase().includes(search.toLowerCase())
      || (r.code ?? '').toLowerCase().includes(search.toLowerCase()))
    && inRange(r.sold, amount.from, amount.to)
    && (!onlyKnown || r.cost !== null))

  const known = rows.filter((r) => r.cost !== null)
  const soldKnown = known.reduce((s, r) => s + r.sold, 0)
  const costKnown = known.reduce((s, r) => s + (r.cost ?? 0), 0)
  const noCost = rows.length - known.length
  const registerCost = q.data.cost

  return (
    <div className="p-4 space-y-4">
      <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
        <MetricTile label="Продано без НДС"
          value={money.format(soldKnown) + ' ₽'}
          hint={`${num.format(known.length)} позиций с известной закупкой из ${num.format(rows.length)}`} />
        <MetricTile label="Себестоимость (расчётная)" value={money.format(costKnown) + ' ₽'}
          hint="средняя цена закупки × проданное количество" />
        <MetricTile label="Маржа" value={money.format(soldKnown - costKnown) + ' ₽'}
          hint={soldKnown ? `${(((soldKnown - costKnown) / soldKnown) * 100).toFixed(1)}% от продаж` : '—'}
          tone={soldKnown - costKnown > 0 ? 'success' : undefined} />
        <MetricTile label={`Себестоимость по ${q.data.costBasis ?? '90.02.1'}`}
          value={registerCost === null ? 'нет данных' : money.format(registerCost) + ' ₽'}
          hint={registerCost
            ? `расчёт ${((costKnown / registerCost) * 100).toFixed(0)}% от регистра`
            : 'оборот регистра не посчитан'} />
      </div>

      <p className="text-[11px] text-muted-foreground">
        Суммы здесь БЕЗ НДС — иначе сравнение с оборотом 90.02.1 завышено на ставку
        налога. Себестоимость считается по строкам поступлений (средневзвешенная цена
        закупки за период), партии и FIFO не учитываются — поэтому оборот 90.02.1 стоит
        рядом как контроль. {noCost > 0 && `У ${num.format(noCost)} позиций закупки в периоде нет —
        услуги, работы и товар со старых остатков; их маржа не считается.`}
      </p>

      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3 flex-wrap">
          <SearchInput value={search} onChange={setSearch}
            placeholder="Наименование или код" label="Поиск по наименованию или коду" />
          <AmountRange from={amount.from} to={amount.to}
            onChange={(from, to) => setAmount({ from, to })} />
          <Tabs value={onlyKnown ? 'known' : 'all'} onChange={(v) => setOnlyKnown(v === 'known')}
            items={[{ key: 'known', label: 'С известной закупкой' }, { key: 'all', label: 'Все позиции' }]} />
        </div>
        <ExportButton onClick={() => exportTable('Маржа по позициям', [
          { header: 'Код', key: 'code', width: 14 },
          { header: 'Позиция', key: 'name', width: 44 },
          { header: 'Продано, кол-во', key: 'soldQty', width: 14 },
          { header: 'Продажи', key: 'sold', width: 16, money: true },
          { header: 'Цена продажи', key: 'avgSale', width: 14, money: true },
          { header: 'Цена закупки', key: 'avgBuy', width: 14, money: true },
          { header: 'Себестоимость', key: 'cost', width: 16, money: true },
          { header: 'Маржа', key: 'margin', width: 16, money: true },
          { header: 'Маржа, %', key: 'marginPct', width: 10 },
        ], shown)} />
      </div>

      <TableCard note={`${num.format(shown.length)} позиций — по сумме продаж`}
        head={<><Th>Позиция</Th><Th right>Продано</Th><Th right>Продажи</Th>
          <Th right>Цена продажи</Th><Th right>Цена закупки</Th>
          <Th right>Маржа</Th><Th right>Маржа, %</Th><Th right>Наценка</Th></>}>
        {shown.map((r) => (
          <tr key={r.key} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5 max-w-[320px] truncate" title={r.name}>
              {r.code ? (
                <button onClick={() => setCard(r.code!)}
                  className="text-left hover:text-primary hover:underline">{r.name}</button>
              ) : r.name}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
              {qty.format(r.soldQty)}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
              {money.format(r.sold)} ₽
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
              {money.format(r.avgSale)}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
              {r.avgBuy ? money.format(r.avgBuy) : '—'}
            </td>
            <td className={cn('px-3 py-1.5 text-right tabular-nums whitespace-nowrap',
              r.margin === null ? 'text-muted-foreground'
              : r.margin >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400')}>
              {r.margin === null ? '—' : `${money.format(r.margin)} ₽`}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
              {r.marginPct === null ? '—' : `${r.marginPct.toFixed(1)}%`}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
              {r.markupPct === null ? '—' : `${r.markupPct.toFixed(0)}%`}
            </td>
          </tr>
        ))}
      </TableCard>
      {card && <NomenclatureWindow companyId={companyId} code={card} onClose={() => setCard(null)} />}
    </div>
  )
}

/**
 * Сверка с бухгалтерией: сумма документов реализации против оборота 90.01.1.
 *
 * Сходимость с регистром — смысл продукта, и она обязана быть видимой: пока
 * расхождение не показано на экране, витрина и бухгалтерия расходятся тихо, а
 * обнаруживается это у заказчика. Эталон — регистр; документы — то, что мы
 * показываем. Период здесь общий (вся история), а не из фильтра: сверяют не
 * «за выбранное», а «всё ли сошлось».
 */
function RevRecon({ companyId }: { companyId: string }) {
  const q = useQuery({
    queryKey: ['books', 'revenue-check', companyId],
    queryFn: () => getRevenueCheck(companyId),
    enabled: !!companyId,
  })
  const [onlyBroken, setOnlyBroken] = useState(false)

  if (q.isError) return <div className="p-4"><QueryError onRetry={() => q.refetch()} /></div>
  if (!q.data) return <Loading />
  const d = q.data
  const months = onlyBroken ? d.months.filter((m) => Math.abs(m.diff) > 1) : d.months
  const ok = Math.abs(d.diff) <= 1

  return (
    <div className="p-4 space-y-4">
      <div className="grid gap-3 grid-cols-3">
        <MetricTile label="По документам" value={money.format(d.totalDocs) + ' ₽'}
          hint="сумма реализаций за всю историю" />
        <MetricTile label="По регистру (90.01.1)" value={money.format(d.totalRegister) + ' ₽'}
          hint="оборот по кредиту счёта выручки" />
        <MetricTile label="Расхождение" value={money.format(d.diff) + ' ₽'}
          hint={ok ? 'сходится до рубля' : `${d.broken.length} месяцев с расхождением`}
          tone={ok ? 'success' : 'danger'} />
      </div>

      <div className="flex items-center justify-between gap-3 flex-wrap">
        <Tabs value={onlyBroken ? 'broken' : 'all'} onChange={(v) => setOnlyBroken(v === 'broken')}
          items={[{ key: 'all', label: 'Все месяцы' }, { key: 'broken', label: 'Только расхождения' }]} />
        <ExportButton onClick={() => exportTable('Сверка реализации с регистром', [
          { header: 'Месяц', key: 'month', width: 12 },
          { header: 'По документам', key: 'docs', width: 18, money: true },
          { header: 'Документов', key: 'docsCount', width: 12 },
          { header: 'По регистру', key: 'register', width: 18, money: true },
          { header: 'Расхождение', key: 'diff', width: 16, money: true },
          { header: 'Период', key: 'periodStatus', width: 10 },
        ], months)} />
      </div>

      <TableCard
        note={ok
          ? 'Витрина и регистр сходятся: расхождение меньше рубля — это округление копеек'
          : 'Эталон — регистр. Расхождение разбирается по месяцу: документ вне периода, ' +
            'проводка без документа или сумма, разошедшаяся с составом'}
        head={<><Th>Месяц</Th><Th right>По документам</Th><Th right>Документов</Th>
          <Th right>По регистру</Th><Th right>Расхождение</Th><Th>Период</Th></>}>
        {months.map((m) => (
          <tr key={m.month} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5">{monthLabel(m.month)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
              {money.format(m.docs)} ₽
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
              {m.docsCount}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
              {money.format(m.register)} ₽
            </td>
            <td className={cn('px-3 py-1.5 text-right tabular-nums whitespace-nowrap',
              Math.abs(m.diff) > 1 ? 'text-rose-600 dark:text-rose-400' : 'text-muted-foreground')}>
              {money.format(m.diff)} ₽
            </td>
            <td className="px-3 py-1.5 text-[11px] text-muted-foreground">
              {m.periodStatus === 'closed' ? 'закрыт' : 'открыт'}
            </td>
          </tr>
        ))}
      </TableCard>
    </div>
  )
}

/* ────────────────────────────────────────────────────────────── */
/*                          Деньги                                */
/* ────────────────────────────────────────────────────────────── */

/**
 * Сроки оплаты: через сколько дней после счёта приходят деньги.
 *
 * Медиана стоит рядом со средним не для полноты: у пилота средний срок 160 дней при
 * медиане втрое меньше — среднее тянут единичные счета, висящие больше двух лет. По
 * среднему нельзя договариваться об отсрочке, по медиане — можно.
 *
 * Экран видит ровно те счета, которые регистр «Оплата счетов» свёл с платежами: по
 * суммам и датам связь не восстановить — один платёж закрывает несколько счетов.
 */
function RevTerms({ companyId, period }: { companyId: string; period: Period }) {
  const q = useQuery({
    queryKey: ['books', 'payment-terms', companyId, period.from, period.to],
    queryFn: () => getPaymentTerms(companyId, period),
    enabled: !!companyId,
  })
  const [bucket, setBucket] = useState<string | null>(null)
  const [card, setCard] = useState<string | null>(null)

  if (q.isError) return <div className="p-4"><QueryError onRetry={() => q.refetch()} /></div>
  if (!q.data) return <Loading />
  const d = q.data
  if (!d.total) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        За выбранный период нет счетов, сведённых с платежами. Связь «счёт ↔ платёж»
        приходит из регистра «Оплата счетов» — если его в выгрузке нет, экран пуст.
      </div>
    )
  }

  const maxBucket = Math.max(...d.buckets.map((b) => b.amount), 1)
  const rows = bucket ? d.rows.filter((r) => r.bucket === bucket) : d.rows

  return (
    <div className="p-4 space-y-4">
      <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
        <MetricTile label="Средний срок оплаты"
          value={d.avgDays === null ? '—' : `${d.avgDays} дн.`}
          hint="от даты счёта до даты платежа" />
        <MetricTile label="Медиана" value={`${d.medianDays} дн.`}
          hint="половина счетов оплачена быстрее" />
        <MetricTile label="Счетов с оплатой" value={num.format(d.total)}
          hint={`${money.format(d.amount)} ₽ · ${num.format(d.payments)} платежей`} />
        <MetricTile label="Дольше 90 дней"
          value={num.format(d.buckets.find((b) => b.key === 'overdue')?.count ?? 0)}
          hint={`${money.format(d.buckets.find((b) => b.key === 'overdue')?.amount ?? 0)} ₽`}
          tone={(d.buckets.find((b) => b.key === 'overdue')?.count ?? 0) > 0 ? 'danger' : undefined} />
      </div>

      <Card>
        <CardContent className="p-4 space-y-2">
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
            Распределение по сроку — полоса отбирает счета
          </div>
          {d.buckets.map((b) => (
            <button key={b.key} onClick={() => setBucket(bucket === b.key ? null : b.key)}
              disabled={!b.count}
              className={cn('w-full text-left space-y-1 rounded-md px-2 py-1',
                !b.count ? 'opacity-40' : bucket === b.key ? 'bg-muted' : 'hover:bg-muted/50')}>
              <div className="flex justify-between text-sm">
                <span>{b.label} <span className="text-muted-foreground">· {b.count} шт.</span></span>
                <span className="tabular-nums">{money.format(b.amount)} ₽</span>
              </div>
              <div className="h-2 rounded bg-muted overflow-hidden">
                <div className={cn('h-full', b.key === 'overdue' ? 'bg-rose-500/60'
                  : b.key === 'advance' ? 'bg-emerald-500/60' : 'bg-primary/60')}
                  style={{ width: `${(b.amount / maxBucket) * 100}%` }} />
              </div>
            </button>
          ))}
        </CardContent>
      </Card>

      {d.orphanPayments > 0 && (
        <p className="text-[11px] text-amber-600 dark:text-amber-400">
          {num.format(d.orphanPayments)} платежей на {money.format(d.orphanAmount)} ₽
          ссылаются на документ, которого в выгрузке нет: они не попадают ни в один
          расчёт этого экрана. Вопрос к выгрузке из 1С.
        </p>
      )}
      <div className="flex justify-end">
        <ExportButton onClick={() => exportTable('Сроки оплаты', [
          { header: 'Покупатель', key: 'name', width: 44 },
          { header: 'Счетов', key: 'invoices', width: 10 },
          { header: 'Сумма', key: 'amount', width: 18, money: true },
          { header: 'Средний срок, дней', key: 'avgDays', width: 18 },
          { header: 'Худший счёт, дней', key: 'maxDays', width: 18 },
        ], d.clients)} />
      </div>

      <TableCard note="Покупатели по среднему сроку оплаты — с кем говорить об отсрочке"
        head={<><Th>Покупатель</Th><Th right>Счетов</Th><Th right>Сумма</Th>
          <Th right>Средний срок</Th><Th right>Худший</Th></>}>
        {d.clients.map((c) => (
          <tr key={c.id ?? c.name} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5 max-w-[320px] truncate" title={c.name}>
              {c.id ? (
                <button onClick={() => setCard(c.id)}
                  className="text-left hover:text-primary hover:underline">{c.name}</button>
              ) : c.name}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">{c.invoices}</td>
            <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
              {money.format(c.amount)} ₽
            </td>
            <td className={cn('px-3 py-1.5 text-right tabular-nums',
              c.avgDays > 90 ? 'text-rose-600 dark:text-rose-400' : c.avgDays > 30 ? 'text-amber-600 dark:text-amber-400' : 'text-emerald-600 dark:text-emerald-400')}>
              {c.avgDays} дн.
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
              {c.maxDays} дн.
            </td>
          </tr>
        ))}
      </TableCard>

      <TableCard
        note={bucket
          ? `${d.buckets.find((b) => b.key === bucket)?.label}: ${num.format(rows.length)} счетов`
          : `Счета с оплатой — ${num.format(rows.length)}, по убыванию срока`}
        head={<><Th>Счёт</Th><Th>Дата</Th><Th>Оплачен</Th><Th>Покупатель</Th>
          <Th right>Сумма</Th><Th right>Дней</Th></>}>
        {rows.map((r) => (
          <tr key={r.id} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5 tabular-nums">{r.number}</td>
            <td className="px-3 py-1.5 tabular-nums whitespace-nowrap">{r.date}</td>
            <td className="px-3 py-1.5 tabular-nums whitespace-nowrap">
              {r.paidAt}
              {r.payments > 1 && (
                <span className="ml-1 text-[10px] text-muted-foreground"
                  title="счёт закрыт несколькими платежами, срок считается по последнему">
                  ×{r.payments}
                </span>
              )}
            </td>
            <td className="px-3 py-1.5 max-w-[280px] truncate" title={r.counterparty}>
              {r.counterparty}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
              {money.format(r.amount)} ₽
            </td>
            <td className={cn('px-3 py-1.5 text-right tabular-nums',
              r.days > 90 ? 'text-rose-600 dark:text-rose-400' : r.days < 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-muted-foreground')}>
              {r.days}
            </td>
          </tr>
        ))}
      </TableCard>
      {card && <CounterpartyWindow companyId={companyId} id={card} onClose={() => setCard(null)} />}
    </div>
  )
}

/**
 * Денежный поток: пришло, ушло, накопленный остаток по месяцам.
 *
 * Считается по банковским документам, а не по обороту 51 счёта: у документа есть
 * контрагент, и рядом с суммой сразу видно, кто платит и кому уходит. Оборот 51 стоит
 * контролем — расхождение означает движение без документа (перевод между своими
 * счетами, эквайринг, инкассация), и это вопрос к выгрузке, а не к экрану.
 */
function RevCashflow({ companyId }: { companyId: string }) {
  const q = useQuery({
    queryKey: ['books', 'cashflow', companyId],
    queryFn: () => getCashflow(companyId),
    enabled: !!companyId,
  })
  const [side, setSide] = useState<'in' | 'out'>('in')

  if (q.isError) return <div className="p-4"><QueryError onRetry={() => q.refetch()} /></div>
  if (!q.data) return <Loading />
  const d = q.data
  const maxFlow = Math.max(...d.months.map((m) => Math.max(m.inflow, m.outflow)), 1)
  const diffIn = d.inflow - d.registerIn
  const diffOut = d.outflow - d.registerOut

  return (
    <div className="p-4 space-y-4">
      <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
        <MetricTile label="Пришло" value={money.format(d.inflow) + ' ₽'}
          hint={`${num.format(d.months.reduce((s, m) => s + m.inDocs, 0))} поступлений`} />
        <MetricTile label="Ушло" value={money.format(d.outflow) + ' ₽'}
          hint={`${num.format(d.months.reduce((s, m) => s + m.outDocs, 0))} списаний`} />
        <MetricTile label="Итог за историю" value={money.format(d.inflow - d.outflow) + ' ₽'}
          tone={d.inflow - d.outflow >= 0 ? 'success' : 'danger'}
          hint="приход минус расход по документам выгрузки, не остаток на счёте" />
        <MetricTile label="Контроль по счёту 51"
          value={Math.abs(diffIn) + Math.abs(diffOut) < 1 ? 'сходится' : 'расхождение'}
          hint={Math.abs(diffIn) + Math.abs(diffOut) < 1
            ? 'документы = обороты регистра'
            : `приход ${money.format(diffIn)} ₽, расход ${money.format(diffOut)} ₽`}
          tone={Math.abs(diffIn) + Math.abs(diffOut) < 1 ? 'success' : 'danger'} />
      </div>

      <Card>
        <CardContent className="p-4">
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground mb-3">
            Помесячно: приход вверх, расход вниз
          </div>
          <div className="flex items-center gap-1 overflow-x-auto" style={{ height: 200 }}>
            {d.months.map((m) => (
              <div key={m.month} className="flex flex-col items-center min-w-[26px] flex-1"
                title={`${monthLabel(m.month)}: пришло ${money.format(m.inflow)} ₽, `
                  + `ушло ${money.format(m.outflow)} ₽, остаток ${money.format(m.balance)} ₽`}>
                <div className="w-full flex flex-col justify-end" style={{ height: 78 }}>
                  <div className="w-full rounded-t bg-emerald-500/60"
                    style={{ height: `${Math.max(1, (m.inflow / maxFlow) * 76)}px` }} />
                </div>
                <div className="w-full" style={{ height: 78 }}>
                  <div className="w-full rounded-b bg-rose-500/60"
                    style={{ height: `${Math.max(1, (m.outflow / maxFlow) * 76)}px` }} />
                </div>
                <div className="text-[9px] text-muted-foreground rotate-45 origin-left h-6 whitespace-nowrap">
                  {m.month.slice(2)}
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <TableCard note="Месяц: приход, расход, разница и накопленный остаток"
        head={<><Th>Месяц</Th><Th right>Пришло</Th><Th right>Ушло</Th>
          <Th right>Разница</Th><Th right>Нарастающим</Th></>}>
        {[...d.months].reverse().map((m) => (
          <tr key={m.month} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5">{monthLabel(m.month)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap text-emerald-600 dark:text-emerald-400">
              {money.format(m.inflow)} ₽
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap text-rose-600 dark:text-rose-400">
              {money.format(m.outflow)} ₽
            </td>
            <td className={cn('px-3 py-1.5 text-right tabular-nums whitespace-nowrap',
              m.net >= 0 ? '' : 'text-rose-600 dark:text-rose-400')}>
              {m.net >= 0 ? '+' : ''}{money.format(m.net)} ₽
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground whitespace-nowrap">
              {money.format(m.balance)} ₽
            </td>
          </tr>
        ))}
      </TableCard>

      <div className="flex items-center justify-between gap-3 flex-wrap">
        <Tabs value={side} onChange={setSide} items={[
          { key: 'in' as const, label: 'Кто платит нам' },
          { key: 'out' as const, label: 'Кому платим мы' },
        ]} />
        <ExportButton onClick={() => exportTable(
          side === 'in' ? 'Поступления по контрагентам' : 'Списания по контрагентам', [
            { header: 'Контрагент', key: 'name', width: 44 },
            { header: 'Сумма', key: side === 'in' ? 'inflow' : 'outflow', width: 18, money: true },
            { header: 'Документов', key: 'docs', width: 12 },
            { header: 'Последний', key: 'last', width: 14 },
          ], side === 'in' ? d.payers : d.payees)} />
      </div>

      <TableCard
        note={side === 'in' ? 'Откуда приходят деньги' : 'Куда уходят деньги'}
        head={<><Th>Контрагент</Th><Th right>Сумма</Th><Th right>Документов</Th>
          <Th>Последний</Th></>}>
        {(side === 'in' ? d.payers : d.payees).map((c) => (
          <tr key={c.name} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5 max-w-[420px] truncate" title={c.name}>{c.name}</td>
            <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
              {money.format(side === 'in' ? (c as { inflow: number }).inflow
                : (c as { outflow: number }).outflow)} ₽
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">{c.docs}</td>
            <td className="px-3 py-1.5 tabular-nums text-muted-foreground">{c.last}</td>
          </tr>
        ))}
      </TableCard>
    </div>
  )
}

/**
 * Продажи в разрезе договоров. Договор — основание сделки, но до сих пор ни один
 * экран по нему не собирал: ссылка у документа появилась, разреза не было.
 *
 * Документы без договора идут отдельной строкой и не прячутся: их больше половины, и
 * это факт о данных, а не пустая клетка. Отсюда же и первая цифра экрана — какая доля
 * выручки вообще опирается на договор.
 */
function RevContracts({ companyId, period }: { companyId: string; period: Period }) {
  const q = useQuery({
    queryKey: ['books', 'contract-sales', companyId, period.from, period.to],
    queryFn: () => getContractSales(companyId, period),
    enabled: !!companyId,
  })
  const [search, setSearch] = useState('')
  const [onlyLinked, setOnlyLinked] = useState(false)

  if (q.isError) return <div className="p-4"><QueryError onRetry={() => q.refetch()} /></div>
  if (!q.data) return <Loading />
  const d = q.data
  const rows = d.rows.filter((r) =>
    (!onlyLinked || r.id)
    && (!search || (r.number ?? '').toLowerCase().includes(search.toLowerCase())
      || (r.counterparty ?? '').toLowerCase().includes(search.toLowerCase())))
  const share = d.salesTotal ? (d.salesWithContract / d.salesTotal) * 100 : 0

  return (
    <div className="p-4 space-y-4">
      <div className="grid gap-3 grid-cols-3">
        <MetricTile label="Договоров с отгрузками" value={num.format(d.withContract)}
          hint={`ещё ${num.format(d.withInvoicesOnly)} договоров только со счетами`} />
        <MetricTile label="Продажи по договорам" value={money.format(d.salesWithContract) + ' ₽'}
          hint={`${share.toFixed(1)}% выручки периода`} />
        <MetricTile label="Без договора"
          value={money.format(d.salesTotal - d.salesWithContract) + ' ₽'}
          hint="документ не сослался на договор в 1С" />
      </div>

      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3 flex-wrap">
          <SearchInput value={search} onChange={setSearch}
            placeholder="Договор или контрагент" label="Поиск по договору или контрагенту" />
          <Tabs value={onlyLinked ? 'linked' : 'all'} onChange={(v) => setOnlyLinked(v === 'linked')}
            items={[{ key: 'all', label: 'Все' }, { key: 'linked', label: 'Только с договором' }]} />
        </div>
        <ExportButton onClick={() => exportTable('Продажи по договорам', [
          { header: 'Договор', key: 'number', width: 24 },
          { header: 'Дата', key: 'date', width: 12 },
          { header: 'Контрагент', key: 'counterparty', width: 40 },
          { header: 'Вид', key: 'kind', width: 20 },
          { header: 'Расчёты', key: 'settlementKind', width: 24 },
          { header: 'Отгрузки', key: 'sales', width: 16, money: true },
          { header: 'Счета', key: 'invoices', width: 16, money: true },
        ], rows)} />
      </div>

      <TableCard note={`${num.format(rows.length)} строк — отгрузки и счета по основанию`}
        head={<><Th>Договор</Th><Th>Контрагент</Th><Th>Вид расчётов</Th>
          <Th right>Отгружено</Th><Th right>Выставлено</Th><Th>Период работы</Th></>}>
        {rows.map((r) => (
          <tr key={r.id ?? 'none'} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5 max-w-[240px] truncate"
              title={r.number ? `${r.number} от ${r.date}` : 'документы без ссылки на договор'}>
              {r.number ?? <span className="text-muted-foreground">без договора</span>}
            </td>
            <td className="px-3 py-1.5 max-w-[260px] truncate"
              title={r.counterparty ?? `${r.counterparties} контрагентов`}>
              {r.counterparty ?? (
                <span className="text-muted-foreground">
                  {num.format(r.counterparties)} контрагентов
                </span>
              )}
            </td>
            <td className="px-3 py-1.5 text-[11px] text-muted-foreground max-w-[200px] truncate"
              title={r.settlementKind ?? ''}>
              {r.settlementKind ?? '—'}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
              {money.format(r.sales)} ₽
              <span className="ml-1 text-[11px] text-muted-foreground">{r.salesDocs}</span>
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap text-muted-foreground">
              {money.format(r.invoices)} ₽
              <span className="ml-1 text-[11px]">{r.invoiceDocs}</span>
            </td>
            <td className="px-3 py-1.5 tabular-nums text-[11px] text-muted-foreground whitespace-nowrap">
              {r.first} — {r.last}
            </td>
          </tr>
        ))}
      </TableCard>
    </div>
  )
}

/* ────────────────────────────────────────────────────────────── */
/*                     Закупки и склад                            */
/* ────────────────────────────────────────────────────────────── */

/**
 * Остатки: приход минус расход по строкам документов.
 *
 * Складского учёта в выгрузке нет вовсе, поэтому способ грубый: остаток в деньгах
 * считается по средней цене закупки, партий и себестоимости списания в данных не
 * существует. Рядом стоит сальдо счёта 41 — расхождение видно на самом экране, а не
 * всплывает у заказчика.
 *
 * Отрицательный остаток тут не «минус на складе», а признак данных: продали то, чего
 * в выгрузке не покупали — товар лежал до начала выгруженного периода. Такие позиции
 * вынесены отдельным счётчиком, потому что они портят и оценку запаса, и маржу.
 */
function RevStock({ companyId }: { companyId: string }) {
  const q = useQuery({
    queryKey: ['books', 'stock', companyId],
    queryFn: () => getStock(companyId),
    enabled: !!companyId,
  })
  const [tab, setTab] = useState<'rest' | 'own' | 'idle' | 'negative'>('rest')
  const [search, setSearch] = useState('')
  const [card, setCard] = useState<string | null>(null)

  if (q.isError) return <div className="p-4"><QueryError onRetry={() => q.refetch()} /></div>
  if (!q.data) return <Loading />
  const d = q.data
  const rows = d.rows
    .filter((r) => tab === 'rest' ? r.restQty > 0 && r.everSold
      : tab === 'own' ? r.restQty > 0 && !r.everSold
      : tab === 'idle' ? r.restQty > 0 && r.everSold && (r.idleDays ?? 0) > 180
      : r.restQty < 0)
    .filter((r) => !search || r.name.toLowerCase().includes(search.toLowerCase())
      || r.code.toLowerCase().includes(search.toLowerCase()))

  return (
    <div className="p-4 space-y-4">
      <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
        <MetricTile label="Товар: куплено и не продано"
          value={money.format(d.goodsAmount) + ' ₽'}
          hint={`${num.format(d.goodsPositions)} позиций, которые компания продаёт`} />
        <MetricTile label="Куплено для себя"
          value={money.format(d.restAmount - d.goodsAmount) + ' ₽'}
          hint={`${num.format(d.positions - d.goodsPositions)} позиций: техника, материалы, канцелярия`} />
        <MetricTile label="Лежит без движения" value={money.format(d.idleAmount) + ' ₽'}
          hint={`${num.format(d.idle)} товарных позиций не двигались полгода`}
          tone={d.idle > 0 ? 'danger' : undefined} />
        <MetricTile label="Сальдо счёта 41" value={money.format(d.register) + ' ₽'}
          hint="товарный остаток по бухгалтерии на дату среза" />
      </div>

      <p className="text-[11px] text-muted-foreground">
        Складского учёта в выгрузке нет: считается «куплено минус продано» по строкам
        документов, оценка — по средней цене закупки без НДС. Это НЕ складской остаток:
        сюда попадает и то, что компания купила себе (техника, материалы под работы) —
        оно списано в затраты, а не лежит товаром. Поэтому колонки разделены, а сальдо
        41 показывает товарный остаток по бухгалтерии.
        {' '}Закуплено по строкам {money.format(d.boughtTotal)} ₽, на счёт 41 попало{' '}
        {money.format(d.registerIntake)} ₽ — разница и есть закупки мимо товарного счёта.
      </p>

      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3 flex-wrap">
          <Tabs value={tab} onChange={setTab} items={[
            { key: 'rest' as const, label: 'Товар' },
            { key: 'own' as const, label: 'Куплено для себя' },
            { key: 'idle' as const, label: 'Неликвиды' },
            { key: 'negative' as const, label: 'Отрицательные' },
          ]} />
          <SearchInput value={search} onChange={setSearch}
            placeholder="Наименование или код" label="Поиск по наименованию или коду" />
        </div>
        <ExportButton onClick={() => exportTable('Остатки по номенклатуре', [
          { header: 'Код', key: 'code', width: 14 },
          { header: 'Позиция', key: 'name', width: 44 },
          { header: 'Куплено', key: 'boughtQty', width: 12 },
          { header: 'Продано', key: 'soldQty', width: 12 },
          { header: 'Остаток', key: 'restQty', width: 12 },
          { header: 'Оценка остатка', key: 'restAmount', width: 16, money: true },
          { header: 'Запас, дней', key: 'daysOfSupply', width: 12 },
          { header: 'Последнее движение', key: 'lastMove', width: 18 },
        ], rows)} />
      </div>

      <TableCard
        note={tab === 'idle'
          ? 'Товар есть, продаж больше полугода нет — деньги стоят на полке'
          : tab === 'negative'
          ? 'Продали больше, чем приходовали: закупка была до начала выгрузки'
          : tab === 'own'
          ? 'Куплено, но никогда не продавалось: закупки для собственных нужд'
          : `${num.format(rows.length)} товарных позиций, купленных и не проданных`}
        head={<><Th>Позиция</Th><Th right>Куплено</Th><Th right>Продано</Th>
          <Th right>Остаток</Th><Th right>Оценка</Th><Th right>Запас</Th>
          <Th>Последнее движение</Th></>}>
        {rows.map((r) => (
          <tr key={r.code} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5 max-w-[340px] truncate" title={r.name}>
              <button onClick={() => setCard(r.code)}
                className="text-left hover:text-primary hover:underline">{r.name}</button>
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
              {qty.format(r.boughtQty)}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
              {qty.format(r.soldQty)}
            </td>
            <td className={cn('px-3 py-1.5 text-right tabular-nums',
              r.restQty < 0 ? 'text-rose-600 dark:text-rose-400' : '')}>
              {qty.format(r.restQty)}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
              {money.format(r.restAmount)} ₽
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
              {r.daysOfSupply === null ? '—' : `${num.format(r.daysOfSupply)} дн.`}
            </td>
            <td className={cn('px-3 py-1.5 tabular-nums whitespace-nowrap',
              (r.idleDays ?? 0) > 365 ? 'text-rose-600 dark:text-rose-400'
              : (r.idleDays ?? 0) > 180 ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground')}>
              {r.lastMove ?? '—'}
              {r.idleDays !== null && <span className="ml-1 text-[11px]">{r.idleDays} дн. назад</span>}
            </td>
          </tr>
        ))}
      </TableCard>
      {card && <NomenclatureWindow companyId={companyId} code={card} onClose={() => setCard(null)} />}
    </div>
  )
}

/**
 * Поставщики и цены закупки — один запрос, два взгляда.
 *
 * `list` отвечает «от кого мы зависим»: доля крупнейшего поставщика и первой тройки.
 * `prices` — «где мы переплачиваем»: одна и та же позиция у разных поставщиков, строки
 * отсортированы по деньгам, которые стоят за разрывом цены (разница × объём), а не по
 * проценту: 40 % на позиции за триста рублей не стоят разговора.
 */
function RevSuppliers({ companyId, period, view }: {
  companyId: string; period: Period; view: 'list' | 'prices'
}) {
  const q = useQuery({
    queryKey: ['books', 'suppliers', companyId, period.from, period.to],
    queryFn: () => getSuppliers(companyId, period),
    enabled: !!companyId,
  })
  const [search, setSearch] = useState('')
  const [card, setCard] = useState<string | null>(null)

  if (q.isError) return <div className="p-4"><QueryError onRetry={() => q.refetch()} /></div>
  if (!q.data) return <Loading />
  const d = q.data

  if (view === 'prices') {
    const rows = d.spread.filter((r) => !search
      || r.name.toLowerCase().includes(search.toLowerCase())
      || r.code.toLowerCase().includes(search.toLowerCase()))
    return (
      <div className="p-4 space-y-3">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <SearchInput value={search} onChange={setSearch}
            placeholder="Наименование или код" label="Поиск по наименованию или коду" />
          <ExportButton onClick={() => exportTable('Цены закупки', [
            { header: 'Код', key: 'code', width: 14 },
            { header: 'Позиция', key: 'name', width: 40 },
            { header: 'Поставщиков', key: 'suppliers', width: 12 },
            { header: 'Мин. цена', key: 'minPrice', width: 14, money: true },
            { header: 'Макс. цена', key: 'maxPrice', width: 14, money: true },
            { header: 'Средняя', key: 'avgPrice', width: 14, money: true },
            { header: 'Дешевле у', key: 'minName', width: 30 },
            { header: 'Дороже у', key: 'maxName', width: 30 },
          ], rows)} />
        </div>
        <TableCard
          note="Позиции у двух и более поставщиков — по сумме разрыва цены. Сравнение идёт
                по коду И наименованию: в выгрузке один код может нести разные товары"
          head={<><Th>Позиция</Th><Th right>Поставщиков</Th><Th right>Мин.</Th>
            <Th right>Макс.</Th><Th right>Разница</Th><Th>Дешевле у</Th></>}>
          {rows.map((r) => (
            <tr key={r.code} className="border-b last:border-0 hover:bg-muted/40">
              <td className="px-3 py-1.5 max-w-[300px] truncate" title={r.name}>
                <button onClick={() => setCard(r.code)}
                  className="text-left hover:text-primary hover:underline">{r.name}</button>
              </td>
              <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
                {r.suppliers}
              </td>
              <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
                {money.format(r.minPrice)}
              </td>
              <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
                {money.format(r.maxPrice)}
              </td>
              <td className={cn('px-3 py-1.5 text-right tabular-nums whitespace-nowrap',
                r.suspicious ? 'text-muted-foreground' : 'text-amber-600 dark:text-amber-400')}>
                {r.minPrice ? `+${((r.maxPrice / r.minPrice - 1) * 100).toFixed(0)}%` : '—'}
                <span className="ml-1 text-[11px] text-muted-foreground">
                  {money.format((r.maxPrice - r.minPrice) * r.qty)} ₽
                </span>
                {/* Разрыв больше пятикратного — почти всегда разные единицы измерения
                    (штука против упаковки), а не переплата. Строку не прячем: у пилота
                    так вскрылись лопаты по 1 ₽ против 150 ₽ при том же количестве. */}
                {r.suspicious && (
                  <span className="ml-1.5 rounded bg-muted px-1 py-0.5 text-[10px]"
                    title="Разрыв больше чем в пять раз: проверьте единицы измерения в документах">
                    проверить ед.
                  </span>
                )}
              </td>
              <td className="px-3 py-1.5 max-w-[240px] truncate text-[11px] text-muted-foreground"
                title={`дешевле: ${r.minName} · дороже: ${r.maxName}`}>
                {r.minName}
              </td>
            </tr>
          ))}
        </TableCard>
        {card && <NomenclatureWindow companyId={companyId} code={card} onClose={() => setCard(null)} />}
      </div>
    )
  }

  const rows = d.rows.filter((r) => !search || r.name.toLowerCase().includes(search.toLowerCase()))
  return (
    <div className="p-4 space-y-4">
      <div className="grid gap-3 grid-cols-3">
        <MetricTile label="Закупки за период" value={money.format(d.total) + ' ₽'}
          hint={`${num.format(d.rows.length)} поставщиков`} />
        <MetricTile label="Доля крупнейшего" value={`${d.topShare} %`}
          hint={d.rows[0]?.name ?? '—'}
          tone={d.topShare > 50 ? 'danger' : undefined} />
        <MetricTile label="Доля первой тройки" value={`${d.top3Share} %`}
          hint="чем выше, тем сильнее зависимость от нескольких поставщиков" />
      </div>
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <SearchInput value={search} onChange={setSearch}
          placeholder="Поставщик" label="Поиск по поставщику" />
        <ExportButton onClick={() => exportTable('Поставщики', [
          { header: 'Поставщик', key: 'name', width: 44 },
          { header: 'ИНН', key: 'inn', width: 14 },
          { header: 'Закупки', key: 'amount', width: 18, money: true },
          { header: 'Документов', key: 'docs', width: 12 },
          { header: 'Позиций', key: 'positions', width: 10 },
          { header: 'Последняя', key: 'last', width: 14 },
        ], rows)} />
      </div>
      <TableCard note={`${num.format(rows.length)} поставщиков по объёму закупок`}
        head={<><Th>Поставщик</Th><Th>ИНН</Th><Th right>Закупки</Th><Th right>Доля</Th>
          <Th right>Документов</Th><Th right>Позиций</Th><Th>Последняя</Th></>}>
        {rows.map((r) => (
          <tr key={r.name} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5 max-w-[300px] truncate" title={r.name}>
              {r.id ? (
                <button onClick={() => setCard(r.id)}
                  className="text-left hover:text-primary hover:underline">{r.name}</button>
              ) : r.name}
            </td>
            <td className="px-3 py-1.5 tabular-nums text-muted-foreground">{r.inn ?? '—'}</td>
            <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
              {money.format(r.amount)} ₽
            </td>
            <td className="px-3 py-1.5"><Share value={r.amount} of={d.total} /></td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">{r.docs}</td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
              {r.positions}
            </td>
            <td className="px-3 py-1.5 tabular-nums text-muted-foreground">{r.last ?? '—'}</td>
          </tr>
        ))}
      </TableCard>
      {card && <CounterpartyWindow companyId={companyId} id={card} onClose={() => setCard(null)} />}
    </div>
  )
}

/**
 * Качество данных продукта: что именно может врать в его цифрах.
 *
 * Отдельно от «Качества данных» пространства: там проверяется слой целиком, здесь —
 * ровно то, от чего зависят экраны «Реализации». Рядом с числом стоит объяснение, чем
 * это грозит: проверка без последствия читается как придирка и её игнорируют.
 */
function RevQuality({ companyId }: { companyId: string }) {
  const q = useQuery({
    queryKey: ['books', 'revenue-quality', companyId],
    queryFn: () => getRevenueQuality(companyId),
    enabled: !!companyId,
  })

  if (q.isError) return <div className="p-4"><QueryError onRetry={() => q.refetch()} /></div>
  if (!q.data) return <Loading />
  const d = q.data

  return (
    <div className="p-4 space-y-4">
      <div className="grid gap-3 grid-cols-3">
        <MetricTile label="Проверок" value={num.format(d.checks.length)}
          hint="гоняются при каждом открытии экрана" />
        <MetricTile label="Есть замечания" value={num.format(d.problems)}
          tone={d.problems ? 'danger' : 'success'}
          hint={d.problems ? 'разобрать с бухгалтерией компании' : 'данные чистые'} />
        <MetricTile label="Реализаций всего" value={num.format(d.salesDocs)}
          hint="на этом множестве считаются все цифры продукта" />
      </div>
      <div className="flex justify-end">
        <ExportButton label="Excel" onClick={() => exportTable('Качество данных · Реализация', [
          { header: 'Проверка', key: 'title', width: 44 },
          { header: 'Найдено', key: 'count', width: 12 },
          { header: 'Чем грозит', key: 'why', width: 70 },
        ], d.checks)} />
      </div>
      <TableCard note="Проверка без последствия читается как придирка — поэтому рядом стоит «чем грозит»"
        head={<><Th>Проверка</Th><Th right>Найдено</Th><Th>Чем это грозит</Th></>}>
        {d.checks.map((c) => (
          <tr key={c.key} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5">{c.title}</td>
            <td className={cn('px-3 py-1.5 text-right tabular-nums',
              c.count ? 'text-amber-600 dark:text-amber-400 font-medium' : 'text-muted-foreground')}>
              {c.count ? num.format(c.count) : 'нет'}
            </td>
            <td className="px-3 py-1.5 text-[11px] text-muted-foreground">{c.why}</td>
          </tr>
        ))}
      </TableCard>
    </div>
  )
}

/* ────────────────────────────────────────────────────────────── */
/*                  Долг, сделки, концентрация                    */
/* ────────────────────────────────────────────────────────────── */

/**
 * Реестр старения долга. Средний срок оплаты отвечает «как платят вообще», а работа
 * идёт с конкретным долгом: чей он и сколько ему дней.
 *
 * ⚠ Срока оплаты по договору в выгрузке нет, поэтому возраст считается от даты счёта,
 * а не от наступления срока платежа. По канону бакеты привязывают к условиям договора
 * (при отсрочке 45 дней просрочка начинается на 46-й) — как приедет реквизит, пороги
 * сдвинутся. Рядом стоит сальдо 62 из регистра: оно знает зачёты и оплаты, которых в
 * регистре «Оплата счетов» нет, поэтому цифры не обязаны совпадать.
 */
function RevAging({ companyId }: { companyId: string }) {
  const q = useQuery({
    queryKey: ['books', 'ar-aging', companyId],
    queryFn: () => getArAging(companyId),
    enabled: !!companyId,
  })
  const [bucket, setBucket] = useState<string | null>(null)
  const [card, setCard] = useState<string | null>(null)

  if (q.isError) return <div className="p-4"><QueryError onRetry={() => q.refetch()} /></div>
  if (!q.data) return <Loading />
  const d = q.data
  const rows = bucket ? d.rows.filter((r) => r.bucket === bucket) : d.rows
  const maxBucket = Math.max(...d.buckets.map((b) => b.amount), 1)
  const old = d.buckets.filter((b) => b.key === 'd180' || b.key === 'older')
    .reduce((s, b) => s + b.amount, 0)

  return (
    <div className="p-4 space-y-4">
      <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
        <MetricTile label="Открытый долг" value={money.format(d.openAmount) + ' ₽'}
          hint={`${num.format(d.openCount)} счетов с известной оплатой`} />
        <MetricTile label="Старше 90 дней" value={money.format(old) + ' ₽'}
          hint={d.openAmount ? `${((old / d.openAmount) * 100).toFixed(0)}% открытого долга` : '—'}
          tone={old > 0 ? 'danger' : 'success'} />
        <MetricTile label="Сальдо 62 по регистру"
          value={money.format(d.registerDebit) + ' ₽'}
          hint={`аванс покупателей ${money.format(d.registerCredit)} ₽`} />
        <MetricTile label="Ожидаемые потери" value={money.format(d.risk) + ' ₽'}
          hint="долг, взвешенный вероятностью невозврата по возрасту"
          tone={d.risk > d.openAmount / 2 ? 'danger' : undefined} />
        <MetricTile label="Оплата неизвестна" value={num.format(d.unknownCount)}
          hint={`${money.format(d.unknownAmount)} ₽ вне расчёта`} />
      </div>

      <p className="text-[11px] text-muted-foreground">
        Возраст считается от даты счёта: срока оплаты по договору в выгрузке нет, и
        отделить отсрочку от просрочки нечем. Ставки риска экспертные и намеренно
        грубые: точность здесь была бы мнимой, а порядок величины рабочий.
        Сальдо 62 рядом — эталон из регистра: он
        знает зачёты авансов и оплаты, которых нет в регистре «Оплата счетов», поэтому
        совпадать цифры не обязаны. Снимок на {d.asOf}.
      </p>

      <Card>
        <CardContent className="p-4 space-y-2">
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
            По возрасту долга — полоса отбирает счета
          </div>
          {d.buckets.map((b) => (
            <button key={b.key} onClick={() => setBucket(bucket === b.key ? null : b.key)}
              disabled={!b.count}
              className={cn('w-full text-left space-y-1 rounded-md px-2 py-1',
                !b.count ? 'opacity-40' : bucket === b.key ? 'bg-muted' : 'hover:bg-muted/50')}>
              <div className="flex justify-between text-sm">
                <span>{b.label} <span className="text-muted-foreground">· {b.count} шт.</span></span>
                <span className="tabular-nums">
                  {money.format(b.amount)} ₽
                  {b.count > 0 && (
                    <span className="ml-2 text-[11px] text-muted-foreground"
                      title="ожидаемые потери: сумма бакета × вероятность невозврата">
                      риск {b.riskPct} % · {money.format(b.risk)} ₽
                    </span>
                  )}
                </span>
              </div>
              <div className="h-2 rounded bg-muted overflow-hidden">
                <div className={cn('h-full',
                  b.key === 'older' || b.key === 'd180' ? 'bg-rose-500/60' : 'bg-primary/60')}
                  style={{ width: `${(b.amount / maxBucket) * 100}%` }} />
              </div>
            </button>
          ))}
        </CardContent>
      </Card>

      <div className="flex justify-end">
        <ExportButton onClick={() => exportTable('Старение долга', [
          { header: 'Покупатель', key: 'name', width: 42 },
          { header: 'Счетов', key: 'invoices', width: 10 },
          { header: 'Долг', key: 'rest', width: 18, money: true },
          { header: 'Дней старшему', key: 'maxAge', width: 14 },
        ], d.clients)} />
      </div>

      <TableCard note="Должники по сумме открытого долга"
        head={<><Th>Покупатель</Th><Th right>Счетов</Th><Th right>Долг</Th>
          <Th right>Старшему счёту</Th><Th>С какой даты</Th></>}>
        {d.clients.length === 0 ? (
          <tr><td colSpan={5} className="px-3 py-3 text-sm text-muted-foreground">
            Среди счетов с известной оплатой открытого долга нет
          </td></tr>
        ) : d.clients.map((c) => (
          <tr key={c.id ?? c.name} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5 max-w-[320px] truncate" title={c.name}>
              {c.id ? (
                <button onClick={() => setCard(c.id)}
                  className="text-left hover:text-primary hover:underline">{c.name}</button>
              ) : c.name}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
              {c.invoices}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
              {money.format(c.rest)} ₽
            </td>
            <td className={cn('px-3 py-1.5 text-right tabular-nums',
              c.maxAge > 180 ? 'text-rose-600 dark:text-rose-400'
              : c.maxAge > 90 ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground')}>
              {num.format(c.maxAge)} дн.
            </td>
            <td className="px-3 py-1.5 tabular-nums text-muted-foreground">{c.oldest ?? '—'}</td>
          </tr>
        ))}
      </TableCard>

      <TableCard
        note={bucket
          ? `${d.buckets.find((b) => b.key === bucket)?.label}: ${num.format(rows.length)} счетов`
          : `Открытые счета — ${num.format(rows.length)}`}
        head={<><Th>Счёт</Th><Th>Дата</Th><Th>Покупатель</Th><Th right>Сумма</Th>
          <Th right>Оплачено</Th><Th right>Долг</Th><Th right>Дней</Th></>}>
        {rows.map((r) => (
          <tr key={r.id} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5 tabular-nums">{r.number}</td>
            <td className="px-3 py-1.5 tabular-nums whitespace-nowrap">{r.date}</td>
            <td className="px-3 py-1.5 max-w-[280px] truncate" title={r.counterparty}>
              {r.counterparty}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums">{money.format(r.amount)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
              {money.format(r.paid ?? 0)}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-rose-600 dark:text-rose-400">
              {money.format(r.rest)}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
              {num.format(r.age)}
            </td>
          </tr>
        ))}
      </TableCard>
      {card && <CounterpartyWindow companyId={companyId} id={card} onClose={() => setCard(null)} />}
    </div>
  )
}

/**
 * Кривая инкассации: какая доля выставленного в месяце собрана к дню 30/60/90/180.
 *
 * Это ответ на вопрос, который средний срок оплаты дать не может: сколько денег из
 * счетов месяца придёт к концу следующего. Месяцы, где счетов меньше пяти, помечены —
 * доля по двум счетам не статистика, а совпадение.
 */
function RevCollection({ companyId }: { companyId: string }) {
  const q = useQuery({
    queryKey: ['books', 'collection-curve', companyId],
    queryFn: () => getCollectionCurve(companyId),
    enabled: !!companyId,
  })

  if (q.isError) return <div className="p-4"><QueryError onRetry={() => q.refetch()} /></div>
  if (!q.data) return <Loading />
  const d = q.data
  if (!d.months.length) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        Нет счетов, которые регистр «Оплата счетов» свёл с платежами, — строить кривую
        не из чего.
      </div>
    )
  }

  const steps = [
    { label: 'к 30 дням', pct: d.avg30 },
    { label: 'к 60 дням', pct: d.avg60 },
    { label: 'к 90 дням', pct: d.avg90 },
    { label: 'к 180 дням', pct: d.avg180 },
  ]

  return (
    <div className="p-4 space-y-4">
      <Card>
        <CardContent className="p-4 space-y-3">
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
            В среднем по всем счетам с оплатой — {money.format(d.billed)} ₽
          </div>
          {steps.map((st) => (
            <div key={st.label} className="space-y-1">
              <div className="flex justify-between text-sm">
                <span>Собрано {st.label}</span>
                <span className="tabular-nums">{st.pct} %</span>
              </div>
              <div className="h-2.5 rounded bg-muted overflow-hidden">
                <div className="h-full bg-primary/60" style={{ width: `${st.pct}%` }} />
              </div>
            </div>
          ))}
          <p className="text-[11px] text-muted-foreground pt-1">
            Хвост после 180 дней — {(100 - d.avg180).toFixed(1)} % выставленного: эти
            деньги приходят позже полугода или не приходят вовсе. По этой кривой
            считается ожидаемое поступление от текущей задолженности.
          </p>
        </CardContent>
      </Card>

      <div className="flex justify-end">
        <ExportButton onClick={() => exportTable('Инкассация по месяцам', [
          { header: 'Месяц', key: 'month', width: 12 },
          { header: 'Счетов', key: 'invoices', width: 10 },
          { header: 'Выставлено', key: 'billed', width: 18, money: true },
          { header: 'К 30 дн., %', key: 'pct30', width: 12 },
          { header: 'К 60 дн., %', key: 'pct60', width: 12 },
          { header: 'К 90 дн., %', key: 'pct90', width: 12 },
          { header: 'К 180 дн., %', key: 'pct180', width: 12 },
        ], d.months)} />
      </div>

      <TableCard note="Месяц выставления счёта → сколько собрано к сроку"
        head={<><Th>Месяц</Th><Th right>Счетов</Th><Th right>Выставлено</Th>
          <Th right>30 дн.</Th><Th right>60 дн.</Th><Th right>90 дн.</Th><Th right>180 дн.</Th></>}>
        {[...d.months].reverse().map((m) => (
          <tr key={m.month} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5">
              {monthLabel(m.month)}
              {m.thin && (
                <span className="ml-1.5 rounded bg-muted px-1 py-0.5 text-[10px] text-muted-foreground"
                  title="меньше пяти счетов: доли по такому числу показывают случайность">
                  мало
                </span>
              )}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
              {m.invoices}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
              {money.format(m.billed)} ₽
            </td>
            {([m.pct30, m.pct60, m.pct90, m.pct180]).map((pct, i) => (
              <td key={i} className={cn('px-3 py-1.5 text-right tabular-nums',
                m.thin ? 'text-muted-foreground'
                : (pct ?? 0) >= 80 ? 'text-emerald-600 dark:text-emerald-400'
                : (pct ?? 0) < 30 ? 'text-rose-600 dark:text-rose-400' : '')}>
                {pct === null ? '—' : `${pct} %`}
              </td>
            ))}
          </tr>
        ))}
      </TableCard>
    </div>
  )
}

/**
 * Сделки: реализация целиком, а не позиция и не месяц.
 *
 * Единица анализа проектной компании — сделка: 218 реализаций за пять лет, и вопрос
 * «какая из них убыточна» распределения не берут. Маржа считается только когда
 * себестоимость известна ПО ВСЕМ строкам: частичная выглядит как настоящая, но
 * завышена на непокрытые позиции.
 */
function RevDeals({ companyId, period }: { companyId: string; period: Period }) {
  const q = useQuery({
    queryKey: ['books', 'deals', companyId, period.from, period.to],
    queryFn: () => getDeals(companyId, period),
    enabled: !!companyId,
  })
  const [search, setSearch] = useState('')
  const [only, setOnly] = useState<'all' | 'low' | 'loss'>('all')
  const [docId, setDocId] = useState<string | null>(null)
  const [card, setCard] = useState<string | null>(null)

  if (q.isError) return <div className="p-4"><QueryError onRetry={() => q.refetch()} /></div>
  if (!q.data) return <Loading />
  const d = q.data
  const rows = d.rows.filter((r) =>
    (!search || r.counterparty.toLowerCase().includes(search.toLowerCase())
      || r.number.toLowerCase().includes(search.toLowerCase()))
    && (only === 'all'
      || (only === 'low' && r.marginPct !== null && r.marginPct < 30)
      || (only === 'loss' && r.margin !== null && r.margin < 0)))
  const avgPct = d.netWithMargin ? (d.marginTotal / d.netWithMargin) * 100 : 0

  return (
    <div className="p-4 space-y-4">
      <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
        <MetricTile label="Сделок за период" value={num.format(d.count)}
          hint={`${money.format(d.net)} ₽ без НДС`} />
        <MetricTile label="Маржа по сделкам" value={money.format(d.marginTotal) + ' ₽'}
          hint={`${avgPct.toFixed(1)} % от суммы сделок с известной себестоимостью`} />
        <MetricTile label="Себестоимость известна" value={num.format(d.withMargin)}
          hint={`из ${num.format(d.count)} сделок`} />
        <MetricTile label="Маржа ниже 30 %" value={num.format(d.lowMargin)}
          hint="порог, за которым проверяют цену и объём работ"
          tone={d.lowMargin > d.withMargin / 2 ? 'danger' : undefined} />
      </div>

      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3 flex-wrap">
          <SearchInput value={search} onChange={setSearch}
            placeholder="Покупатель или номер" label="Поиск по покупателю или номеру" />
          <Tabs value={only} onChange={setOnly} items={[
            { key: 'all' as const, label: 'Все' },
            { key: 'low' as const, label: 'Маржа ниже 30 %' },
            { key: 'loss' as const, label: 'В убыток' },
          ]} />
        </div>
        <ExportButton onClick={() => exportTable('Сделки', [
          { header: 'Дата', key: 'date', width: 12 },
          { header: 'Номер', key: 'number', width: 16 },
          { header: 'Покупатель', key: 'counterparty', width: 40 },
          { header: 'Сумма без НДС', key: 'net', width: 18, money: true },
          { header: 'Себестоимость', key: 'cost', width: 18, money: true },
          { header: 'Маржа', key: 'margin', width: 16, money: true },
          { header: 'Маржа, %', key: 'marginPct', width: 10 },
        ], rows)} />
      </div>

      <TableCard note={`${num.format(rows.length)} сделок из ${num.format(d.count)}`}
        head={<><Th>Дата</Th><Th>Номер</Th><Th>Покупатель</Th><Th right>Без НДС</Th>
          <Th right>Себестоимость</Th><Th right>Маржа</Th><Th right>%</Th></>}>
        {rows.map((r) => (
          <tr key={r.id} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5 tabular-nums whitespace-nowrap">{r.date}</td>
            <td className="px-3 py-1.5 tabular-nums">
              <button onClick={() => setDocId(r.id)}
                className="hover:text-primary hover:underline">{r.number}</button>
            </td>
            <td className="px-3 py-1.5 max-w-[280px] truncate" title={r.counterparty}>
              {r.counterpartyId ? (
                <button onClick={() => setCard(r.counterpartyId)}
                  className="text-left hover:text-primary hover:underline">{r.counterparty}</button>
              ) : r.counterparty}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
              {money.format(r.net)} ₽
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
              {r.cost === null || r.unknownLines ? '—' : money.format(r.cost)}
            </td>
            <td className={cn('px-3 py-1.5 text-right tabular-nums whitespace-nowrap',
              r.margin === null ? 'text-muted-foreground'
              : r.margin < 0 ? 'text-rose-600 dark:text-rose-400'
              : 'text-emerald-600 dark:text-emerald-400')}>
              {r.margin === null ? 'нет данных' : `${money.format(r.margin)} ₽`}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
              {r.marginPct === null ? '—' : `${r.marginPct.toFixed(1)} %`}
            </td>
          </tr>
        ))}
      </TableCard>
      {docId && <DocumentWindow companyId={companyId} docId={docId} onClose={() => setDocId(null)} />}
      {card && <CounterpartyWindow companyId={companyId} id={card} onClose={() => setCard(null)} />}
    </div>
  )
}

/**
 * Концентрация: насколько выручка держится на нескольких клиентах.
 *
 * HHI — сумма квадратов долей в процентах. До 1000 концентрация низкая, 1000–2000
 * умеренная, выше 2000 высокая. Для поставщика это зеркало антимонопольной метрики:
 * высокий индекс значит, что уход одного покупателя уносит заметную часть выручки.
 * Смотреть надо по годам: за всю историю индекс размывается теми, кто давно ушёл.
 */
function RevConcentration({ companyId }: { companyId: string }) {
  const q = useQuery({
    queryKey: ['books', 'concentration', companyId],
    queryFn: () => getConcentration(companyId),
    enabled: !!companyId,
  })

  if (q.isError) return <div className="p-4"><QueryError onRetry={() => q.refetch()} /></div>
  if (!q.data) return <Loading />
  const d = q.data
  const level = (hhi: number | null) =>
    hhi === null ? '—'
    : hhi > d.levels.high ? 'высокая'
    : hhi > d.levels.low ? 'умеренная' : 'низкая'
  const tone = (hhi: number | null) =>
    hhi === null ? undefined
    : hhi > d.levels.high ? 'danger' as const
    : hhi > d.levels.low ? undefined : 'success' as const
  const last = d.years[d.years.length - 1]

  return (
    <div className="p-4 space-y-4">
      <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
        <MetricTile label="HHI за всю историю" value={String(d.total.hhi ?? '—')}
          hint={`${level(d.total.hhi)} концентрация · ${num.format(d.total.clients)} покупателей`}
          tone={tone(d.total.hhi)} />
        <MetricTile label={`HHI за ${last?.year ?? '—'}`} value={String(last?.hhi ?? '—')}
          hint={`${level(last?.hhi ?? null)} концентрация · ${num.format(last?.clients ?? 0)} покупателей`}
          tone={tone(last?.hhi ?? null)} />
        <MetricTile label="Доля крупнейшего" value={`${last?.cr1 ?? '—'} %`}
          hint="в последнем году" />
        <MetricTile label="Доля первой тройки" value={`${last?.cr3 ?? '—'} %`}
          hint="в последнем году" />
      </div>

      <p className="text-[11px] text-muted-foreground">
        HHI — сумма квадратов долей покупателей в процентах: до {num.format(d.levels.low)} концентрация
        низкая, до {num.format(d.levels.high)} умеренная, выше — высокая. За всю историю индекс
        размывается теми, кто давно перестал покупать, поэтому решение принимают по годам.
      </p>

      <div className="flex justify-end">
        <ExportButton onClick={() => exportTable('Концентрация выручки', [
          { header: 'Год', key: 'year', width: 8 },
          { header: 'Покупателей', key: 'clients', width: 12 },
          { header: 'Выручка', key: 'amount', width: 18, money: true },
          { header: 'HHI', key: 'hhi', width: 10 },
          { header: 'CR1, %', key: 'cr1', width: 10 },
          { header: 'CR3, %', key: 'cr3', width: 10 },
          { header: 'CR5, %', key: 'cr5', width: 10 },
        ], d.years)} />
      </div>

      <TableCard note="По годам: чем выше индекс, тем сильнее выручка зависит от нескольких клиентов"
        head={<><Th>Год</Th><Th right>Покупателей</Th><Th right>Выручка</Th><Th right>HHI</Th>
          <Th>Уровень</Th><Th right>CR1</Th><Th right>CR3</Th><Th right>CR5</Th></>}>
        {[...d.years].reverse().map((y) => (
          <tr key={y.year} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5 tabular-nums">{y.year}</td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
              {num.format(y.clients)}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
              {money.format(y.amount ?? 0)} ₽
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums">{y.hhi ?? '—'}</td>
            <td className={cn('px-3 py-1.5 text-[11px]',
              (y.hhi ?? 0) > d.levels.high ? 'text-rose-600 dark:text-rose-400'
              : (y.hhi ?? 0) > d.levels.low ? 'text-amber-600 dark:text-amber-400'
              : 'text-muted-foreground')}>
              {level(y.hhi)}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
              {y.cr1 ?? '—'} %
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
              {y.cr3 ?? '—'} %
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
              {y.cr5 ?? '—'} %
            </td>
          </tr>
        ))}
      </TableCard>
    </div>
  )
}

/**
 * Счета, за которыми не пошла отгрузка.
 *
 * Ссылки «счёт → реализация» в выгрузке нет, поэтому сопоставление идёт по клиенту:
 * тот, у кого есть счета и ни одной реализации, — это либо незакрытая сделка, либо
 * мусор в базе. Экран не решает, какое из двух: он показывает список, с которым идут
 * к заказчику.
 */
function RevBacklog({ companyId }: { companyId: string }) {
  const q = useQuery({
    queryKey: ['books', 'backlog', companyId],
    queryFn: () => getBacklog(companyId),
    enabled: !!companyId,
  })
  const [only, setOnly] = useState<'all' | 'silent'>('silent')
  const [card, setCard] = useState<string | null>(null)

  if (q.isError) return <div className="p-4"><QueryError onRetry={() => q.refetch()} /></div>
  if (!q.data) return <Loading />
  const d = q.data
  const rows = only === 'silent' ? d.rows.filter((r) => !r.sales) : d.rows

  return (
    <div className="p-4 space-y-4">
      <div className="grid gap-3 grid-cols-3">
        <MetricTile label="Выставлено всего" value={money.format(d.invoiced) + ' ₽'} />
        <MetricTile label="Отгружено" value={money.format(d.shipped) + ' ₽'}
          hint={d.invoiced ? `${((d.shipped / d.invoiced) * 100).toFixed(1)} % выставленного` : '—'} />
        <MetricTile label="Клиентов без единой отгрузки" value={num.format(d.silentCount)}
          hint={`счетов на ${money.format(d.silentAmount)} ₽`}
          tone={d.silentCount ? 'danger' : 'success'} />
      </div>

      <p className="text-[11px] text-muted-foreground">
        Сопоставление идёт по клиенту, а не по документу: основания «счёт → реализация»
        выгрузка 1С не несёт. Клиент со счетами и нулём отгрузок — это либо незакрытая
        сделка, либо отменённые счета, оставшиеся в базе. Разбирается с бухгалтерией
        компании: до ответа любая конверсия воронки условна.
      </p>

      <div className="flex items-center justify-between gap-3 flex-wrap">
        <Tabs value={only} onChange={setOnly} items={[
          { key: 'silent' as const, label: 'Без отгрузок' },
          { key: 'all' as const, label: 'Все клиенты' },
        ]} />
        <ExportButton onClick={() => exportTable('Счета без отгрузки', [
          { header: 'Покупатель', key: 'counterparty', width: 42 },
          { header: 'Счетов', key: 'invoices', width: 10 },
          { header: 'Выставлено', key: 'invoiced', width: 18, money: true },
          { header: 'Реализаций', key: 'sales', width: 12 },
          { header: 'Отгружено', key: 'shipped', width: 18, money: true },
          { header: 'Разрыв', key: 'gap', width: 18, money: true },
          { header: 'Последний счёт', key: 'lastInvoice', width: 14 },
        ], rows)} />
      </div>

      <TableCard note={`${num.format(rows.length)} клиентов`}
        head={<><Th>Покупатель</Th><Th right>Счетов</Th><Th right>Выставлено</Th>
          <Th right>Отгружено</Th><Th right>Разрыв</Th><Th>Последний счёт</Th></>}>
        {rows.map((r) => (
          <tr key={r.counterparty} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5 max-w-[320px] truncate" title={r.counterparty}>
              {r.counterpartyId ? (
                <button onClick={() => setCard(r.counterpartyId)}
                  className="text-left hover:text-primary hover:underline">{r.counterparty}</button>
              ) : r.counterparty}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
              {r.invoices}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
              {money.format(r.invoiced)} ₽
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
              {r.sales ? `${money.format(r.shipped)} ₽` : <span className="text-muted-foreground">нет</span>}
            </td>
            <td className={cn('px-3 py-1.5 text-right tabular-nums whitespace-nowrap',
              r.gap > 0 ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground')}>
              {money.format(r.gap)} ₽
            </td>
            <td className="px-3 py-1.5 tabular-nums text-muted-foreground whitespace-nowrap">
              {r.lastInvoice ?? '—'}
              {r.daysSinceLast !== null && (
                <span className="ml-1 text-[11px]">{num.format(r.daysSinceLast)} дн. назад</span>
              )}
            </td>
          </tr>
        ))}
      </TableCard>
      {card && <CounterpartyWindow companyId={companyId} id={card} onClose={() => setCard(null)} />}
    </div>
  )
}

/**
 * Прогноз поступлений от открытого долга.
 *
 * Считается не «по сроку договора», а по исторической кривой инкассации: деньги,
 * которые должны были прийти за прошедшие дни жизни счёта, уже не пришли, и это
 * меняет ожидание. Для счёта возраста A ожидаемая доля досбора равна
 * (F_итог − F(A)) / (1 − F(A)) — условная вероятность на том, что до сих пор не
 * оплачено. Поэтому свежий счёт даёт 45 %, а зависший на четыре года — ноль.
 *
 * Цифра консервативна дважды: кривая построена по счетам, которые регистр «Оплата
 * счетов» свёл (остальные не видны вовсе), и её потолок — историческая доля сбора,
 * а не сто процентов.
 */
function RevForecast({ companyId }: { companyId: string }) {
  const q = useQuery({
    queryKey: ['books', 'cash-forecast', companyId],
    queryFn: () => getCashForecast(companyId),
    enabled: !!companyId,
  })
  const [card, setCard] = useState<string | null>(null)

  if (q.isError) return <div className="p-4"><QueryError onRetry={() => q.refetch()} /></div>
  if (!q.data) return <Loading />
  const d = q.data
  if (!d.openCount) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        Открытых счетов с известной оплатой нет — прогнозировать нечего.
        {d.unknownCount > 0 && ` Ещё ${num.format(d.unknownCount)} счетов вне расчёта:
        регистр «Оплата счетов» их не свёл.`}
      </div>
    )
  }
  const maxWindow = Math.max(...d.windows.map((w) => w.amount), 1)

  return (
    <div className="p-4 space-y-4">
      <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
        <MetricTile label="Открытый долг" value={money.format(d.openAmount) + ' ₽'}
          hint={`${num.format(d.openCount)} счетов с известной оплатой`} />
        <MetricTile label="Ожидаем получить" value={money.format(d.expected) + ' ₽'}
          hint={`${((d.expected / d.openAmount) * 100).toFixed(1)} % открытого долга`}
          tone={d.expected / d.openAmount > 0.5 ? 'success' : 'danger'} />
        <MetricTile label="Из них в ближайшие 90 дней"
          value={money.format(d.windows.find((w) => w.days === 90)?.amount ?? 0) + ' ₽'} />
        <MetricTile label="Вне прогноза" value={num.format(d.unknownCount)}
          hint={`${money.format(d.unknownAmount)} ₽: оплата неизвестна`} />
      </div>

      <Card>
        <CardContent className="p-4 space-y-3">
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
            Ожидаемые поступления накопительно — снимок на {d.asOf}
          </div>
          {d.windows.map((w) => (
            <div key={w.days} className="space-y-1">
              <div className="flex justify-between text-sm">
                <span>В ближайшие {w.label}</span>
                <span className="tabular-nums">{money.format(w.amount)} ₽</span>
              </div>
              <div className="h-2.5 rounded bg-muted overflow-hidden">
                <div className="h-full bg-primary/60"
                  style={{ width: `${(w.amount / maxWindow) * 100}%` }} />
              </div>
            </div>
          ))}
          <p className="text-[11px] text-muted-foreground pt-1">
            Прогноз идёт по исторической кривой: из выставленного собирается{' '}
            {d.totalSharePct} % (по {num.format(d.historyInvoices)} счетам на{' '}
            {money.format(d.historyBilled)} ₽). Для счёта, дожившего до своего возраста
            и не оплаченного, ожидание считается от НЕПРИШЕДШЕЙ части — поэтому свежий
            счёт даёт заметную долю, а зависший на годы почти ноль. Цифра консервативна:
            счета, которых регистр не свёл с платежами, в кривую не входят.
          </p>
        </CardContent>
      </Card>

      <TableCard note="Историческая кривая инкассации: доля собранного к дню"
        head={<>{d.curve.map((c) => <Th key={c.days} right>{c.days} дн.</Th>)}</>}>
        <tr>
          {d.curve.map((c) => (
            <td key={c.days} className="px-3 py-1.5 text-right tabular-nums">{c.pct} %</td>
          ))}
        </tr>
      </TableCard>

      <div className="flex justify-end">
        <ExportButton onClick={() => exportTable('Прогноз поступлений', [
          { header: 'Счёт', key: 'number', width: 16 },
          { header: 'Дата', key: 'date', width: 12 },
          { header: 'Покупатель', key: 'counterparty', width: 40 },
          { header: 'Долг', key: 'rest', width: 18, money: true },
          { header: 'Возраст, дней', key: 'age', width: 14 },
          { header: 'Ожидаем', key: 'expected', width: 18, money: true },
          { header: 'Доля, %', key: 'expectedPct', width: 10 },
          { header: 'В 30 дней', key: 'in30', width: 16, money: true },
        ], d.rows)} />
      </div>

      <TableCard note="По каждому открытому счёту: сколько ждём и как скоро"
        head={<><Th>Счёт</Th><Th>Покупатель</Th><Th right>Долг</Th><Th right>Возраст</Th>
          <Th right>Ожидаем</Th><Th right>Доля</Th><Th right>В 30 дней</Th></>}>
        {d.rows.map((r) => (
          <tr key={r.id} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5 tabular-nums whitespace-nowrap">
              {r.number}
              <span className="ml-1 text-[11px] text-muted-foreground">{r.date}</span>
            </td>
            <td className="px-3 py-1.5 max-w-[260px] truncate" title={r.counterparty}>
              {r.counterpartyId ? (
                <button onClick={() => setCard(r.counterpartyId)}
                  className="text-left hover:text-primary hover:underline">{r.counterparty}</button>
              ) : r.counterparty}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
              {money.format(r.rest)} ₽
            </td>
            <td className={cn('px-3 py-1.5 text-right tabular-nums',
              r.age > 180 ? 'text-rose-600 dark:text-rose-400' : 'text-muted-foreground')}>
              {num.format(r.age)} дн.
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
              {money.format(r.expected)} ₽
            </td>
            <td className={cn('px-3 py-1.5 text-right tabular-nums',
              r.expectedPct >= 40 ? 'text-emerald-600 dark:text-emerald-400'
              : r.expectedPct < 10 ? 'text-rose-600 dark:text-rose-400' : 'text-muted-foreground')}>
              {r.expectedPct} %
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground whitespace-nowrap">
              {money.format(r.in30)} ₽
            </td>
          </tr>
        ))}
      </TableCard>
      {card && <CounterpartyWindow companyId={companyId} id={card} onClose={() => setCard(null)} />}
    </div>
  )
}

/**
 * Движение денег по статьям — «за что платим», в дополнение к «сколько».
 *
 * Статья размечена в самом документе, поэтому разрез честный: это не догадка по
 * назначению платежа. Деление на текущую, инвестиционную и финансовую деятельность —
 * канон отчёта о движении денежных средств: первая показывает, кормит ли бизнес сам
 * себя, вторая — во что вкладывается, третья — чем закрывается разрыв.
 *
 * Документы без статьи вынесены отдельно: пока их много, разрез неполон, и это вопрос
 * к бухгалтерии компании, а не к витрине.
 */
function RevCashflowItems({ companyId, period }: { companyId: string; period: Period }) {
  const q = useQuery({
    queryKey: ['books', 'cashflow-items', companyId, period.from, period.to],
    queryFn: () => getCashflowItems(companyId, period),
    enabled: !!companyId,
  })
  const [side, setSide] = useState<'all' | 'in' | 'out'>('all')

  if (q.isError) return <div className="p-4"><QueryError onRetry={() => q.refetch()} /></div>
  if (!q.data) return <Loading />
  const d = q.data
  if (!d.rows.length) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        За выбранный период банковских документов нет.
      </div>
    )
  }

  const rows = d.rows.filter((r) =>
    side === 'all' ? true : side === 'in' ? r.inflow > 0 : r.outflow > 0)
  const max = Math.max(...d.rows.map((r) => Math.max(r.inflow, r.outflow)), 1)

  return (
    <div className="p-4 space-y-4">
      <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
        {d.kinds.map((k) => (
          <MetricTile key={k.kind} label={k.label}
            value={money.format(k.net) + ' ₽'}
            hint={`пришло ${money.format(k.inflow)} · ушло ${money.format(k.outflow)}`}
            tone={k.kind === 'operating' ? (k.net >= 0 ? 'success' : 'danger') : undefined} />
        ))}
        <MetricTile label="Итог движения"
          value={money.format(d.inflow - d.outflow) + ' ₽'}
          hint={`${num.format(d.rows.length)} статей за период`} />
      </div>

      {d.noItemDocs > 0 && (
        <p className="text-[11px] text-amber-600 dark:text-amber-400">
          У {num.format(d.noItemDocs)} документов на {money.format(d.noItemAmount)} ₽ статья
          движения не заполнена — они попадают в строку «Без статьи» и в вид деятельности
          не относятся. Разбирается в бухгалтерии компании.
        </p>
      )}

      <div className="flex items-center justify-between gap-3 flex-wrap">
        <Tabs value={side} onChange={setSide} label="Направление движения" items={[
          { key: 'all' as const, label: 'Все статьи' },
          { key: 'in' as const, label: 'Поступления' },
          { key: 'out' as const, label: 'Платежи' },
        ]} />
        <ExportButton onClick={() => exportTable('Статьи движения денег', [
          { header: 'Статья', key: 'item', width: 40 },
          { header: 'Вид деятельности', key: 'kindLabel', width: 22 },
          { header: 'Поступило', key: 'inflow', width: 18, money: true },
          { header: 'Ушло', key: 'outflow', width: 18, money: true },
          { header: 'Итог', key: 'net', width: 18, money: true },
        ], rows.map((r) => ({
          ...r,
          kindLabel: d.kinds.find((k) => k.kind === r.kind)?.label ?? r.kind,
        })))} />
      </div>

      <TableCard note="Статья движения размечена в самом документе, а не выведена из назначения платежа"
        head={<><Th>Статья</Th><Th>Вид</Th><Th right>Поступило</Th><Th right>Ушло</Th>
          <Th right>Итог</Th><Th>Период</Th></>}>
        {rows.map((r) => (
          <tr key={r.item} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5 max-w-[320px] truncate" title={r.item}>
              {r.item}
              <div className="mt-0.5 h-1 w-24 rounded bg-muted overflow-hidden">
                <div className={cn('h-full', r.inflow >= r.outflow
                  ? 'bg-emerald-500/60' : 'bg-rose-500/60')}
                  style={{ width: `${(Math.max(r.inflow, r.outflow) / max) * 100}%` }} />
              </div>
            </td>
            <td className="px-3 py-1.5 text-[11px] text-muted-foreground">
              {d.kinds.find((k) => k.kind === r.kind)?.label ?? r.kind}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
              {r.inflow ? `${money.format(r.inflow)} ₽` : '—'}
              {r.inDocs > 0 && (
                <span className="ml-1 text-[11px] text-muted-foreground">{r.inDocs}</span>
              )}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
              {r.outflow ? `${money.format(r.outflow)} ₽` : '—'}
              {r.outDocs > 0 && (
                <span className="ml-1 text-[11px] text-muted-foreground">{r.outDocs}</span>
              )}
            </td>
            <td className={cn('px-3 py-1.5 text-right tabular-nums whitespace-nowrap',
              r.net >= 0 ? 'text-emerald-600 dark:text-emerald-400'
                : 'text-rose-600 dark:text-rose-400')}>
              {money.format(r.net)} ₽
            </td>
            <td className="px-3 py-1.5 text-[11px] text-muted-foreground tabular-nums whitespace-nowrap">
              {r.first} — {r.last}
            </td>
          </tr>
        ))}
      </TableCard>
    </div>
  )
}

/**
 * Что требует внимания — единственный экран продукта, отвечающий на вопрос, который
 * человек задать не догадался.
 *
 * Своих расчётов не заводит: собирает уже посчитанное другими экранами, иначе сигнал
 * и экран, на который он ведёт, разошлись бы в цифрах. Каждый сигнал знает адрес —
 * клик открывает тот экран, где с этим разбираются.
 */
function RevAttention({ companyId, period }: { companyId: string; period: Period }) {
  const { setCoreMode } = useWorkspace()
  const q = useQuery({
    queryKey: ['books', 'attention', companyId, period.from, period.to],
    queryFn: () => getAttention(companyId, period),
    enabled: !!companyId,
  })

  if (q.isError) return <div className="p-4"><QueryError onRetry={() => q.refetch()} /></div>
  if (!q.data) return <Loading />
  const d = q.data

  if (!d.signals.length) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        Сигналов нет: долг в пределах срока, сходимость с бухгалтерией держится,
        замечаний к данным не нашлось. Снимок на {d.asOf}.
      </div>
    )
  }

  return (
    <div className="p-4 space-y-4">
      <div className="grid gap-3 grid-cols-3">
        <MetricTile label="Требуют решения" value={num.format(d.danger)}
          hint="деньги или доверие к цифрам"
          tone={d.danger ? 'danger' : 'success'} />
        <MetricTile label="Стоит посмотреть" value={num.format(d.warn)}
          hint="не срочно, но накапливается" />
        <MetricTile label="Снимок" value={d.asOf}
          hint="сигналы считаются на момент открытия" />
      </div>

      <div className="space-y-2">
        {d.signals.map((sg) => (
          <Card key={sg.key}>
            <CardContent className="p-3">
              <button onClick={() => setCoreMode(sg.mode as never, sg.sub)}
                className="w-full text-left group">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className={cn('h-2 w-2 rounded-full shrink-0',
                        sg.level === 'danger' ? 'bg-rose-500' : 'bg-amber-500')} />
                      <span className="font-medium group-hover:text-primary">{sg.title}</span>
                    </div>
                    <p className="text-[11px] text-muted-foreground mt-1 pl-4">{sg.why}</p>
                  </div>
                  <div className="text-right shrink-0">
                    <div className="tabular-nums whitespace-nowrap">{sg.value}</div>
                    <div className="text-[11px] text-muted-foreground group-hover:text-primary">
                      разобрать →
                    </div>
                  </div>
                </div>
              </button>
            </CardContent>
          </Card>
        ))}
      </div>

      <p className="text-[11px] text-muted-foreground">
        Сигналы собраны из тех же расчётов, что стоят за экранами продукта: своих цифр
        здесь нет, иначе они разошлись бы с тем, что человек увидит, перейдя по ссылке.
      </p>
    </div>
  )
}
