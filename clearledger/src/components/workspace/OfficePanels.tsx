/**
 * Рабочие места компании без объектов (профиль `office`): «Реализация» и «Бухгалтерия».
 *
 * Устроены как остальные продукты пространства: раздел выбирается в рельсе приложения,
 * его экраны — во второй панели, содержимое рисует эта панель по `?sub=`. Раньше оба
 * жили страницами с самодельной полосой вкладок внутри — единственные рабочие места
 * пространства, устроенные не как все (13.08.2026).
 *
 * «Продажи» и «Услуги» — два раздела ОДНОГО продукта: своих чисел они не заводят,
 * читают те же документы бухгалтерии (`accounting_docs`) под своим углом. Экран у них
 * общий с параметром: две копии разошлись бы в первую же правку, а расхождение цифр
 * между соседними витринами — причина, по которой такие витрины бросают.
 *
 * Числа приходят посчитанными с бэкенда (`/api/books/*`): фронт не пересчитывает
 * ничего, иначе «Реализация» и «Бухгалтерия» разошлись бы на копейках округления —
 * а сходимость с бухгалтерией здесь и есть смысл продукта.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronRight } from 'lucide-react'

import { useCompany } from '@/contexts/CompanyContext'
import { useFilters } from '@/contexts/FilterContext'
import { useWorkspace, useWorkspaceSubView } from '@/contexts/WorkspaceContext'
import { QueryError } from '@/components/common/QueryError'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Card, CardContent } from '@/components/ui/card'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { MetricTile } from '@/components/ui/metric-tile'
import { cn } from '@/lib/utils'
import {
  getAccountCard, getBalance, getBooksOverview, getDocs, getEntries, getPeriods, getSlice,
  type BalanceTotals, type BooksOverview, type SliceData,
} from '@/services/booksService'
import { useWorkspaceSections } from './workspaceSections'

const money = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const num = new Intl.NumberFormat('ru-RU')
const qty = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 })
const MONTHS = ['', 'январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль',
  'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь']

const DOC_LABEL: Record<string, string> = {
  sale_goods: 'Реализация товаров',
  sale_services: 'Оказание услуг',
  purchase: 'Поступление',
}

/** Полный список, а не топ-15: экран разреза и есть его реестр. */
const FULL = 500

function Loading() {
  return <div className="p-6 text-sm text-muted-foreground">Загрузка…</div>
}

function NoCompany() {
  return <div className="p-6 text-sm text-muted-foreground">Не выбрана организация.</div>
}

/** Шапка таблицы — одинаковая во всех разрезах пространства. */
function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return (
    <th className={cn('font-normal px-3 py-2', right ? 'text-right' : 'text-left')}>{children}</th>
  )
}

function TableCard({ note, head, children }: {
  note?: string; head: React.ReactNode; children: React.ReactNode
}) {
  return (
    <Card>
      <CardContent className="p-0 overflow-x-auto">
        {note && <div className="px-3 py-2 text-[11px] text-muted-foreground border-b">{note}</div>}
        <table className="w-full text-sm">
          <thead className="text-[11px] uppercase tracking-wider text-muted-foreground">
            <tr className="border-b">{head}</tr>
          </thead>
          <tbody>{children}</tbody>
        </table>
      </CardContent>
    </Card>
  )
}

/* ────────────────────────────────────────────────────────────── */
/*                          Реализация                            */
/* ────────────────────────────────────────────────────────────── */

const REV_COPY = {
  sales: {
    docType: 'sale_goods',
    clients: 'Покупатели',
    items: 'Номенклатура',
    itemsHint: 'по сумме отгрузок',
    docsNote: 'Документы реализации товаров за выбранный период',
  },
  services: {
    docType: 'sale_services',
    clients: 'Заказчики',
    items: 'Виды услуг',
    itemsHint: 'по сумме актов',
    docsNote: 'Акты оказанных услуг за выбранный период',
  },
} as const

type RevKind = keyof typeof REV_COPY

