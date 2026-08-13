/**
 * «Бухгалтерия» — рабочее место компании без объектов (профиль `office`).
 *
 * Первоисток концепции: бухгалтерия такой компании и есть источник ЭТАЛОНА.
 * Закрытый месяц неизменяем, с ним сверяется всё остальное; открытый — ещё поедет.
 * Поэтому разделы идут от эталона к первичке: сводка → оборотка → проводки →
 * периоды → документы, а не наоборот.
 *
 * Числа приходят посчитанными с бэкенда (`/api/books/*`): фронт не пересчитывает
 * ничего, иначе «Продажи» и «Бухгалтерия» разошлись бы на копейках округления —
 * а сходимость с бухгалтерией здесь и есть смысл продукта.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { BookOpen, FileText, CalendarCheck, Scale, ListOrdered } from 'lucide-react'

import { useCompany } from '@/contexts/CompanyContext'
import { QueryError } from '@/components/common/QueryError'
import { Card, CardContent } from '@/components/ui/card'
import { MetricTile } from '@/components/ui/metric-tile'
import { cn } from '@/lib/utils'
import {
  getBooksOverview, getDocs, getEntries, getPeriods, getTurnover, type BooksOverview,
} from '@/services/booksService'

const money = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const num = new Intl.NumberFormat('ru-RU')
const MONTHS = ['', 'январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль',
  'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь']

const SECTIONS = [
  { key: 'summary', label: 'Сводка', icon: BookOpen },
  { key: 'turnover', label: 'Оборотка', icon: Scale },
  { key: 'entries', label: 'Проводки', icon: ListOrdered },
  { key: 'periods', label: 'Периоды', icon: CalendarCheck },
  { key: 'docs', label: 'Документы', icon: FileText },
] as const

type SectionKey = (typeof SECTIONS)[number]['key']

const DOC_LABEL: Record<string, string> = {
  sale_goods: 'Реализация товаров',
  sale_services: 'Оказание услуг',
  purchase: 'Поступление',
}

export function BooksPage() {
  const { companyId } = useCompany()
  const [section, setSection] = useState<SectionKey>('summary')

  const overview = useQuery({
    queryKey: ['books', 'overview', companyId],
    queryFn: () => getBooksOverview(companyId),
    enabled: !!companyId,
  })

  if (!companyId) {
    return <div className="p-6 text-sm text-muted-foreground">Не выбрана организация.</div>
  }

  return (
    <div className="p-4 space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Бухгалтерия</h1>
        <p className="text-xs text-muted-foreground mt-0.5">
          Эталон учёта организации: закрытый период неизменяем, с ним сверяется первичка
        </p>
      </div>

      <div className="flex flex-wrap gap-1">
        {SECTIONS.map((s) => (
          <button
            key={s.key}
            onClick={() => setSection(s.key)}
            className={cn(
              'flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition-colors',
              section === s.key
                ? 'bg-primary/10 text-primary font-medium'
                : 'text-muted-foreground hover:bg-muted',
            )}
          >
            <s.icon className="size-4" />
            {s.label}
          </button>
        ))}
      </div>

      {overview.isError && (
        <QueryError message="Не удалось загрузить сводку бухгалтерии"
          onRetry={() => overview.refetch()} />
      )}

      {section === 'summary' && overview.data && <Summary data={overview.data} />}
      {section === 'turnover' && <Turnover companyId={companyId} />}
      {section === 'entries' && <Entries companyId={companyId} />}
      {section === 'periods' && <Periods companyId={companyId} />}
      {section === 'docs' && <Docs companyId={companyId} />}
    </div>
  )
}

function Summary({ data }: { data: BooksOverview }) {
  const margin = data.revenueNet > 0 ? (data.grossProfit / data.revenueNet) * 100 : 0
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
            {data.years.map((y) => {
              const max = Math.max(...data.years.map((x) => x.revenue), 1)
              return (
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
              )
            })}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

function Turnover({ companyId }: { companyId: string }) {
  const q = useQuery({
    queryKey: ['books', 'turnover', companyId],
    queryFn: () => getTurnover(companyId),
  })
  if (q.isError) return <QueryError onRetry={() => q.refetch()} />
  if (!q.data) return <div className="text-sm text-muted-foreground">Загрузка…</div>

  return (
    <Card>
      <CardContent className="p-0 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-[11px] uppercase tracking-wider text-muted-foreground">
            <tr className="border-b">
              <th className="text-left font-normal px-3 py-2">Счёт</th>
              <th className="text-left font-normal px-3 py-2">Наименование</th>
              <th className="text-right font-normal px-3 py-2">Оборот по дебету</th>
              <th className="text-right font-normal px-3 py-2">Оборот по кредиту</th>
              <th className="text-right font-normal px-3 py-2">Проводок</th>
            </tr>
          </thead>
          <tbody>
            {q.data.rows.map((r) => (
              <tr key={r.code} className="border-b last:border-0 hover:bg-muted/40">
                <td className="px-3 py-1.5 tabular-nums font-medium">{r.code}</td>
                <td className="px-3 py-1.5 text-muted-foreground">{r.name}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">
                  {r.debit ? money.format(r.debit) : '—'}
                </td>
                <td className="px-3 py-1.5 text-right tabular-nums">
                  {r.credit ? money.format(r.credit) : '—'}
                </td>
                <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
                  {num.format(r.entries)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  )
}

function Entries({ companyId }: { companyId: string }) {
  const q = useQuery({
    queryKey: ['books', 'entries', companyId],
    queryFn: () => getEntries(companyId, { limit: 200 }),
  })
  if (q.isError) return <QueryError onRetry={() => q.refetch()} />
  if (!q.data) return <div className="text-sm text-muted-foreground">Загрузка…</div>

  return (
    <Card>
      <CardContent className="p-0 overflow-x-auto">
        <div className="px-3 py-2 text-[11px] text-muted-foreground border-b">
          Последние 200 из {num.format(q.data.total)} проводок
        </div>
        <table className="w-full text-sm">
          <thead className="text-[11px] uppercase tracking-wider text-muted-foreground">
            <tr className="border-b">
              <th className="text-left font-normal px-3 py-2">Дата</th>
              <th className="text-left font-normal px-3 py-2">Документ</th>
              <th className="text-left font-normal px-3 py-2">Дт</th>
              <th className="text-left font-normal px-3 py-2">Кт</th>
              <th className="text-right font-normal px-3 py-2">Сумма</th>
              <th className="text-left font-normal px-3 py-2">Содержание</th>
            </tr>
          </thead>
          <tbody>
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
          </tbody>
        </table>
      </CardContent>
    </Card>
  )
}

function Periods({ companyId }: { companyId: string }) {
  const q = useQuery({
    queryKey: ['books', 'periods', companyId],
    queryFn: () => getPeriods(companyId),
  })
  if (q.isError) return <QueryError onRetry={() => q.refetch()} />
  if (!q.data) return <div className="text-sm text-muted-foreground">Загрузка…</div>

  return (
    <Card>
      <CardContent className="p-0 overflow-x-auto">
        <div className="px-3 py-2 text-[11px] text-muted-foreground border-b">
          Закрытый месяц — эталон: его цифры не меняются. Открытый ещё поедет.
        </div>
        <table className="w-full text-sm">
          <thead className="text-[11px] uppercase tracking-wider text-muted-foreground">
            <tr className="border-b">
              <th className="text-left font-normal px-3 py-2">Период</th>
              <th className="text-left font-normal px-3 py-2">Состояние</th>
              <th className="text-right font-normal px-3 py-2">Проводок</th>
              <th className="text-right font-normal px-3 py-2">Выручка</th>
            </tr>
          </thead>
          <tbody>
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
          </tbody>
        </table>
      </CardContent>
    </Card>
  )
}

function Docs({ companyId }: { companyId: string }) {
  const [type, setType] = useState<string | undefined>()
  const q = useQuery({
    queryKey: ['books', 'docs', companyId, type],
    queryFn: () => getDocs(companyId, type),
  })
  if (q.isError) return <QueryError onRetry={() => q.refetch()} />
  if (!q.data) return <div className="text-sm text-muted-foreground">Загрузка…</div>

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <button onClick={() => setType(undefined)}
          className={cn('rounded-md border px-3 py-1.5 text-sm',
            !type ? 'bg-primary/10 text-primary font-medium' : 'text-muted-foreground')}>
          Все
        </button>
        {q.data.kinds.map((k) => (
          <button key={k.type} onClick={() => setType(k.type)}
            className={cn('rounded-md border px-3 py-1.5 text-sm',
              type === k.type ? 'bg-primary/10 text-primary font-medium' : 'text-muted-foreground')}>
            {DOC_LABEL[k.type] ?? k.type}
            <span className="ml-1.5 text-[11px] tabular-nums opacity-70">{k.count}</span>
          </button>
        ))}
      </div>

      <Card>
        <CardContent className="p-0 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-[11px] uppercase tracking-wider text-muted-foreground">
              <tr className="border-b">
                <th className="text-left font-normal px-3 py-2">Дата</th>
                <th className="text-left font-normal px-3 py-2">Номер</th>
                <th className="text-left font-normal px-3 py-2">Вид</th>
                <th className="text-left font-normal px-3 py-2">Контрагент</th>
                <th className="text-right font-normal px-3 py-2">Сумма</th>
                <th className="text-right font-normal px-3 py-2">НДС</th>
                <th className="text-right font-normal px-3 py-2">Строк</th>
              </tr>
            </thead>
            <tbody>
              {q.data.rows.map((r, i) => (
                <tr key={i} className="border-b last:border-0 hover:bg-muted/40">
                  <td className="px-3 py-1.5 tabular-nums whitespace-nowrap">{r.date}</td>
                  <td className="px-3 py-1.5 tabular-nums">{r.number}</td>
                  <td className="px-3 py-1.5 text-muted-foreground">{DOC_LABEL[r.type] ?? r.type}</td>
                  <td className="px-3 py-1.5 max-w-[280px] truncate" title={r.counterparty}>
                    {r.counterparty}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{money.format(r.amount)}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
                    {money.format(r.vat)}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
                    {r.lines}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  )
}
