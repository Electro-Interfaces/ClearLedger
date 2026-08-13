/**
 * «Бухгалтерия» → «Взаиморасчёты» и «Счета-фактуры»: экраны аналитического слоя.
 *
 * Оба стоят на том, чего у слоя раньше не было вовсе — на субконто. Проводка знает
 * корреспонденцию и сумму, но не знает, ЧЕЙ это долг: в основной таблице регистра
 * бухгалтерии субконто через COM недоступно. Аналитика приезжает отдельными
 * наборами — сальдо счёта с аналитикой и обороты Дт-Кт помесячно.
 *
 * Отдельный файл, а не блок в `OfficePanels`: тот правится в соседней сессии, и две
 * записи в один файл кончаются потерянной правкой.
 *
 * Числа приходят посчитанными с бэкенда — фронт не пересчитывает ничего, иначе
 * «Взаиморасчёты» разойдутся с оборотками на копейках округления.
 */
import { useQuery } from '@tanstack/react-query'

import { QueryError } from '@/components/common/QueryError'
import { Card, CardContent } from '@/components/ui/card'
import { MetricTile } from '@/components/ui/metric-tile'
import { cn } from '@/lib/utils'
import {
  getPayroll, getSettlements, getVat,
  type SettlementKind, type SettlementsData, type VatData, type VatKind,
} from '@/services/booksService'

const money = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const MONTHS = ['', 'январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль',
  'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь']

function monthLabel(m: string) {
  const [y, mm] = m.split('-')
  return `${MONTHS[Number(mm)] ?? mm} ${y}`
}

function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return <th className={cn('font-normal px-3 py-2', right ? 'text-right' : 'text-left')}>{children}</th>
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

function Tabs<T extends string>({ value, onChange, items }: {
  value: T; onChange: (v: T) => void; items: { key: T; label: string; hint?: string }[]
}) {
  return (
    <div className="flex flex-wrap gap-1">
      {items.map((i) => (
        <button key={i.key} onClick={() => onChange(i.key)}
          className={cn('rounded-md px-2.5 py-1 text-xs',
            value === i.key ? 'bg-muted font-medium' : 'text-muted-foreground hover:bg-muted/50')}>
          {i.label}
          {i.hint && <span className="ml-1.5 tabular-nums opacity-70">{i.hint}</span>}
        </button>
      ))}
    </div>
  )
}

/* ────────────────────────────── Взаиморасчёты ────────────────────────────── */

const SETTLE_TABS: { key: SettlementKind; label: string; note: string }[] = [
  { key: 'receivable', label: 'Покупатели', note: 'Счёт 62: дебет — нам должны, кредит — аванс от покупателя' },
  { key: 'payable', label: 'Поставщики', note: 'Счёт 60: кредит — должны мы, дебет — наш аванс поставщику' },
  { key: 'other', label: 'Прочие расчёты', note: 'Счёт 76: расчёты с разными дебиторами и кредиторами' },
]

export function BooksSettlements({ companyId, kind, onKind }: {
  companyId: string; kind: SettlementKind; onKind: (k: SettlementKind) => void
}) {
  const q = useQuery({
    queryKey: ['books', 'settlements', companyId, kind],
    queryFn: () => getSettlements(companyId, kind),
  })
  if (q.isError) {
    return <div className="p-4"><QueryError message="Не удалось загрузить взаиморасчёты" onRetry={() => q.refetch()} /></div>
  }
  if (!q.data) return <div className="p-6 text-sm text-muted-foreground">Загрузка…</div>
  return <SettlementsView data={q.data} kind={kind} onKind={onKind} />
}