export function RevenuePanel() {
  const { coreMode } = useWorkspace()
  const kind: RevKind = coreMode === 'rev_services' ? 'services' : 'sales'
  const sections = useWorkspaceSections()
  const items = sections.find((s) => s.mode === coreMode)?.items ?? []
  const [sub] = useWorkspaceSubView(items[0]?.key ?? '', items.map((i) => i.key))
  const { companyId } = useCompany()
  const { period } = useFilters()
  const copy = REV_COPY[kind]

  const q = useQuery({
    queryKey: ['books', kind, companyId, period.from, period.to],
    queryFn: () => getSlice(companyId, kind, { top: FULL, from: period.from, to: period.to }),
    enabled: !!companyId,
  })

  if (!companyId) return <NoCompany />
  // Реестр документов ходит своей ручкой — разрез его не считает.
  const view = sub.endsWith('_docs')
    ? <RevDocs companyId={companyId} docType={copy.docType} note={copy.docsNote} />
    : q.isError ? <div className="p-4"><QueryError onRetry={() => q.refetch()} /></div>
    : !q.data ? <Loading />
    : sub.endsWith('_clients') ? <RevClients data={q.data} title={copy.clients} />
    : sub.endsWith('_items') ? <RevItems data={q.data} title={copy.items} hint={copy.itemsHint} />
    : <RevOverview data={q.data} clientsLabel={copy.clients} />

  return (
    <div className="h-full flex flex-col">
      <ScrollArea className="flex-1 min-h-0">{view}</ScrollArea>
    </div>
  )
}

