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
import { useQuery } from '@tanstack/react-query'
import { Download } from 'lucide-react'

import { useCompany } from '@/contexts/CompanyContext'
import { useFilters, type Period } from '@/contexts/FilterContext'
import { useWorkspace, useWorkspaceSubView } from '@/contexts/WorkspaceContext'
import { QueryError } from '@/components/common/QueryError'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Card, CardContent } from '@/components/ui/card'
import { MetricTile } from '@/components/ui/metric-tile'
import { cn } from '@/lib/utils'
import {
  getAssortment, getDocs, getRevenue, getRevenueCheck,
  type DocRow, type RevKind,
} from '@/services/booksService'
import { exportTable } from '@/services/booksExport'
import { DocumentWindow } from '@/components/books/DocumentWindow'
import {
  CounterpartyWindow, Loading, NoCompany, NomenclatureWindow, TableCard, Th,
} from './OfficePanels'
import { useWorkspaceSections } from './workspaceSections'

const money = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const num = new Intl.NumberFormat('ru-RU')
const qty = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 })
const MONTHS = ['', 'январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль',
  'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь']

/** Полный список, а не топ-15: экран разреза и есть его реестр. */
const FULL = 500

const monthLabel = (m: string) => {
  const [y, mm] = m.split('-')
  return `${MONTHS[Number(mm)] ?? mm} ${y}`
}

/* ── Периоды сравнения ───────────────────────────────────────────────────── */
// Дата хранится строкой ISO, и сравнение периодов — единственное место, где её
// приходится считать. Считаем ЦЕЛИКОМ в UTC (`Z`, `setUTC*`, `toISOString`): смесь
// локальной полуночи с `toISOString()` в московском поясе уводит каждую границу на
// день назад, и «август» превращается в «31 июля — 30 августа». Проверка —
// `scripts/period-check.mjs`.