function SettlementsView({ data, kind, onKind }: {
  data: SettlementsData; kind: SettlementKind; onKind: (k: SettlementKind) => void
}) {
  const tab = SETTLE_TABS.find((t) => t.key === kind)!
  // «Нам должны» и «мы должны» — разные стороны у разных счетов, поэтому итог
  // считаем как сальдо, а подпись берём от вкладки.
  const ours = kind === 'receivable' ? data.totals.debit - data.totals.credit
    : data.totals.credit - data.totals.debit
  const rows = data.rows.filter((r) => Math.abs(r.net) > 0.004)

  return (
    <div className="p-4 space-y-4">
      <Tabs value={kind} onChange={onKind} items={SETTLE_TABS.map((t) => ({ key: t.key, label: t.label }))} />

      <div className="grid gap-3 sm:grid-cols-3">
        <MetricTile label={kind === 'payable' ? 'Наш долг' : 'Нам должны'}
          value={`${money.format(Math.abs(ours))} ₽`}
          hint={data.asOf ? `сальдо на ${data.asOf.split('-').reverse().join('.')}` : undefined} />
        <MetricTile label="Дебет" value={`${money.format(data.totals.debit)} ₽`} />
        <MetricTile label="Кредит" value={`${money.format(data.totals.credit)} ₽`} />
      </div>

      <TableCard note={tab.note}
        head={<><Th>Счёт</Th><Th>Контрагент</Th><Th>Договор</Th>
          <Th right>Дебет</Th><Th right>Кредит</Th><Th right>Сальдо</Th></>}>
        {rows.length === 0 ? (
          <tr><td colSpan={6} className="px-3 py-6 text-center text-muted-foreground">
            Незакрытых расчётов нет — по этим счетам всё закрыто.
          </td></tr>
        ) : rows.map((r, i) => (
          <tr key={i} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5 tabular-nums whitespace-nowrap" title={r.accountName ?? ''}>{r.account}</td>
            <td className="px-3 py-1.5 max-w-[280px] truncate" title={r.counterparty ?? ''}>{r.counterparty || '—'}</td>
            <td className="px-3 py-1.5 max-w-[240px] truncate text-muted-foreground" title={r.contract ?? ''}>{r.contract || '—'}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{r.debit ? money.format(r.debit) : '—'}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{r.credit ? money.format(r.credit) : '—'}</td>
            <td className="px-3 py-1.5 text-right tabular-nums font-medium">{money.format(r.net)}</td>
          </tr>
        ))}
      </TableCard>

      <TableCard note="Движение расчётов помесячно: выросло — отгрузили или начислили, закрыто — оплатили или зачли"
        head={<><Th>Месяц</Th><Th right>Выросло</Th><Th right>Закрыто</Th></>}>
        {data.months.map((m) => (
          <tr key={m.month} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5">{monthLabel(m.month)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{m.grew ? money.format(m.grew) : '—'}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{m.closed ? money.format(m.closed) : '—'}</td>
          </tr>
        ))}
      </TableCard>
    </div>
  )
}

/* ─────────────────────────────── Счета-фактуры ────────────────────────────── */

const VAT_TABS: { key: VatKind; label: string; note: string }[] = [
  { key: 'issued', label: 'Выставленные', note: 'Журнал учёта: счета-фактуры покупателям. Сумма выше выручки — в журнал входят авансовые, у которых отгрузки ещё не было' },
  { key: 'received', label: 'Полученные', note: 'Журнал учёта: счета-фактуры поставщиков' },
  { key: 'claimed', label: 'Предъявленный НДС', note: 'Движение налога, предъявленного поставщиком: основание вычета' },
]

export function BooksVat({ companyId, kind, onKind }: {
  companyId: string; kind: VatKind; onKind: (k: VatKind) => void
}) {
  const q = useQuery({
    queryKey: ['books', 'vat', companyId, kind],
    queryFn: () => getVat(companyId, kind),
  })
  if (q.isError) {
    return <div className="p-4"><QueryError message="Не удалось загрузить счета-фактуры" onRetry={() => q.refetch()} /></div>
  }
  if (!q.data) return <div className="p-6 text-sm text-muted-foreground">Загрузка…</div>
  return <VatView data={q.data} kind={kind} onKind={onKind} />
}