function RevOverview({ data, clientsLabel }: { data: SliceData; clientsLabel: string }) {
  const avg = data.docs ? data.total / data.docs : 0
  const maxMonth = Math.max(...data.months.map((m) => m.amount), 1)
  // Последние два года: полная история за пять лет в столбик не читается.
  const months = data.months.slice(-24)

  return (
    <div className="p-4 space-y-4">
      <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
        <MetricTile label="Оборот с НДС" value={money.format(data.total) + ' ₽'}
          hint={`без НДС ${money.format(data.net)} ₽`} />
        <MetricTile label="Документов" value={num.format(data.docs)}
          hint={`средний ${money.format(avg)} ₽`} />
        <MetricTile label={clientsLabel} value={num.format(data.clients)} />
        <MetricTile label="НДС" value={money.format(data.vat) + ' ₽'} />
      </div>

      <Card>
        <CardContent className="p-4">
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground mb-3">
            Помесячно {months.length ? `(последние ${months.length} мес.)` : ''}
          </div>
          {months.length === 0 ? (
            <div className="py-6 text-center text-sm text-muted-foreground">
              За выбранный период документов нет
            </div>
          ) : (
            /* Высота столбца — в пикселях: проценты внутри flex без своей высоты
               разворачиваются в ноль, и график становится пустой полосой. */
            <div className="flex items-end gap-1 h-40 overflow-x-auto">
              {months.map((m) => (
                <div key={m.month} className="flex flex-col items-center gap-1 min-w-[26px] flex-1"
                  title={`${m.month}: ${money.format(m.amount)} ₽, документов ${m.docs}`}>
                  <div className="w-full rounded-t bg-primary/70"
                    style={{ height: `${Math.max(2, (m.amount / maxMonth) * 128)}px` }} />
                  <div className="text-[9px] text-muted-foreground rotate-45 origin-left h-6 whitespace-nowrap">
                    {m.month.slice(2)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function RevClients({ data, title }: { data: SliceData; title: string }) {
  const total = data.total || 1
  return (
    <div className="p-4">
      <TableCard
        note={`${title}: ${num.format(data.clients)} — по обороту за период`}
        head={<>
          <Th>{title}</Th><Th>ИНН</Th><Th right>Документов</Th>
          <Th right>Оборот</Th><Th right>Доля</Th>
        </>}>
        {data.topClients.map((c) => (
          <tr key={c.name} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5 max-w-[320px] truncate" title={c.name}>{c.name}</td>
            <td className="px-3 py-1.5 tabular-nums text-muted-foreground">{c.inn ?? '—'}</td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">{c.docs}</td>
            <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
              {money.format(c.amount)} ₽
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
              {((c.amount / total) * 100).toFixed(1)}%
            </td>
          </tr>
        ))}
      </TableCard>
    </div>
  )
}

function RevItems({ data, title, hint }: { data: SliceData; title: string; hint: string }) {
  return (
    <div className="p-4">
      <TableCard
        note={`${title} — ${hint}`}
        head={<><Th>{title}</Th><Th right>Количество</Th><Th right>Сумма</Th></>}>
        {data.topItems.map((it) => (
          <tr key={it.name} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5 max-w-[420px] truncate" title={it.name}>{it.name}</td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
              {it.qty ? qty.format(it.qty) : '—'}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
              {money.format(it.amount)} ₽
            </td>
          </tr>
        ))}
      </TableCard>
    </div>
  )
}

function RevDocs({ companyId, docType, note }: {
  companyId: string; docType: string; note: string
}) {
  const { period } = useFilters()
  const q = useQuery({
    queryKey: ['books', 'docs', companyId, docType, period.from, period.to],
    queryFn: () => getDocs(companyId, docType, { from: period.from, to: period.to }),
  })
  if (q.isError) return <div className="p-4"><QueryError onRetry={() => q.refetch()} /></div>
  if (!q.data) return <Loading />

  return (
    <div className="p-4">
      <TableCard
        note={`${note} — ${num.format(q.data.total)} шт.`}
        head={<>
          <Th>Дата</Th><Th>Номер</Th><Th>Контрагент</Th>
          <Th right>Сумма</Th><Th right>НДС</Th><Th right>Строк</Th>
        </>}>
        {q.data.rows.map((r, i) => (
          <tr key={i} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5 tabular-nums whitespace-nowrap">{r.date}</td>
            <td className="px-3 py-1.5 tabular-nums">{r.number}</td>
            <td className="px-3 py-1.5 max-w-[320px] truncate" title={r.counterparty}>
              {r.counterparty}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums">{money.format(r.amount)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
              {money.format(r.vat)}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">{r.lines}</td>
          </tr>
        ))}
      </TableCard>
    </div>
  )
}

/* ────────────────────────────────────────────────────────────── */
/*                          Бухгалтерия                           */
/* ────────────────────────────────────────────────────────────── */

/**
 * Эталон учёта организации: закрытый период неизменяем, с ним сверяется первичка.
 * Разделы идут от эталона к документам — «Регистр» (сводка, обороты, проводки) и
 * «Документы» (первичка и периоды).
 */
export function BooksPanel() {
  const { coreMode } = useWorkspace()
  const sections = useWorkspaceSections()
  const items = sections.find((s) => s.mode === coreMode)?.items ?? []
  const [sub] = useWorkspaceSubView(items[0]?.key ?? '', items.map((i) => i.key))
  const { companyId } = useCompany()

  if (!companyId) return <NoCompany />

  return (
    <div className="h-full flex flex-col">
      <ScrollArea className="flex-1 min-h-0">
        {sub === 'bk_summary' && <BooksSummary companyId={companyId} />}
        {sub === 'bk_turnover' && <BooksBalance companyId={companyId} />}
        {sub === 'bk_entries' && <BooksEntries companyId={companyId} />}
        {sub === 'bk_docs' && <BooksDocs companyId={companyId} />}
        {sub === 'bk_periods' && <BooksPeriods companyId={companyId} />}
      </ScrollArea>
    </div>
  )
}

function BooksSummary({ companyId }: { companyId: string }) {
  const q = useQuery({
    queryKey: ['books', 'overview', companyId],
    queryFn: () => getBooksOverview(companyId),
  })
  if (q.isError) {
    return <div className="p-4">
      <QueryError message="Не удалось загрузить сводку бухгалтерии" onRetry={() => q.refetch()} />
    </div>
  }
  if (!q.data) return <Loading />
  return <div className="p-4"><Summary data={q.data} /></div>
}

function Summary({ data }: { data: BooksOverview }) {
  const margin = data.revenueNet > 0 ? (data.grossProfit / data.revenueNet) * 100 : 0
  const max = Math.max(...data.years.map((x) => x.revenue), 1)
  return (
    <div className="space-y-4">
      <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
        <MetricTile label="Выручка без НДС" value={money.format(data.revenueNet) + ' ₽'}
          hint={`с НДС ${money.format(data.revenue)} ₽`} />
        <MetricTile label="Себестоимость" value={money.format(data.cost) + ' ₽'}
          hint="счёт 90.02" />
        <MetricTile label="Валовая прибыль" value={money.format(data.grossProfit) + ' ₽'}
          hint={`рентабельность ${margin.toFixed(1)}%`}
          tone={data.grossProfit > 0 ? 'success' : 'danger'} />
        <MetricTile label="НДС с продаж" value={money.format(data.vat) + ' ₽'}
          hint="счёт 90.03 → 68.02" />
      </div>

      <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
        <MetricTile label="Проводок" value={num.format(data.entries)}
          hint={data.firstEntry ? `с ${data.firstEntry} по ${data.lastEntry}` : undefined} />
        <MetricTile label="Периодов" value={num.format(data.periodsTotal)} hint="месяцев с движениями" />
        <MetricTile label="Закрыто" value={num.format(data.periodsClosed)}
          hint={`открыто ${data.periodsTotal - data.periodsClosed}`}
          tone={data.periodsClosed === data.periodsTotal ? 'success' : 'warning'} />
        <MetricTile label="Лет в базе" value={num.format(data.years.length)} />
      </div>

      <Card>
        <CardContent className="p-4">
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground mb-3">
            Выручка по годам (с НДС)
          </div>
          <div className="space-y-2">
            {data.years.map((y) => (
              <div key={y.year} className="flex items-center gap-3">
                <div className="w-12 text-sm tabular-nums text-muted-foreground">{y.year}</div>
                <div className="flex-1 h-5 rounded bg-muted/50 overflow-hidden">
                  <div className="h-full rounded bg-primary/70"
                    style={{ width: `${(y.revenue / max) * 100}%` }} />
                </div>
                <div className="w-32 text-right text-sm tabular-nums">
                  {money.format(y.revenue)} ₽
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

/**
 * Оборотно-сальдовая ведомость — главный экран бухгалтера.
 *
 * Обороты без сальдо отвечают только на «сколько прошло через счёт», а проверка
 * любого месяца начинается с вопроса «сколько на нём лежало и сколько осталось».
 * Отсюда шесть колонок: сальдо на начало · обороты · сальдо на конец.
 *
 * Дерево свёрнуто до счетов первого уровня: бухгалтер читает ведомость сверху
 * («что на 90-м»), а субсчета разворачивает там, где нужно. Клик по строке
 * открывает карточку счёта — тот же путь, что в 1С.
 */
function BooksBalance({ companyId }: { companyId: string }) {
  const { period } = useFilters()
  const [open, setOpen] = useState<Set<string>>(new Set())
  const [card, setCard] = useState<string | null>(null)
  const q = useQuery({
    queryKey: ['books', 'balance', companyId, period.from, period.to],
    queryFn: () => getBalance(companyId, { from: period.from, to: period.to }),
  })
  if (q.isError) return <div className="p-4"><QueryError onRetry={() => q.refetch()} /></div>
  if (!q.data) return <Loading />

  const toggle = (code: string) => setOpen((prev) => {
    const next = new Set(prev)
    next.has(code) ? next.delete(code) : next.add(code)
    return next
  })
  // Строка видна, если раскрыты ВСЕ её предки: иначе разворот верхнего уровня
  // вываливал бы сразу и субсчета третьего.
  const visible = q.data.rows.filter((r) => {
    let p = r.parent
    while (p) {
      if (!open.has(p)) return false
      p = q.data!.rows.find((x) => x.code === p)?.parent ?? null
    }
    return true
  })
  const balance = visible.filter((r) => !r.offBalance)
  const off = visible.filter((r) => r.offBalance)

  const row = (r: typeof balance[number]) => (
    <tr key={r.code} className="border-b last:border-0 hover:bg-muted/40">
      <td className="px-3 py-1.5 tabular-nums" style={{ paddingLeft: 12 + r.level * 16 }}>
        <span className="inline-flex items-center gap-1">
          {r.hasChildren ? (
            <button onClick={() => toggle(r.code)} className="text-muted-foreground hover:text-foreground"
              title={open.has(r.code) ? 'Свернуть субсчета' : 'Развернуть субсчета'}>
              {open.has(r.code) ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
            </button>
          ) : <span className="inline-block w-3.5" />}
          <button onClick={() => setCard(r.code)}
            className={cn('hover:text-primary hover:underline', !r.parent && 'font-semibold')}>
            {r.code}
          </button>
        </span>
      </td>
      <td className="px-3 py-1.5 text-muted-foreground max-w-[380px] truncate" title={r.name}>
        {r.name}
      </td>
      <Money v={r.saldoInDt} /><Money v={r.saldoInKt} />
      <Money v={r.turnoverDt} /><Money v={r.turnoverKt} />
      <Money v={r.saldoOutDt} strong /><Money v={r.saldoOutKt} strong />
    </tr>
  )

  const totals = q.data.totals
  return (
    <div className="p-4 space-y-3">
      <Card>
        <CardContent className="p-0 overflow-x-auto">
          <div className="px-3 py-2 text-[11px] text-muted-foreground border-b">
            Сальдо считается нарастающим итогом от первой проводки: входящих остатков
            в выгрузке нет, зато регистр полон с первого дня. Сальдо свёрнутое —
            развёрнутое по 60, 62 и 76 требует субконто.
          </div>
          <table className="w-full text-sm">
            <thead className="text-[11px] uppercase tracking-wider text-muted-foreground">
              <tr className="border-b">
                <th className="text-left font-normal px-3 py-2" rowSpan={2}>Счёт</th>
                <th className="text-left font-normal px-3 py-2" rowSpan={2}>Наименование</th>
                <th className="text-center font-normal px-3 py-1 border-l" colSpan={2}>Сальдо на начало</th>
                <th className="text-center font-normal px-3 py-1 border-l" colSpan={2}>Обороты за период</th>
                <th className="text-center font-normal px-3 py-1 border-l" colSpan={2}>Сальдо на конец</th>
              </tr>
              <tr className="border-b">
                <th className="text-right font-normal px-3 py-1 border-l">Дт</th>
                <th className="text-right font-normal px-3 py-1">Кт</th>
                <th className="text-right font-normal px-3 py-1 border-l">Дт</th>
                <th className="text-right font-normal px-3 py-1">Кт</th>
                <th className="text-right font-normal px-3 py-1 border-l">Дт</th>
                <th className="text-right font-normal px-3 py-1">Кт</th>
              </tr>
            </thead>
            <tbody>
              {balance.map(row)}
              <tr className="border-t-2 bg-muted/30 font-medium">
                <td className="px-3 py-2" colSpan={2}>Итого</td>
                <Money v={totals.saldoInDt} strong /><Money v={totals.saldoInKt} strong />
                <Money v={totals.turnoverDt} strong /><Money v={totals.turnoverKt} strong />
                <Money v={totals.saldoOutDt} strong /><Money v={totals.saldoOutKt} strong />
              </tr>
              {off.length > 0 && (
                <>
                  <tr className="border-t bg-muted/10">
                    <td className="px-3 py-1.5 text-[11px] uppercase tracking-wider text-muted-foreground"
                      colSpan={8}>Забалансовые счета</td>
                  </tr>
                  {off.map(row)}
                </>
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>
      {/* Актив равен пассиву — единственная проверка, которая говорит, что
          ведомость не врёт. Показываем её, а не прячем в тест. */}
      <BalanceCheck totals={totals} />
      {card && <AccountCardWindow companyId={companyId} code={card} onClose={() => setCard(null)} />}
    </div>
  )
}

function Money({ v, strong }: { v: number; strong?: boolean }) {
  return (
    <td className={cn('px-3 py-1.5 text-right tabular-nums whitespace-nowrap',
      !v && 'text-muted-foreground/40', strong && v && 'font-medium')}>
      {v ? money.format(v) : '—'}
    </td>
  )
}

function BalanceCheck({ totals }: { totals: BalanceTotals }) {
  const diff = totals.saldoOutDt - totals.saldoOutKt
  const ok = Math.abs(diff) < 1
  return (
    <div className={cn('rounded-md border px-3 py-2 text-xs',
      ok ? 'border-emerald-500/40 bg-emerald-500/5 text-emerald-700 dark:text-emerald-400'
         : 'border-red-500/40 bg-red-500/5 text-red-600 dark:text-red-400')}>
      {ok
        ? `Актив равен пассиву: ${money.format(totals.saldoOutDt)} ₽ — ведомость сходится.`
        : `Расхождение актива и пассива: ${money.format(diff)} ₽ — в выгрузке не хватает проводок.`}
    </div>
  )
}

/**
 * Карточка счёта окном поверх ведомости: проводки с корреспонденцией и сальдо
 * нарастающим итогом. Уводить бухгалтера с ведомости на отдельный экран нельзя —
 * он смотрит карточку, чтобы понять СТРОКУ ведомости, и должен вернуться в неё.
 */
function AccountCardWindow({ companyId, code, onClose }: {
  companyId: string; code: string; onClose: () => void
}) {
  const { period } = useFilters()
  const q = useQuery({
    queryKey: ['books', 'account', companyId, code, period.from, period.to],
    queryFn: () => getAccountCard(companyId, code, { from: period.from, to: period.to }),
  })
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-6xl max-h-[85vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="text-base">
            Счёт {code}
            {q.data?.name && <span className="ml-2 font-normal text-muted-foreground">{q.data.name}</span>}
          </DialogTitle>
        </DialogHeader>
        {q.isError && <QueryError onRetry={() => q.refetch()} />}
        {!q.data ? <Loading /> : (
          <div className="flex-1 min-h-0 overflow-y-auto space-y-3 pr-1">
            <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
              <MetricTile label="Сальдо на начало"
                value={saldoText(q.data.saldoInDt, q.data.saldoInKt)} />
              <MetricTile label="Оборот по дебету" value={money.format(q.data.turnoverDt) + ' ₽'} />
              <MetricTile label="Оборот по кредиту" value={money.format(q.data.turnoverKt) + ' ₽'} />
              <MetricTile label="Сальдо на конец"
                value={saldoText(q.data.saldoOutDt, q.data.saldoOutKt)} />
            </div>

            {q.data.corr.length > 0 && (
              <TableCard note="С какими счетами корреспондирует"
                head={<><Th>Счёт</Th><Th right>В дебет</Th><Th right>В кредит</Th><Th right>Проводок</Th></>}>
                {q.data.corr.slice(0, 12).map((c) => (
                  <tr key={c.code} className="border-b last:border-0 hover:bg-muted/40">
                    <td className="px-3 py-1.5 tabular-nums">{c.code}</td>
                    <Money v={c.debit} /><Money v={c.credit} />
                    <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
                      {c.entries}
                    </td>
                  </tr>
                ))}
              </TableCard>
            )}

            <TableCard
              note={q.data.shown < q.data.total
                ? `Показаны первые ${num.format(q.data.shown)} из ${num.format(q.data.total)} проводок за период`
                : `${num.format(q.data.total)} проводок за период`}
              head={<>
                <Th>Дата</Th><Th>Документ</Th><Th>Корр. счёт</Th>
                <Th right>Дебет</Th><Th right>Кредит</Th><Th right>Сальдо</Th>
              </>}>
              {q.data.rows.map((r, i) => (
                <tr key={i} className="border-b last:border-0 hover:bg-muted/40">
                  <td className="px-3 py-1.5 tabular-nums whitespace-nowrap">{r.date}</td>
                  <td className="px-3 py-1.5 text-muted-foreground max-w-[280px] truncate"
                    title={r.docTitle ?? ''}>{r.docKind}</td>
                  <td className="px-3 py-1.5 tabular-nums">{r.corr ?? '—'}</td>
                  <Money v={r.debit} /><Money v={r.credit} />
                  <td className="px-3 py-1.5 text-right tabular-nums font-medium">
                    {money.format(r.saldo)}
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

/** Сальдо одной строкой: сторона важнее знака — «Дт 1 057 692» читается сразу. */
function saldoText(dt: number, kt: number): string {
  if (!dt && !kt) return '—'
  return dt ? `Дт ${money.format(dt)} ₽` : `Кт ${money.format(kt)} ₽`
}

function BooksEntries({ companyId }: { companyId: string }) {
  const q = useQuery({
    queryKey: ['books', 'entries', companyId],
    queryFn: () => getEntries(companyId, { limit: 200 }),
  })
  if (q.isError) return <div className="p-4"><QueryError onRetry={() => q.refetch()} /></div>
  if (!q.data) return <Loading />

  return (
    <div className="p-4">
      <TableCard
        note={`Последние 200 из ${num.format(q.data.total)} проводок`}
        head={<>
          <Th>Дата</Th><Th>Документ</Th><Th>Дт</Th><Th>Кт</Th>
          <Th right>Сумма</Th><Th>Содержание</Th>
        </>}>
        {q.data.rows.map((r, i) => (
          <tr key={i} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5 tabular-nums whitespace-nowrap">{r.date}</td>
            <td className="px-3 py-1.5 text-muted-foreground max-w-[220px] truncate"
              title={r.docTitle ?? ''}>{r.docKind}</td>
            <td className="px-3 py-1.5 tabular-nums">{r.accountDt ?? '—'}</td>
            <td className="px-3 py-1.5 tabular-nums">{r.accountKt ?? '—'}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{money.format(r.amount)}</td>
            <td className="px-3 py-1.5 text-muted-foreground max-w-[320px] truncate"
              title={r.content ?? ''}>{r.content}</td>
          </tr>
        ))}
      </TableCard>
    </div>
  )
}

function BooksPeriods({ companyId }: { companyId: string }) {
  const q = useQuery({
    queryKey: ['books', 'periods', companyId],
    queryFn: () => getPeriods(companyId),
  })
  if (q.isError) return <div className="p-4"><QueryError onRetry={() => q.refetch()} /></div>
  if (!q.data) return <Loading />

  return (
    <div className="p-4">
      <TableCard
        note="Закрытый месяц — эталон: его цифры не меняются. Открытый ещё поедет."
        head={<><Th>Период</Th><Th>Состояние</Th><Th right>Проводок</Th><Th right>Выручка</Th></>}>
        {q.data.rows.map((r) => (
          <tr key={`${r.year}-${r.month}`} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5">{MONTHS[r.month]} {r.year}</td>
            <td className="px-3 py-1.5">
              <span className={cn(
                'rounded px-1.5 py-0.5 text-[11px] border',
                r.status === 'closed'
                  ? 'border-emerald-500/40 bg-emerald-500/5 text-emerald-700 dark:text-emerald-400'
                  : 'border-amber-500/40 bg-amber-500/5 text-amber-700 dark:text-amber-400',
              )}>
                {r.status === 'closed' ? 'закрыт' : 'открыт'}
              </span>
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums">{num.format(r.entries)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">
              {r.revenue ? money.format(r.revenue) + ' ₽' : '—'}
            </td>
          </tr>
        ))}
      </TableCard>
    </div>
  )
}

/**
 * Реестр документов: папки — УЧАСТКИ УЧЁТА, внутри них виды документов.
 *
 * Плоский список видов не годился — их пятнадцать, и «Счёт покупателю» стоял рядом
 * с «Регламентной операцией», хотя вопросы к ним разные. Аудитор идёт от участка
 * («что с деньгами», «чем закрыт счёт»), вид документа — уточнение внутри. Состав
 * папок задан на сервере (`books_router.DOC_SECTIONS`): один словарь на экран,
 * выгрузки и витрину «Данные».
 */
function BooksDocs({ companyId }: { companyId: string }) {
  const { period } = useFilters()
  const [section, setSection] = useState<string | undefined>()
  const [type, setType] = useState<string | undefined>()
  const q = useQuery({
    queryKey: ['books', 'docs', companyId, section, type, period.from, period.to],
    queryFn: () => getDocs(companyId, type, { from: period.from, to: period.to }, section),
  })
  if (q.isError) return <div className="p-4"><QueryError onRetry={() => q.refetch()} /></div>
  if (!q.data) return <Loading />

  const sections = q.data.sections ?? []
  const open = sections.find((s) => s.code === section)
  const pick = (code?: string) => { setSection(code); setType(undefined) }

  return (
    <div className="p-4 space-y-3">
      <div className="flex flex-wrap gap-2">
        <button onClick={() => pick(undefined)}
          className={cn('rounded-md border px-3 py-1.5 text-sm',
            !section ? 'bg-primary/10 text-primary font-medium' : 'text-muted-foreground')}>
          Все документы
          <span className="ml-1.5 text-[11px] tabular-nums opacity-70">
            {sections.reduce((n, s) => n + s.count, 0)}
          </span>
        </button>
        {sections.map((s) => (
          <button key={s.code} onClick={() => pick(s.code)} disabled={!s.count}
            className={cn('rounded-md border px-3 py-1.5 text-sm disabled:opacity-40',
              section === s.code ? 'bg-primary/10 text-primary font-medium' : 'text-muted-foreground')}>
            {s.title}
            <span className="ml-1.5 text-[11px] tabular-nums opacity-70">{s.count}</span>
          </button>
        ))}
      </div>

      {/* Виды — второй уровень, только внутри выбранного участка. */}
      {open && open.kinds.filter((k) => k.count).length > 1 && (
        <div className="flex flex-wrap gap-1.5">
          <button onClick={() => setType(undefined)}
            className={cn('rounded-md px-2 py-1 text-xs',
              !type ? 'bg-muted font-medium' : 'text-muted-foreground hover:bg-muted/50')}>
            весь участок
          </button>
          {open.kinds.filter((k) => k.count).map((k) => (
            <button key={k.type} onClick={() => setType(k.type)}
              className={cn('rounded-md px-2 py-1 text-xs',
                type === k.type ? 'bg-muted font-medium' : 'text-muted-foreground hover:bg-muted/50')}>
              {k.label}
              <span className="ml-1 tabular-nums opacity-70">{k.count}</span>
            </button>
          ))}
        </div>
      )}

      <TableCard note={q.data.total > q.data.rows.length
        ? `Показаны ${q.data.rows.length} из ${q.data.total} — сузьте период или участок.`
        : undefined}
        head={<>
          <Th>Дата</Th><Th>Номер</Th><Th>Вид</Th><Th>Контрагент</Th><Th>Назначение</Th>
          <Th right>Сумма</Th><Th right>Строк</Th>
        </>}>
        {q.data.rows.map((r, i) => (
          <tr key={i} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5 tabular-nums whitespace-nowrap">
              {r.date}
              {/* Закрытый месяц: документ в источнике уже не переписать. */}
              {r.periodStatus === 'closed' && (
                <span className="ml-1.5 text-[10px] text-muted-foreground" title="период закрыт">🔒</span>
              )}
            </td>
            <td className="px-3 py-1.5 tabular-nums">{r.number}</td>
            <td className="px-3 py-1.5 text-muted-foreground">{r.label || DOC_LABEL[r.type] || r.type}</td>
            <td className="px-3 py-1.5 max-w-[240px] truncate" title={r.counterparty}>
              {r.counterparty}
              {r.status && r.status !== 'Проведён' && (
                <span className="ml-1.5 text-[10px] text-amber-600">{r.status}</span>
              )}
            </td>
            <td className="px-3 py-1.5 max-w-[260px] truncate text-muted-foreground"
              title={r.operation ?? ''}>{r.operation || '—'}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{money.format(r.amount)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
              {r.lines || '—'}
            </td>
          </tr>
        ))}
      </TableCard>
    </div>
  )
}