const shiftDays = (iso: string, days: number) => {
  const d = new Date(`${iso}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}

const shiftYears = (iso: string, years: number) => {
  const d = new Date(`${iso}T00:00:00Z`)
  d.setUTCFullYear(d.getUTCFullYear() + years)
  return d.toISOString().slice(0, 10)
}

const lengthDays = (p: Period) =>
  Math.round((Date.parse(p.to) - Date.parse(p.from)) / 86400000) + 1

/** Предыдущий период той же длины — «месяц к месяцу». */
const prevPeriod = (p: Period): Period => {
  const len = lengthDays(p)
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

function Tabs<T extends string>({ value, onChange, items }: {
  value: T; onChange: (v: T) => void; items: { key: T; label: string }[]
}) {
  return (
    <div className="flex flex-wrap gap-1">
      {items.map((i) => (
        <button key={i.key} onClick={() => onChange(i.key)}
          className={cn('rounded-md px-2.5 py-1 text-xs',
            value === i.key ? 'bg-muted font-medium' : 'text-muted-foreground hover:bg-muted/50')}>
          {i.label}
        </button>
      ))}
    </div>
  )
}

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
        placeholder="от" inputMode="numeric" className={cls} />
      <input value={to} onChange={(e) => onChange(from, e.target.value)}
        placeholder="до" inputMode="numeric" className={cls} />
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

/** Кнопка выгрузки — по канону отчётности пространства: выгружается видимое. */
function ExportButton({ onClick, label = 'Excel' }: { onClick: () => void; label?: string }) {
  return (
    <button onClick={onClick}
      className="inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs
                 text-muted-foreground hover:bg-muted/50">
      <Download className="h-3.5 w-3.5" />{label}
    </button>
  )
}

/**
 * Изменение к прошлому периоду. Рост с нуля процентом не выражается — показываем
 * «был ноль», иначе экран рисует «+∞ %» и в него перестают смотреть.
 */
function Delta({ now, was }: { now: number; was: number }) {
  if (!was) return <span className="text-muted-foreground">{now ? 'было пусто' : '—'}</span>
  const pct = ((now - was) / Math.abs(was)) * 100
  const up = pct >= 0
  return (
    <span className={cn('tabular-nums', up ? 'text-emerald-600' : 'text-rose-600')}>
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

/** Столбики помесячно — один и тот же график в «Обзоре» и «Динамике». */
function MonthBars({ months, height = 128 }: {
  months: { month: string; amount: number; docs: number }[]; height?: number
}) {
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

/** Ключ покупателя: ссылка на карточку, а имя — только когда ссылки нет. */
const clientKey = (c: { id: string | null; name: string }) => c.id ?? c.name

/* ────────────────────────────────────────────────────────────── */
/*                            Панель                              */
/* ────────────────────────────────────────────────────────────── */

/** Разрез задаётся пунктом там, где он и есть предмет пункта. */
const FIXED_KIND: Record<string, RevKind> = {
  rev_nomen: 'goods',
  rev_svc: 'service',
  rev_abc_items: 'goods',
  rev_margin: 'goods',
}

/** Экраны, у которых своя ручка и разрез над ними не имеет смысла. */
const NO_KIND = ['rev_invoices', 'rev_funnel', 'rev_recon', 'rev_abc', 'rev_abc_items', 'rev_margin']

export function RevenuePanel() {
  const { coreMode } = useWorkspace()
  const sections = useWorkspaceSections()
  const items = sections.find((s) => s.mode === coreMode)?.items ?? []
  const [sub] = useWorkspaceSubView(items[0]?.key ?? '', items.map((i) => i.key))
  const { companyId } = useCompany()
  const { period } = useFilters()
  // Разрез живёт в панели, а не в экране: человек выбрал «услуги» и ходит с этим
  // взглядом по разделам, а не переключает его заново на каждом пункте.
  const [kind, setKind] = useState<RevKind>('all')
  const shown = FIXED_KIND[sub] ?? kind

  if (!companyId) return <NoCompany />

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
          {!p ? <div className="text-sm text-muted-foreground">Считаем…</div> : (
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

  if (a.isError) return <div className="p-4"><QueryError onRetry={() => a.refetch()} /></div>
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

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <Tabs value={base} onChange={setBase} items={[
          { key: 'prev' as const, label: 'Предыдущий период' },
          { key: 'year' as const, label: 'Год назад' },
        ]} />
        <div className="text-xs text-muted-foreground tabular-nums">
          {periodLabel(period)} · против · {periodLabel(other)}
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
              c.now - c.was >= 0 ? 'text-emerald-600' : 'text-rose-600')}>
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
  const total = q.data.total || 1

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
        note={`${rows.length} строк · итог ${money.format(q.data.total)} ₽`}
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
          <input value={search} onChange={(e) => setSearch(e.target.value)}
            placeholder="Покупатель или ИНН"
            className="h-8 w-56 rounded-md border bg-background px-2.5 text-sm" />
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
                days !== null && days > 180 ? 'text-rose-600'
                : days !== null && days > 90 ? 'text-amber-600' : 'text-muted-foreground')}>
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
    queryKey: ['books', 'assortment', companyId, of, period.from, period.to],
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
                r.abc === 'A' ? 'bg-emerald-500/15 text-emerald-600'
                : r.abc === 'B' ? 'bg-amber-500/15 text-amber-600'
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
              r.trend === 'up' ? 'text-emerald-600'
              : r.trend === 'down' ? 'text-rose-600' : 'text-muted-foreground')}>
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

  if (cur.isError) return <div className="p-4"><QueryError onRetry={() => cur.refetch()} /></div>
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
          <input value={search} onChange={(e) => setSearch(e.target.value)}
            placeholder="Наименование или код"
            className="h-8 w-56 rounded-md border bg-background px-2.5 text-sm" />
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
        note={`${title} — ${num.format(found.length)} позиций, ${money.format(q.data.total)} ₽`}
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

function useDocs(companyId: string, docType: string, period: Period, lineKind?: string) {
  return useQuery({
    queryKey: ['books', 'docs', companyId, docType, lineKind, period.from, period.to],
    queryFn: () => getDocs(companyId, docType, { from: period.from, to: period.to },
                           undefined, 0, lineKind),
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
          <input value={search} onChange={(e) => setSearch(e.target.value)}
            placeholder="Контрагент или номер"
            className="h-8 w-56 rounded-md border bg-background px-2.5 text-sm" />
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

  const rows = q.data.rows.filter((r) =>
    (!onlyDebt || (r.amount - (r.paid ?? 0)) > 0.01) && inRange(r.amount, amount.from, amount.to))
  const billed = q.data.rows.reduce((s, r) => s + r.amount, 0)
  const paid = q.data.rows.reduce((s, r) => s + (r.paid ?? 0), 0)

  return (
    <div className="p-4 space-y-3">
      <div className="grid gap-3 grid-cols-3">
        <MetricTile label="Выставлено" value={money.format(billed) + ' ₽'}
          hint={`${num.format(q.data.rows.length)} счетов`} />
        <MetricTile label="Оплачено" value={money.format(paid) + ' ₽'}
          hint={billed ? `${((paid / billed) * 100).toFixed(1)}% суммы счетов` : '—'} />
        <MetricTile label="Не оплачено" value={money.format(billed - paid) + ' ₽'} />
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
      <TableCard note={`${num.format(rows.length)} счетов за период`}
        head={<>
          <Th>Дата</Th><Th>Номер</Th><Th>Покупатель</Th>
          <Th right>Сумма</Th><Th right>Оплачено</Th><Th right>Остаток</Th>
        </>}>
        {rows.map((r) => {
          const rest = r.amount - (r.paid ?? 0)
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
                {r.paid == null ? '—' : money.format(r.paid)}
              </td>
              <td className={cn('px-3 py-1.5 text-right tabular-nums',
                rest > 0.01 ? 'text-rose-600' : 'text-muted-foreground')}>
                {money.format(rest)}
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
    const by = new Map<string, { billed: number; shipped: number; paid: number }>()
    const cell = (m: string) => {
      const c = by.get(m) ?? { billed: 0, shipped: 0, paid: 0 }
      by.set(m, c)
      return c
    }
    for (const r of inv.data?.rows ?? []) {
      const c = cell(r.date.slice(0, 7))
      c.billed += r.amount
      c.paid += r.paid ?? 0
    }
    for (const r of sale.data?.rows ?? []) cell(r.date.slice(0, 7)).shipped += r.amount
    return [...by.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([month, v]) => ({ month, ...v }))
  }, [inv.data, sale.data])

  if (inv.isError) return <div className="p-4"><QueryError onRetry={() => inv.refetch()} /></div>
  if (!inv.data || !sale.data) return <Loading />

  const billed = months.reduce((s, m) => s + m.billed, 0)
  const shipped = months.reduce((s, m) => s + m.shipped, 0)
  const paid = months.reduce((s, m) => s + m.paid, 0)
  const stages: { label: string; value: number; note: string }[] = [
    { label: 'Выставлено счетов', value: billed, note: `${num.format(inv.data.rows.length)} документов` },
    { label: 'Отгружено', value: shipped, note: `${num.format(sale.data.rows.length)} реализаций` },
    { label: 'Оплачено по счетам', value: paid, note: 'из регистра «Оплата счетов»' },
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
            несёт, документ-основание в ней не заполнено. Оплата — только по счетам,
            попавшим в период.
          </p>
        </CardContent>
      </Card>

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
  const unpaid = rows
    .map((r) => ({ ...r, rest: r.amount - (r.paid ?? 0) }))
    .filter((r) => r.rest > 0.01)
    .sort((a, b) => b.rest - a.rest)

  return (
    <>
      <TableCard note={`Счета без полной оплаты: ${num.format(unpaid.length)} на `
        + `${money.format(unpaid.reduce((s, r) => s + r.rest, 0))} ₽`}
        head={<><Th>Дата</Th><Th>Номер</Th><Th>Покупатель</Th>
          <Th right>Сумма</Th><Th right>Не оплачено</Th><Th right>Дней</Th></>}>
        {unpaid.length === 0 ? (
          <tr><td colSpan={6} className="px-3 py-3 text-sm text-muted-foreground">
            Все счета периода оплачены
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
            <td className="px-3 py-1.5 text-right tabular-nums text-rose-600">
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
    const sold = r.soldAmount ?? 0
    const boughtQty = r.boughtQty ?? 0
    const bought = r.boughtAmount ?? 0
    // Средняя цена — сумма / количество, а не среднее из цен строк: строка на сто
    // штук весит столько же, сколько строка на одну, и «среднее из средних» врёт.
    const avgSale = soldQty ? sold / soldQty : 0
    const avgBuy = boughtQty ? bought / boughtQty : 0
    const cost = avgBuy ? avgBuy * soldQty : null
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
  const registerCost = q.data.cost ?? 0

  return (
    <div className="p-4 space-y-4">
      <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
        <MetricTile label="Продано (с известной закупкой)"
          value={money.format(soldKnown) + ' ₽'}
          hint={`${num.format(known.length)} позиций из ${num.format(rows.length)}`} />
        <MetricTile label="Себестоимость (расчётная)" value={money.format(costKnown) + ' ₽'}
          hint="средняя цена закупки × проданное количество" />
        <MetricTile label="Маржа" value={money.format(soldKnown - costKnown) + ' ₽'}
          hint={soldKnown ? `${(((soldKnown - costKnown) / soldKnown) * 100).toFixed(1)}% от продаж` : '—'}
          tone={soldKnown - costKnown > 0 ? 'success' : undefined} />
        <MetricTile label="Себестоимость по 90.02.1" value={money.format(registerCost) + ' ₽'}
          hint={`расчёт ${registerCost ? ((costKnown / registerCost) * 100).toFixed(0) : '—'}% от регистра`} />
      </div>

      <p className="text-[11px] text-muted-foreground">
        Себестоимость считается по строкам поступлений (средневзвешенная цена закупки за
        период), партии и FIFO не учитываются — поэтому рядом стоит оборот 90.02.1 как
        контроль. {noCost > 0 && `У ${num.format(noCost)} позиций закупки в периоде нет —
        услуги, работы и товар со старых остатков; их маржа не считается.`}
      </p>

      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3 flex-wrap">
          <input value={search} onChange={(e) => setSearch(e.target.value)}
            placeholder="Наименование или код"
            className="h-8 w-56 rounded-md border bg-background px-2.5 text-sm" />
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
              : r.margin >= 0 ? 'text-emerald-600' : 'text-rose-600')}>
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
              Math.abs(m.diff) > 1 ? 'text-rose-600' : 'text-muted-foreground')}>
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