function VatView({ data, kind, onKind }: { data: VatData; kind: VatKind; onKind: (k: VatKind) => void }) {
  const tab = VAT_TABS.find((t) => t.key === kind)!
  const byKind = new Map(data.kinds.map((k) => [k.kind, k]))
  return (
    <div className="p-4 space-y-4">
      <Tabs value={kind} onChange={onKind}
        items={VAT_TABS.map((t) => ({ key: t.key, label: t.label, hint: String(byKind.get(t.key)?.count ?? 0) }))} />

      <div className="grid gap-3 sm:grid-cols-3">
        <MetricTile label="Документов" value={String(data.total)} />
        <MetricTile label="Сумма" value={`${money.format(data.amount)} ₽`} />
        <MetricTile label="НДС" value={`${money.format(data.vat)} ₽`} />
      </div>

      <TableCard note={tab.note}
        head={<><Th>Дата</Th><Th>Номер</Th><Th>Контрагент</Th><Th>ИНН</Th>
          <Th right>Сумма</Th><Th right>НДС</Th><Th>Ставка</Th></>}>
        {data.rows.map((r, i) => (
          <tr key={i} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5 tabular-nums whitespace-nowrap">
              {r.date ? r.date.split('-').reverse().join('.') : '—'}
            </td>
            <td className="px-3 py-1.5 tabular-nums">{r.number || '—'}</td>
            <td className="px-3 py-1.5 max-w-[280px] truncate" title={r.invoice ?? r.counterparty ?? ''}>
              {r.counterparty || '—'}
            </td>
            <td className="px-3 py-1.5 tabular-nums text-muted-foreground">{r.inn || '—'}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{money.format(r.amount)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{money.format(r.vat)}</td>
            <td className="px-3 py-1.5 text-muted-foreground">{r.rate || '—'}</td>
          </tr>
        ))}
      </TableCard>

      <TableCard note="По месяцам — как в декларации"
        head={<><Th>Месяц</Th><Th right>Документов</Th><Th right>Сумма</Th><Th right>НДС</Th></>}>
        {data.months.map((m) => (
          <tr key={m.month} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5">{monthLabel(m.month)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{m.count}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{money.format(m.amount)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{money.format(m.vat)}</td>
          </tr>
        ))}
      </TableCard>
    </div>
  )
}

/* ──────────────────────────── Расчёт с персоналом ─────────────────────────── */

/**
 * «Бухгалтерия» → «Зарплата»: начислено, удержано, взносы, выплачено.
 *
 * Считается по строкам расчёта, а не по документам: месяц расчёта и дата документа
 * расходятся — за декабрь считают в декабре, платят в январе.
 *
 * ⚠ Экран показывает персональные данные сотрудников клиента (ФИО, ИНН, СНИЛС).
 */
export function BooksPayroll({ companyId }: { companyId: string }) {
  const q = useQuery({
    queryKey: ['books', 'payroll', companyId],
    queryFn: () => getPayroll(companyId),
  })
  if (q.isError) {
    return <div className="p-4"><QueryError message="Не удалось загрузить расчёт" onRetry={() => q.refetch()} /></div>
  }
  if (!q.data) return <div className="p-6 text-sm text-muted-foreground">Загрузка…</div>
  const d = q.data
  const t = d.totals
  if (!t.employees && !d.docs.length) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        Зарплатный блок не загружен: в срезе компании нет ни начислений, ни ведомостей.
      </div>
    )
  }
  // «Начислено» включает аванс за первую половину месяца, а он проводок не делает —
  // без этой оговорки экран расходится с оборотами регистра, и человек ищет ошибку.
  const posted = t.accrued - t.advance

  return (
    <div className="p-4 space-y-4">
      <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <MetricTile label="Начислено" value={`${money.format(t.accrued)} ₽`}
          hint={t.advance ? `в т. ч. аванс ${money.format(t.advance)} ₽` : undefined} />
        <MetricTile label="НДФЛ" value={`${money.format(t.ndfl)} ₽`} hint="удержано" />
        <MetricTile label="Страховые взносы" value={`${money.format(t.contributions)} ₽`} />
        <MetricTile label="Выплачено" value={`${money.format(t.paid)} ₽`} hint="по ведомостям" />
        <MetricTile label="Долг перед людьми" value={`${money.format(t.debt)} ₽`}
          hint="сальдо 70" tone={t.debt > 0 ? 'warning' : undefined} />
      </div>

      {t.advance > 0 && (
        <p className="text-[11px] text-muted-foreground">
          Аванс за первую половину месяца входит в начисления, но проводок не делает:
          в регистре бухгалтерии отражено {money.format(posted)} ₽.
        </p>
      )}

      <TableCard note="По месяцу начисления, а не по дате документа: за декабрь считают в декабре, платят в январе"
        head={<><Th>Месяц</Th><Th right>Начислено</Th><Th right>НДФЛ</Th>
          <Th right>Взносы</Th><Th right>Выплачено</Th></>}>
        {d.months.map((m) => (
          <tr key={m.month} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5">{monthLabel(m.month)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{m.accrued ? money.format(m.accrued) : '—'}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{m.ndfl ? money.format(m.ndfl) : '—'}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{m.contributions ? money.format(m.contributions) : '—'}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{m.paid ? money.format(m.paid) : '—'}</td>
          </tr>
        ))}
      </TableCard>

      <TableCard note={`Сотрудников: ${d.employees.length}. Персональные данные — не для общего доступа`}
        head={<><Th>Сотрудник</Th><Th>ИНН</Th><Th right>Начислено</Th><Th right>НДФЛ</Th>
          <Th right>Взносы</Th><Th right>Выплачено</Th><Th right>Месяцев</Th></>}>
        {d.employees.map((e, i) => (
          <tr key={e.id ?? i} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5 max-w-[280px] truncate" title={e.snils ? `СНИЛС ${e.snils}` : ''}>
              {e.name || '—'}
            </td>
            <td className="px-3 py-1.5 tabular-nums text-muted-foreground">{e.inn || '—'}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{money.format(e.accrued)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{money.format(e.ndfl)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{money.format(e.contributions)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{money.format(e.paid)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">{e.months}</td>
          </tr>
        ))}
      </TableCard>

      <TableCard note="Из чего сложилась сумма: виды начислений, удержаний и взносов"
        head={<><Th>Вид</Th><Th>Что это</Th><Th right>Сумма</Th><Th right>Строк</Th></>}>
        {d.kinds.map((k, i) => (
          <tr key={i} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5 text-muted-foreground">{KIND_LABEL[k.kind] ?? k.kind}</td>
            <td className="px-3 py-1.5 max-w-[320px] truncate" title={k.name}>{k.name}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{money.format(k.amount)}</td>
            <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">{k.rows}</td>
          </tr>
        ))}
      </TableCard>

      <TableCard note={`Документы блока: ${d.docs.length}`}
        head={<><Th>Дата</Th><Th>Документ</Th><Th>Номер</Th><Th>Месяц</Th>
          <Th right>Сумма</Th><Th>Статус</Th></>}>
        {d.docs.map((doc) => (
          <tr key={doc.id} className="border-b last:border-0 hover:bg-muted/40">
            <td className="px-3 py-1.5 tabular-nums whitespace-nowrap">
              {doc.date.split('-').reverse().join('.')}
            </td>
            <td className="px-3 py-1.5 text-muted-foreground">
              {doc.label}
              {doc.advance && <span className="ml-1.5 text-[10px] text-amber-600">аванс</span>}
            </td>
            <td className="px-3 py-1.5 tabular-nums">{doc.number}</td>
            <td className="px-3 py-1.5 text-muted-foreground">{doc.month ? monthLabel(doc.month) : '—'}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{money.format(doc.amount)}</td>
            <td className={cn('px-3 py-1.5 whitespace-nowrap',
              doc.status !== 'Проведён' && 'text-amber-600')}>{doc.status}</td>
          </tr>
        ))}
      </TableCard>
    </div>
  )
}

/** Виды строк расчёта — человеческими словами. */
const KIND_LABEL: Record<string, string> = {
  accrual: 'Начислено', ndfl: 'НДФЛ', contribution: 'Взносы',
  payment: 'Выплата', deduction: 'Удержано',
}
