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
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { QueryError } from '@/components/common/QueryError'
import { Card, CardContent } from '@/components/ui/card'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { MetricTile } from '@/components/ui/metric-tile'
import { cn } from '@/lib/utils'
import {
  applyExportRules, createRequestsFromGaps, decideFinding, getChecks, getClosing,
  getExportLayer,
  getPayroll, getRequestLetter, getRequests, getTaxCalendar, getTrends,
  sendRequestLetter,
  getSettlements, getTaxForecast, getVat, resolveRequests, updateAdjustment,
  updateRequest,
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

      {d.taxRegisters?.length > 0 && (
        <TableCard note="Налоговые регистры зарплаты из 1С: из них собираются 6-НДФЛ и РСВ"
          head={<><Th>Месяц</Th><Th right>Доход</Th><Th right>НДФЛ начислен</Th>
            <Th right>НДФЛ перечислен</Th><Th right>База взносов</Th>
            <Th right>Взносы</Th></>}>
          {d.taxRegisters.map((r) => (
            <tr key={r.period} className="border-b last:border-0 hover:bg-muted/40">
              <td className="px-3 py-1.5 whitespace-nowrap">{monthLabel(r.period)}</td>
              <td className="px-3 py-1.5 text-right tabular-nums">{money.format(r.income)}</td>
              <td className="px-3 py-1.5 text-right tabular-nums">{money.format(r.ndflAccrued)}</td>
              <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
                {money.format(r.ndflPaid)}
              </td>
              <td className="px-3 py-1.5 text-right tabular-nums">{money.format(r.contribBase)}</td>
              <td className="px-3 py-1.5 text-right tabular-nums">{money.format(r.contribAccrued)}</td>
            </tr>
          ))}
        </TableCard>
      )}

    </div>
  )
}

/** Виды строк расчёта — человеческими словами. */
const KIND_LABEL: Record<string, string> = {
  accrual: 'Начислено', ndfl: 'НДФЛ', contribution: 'Взносы',
  payment: 'Выплата', deduction: 'Удержано',
}


/* ──────────────────────────── Закрытие периода ────────────────────────────── */

/**
 * «Бухгалтерия» → «Закрытие периода»: что собрано, чего не хватает, кто должен.
 *
 * Приложение стоит между нормализованным слоем и выгрузкой в 1С, и главный его
 * вопрос — можно ли закрывать месяц. Правило то же, что у закрытия месяца в
 * «Эксплуатации»: период закрывается тем, что есть, но «не пришло» обязано быть
 * отличимо от «не смотрели» — поимённо, с суммой и с тем, кто на той стороне.
 */
export function BooksClosing({ companyId }: { companyId: string }) {
  const [period, setPeriod] = useState<string | null>(null)
  const [openGap, setOpenGap] = useState<string | null>(null)
  const qc = useQueryClient()
  const takeControl = useMutation({
    mutationFn: (v: { rule: string; title: string }) =>
      createRequestsFromGaps(companyId, v.rule, period),
    onSuccess: (r) => {
      toast.success(r.created
        ? `Взято под контроль: ${r.created}, срок до ${r.dueDate.split('-').reverse().join('.')}`
        : 'Всё уже на контроле — новых требований не появилось')
      qc.invalidateQueries({ queryKey: ['books', 'requests', companyId] })
    },
    onError: (e) => toast.error(`Не вышло: ${(e as Error).message}`),
  })
  const q = useQuery({
    queryKey: ['books', 'closing', companyId, period],
    queryFn: () => getClosing(companyId, period),
  })
  if (q.isError) {
    return <div className="p-4"><QueryError message="Не удалось загрузить состояние периодов" onRetry={() => q.refetch()} /></div>
  }
  if (!q.data) return <div className="p-6 text-sm text-muted-foreground">Загрузка…</div>
  const d = q.data
  // Месяцы без единого движения не показываем: пустая строка не несёт вопроса.
  const months = d.months.filter((m) => m.docs || m.entries)
  const totalGaps = d.gaps.reduce((s, g) => s + g.count, 0)

  return (
    <div className="p-4 space-y-4">
      <div className="grid gap-3 sm:grid-cols-4">
        <MetricTile label="Закрыто месяцев"
          value={`${months.filter((m) => m.status === 'closed').length} из ${months.length}`} />
        <MetricTile label="Открытых" value={String(months.filter((m) => m.status !== 'closed').length)}
          hint="в них ещё можно править" />
        <MetricTile label="Требует внимания" value={String(totalGaps)}
          hint={period ? `за ${monthLabel(period)}` : 'за всю историю'}
          tone={totalGaps ? 'warning' : undefined} />
        <MetricTile label="Ждём документов на"
          value={`${money.format(d.gaps.filter((g) => g.key !== 'not_posted')
            .reduce((s, g) => s + g.amount, 0))} ₽`} />
      </div>

      {/* Главный вопрос по недостающему документу — до какого числа его ещё можно
          оформить. Ответ зависит от способа получения, а не от желания бухгалтера. */}
      <p className="text-[11px] text-muted-foreground">{d.docFlow.note}</p>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-muted-foreground">Период:</span>
        <button onClick={() => setPeriod(null)}
          className={cn('rounded-md px-2.5 py-1 text-xs',
            !period ? 'bg-muted font-medium' : 'text-muted-foreground hover:bg-muted/50')}>
          вся история
        </button>
        {months.slice(0, 14).map((m) => (
          <button key={m.month} onClick={() => setPeriod(m.month)}
            className={cn('rounded-md px-2.5 py-1 text-xs',
              period === m.month ? 'bg-muted font-medium' : 'text-muted-foreground hover:bg-muted/50')}>
            {monthLabel(m.month)}
            {m.status === 'closed' && <span className="ml-1 opacity-60">🔒</span>}
          </button>
        ))}
      </div>

      {/* Находки: сначала что мешает, потом уже реестр месяцев */}
      <div className="space-y-2">
        {d.gaps.filter((g) => g.count > 0).map((g) => (
          <Card key={g.key}>
            <CardContent className="p-0">
              <button onClick={() => setOpenGap(openGap === g.key ? null : g.key)}
                className="flex w-full items-center gap-3 px-3 py-2.5 text-left hover:bg-muted/40">
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium">{g.title}</div>
                  <div className="text-[11px] text-muted-foreground">{g.why}</div>
                </div>
                <div className="shrink-0 text-right">
                  <div className="text-sm tabular-nums">{g.count}</div>
                  <div className="text-[11px] text-muted-foreground tabular-nums">
                    {money.format(g.amount)} ₽
                  </div>
                </div>
              </button>
              {/* Находка живёт до перезагрузки данных — под контроль её берёт человек. */}
              <div className="flex items-center gap-2 border-t px-3 py-1.5">
                <button
                  onClick={() => takeControl.mutate({ rule: g.key, title: g.title })}
                  disabled={takeControl.isPending}
                  className="rounded-md border border-border px-2.5 py-1 text-[12px] hover:bg-accent disabled:opacity-40">
                  Взять под контроль
                </button>
                <span className="text-[11px] text-muted-foreground">
                  заведёт требования по каждому документу со сроком две недели
                </span>
              </div>
              {openGap === g.key && (
                <div className="overflow-x-auto border-t">
                  <table className="w-full text-sm">
                    <thead className="text-[11px] uppercase tracking-wider text-muted-foreground">
                      <tr className="border-b">
                        <Th>Дата</Th><Th>Номер</Th><Th>Контрагент</Th><Th right>Сумма</Th>
                      </tr>
                    </thead>
                    <tbody>
                      {g.rows.map((r) => (
                        <tr key={r.id} className="border-b last:border-0 hover:bg-muted/40">
                          <td className="px-3 py-1.5 tabular-nums whitespace-nowrap">
                            {r.date.split('-').reverse().join('.')}
                          </td>
                          <td className="px-3 py-1.5 tabular-nums">{r.number || 'б/н'}</td>
                          <td className="px-3 py-1.5 max-w-[280px] truncate">{r.counterparty || '—'}</td>
                          <td className="px-3 py-1.5 text-right tabular-nums">{money.format(r.amount)}</td>
                        </tr>
                      ))}
                      {g.count > g.rows.length && (
                        <tr><td colSpan={4} className="px-3 py-2 text-[11px] text-muted-foreground">
                          Показаны {g.rows.length} из {g.count} — сузьте период.
                        </td></tr>
                      )}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>
        ))}
        {totalGaps === 0 && (
          <Card><CardContent className="py-8 text-center text-sm text-muted-foreground">
            За выбранный период всё собрано: документы на месте и проведены.
          </CardContent></Card>
        )}
      </div>

      {d.byCounterparty.length > 0 && (
        <TableCard note="С кем разговаривать: тот же список, свёрнутый по контрагенту — документы просят у людей, а не у документов"
          head={<><Th>Контрагент</Th><Th>Чего ждём</Th><Th right>Документов</Th><Th right>Сумма</Th></>}>
          {d.byCounterparty.map((c, i) => (
            <tr key={i} className="border-b last:border-0 hover:bg-muted/40">
              <td className="px-3 py-1.5 max-w-[280px] truncate">{c.counterparty}</td>
              <td className="px-3 py-1.5 max-w-[320px] truncate text-muted-foreground">
                {c.kinds.join(' · ')}
              </td>
              <td className="px-3 py-1.5 text-right tabular-nums">{c.count}</td>
              <td className="px-3 py-1.5 text-right tabular-nums">{money.format(c.amount)}</td>
            </tr>
          ))}
        </TableCard>
      )}

      <TableCard note="Реестр периодов: закрытый месяц не переписывается — опоздавший документ идёт корректировкой в текущий"
        head={<><Th>Месяц</Th><Th>Состояние</Th><Th right>Документов</Th><Th right>Проводок</Th>
          <Th right>Оборот</Th><Th>Закрыт</Th></>}>
        {months.map((m) => (
          <tr key={m.month}
            onClick={() => setPeriod(m.month === period ? null : m.month)}
            className={cn('border-b last:border-0 cursor-pointer hover:bg-accent/40',
              period === m.month && 'bg-primary/10')}>
            <td className="px-3 py-1.5">{monthLabel(m.month)}</td>
            <td className="px-3 py-1.5">
              {m.status === 'closed'
                ? <span className="text-muted-foreground">закрыт 🔒</span>
                : <span className="text-amber-600">открыт</span>}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums">{m.docs || '—'}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{m.entries || '—'}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{money.format(m.turnover)}</td>
            <td className="px-3 py-1.5 text-muted-foreground text-[11px]">
              {m.closedAt ? `${m.closedAt.slice(0, 10).split('-').reverse().join('.')}${
                m.closureSource ? ` · ${CLOSURE_LABEL[m.closureSource] ?? m.closureSource}` : ''}` : '—'}
            </td>
          </tr>
        ))}
      </TableCard>
    </div>
  )
}

/** Чем закрыт месяц: регламентными операциями или датой запрета изменений. */
const CLOSURE_LABEL: Record<string, string> = {
  from_bp: 'по данным бухгалтерии',
  regламент: 'регламентные операции',
  lock: 'запрет изменения данных',
  closing_ops: 'регламентные операции',
}


/* ──────────────────────────── Проверки учёта ──────────────────────────────── */

const CHECK_TONE: Record<string, string> = {
  error: 'text-red-600 dark:text-red-400',
  warn: 'text-amber-600 dark:text-amber-400',
  info: 'text-sky-600 dark:text-sky-400',
  ok: 'text-emerald-600 dark:text-emerald-400',
  reviewed: 'text-muted-foreground',
}
const CHECK_MARK: Record<string, string> = {
  error: '●', warn: '●', info: '●', ok: '✓', reviewed: '✓',
}

/**
 * «Бухгалтерия» → «Проверки учёта»: жанр, который бухгалтер знает по 1С.
 *
 * Отличие от «Качества данных» в «Данных»: там про загрузку — доехали ли цифры;
 * здесь про сам учёт — что в нём не так, независимо от того, как он к нам попал.
 *
 * Каждая проверка обязана показать НАРУШИТЕЛЕЙ: правило без списка документов
 * человек всё равно пойдёт проверять руками, и смысл проверки теряется.
 */
export function BooksChecks({ companyId }: { companyId: string }) {
  const [open, setOpen] = useState<string | null>(null)
  const q = useQuery({
    queryKey: ['books', 'checks', companyId],
    queryFn: () => getChecks(companyId),
  })
  if (q.isError) {
    return <div className="p-4"><QueryError message="Не удалось выполнить проверки" onRetry={() => q.refetch()} /></div>
  }
  if (!q.data) return <div className="p-6 text-sm text-muted-foreground">Проверяем…</div>
  const d = q.data

  return (
    <div className="p-4 space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <MetricTile label="Требует исправления" value={String(d.errors)}
          tone={d.errors ? 'danger' : undefined} hint="учёт считается неверным" />
        <MetricTile label="Стоит посмотреть" value={String(d.warnings)}
          tone={d.warnings ? 'warning' : undefined} hint="не ошибка, но объяснимо не всё" />
        <MetricTile label="В порядке" value={String(d.ok)}
          hint={d.reviewed ? `плюс ${d.reviewed} разобрано` : undefined} />
      </div>

      {/* Настройки, с которыми сверяется учёт. Проверка без показанной
          политики требует помнить настройки наизусть. */}
      {d.policy?.length > 0 && (
        <details className="rounded-lg border border-border">
          <summary className="cursor-pointer px-3 py-2 text-sm">
            Учётная политика и режим налогообложения
            <span className="ml-2 text-[11px] text-muted-foreground">
              чему должен соответствовать учёт
            </span>
          </summary>
          <div className="border-t px-3 py-2 space-y-3">
            {d.policy.map((pl) => (
              <div key={pl.kind}>
                <div className="text-[11px] uppercase tracking-wider text-muted-foreground mb-1">
                  {pl.title}
                </div>
                <div className="grid gap-x-6 gap-y-1 sm:grid-cols-2">
                  {Object.entries(pl.settings).map(([k, v]) => (
                    <div key={k} className="flex justify-between gap-3 text-[13px]">
                      <span className="text-muted-foreground">{k}</span>
                      <span className="text-right">{v}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </details>
      )}

      {d.groups.filter((g) => g.checks.length).map((g) => (
        <div key={g.key} className="space-y-2">
          <div className="flex items-baseline gap-2">
            <h4 className="text-sm font-medium">{g.title}</h4>
            {(g.errors > 0 || g.warnings > 0) && (
              <span className="text-[11px] text-muted-foreground">
                {g.errors > 0 && <span className={CHECK_TONE.error}>ошибок {g.errors}</span>}
                {g.errors > 0 && g.warnings > 0 && ' · '}
                {g.warnings > 0 && <span className={CHECK_TONE.warn}>внимание {g.warnings}</span>}
              </span>
            )}
          </div>
          <Card>
            <CardContent className="p-0">
              {g.checks.map((c, i) => (
                <div key={c.key} className={cn(i > 0 && 'border-t')}>
                  <button
                    onClick={() => setOpen(open === c.key ? null : c.key)}
                    disabled={!c.rows.length}
                    className={cn('flex w-full items-center gap-3 px-3 py-2 text-left',
                      c.rows.length ? 'hover:bg-muted/40' : 'cursor-default')}>
                    <span className={cn('shrink-0 text-xs', CHECK_TONE[c.status])}>
                      {CHECK_MARK[c.status] ?? '●'}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="text-sm">{c.title}</div>
                      {c.status !== 'ok' && (
                        <div className="text-[11px] text-muted-foreground">{c.risk}</div>
                      )}
                    </div>
                    <div className="shrink-0 text-right">
                      <div className={cn('text-sm tabular-nums', CHECK_TONE[c.status])}>{c.value}</div>
                      {c.amount > 0 && c.count > 1 && (
                        <div className="text-[11px] text-muted-foreground tabular-nums">
                          {money.format(c.amount)} ₽
                        </div>
                      )}
                    </div>
                  </button>
                  {c.count > 0 && (
                    <div className="px-3 pb-1.5 -mt-1 text-right">
                      <ReviewButton companyId={companyId} scope="checks" ruleKey={c.key}
                        decision={c.decision} onDone={() => q.refetch()} />
                    </div>
                  )}
                  {open === c.key && c.rows.length > 0 && (
                    <div className="overflow-x-auto border-t bg-muted/20">
                      <table className="w-full text-sm">
                        <thead className="text-[11px] uppercase tracking-wider text-muted-foreground">
                          <tr className="border-b">
                            <Th>Дата</Th><Th>Номер</Th><Th>Что именно</Th><Th right>Сумма</Th>
                          </tr>
                        </thead>
                        <tbody>
                          {c.rows.map((r, k) => (
                            <tr key={k} className="border-b last:border-0">
                              <td className="px-3 py-1.5 tabular-nums whitespace-nowrap">
                                {r.date ? r.date.slice(0, 10).split('-').reverse().join('.') : '—'}
                              </td>
                              <td className="px-3 py-1.5 tabular-nums">{r.number || '—'}</td>
                              <td className="px-3 py-1.5 max-w-[420px] truncate" title={r.subject}>
                                {r.subject || '—'}
                              </td>
                              <td className="px-3 py-1.5 text-right tabular-nums">
                                {r.amount ? money.format(r.amount) : '—'}
                              </td>
                            </tr>
                          ))}
                          {c.count > c.rows.length && (
                            <tr><td colSpan={4} className="px-3 py-2 text-[11px] text-muted-foreground">
                              Показаны {c.rows.length} из {c.count}.
                            </td></tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              ))}
            </CardContent>
          </Card>
        </div>
      ))}
    </div>
  )
}


/* ───────────────────────────── Требования документов ──────────────────────── */

const REQ_STATUSES = ['open', 'requested', 'promised', 'received', 'disputed', 'dropped'] as const

/**
 * «Бухгалтерия» → «Требования»: что ждём от контрагентов и что для этого делали.
 *
 * Находка из «Закрытия периода» живёт до перезагрузки данных; требование — та же
 * находка, взятая под контроль: со сроком, ответственным и лентой обращений.
 * Закрывается оно появлением документа в слое, а не кнопкой «сделано» — иначе
 * реестр расходится с учётом.
 */
export function BooksRequests({ companyId }: { companyId: string }) {
  const [status, setStatus] = useState<string>('')
  const [openRow, setOpenRow] = useState<string | null>(null)
  const [letterFor, setLetterFor] = useState<string | null>(null)
  const [text, setText] = useState('')
  const qc = useQueryClient()
  const q = useQuery({
    queryKey: ['books', 'requests', companyId, status],
    queryFn: () => getRequests(companyId, { status: status || undefined }),
  })
  const refresh = () => qc.invalidateQueries({ queryKey: ['books', 'requests', companyId] })

  const check = useMutation({
    mutationFn: () => resolveRequests(companyId),
    onSuccess: (r) => {
      toast.success(r.resolved
        ? `Документы нашлись у ${r.resolved} требований`
        : 'Новых документов пока нет')
      refresh()
    },
  })
  const patch = useMutation({
    mutationFn: (v: { id: string; status?: string; escalation?: string }) =>
      updateRequest(companyId, v.id, v),
    onSuccess: () => { setText(''); refresh() },
    onError: (e) => toast.error(`Не вышло: ${(e as Error).message}`),
  })

  if (q.isError) {
    return <div className="p-4"><QueryError message="Не удалось загрузить требования" onRetry={() => q.refetch()} /></div>
  }
  if (!q.data) return <div className="p-6 text-sm text-muted-foreground">Загрузка…</div>
  const d = q.data

  if (!d.total) {
    return (
      <div className="p-6 space-y-2">
        <p className="text-sm text-muted-foreground">
          Реестр пуст. Требования заводятся из «Закрытия периода»: там видно, чего не
          хватает, и находку можно взять под контроль.
        </p>
      </div>
    )
  }

  return (
    <div className="p-4 space-y-4">
      <div className="grid gap-3 sm:grid-cols-4">
        <MetricTile label="В работе" value={String(d.open)} hint="ждём документ" />
        <MetricTile label="Просрочено" value={String(d.overdue)}
          tone={d.overdue ? 'warning' : undefined} hint="срок прошёл" />
        <MetricTile label="Ждём документов на" value={`${money.format(d.amount)} ₽`} />
        <MetricTile label="Всего в реестре" value={String(d.total)} />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <button onClick={() => setStatus('')}
          className={cn('rounded-md px-2.5 py-1 text-xs',
            !status ? 'bg-muted font-medium' : 'text-muted-foreground hover:bg-muted/50')}>
          все
        </button>
        {d.byStatus.map((s) => (
          <button key={s.status} onClick={() => setStatus(s.status)}
            className={cn('rounded-md px-2.5 py-1 text-xs',
              status === s.status ? 'bg-muted font-medium' : 'text-muted-foreground hover:bg-muted/50')}>
            {s.label} <span className="ml-1 tabular-nums opacity-70">{s.count}</span>
          </button>
        ))}
        <button onClick={() => check.mutate()} disabled={check.isPending}
          className="ml-auto rounded-md border border-border px-2.5 py-1 text-xs hover:bg-accent disabled:opacity-40">
          {check.isPending ? 'Проверяем…' : 'Проверить, не пришли ли'}
        </button>
      </div>

      <TableCard note="Требование закрывается появлением документа в слое, а не отметкой «сделано»"
        head={<><Th>Период</Th><Th>Контрагент</Th><Th>Чего ждём</Th><Th right>Сумма</Th>
          <Th>Срок</Th><Th>Состояние</Th><Th /></>}>
        {d.items.map((r) => (
          <>
            <tr key={r.id} onClick={() => setOpenRow(openRow === r.id ? null : r.id)}
              className="border-b last:border-0 hover:bg-accent/40 cursor-pointer">
              <td className="px-3 py-1.5 whitespace-nowrap">{monthLabel(r.period)}</td>
              <td className="px-3 py-1.5 max-w-[240px] truncate">{r.counterparty || '—'}</td>
              <td className="px-3 py-1.5 max-w-[280px] truncate text-muted-foreground">{r.docKind}</td>
              <td className="px-3 py-1.5 text-right tabular-nums">{money.format(r.amount)}</td>
              <td className={cn('px-3 py-1.5 tabular-nums whitespace-nowrap',
                r.overdue && 'text-amber-600')}>
                {r.dueDate ? r.dueDate.split('-').reverse().join('.') : '—'}
                {r.overdue && ' просрочено'}
              </td>
              <td className="px-3 py-1.5 whitespace-nowrap">
                {r.statusLabel}
                {r.escalations.length > 0 && (
                  <span className="ml-1.5 text-[10px] text-muted-foreground">
                    обращений {r.escalations.length}
                  </span>
                )}
              </td>
              <td className="px-3 py-1.5 text-right whitespace-nowrap">
                <button onClick={(e) => { e.stopPropagation(); setLetterFor(r.id) }}
                  className="rounded-md px-2 py-0.5 text-[12px] text-muted-foreground hover:bg-accent">
                  написать
                </button>
              </td>
            </tr>
            {openRow === r.id && (
              <tr key={`${r.id}-open`} className="border-b bg-muted/20">
                <td colSpan={7} className="px-3 py-3 space-y-3">
                  {r.escalations.length > 0 && (
                    <div className="space-y-1">
                      {r.escalations.map((e, i) => (
                        <div key={i} className="text-[11px] text-muted-foreground">
                          {e.at.slice(0, 16).replace('T', ' ')} · {e.who}
                          {e.channel ? ` · ${e.channel}` : ''} — {e.text}
                        </div>
                      ))}
                    </div>
                  )}
                  <div className="flex flex-wrap items-center gap-2">
                    <input value={text} onChange={(ev) => setText(ev.target.value)}
                      placeholder="Что сделали: написали, позвонили, обещали к пятнице"
                      className="h-8 min-w-[280px] flex-1 rounded-md border border-border bg-background px-2.5 text-[13px] outline-none" />
                    <button
                      onClick={() => text.trim() && patch.mutate({ id: r.id, escalation: text.trim() })}
                      disabled={!text.trim() || patch.isPending}
                      className="h-8 rounded-md border border-border px-2.5 text-[13px] hover:bg-accent disabled:opacity-40">
                      Записать обращение
                    </button>
                    {REQ_STATUSES.filter((s) => s !== r.status).map((s) => (
                      <button key={s} onClick={() => patch.mutate({ id: r.id, status: s })}
                        className="h-8 rounded-md px-2.5 text-[13px] text-muted-foreground hover:bg-accent">
                        {REQ_STATUS_LABEL[s]}
                      </button>
                    ))}
                  </div>
                </td>
              </tr>
            )}
          </>
        ))}
      </TableCard>

      {letterFor && (
        <RequestLetterDialog companyId={companyId} requestId={letterFor}
          onClose={() => setLetterFor(null)} onSent={() => q.refetch()} />
      )}
    </div>
  )
}

const REQ_STATUS_LABEL: Record<string, string> = {
  open: 'На контроле', requested: 'Запрошен', promised: 'Обещан',
  received: 'Получен', disputed: 'Спорный', dropped: 'Не ждём',
}


/* ─────────────────────────── Налоги заранее ───────────────────────────────── */

/**
 * «Бухгалтерия» → «Налоги заранее»: сколько заплатим, если закрыть период как есть.
 *
 * Отличие от «Налогов» в «Экономике»: там факт — начислено и уплачено. Здесь
 * ПРОГНОЗ и цена работы: рядом с «как есть» стоит сценарий «если недостающие
 * документы придут», и разница между ними — рубли, ради которых собирают первичку.
 *
 * Это оценка по нашим данным, а не декларация, и на экране так и написано:
 * подменять бухгалтерию нельзя, а дать порядок суммы заранее — можно.
 */
export function BooksForecast({ companyId }: { companyId: string }) {
  const q = useQuery({
    queryKey: ['books', 'tax-forecast', companyId],
    queryFn: () => getTaxForecast(companyId),
  })
  if (q.isError) {
    return <div className="p-4"><QueryError message="Не удалось посчитать прогноз" onRetry={() => q.refetch()} /></div>
  }
  if (!q.data) return <div className="p-6 text-sm text-muted-foreground">Считаем…</div>
  const d = q.data
  const t = d.totals

  return (
    <div className="p-4 space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <MetricTile label="НДС к уплате" value={`${money.format(t.vatDue)} ₽`}
          hint="книга продаж минус книга покупок" />
        <MetricTile label="Налог на прибыль" value={`${money.format(t.profitTax)} ₽`}
          hint="20 % от прибыли по данным периода" />
        <MetricTile label="Если собрать документы"
          value={`${money.format(t.vatDueIfCollected + t.profitTaxIfCollected)} ₽`}
          hint="оба налога вместе" />
        <MetricTile label="Цена сбора первички" value={`${money.format(t.saving)} ₽`}
          tone={t.saving > 0 ? 'warning' : undefined}
          hint="столько переплатим, если документы не дойдут" />
      </div>

      <div className="rounded-lg border border-border px-3 py-2">
        <p className="text-[11px] text-muted-foreground">{d.disclaimer}</p>
        {d.notIncluded?.length > 0 && (
          <p className="mt-1 text-[11px] text-muted-foreground">
            <span className="font-medium">В расчёт НЕ входит:</span>{' '}
            {d.notIncluded.join(' · ')}. Ставки периода: НДС{' '}
            {Math.round((d.rates?.vat ?? 0.22) * 100)} %, прибыль{' '}
            {Math.round((d.rates?.profit ?? 0.25) * 100)} %.
          </p>
        )}
      </div>

      <TableCard note="По кварталам: слева как есть, справа — если недостающие документы придут"
        head={<><Th>Квартал</Th><Th right>НДС начислен</Th><Th right>Вычет</Th>
          <Th right>НДС к уплате</Th><Th right>Прибыль</Th><Th right>Налог</Th>
          <Th right>Ждём документов</Th><Th right>Станет налога</Th></>}>
        {d.quarters.map((r) => {
          const after = r.vatDueIfCollected + r.profitTaxIfCollected
          const now = r.vatDue + r.profitTax
          return (
            <tr key={r.quarter} className="border-b last:border-0 hover:bg-muted/40">
              <td className="px-3 py-1.5 whitespace-nowrap">{r.quarter.replace('-Q', ' кв. ')}</td>
              <td className="px-3 py-1.5 text-right tabular-nums">{money.format(r.vatOut)}</td>
              <td className="px-3 py-1.5 text-right tabular-nums">{money.format(r.vatIn)}</td>
              <td className="px-3 py-1.5 text-right tabular-nums font-medium">{money.format(r.vatDue)}</td>
              <td className="px-3 py-1.5 text-right tabular-nums">{money.format(r.profit)}</td>
              <td className="px-3 py-1.5 text-right tabular-nums">{money.format(r.profitTax)}</td>
              <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
                {r.pendingExpense || r.pendingVat
                  ? money.format(r.pendingExpense + r.pendingVat) : '—'}
              </td>
              <td className={cn('px-3 py-1.5 text-right tabular-nums',
                after < now && 'text-emerald-600 dark:text-emerald-400')}>
                {money.format(after)}
              </td>
            </tr>
          )
        })}
      </TableCard>

      <div className="grid gap-3 lg:grid-cols-2">
        <TableCard note="Долг перед бюджетом на дату среза: начислено и не уплачено"
          head={<><Th>Счёт</Th><Th>Налог</Th><Th right>Долг</Th></>}>
          {d.budget.map((b) => (
            <tr key={b.account} className="border-b last:border-0 hover:bg-muted/40">
              <td className="px-3 py-1.5 tabular-nums">{b.account}</td>
              <td className="px-3 py-1.5 max-w-[280px] truncate">{b.name}</td>
              <td className="px-3 py-1.5 text-right tabular-nums">{money.format(b.debt)}</td>
            </tr>
          ))}
        </TableCard>

        <TableCard note="Зарплатные налоги за всю историю"
          head={<><Th>Показатель</Th><Th right>Сумма</Th></>}>
          <tr className="border-b">
            <td className="px-3 py-1.5">НДФЛ удержан</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{money.format(t.ndfl)}</td>
          </tr>
          <tr>
            <td className="px-3 py-1.5">Страховые взносы начислены</td>
            <td className="px-3 py-1.5 text-right tabular-nums">{money.format(t.contributions)}</td>
          </tr>
        </TableCard>
      </div>
    </div>
  )
}



/**
 * Отметка «разобрано» у находки. Проверки и тенденции пересчитываются каждый раз,
 * поэтому решение хранится отдельно и цепляется ключом «правило + строка»: иначе
 * объяснённый однажды случай остаётся красным навсегда.
 */
function ReviewButton({ companyId, scope, ruleKey, rowKey, decision, onDone }: {
  companyId: string; scope: 'checks' | 'trends'; ruleKey: string; rowKey?: string
  decision?: { decision: string; note?: string } | null; onDone: () => void
}) {
  const m = useMutation({
    mutationFn: (v: string) => decideFinding(companyId, scope, ruleKey,
      { rowKey, decision: v, note: v === 'ignored' ? 'правило шумит на этих данных' : '' }),
    onSuccess: onDone,
    onError: (e) => toast.error(`Не вышло: ${(e as Error).message}`),
  })
  if (decision) {
    return (
      <button onClick={() => m.mutate('open')} disabled={m.isPending}
        title={decision.note || undefined}
        className="rounded-md px-2 py-0.5 text-[12px] text-muted-foreground hover:bg-accent">
        разобрано ✓
      </button>
    )
  }
  return (
    <button onClick={() => m.mutate('reviewed')} disabled={m.isPending}
      className="rounded-md px-2 py-0.5 text-[12px] text-muted-foreground hover:bg-accent">
      разобрать
    </button>
  )
}

/* ───────────────────────────── Слой выгрузки ──────────────────────────────── */

/**
 * «Бухгалтерия» → «Слой выгрузки»: чем то, что уйдёт в 1С, отличается от слоя.
 *
 * Слой — копия учёта клиента, «что есть». Выгрузка — «что мы предлагаем провести».
 * Корректировка не меняет документ, а лежит рядом: было → стало, причина, автор.
 * Утверждает человек; правила лишь предлагают, повторяя решение в новых периодах.
 */
export function BooksExportLayer({ companyId }: { companyId: string }) {
  const [period, setPeriod] = useState<string>('')
  const qc = useQueryClient()
  const q = useQuery({
    queryKey: ['books', 'export-layer', companyId, period],
    queryFn: () => getExportLayer(companyId, period || undefined),
  })
  const refresh = () => qc.invalidateQueries({ queryKey: ['books', 'export-layer', companyId] })

  const decide = useMutation({
    mutationFn: (v: { id: string; status: string }) =>
      updateAdjustment(companyId, v.id, { status: v.status }),
    onSuccess: () => refresh(),
    onError: (e) => toast.error(`Не вышло: ${(e as Error).message}`),
  })
  const apply = useMutation({
    mutationFn: (pd: string) => applyExportRules(companyId, pd),
    onSuccess: (r) => {
      toast.success(r.created
        ? `Правила предложили корректировок: ${r.created}`
        : 'Правила ничего не предложили для этого периода')
      refresh()
    },
  })

  if (q.isError) {
    return <div className="p-4"><QueryError message="Не удалось загрузить слой выгрузки" onRetry={() => q.refetch()} /></div>
  }
  if (!q.data) return <div className="p-6 text-sm text-muted-foreground">Загрузка…</div>
  const d = q.data
  const draft = d.adjustments.filter((a) => a.status === 'draft').length
  const approved = d.adjustments.filter((a) => a.status === 'approved').length

  return (
    <div className="p-4 space-y-4">
      <div className="grid gap-3 sm:grid-cols-4">
        <MetricTile label="Черновики" value={String(draft)} hint="предложено, не утверждено" />
        <MetricTile label="Утверждено к выгрузке" value={String(approved)}
          tone={approved ? 'warning' : undefined} />
        <MetricTile label="Изменится сумма" value={`${money.format(d.effect.amount)} ₽`}
          hint="по утверждённым" />
        <MetricTile label="Изменится НДС" value={`${money.format(d.effect.vat)} ₽`} />
      </div>

      <p className="text-[11px] text-muted-foreground">
        Слой не меняется: корректировка лежит рядом с документом и уходит только в
        выгрузку. Утверждённое не переписывается — поправить можно новой корректировкой.
      </p>

      <div className="flex flex-wrap items-center gap-2">
        <input value={period} onChange={(e) => setPeriod(e.target.value)}
          placeholder="ГГГГ-ММ" maxLength={7}
          className="h-8 w-28 rounded-md border border-border bg-background px-2.5 text-[13px] outline-none" />
        <button onClick={() => period.length === 7 && apply.mutate(period)}
          disabled={period.length !== 7 || apply.isPending}
          className="h-8 rounded-md border border-border px-2.5 text-[13px] hover:bg-accent disabled:opacity-40">
          {apply.isPending ? 'Применяем…' : 'Применить правила к периоду'}
        </button>
        <span className="text-[11px] text-muted-foreground">
          правило заводит черновики — решение прошлого квартала может не подойти этому
        </span>
      </div>

      {d.adjustments.length > 0 && (
        <TableCard note="Каждая корректировка адресная: документ, поле и обоснование"
          head={<><Th>Период</Th><Th>Документ</Th><Th>Что меняем</Th><Th>Было</Th><Th>Станет</Th>
            <Th>Причина</Th><Th>Состояние</Th><Th>{''}</Th></>}>
          {d.adjustments.map((a) => (
            <tr key={a.id} className="border-b last:border-0 hover:bg-muted/40">
              <td className="px-3 py-1.5 whitespace-nowrap">{monthLabel(a.period)}</td>
              <td className="px-3 py-1.5 max-w-[220px] truncate">
                {a.doc ? `${a.doc.label} № ${a.doc.number}` : '—'}
              </td>
              <td className="px-3 py-1.5 whitespace-nowrap">{a.fieldLabel}</td>
              <td className="px-3 py-1.5 tabular-nums text-muted-foreground">{a.oldValue || '—'}</td>
              <td className="px-3 py-1.5 tabular-nums font-medium">{a.newValue || '—'}</td>
              <td className="px-3 py-1.5 max-w-[280px] truncate" title={a.reason}>{a.reason}</td>
              <td className="px-3 py-1.5 whitespace-nowrap">{a.statusLabel}</td>
              <td className="px-3 py-1.5 whitespace-nowrap text-right">
                {a.status === 'draft' && (
                  <>
                    <button onClick={() => decide.mutate({ id: a.id, status: 'approved' })}
                      className="rounded-md px-2 py-0.5 text-[12px] hover:bg-accent">
                      утвердить
                    </button>
                    <button onClick={() => decide.mutate({ id: a.id, status: 'rejected' })}
                      className="rounded-md px-2 py-0.5 text-[12px] text-muted-foreground hover:bg-accent">
                      отклонить
                    </button>
                  </>
                )}
              </td>
            </tr>
          ))}
        </TableCard>
      )}

      {d.rules.length > 0 && (
        <TableCard note="Правила повторяют решение в новых периодах — но только предлагают"
          head={<><Th>Правило</Th><Th>К чему применяется</Th><Th>Что ставит</Th>
            <Th right>Применено</Th><Th>Действует с</Th></>}>
          {d.rules.map((r) => (
            <tr key={r.id} className="border-b last:border-0 hover:bg-muted/40">
              <td className="px-3 py-1.5 max-w-[240px] truncate" title={r.reason}>{r.name}</td>
              <td className="px-3 py-1.5 text-muted-foreground">
                {r.docTypeLabel}{r.matchText ? ` · «${r.matchText}»` : ''}
              </td>
              <td className="px-3 py-1.5">{r.fieldLabel}: {r.newValue}</td>
              <td className="px-3 py-1.5 text-right tabular-nums">{r.applied}</td>
              <td className="px-3 py-1.5 text-muted-foreground">{r.validFrom || '—'}</td>
            </tr>
          ))}
        </TableCard>
      )}

      {!d.adjustments.length && (
        <Card><CardContent className="py-8 text-center text-sm text-muted-foreground">
          Корректировок нет: выгрузка совпадает со слоем. Заводятся они из карточки
          документа или правилом, когда решение повторяется каждый период.
        </CardContent></Card>
      )}
    </div>
  )
}


/* ─────────────────────────────── Тенденции ────────────────────────────────── */

/**
 * «Бухгалтерия» → «Тенденции»: на что посмотреть, когда формально всё сходится.
 *
 * «Проверки учёта» ловят нарушенное правило. Здесь правило не нарушено — цифра
 * просто ведёт себя необычно. Поэтому каждая находка подаётся с объяснением
 * «почему это спрашивают», а не как ошибка: иначе экран станет генератором
 * ложных тревог, и его перестанут открывать на второй неделе.
 */
export function BooksTrends({ companyId }: { companyId: string }) {
  const [open, setOpen] = useState<string | null>(null)
  const q = useQuery({
    queryKey: ['books', 'trends', companyId],
    queryFn: () => getTrends(companyId),
  })

  if (q.isError) {
    return <div className="p-4"><QueryError message="Не удалось загрузить тенденции" onRetry={() => q.refetch()} /></div>
  }
  if (!q.data) return <div className="p-6 text-sm text-muted-foreground">Загрузка…</div>
  const d = q.data
  const shown = d.months.filter((m) => m.revenue || m.cost || m.expense)
  const peak = Math.max(1, ...shown.map((m) => Math.max(m.revenue, m.cost + m.expense)))

  return (
    <div className="p-4 space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <MetricTile label="Месяцев с оборотом" value={String(shown.length)} />
        <MetricTile label="Поводов посмотреть" value={String(d.summary.open)}
          tone={d.summary.open ? 'warning' : undefined}
          hint={`не разобрано из ${d.summary.findings}`} />
        <MetricTile label="Прибыль за год"
          value={`${money.format(shown.slice(-12).reduce((s, m) => s + m.profit, 0))} ₽`}
          hint="последние 12 месяцев с оборотом" />
      </div>

      {/* Столбики без графической библиотеки: выручка против затрат помесячно.
          Ставить сюда чарт-пакет ради двух рядов — лишняя зависимость. */}
      <Card>
        <CardContent className="p-3">
          <div className="text-[11px] text-muted-foreground mb-2">
            Выручка (сверху) против себестоимости и расходов (снизу) по месяцам
          </div>
          <div className="flex items-end gap-[3px] overflow-x-auto pb-1">
            {shown.slice(-36).map((m) => (
              <div key={m.month} className="flex flex-col items-center gap-[2px] min-w-[14px]"
                title={`${monthLabel(m.month)}\nвыручка ${money.format(m.revenue)} ₽\n`
                  + `себестоимость ${money.format(m.cost)} ₽\nрасходы ${money.format(m.expense)} ₽\n`
                  + `прибыль ${money.format(m.profit)} ₽\nдокументов ${m.docs}`}>
                <div className="w-full bg-primary/70 rounded-sm"
                  style={{ height: `${Math.round((m.revenue / peak) * 70)}px` }} />
                <div className={cn('w-full rounded-sm',
                  m.profit < 0 ? 'bg-destructive/60' : 'bg-muted-foreground/35')}
                  style={{ height: `${Math.round(((m.cost + m.expense) / peak) * 70)}px` }} />
                <span className="text-[9px] text-muted-foreground rotate-0">
                  {m.month.slice(5)}
                </span>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Приказ ФНС ММ-3-06/333@: те же показатели инспекция считает по нашей же
          отчётности. Увидеть их до неё — весь смысл раздела. */}
      {d.fnsRisk?.length > 0 && (
        <Card>
          <CardContent className="p-0">
            <div className="px-3 py-2 text-[11px] text-muted-foreground border-b">
              Как компанию видит налоговая — критерии самостоятельной оценки рисков
            </div>
            <table className="w-full text-sm">
              <tbody>
                {d.fnsRisk.map((r) => (
                  <tr key={r.title} className="border-b last:border-0">
                    <td className="px-3 py-1.5 w-64">{r.title}</td>
                    <td className={cn('px-3 py-1.5 w-48 tabular-nums font-medium',
                      r.status === 'warn' && 'text-amber-600 dark:text-amber-500')}>
                      {r.value}
                    </td>
                    <td className="px-3 py-1.5 text-[11px] text-muted-foreground">{r.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}

      {d.findings.map((f) => (
        <Card key={f.key}>
          <CardContent className="p-0">
            <div className={cn('w-full flex items-start gap-3 px-3 py-2.5',
              f.decision && 'opacity-60')}>
              <button onClick={() => setOpen(open === f.key ? null : f.key)}
                className="flex flex-1 items-start gap-3 text-left">
                <span className="mt-0.5 text-muted-foreground text-xs">
                  {open === f.key ? '▾' : '▸'}
                </span>
                <span className="flex-1">
                  <span className="text-sm font-medium">{f.title}</span>
                  <span className="block text-[11px] text-muted-foreground mt-0.5">{f.why}</span>
                </span>
              </button>
              <span className="text-sm tabular-nums text-muted-foreground">
                {f.decision ? f.count : `${f.open} из ${f.count}`}
              </span>
              <ReviewButton companyId={companyId} scope="trends" ruleKey={f.key}
                decision={f.decision} onDone={() => q.refetch()} />
            </div>
            {open === f.key && (
              <table className="w-full text-sm border-t">
                <tbody>
                  {f.rows.map((r, i) => (
                    <tr key={i} className={cn('border-b last:border-0',
                      r.decision && 'opacity-50')}>
                      <td className="px-3 py-1.5 w-28 whitespace-nowrap text-muted-foreground">
                        {r.period ? monthLabel(r.period) : '—'}
                      </td>
                      <td className="px-3 py-1.5">{r.subject}</td>
                      <td className="px-3 py-1.5 w-32 text-right tabular-nums whitespace-nowrap">
                        {r.amount ? `${money.format(r.amount)} ₽` : ''}
                      </td>
                      <td className="px-3 py-1.5 w-56 text-[11px] text-muted-foreground">
                        {r.note}
                      </td>
                      <td className="px-3 py-1.5 w-24 text-right whitespace-nowrap">
                        <ReviewButton companyId={companyId} scope="trends" ruleKey={f.key}
                          rowKey={r.rowKey} decision={r.decision}
                          onDone={() => q.refetch()} />
                      </td>
                    </tr>
                  ))}
                  {f.count > f.rows.length && (
                    <tr><td colSpan={5} className="px-3 py-1.5 text-[11px] text-muted-foreground">
                      показаны первые {f.rows.length} из {f.count}
                    </td></tr>
                  )}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>
      ))}

      {!d.findings.length && (
        <Card><CardContent className="py-8 text-center text-sm text-muted-foreground">
          Ничего необычного: расходы ровные, разовых поставщиков нет, встречных
          операций тоже. Экран заполнится, когда цифра начнёт выделяться.
        </CardContent></Card>
      )}
    </div>
  )
}


/* ──────────────────────────── Сроки и бюджет ──────────────────────────────── */

const TASK_TONE: Record<string, string> = {
  'срок прошёл': 'text-amber-600 dark:text-amber-500',
  'на этой неделе': 'text-foreground font-medium',
  'сдано': 'text-muted-foreground',
}

/**
 * «Бухгалтерия» → «Сроки и бюджет»: что горит, что сдано, сколько должны.
 *
 * Раздел не считает ничего своего. Календарь бухгалтера, начисления на ЕНС,
 * уведомления и сданная отчётность приезжают из 1С в слой — здесь они собраны в
 * одном месте и упорядочены по сроку. Смысл прослойки в том, чтобы бухгалтер
 * видел горящее, не открывая 1С.
 */
export function BooksCalendar({ companyId }: { companyId: string }) {
  const [tab, setTab] = useState<'tasks' | 'enp' | 'filed'>('tasks')
  const q = useQuery({
    queryKey: ['books', 'calendar', companyId],
    queryFn: () => getTaxCalendar(companyId),
  })

  if (q.isError) {
    return <div className="p-4"><QueryError message="Не удалось загрузить сроки" onRetry={() => q.refetch()} /></div>
  }
  if (!q.data) return <div className="p-6 text-sm text-muted-foreground">Загрузка…</div>
  const d = q.data

  return (
    <div className="p-4 space-y-4">
      <div className="grid gap-3 sm:grid-cols-4">
        <MetricTile label="Срок прошёл" value={String(d.summary.overdue)}
          tone={d.summary.overdue ? 'warning' : undefined} hint="без отметки о сдаче" />
        <MetricTile label="На этой неделе" value={String(d.summary.soon)} />
        <MetricTile label="Долг перед бюджетом"
          value={`${money.format(d.summary.budgetDebt)} ₽`}
          tone={d.summary.budgetDebt > 0 ? 'warning' : undefined} hint="счета 68 и 69" />
        <MetricTile label="Сальдо ЕНС" value={`${money.format(d.summary.enpBalance)} ₽`}
          hint="счёт 68.90" />
      </div>

      <p className="text-[11px] text-muted-foreground">{d.note}</p>

      <div className="flex gap-1">
        {([['tasks', 'Календарь'], ['enp', 'ЕНС и уведомления'],
           ['filed', 'Сдано']] as const).map(([k, label]) => (
          <button key={k} onClick={() => setTab(k)}
            className={cn('rounded-md px-2.5 py-1 text-xs',
              tab === k ? 'bg-muted font-medium' : 'text-muted-foreground hover:bg-muted/50')}>
            {label}
          </button>
        ))}
      </div>

      {tab === 'tasks' && (
        <TableCard note="Задачи бухгалтера из 1С: полтора месяца назад и всё, что впереди"
          head={<><Th>Срок</Th><Th>Что сделать</Th><Th>Период</Th><Th>Состояние</Th></>}>
          {d.tasks.map((t, i) => (
            <tr key={`${t.due}-${i}`} className="border-b last:border-0 hover:bg-muted/40">
              <td className="px-3 py-1.5 whitespace-nowrap tabular-nums">{t.due || '—'}</td>
              <td className="px-3 py-1.5">{t.title}</td>
              <td className="px-3 py-1.5 text-muted-foreground whitespace-nowrap">
                {t.period_kind || '—'}
              </td>
              <td className={cn('px-3 py-1.5 whitespace-nowrap text-[13px]',
                TASK_TONE[t.state] ?? 'text-muted-foreground')}>
                {t.state}{t.status && t.status !== 'Сдано' ? ` · ${t.status}` : ''}
              </td>
            </tr>
          ))}
        </TableCard>
      )}

      {tab === 'enp' && (
        <div className="space-y-4">
          {d.debtMonths?.length > 0 && (
            <TableCard note="Долг перед бюджетом на конец месяца — из помесячных срезов сальдо"
              head={<><Th>Месяц</Th><Th right>Должны на конец</Th></>}>
              {d.debtMonths.map((m) => (
                <tr key={m.month} className="border-b last:border-0">
                  <td className="px-3 py-1.5 whitespace-nowrap">{monthLabel(m.month)}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{money.format(m.amount)} ₽</td>
                </tr>
              ))}
            </TableCard>
          )}

          {d.debts.length > 0 && (
            <TableCard note="Сальдо счетов расчётов с бюджетом и фондами на последнюю дату"
              head={<><Th>Счёт</Th><Th>Налог</Th><Th right>Должны</Th></>}>
              {d.debts.map((x) => (
                <tr key={x.account} className="border-b last:border-0">
                  <td className="px-3 py-1.5 tabular-nums whitespace-nowrap">{x.account}</td>
                  <td className="px-3 py-1.5">{x.name}</td>
                  <td className={cn('px-3 py-1.5 text-right tabular-nums',
                    x.amount > 0 && 'font-medium')}>{money.format(x.amount)} ₽</td>
                </tr>
              ))}
            </TableCard>
          )}

          {d.notices.length > 0 && (
            <TableCard note="Уведомления об исчисленных суммах: состав и срок уплаты"
              head={<><Th>Дата</Th><Th>Номер</Th><Th>Налоги</Th><Th>Срок уплаты</Th>
                <Th right>Сумма</Th></>}>
              {d.notices.map((n) => (
                <tr key={`${n.number}-${n.date}`} className="border-b last:border-0">
                  <td className="px-3 py-1.5 whitespace-nowrap tabular-nums">{n.date}</td>
                  <td className="px-3 py-1.5 whitespace-nowrap">{n.number}</td>
                  <td className="px-3 py-1.5">{n.taxes || '—'}</td>
                  <td className="px-3 py-1.5 whitespace-nowrap tabular-nums">{n.due || '—'}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{money.format(n.amount)} ₽</td>
                </tr>
              ))}
            </TableCard>
          )}

          {d.enp.length > 0 && (
            <TableCard note="Начисления налогов на единый налоговый счёт"
              head={<><Th>Период</Th><Th>Налог</Th><Th>Срок уплаты</Th><Th right>Начислено</Th></>}>
              {d.enp.map((e, i) => (
                <tr key={`${e.period}-${i}`} className="border-b last:border-0">
                  <td className="px-3 py-1.5 whitespace-nowrap tabular-nums">{e.period}</td>
                  <td className="px-3 py-1.5">
                    {e.tax || '—'}{e.advance ? ' · аванс' : ''}
                  </td>
                  <td className="px-3 py-1.5 whitespace-nowrap tabular-nums">{e.due || '—'}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{money.format(e.amount)} ₽</td>
                </tr>
              ))}
            </TableCard>
          )}
        </div>
      )}

      {tab === 'filed' && (
        <TableCard note="Сданная отчётность: чем период закрыт перед государством"
          head={<><Th>Дата</Th><Th>Отчёт</Th><Th>Период</Th><Th>Подписан</Th></>}>
          {d.filed.map((f, i) => (
            <tr key={`${f.date}-${i}`} className="border-b last:border-0 hover:bg-muted/40">
              <td className="px-3 py-1.5 whitespace-nowrap tabular-nums">{f.date}</td>
              <td className="px-3 py-1.5">{f.title}</td>
              <td className="px-3 py-1.5 text-muted-foreground whitespace-nowrap">
                {f.period || '—'}
              </td>
              <td className="px-3 py-1.5 whitespace-nowrap tabular-nums text-muted-foreground">
                {f.signed || '—'}
              </td>
            </tr>
          ))}
        </TableCard>
      )}
    </div>
  )
}


/**
 * Письмо контрагенту по требованию: заготовка с адресом, темой и текстом.
 *
 * Реестр без письма — это список, который кто-то должен отработать «в другом
 * месте». Текст готовит бэкенд из самого требования (что просим, по какому
 * документу, к какому сроку), человек правит и отправляет. Факт обращения
 * остаётся в ленте требования.
 */
export function RequestLetterDialog({ companyId, requestId, onClose, onSent }: {
  companyId: string; requestId: string; onClose: () => void; onSent: () => void
}) {
  const [to, setTo] = useState('')
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')
  const q = useQuery({
    queryKey: ['books', 'request-letter', companyId, requestId],
    queryFn: () => getRequestLetter(companyId, requestId),
  })
  useEffect(() => {
    if (q.data) {
      setTo(q.data.to)
      setSubject(q.data.subject)
      setBody(q.data.body)
    }
  }, [q.data])

  const send = useMutation({
    mutationFn: () => sendRequestLetter(companyId, requestId, { to, subject, body }),
    onSuccess: () => { toast.success('Письмо отправлено'); onSent(); onClose() },
    onError: (e) => toast.error(`Не отправилось: ${(e as Error).message}`),
  })

  const d = q.data
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="text-base">
            Письмо контрагенту{d?.counterparty ? ` · ${d.counterparty}` : ''}
          </DialogTitle>
        </DialogHeader>
        {!d ? (
          <div className="py-6 text-sm text-muted-foreground">Готовим письмо…</div>
        ) : (
          <div className="space-y-3">
            {!d.canSend && (
              <div className="rounded-md border border-amber-500/40 bg-amber-500/5 px-3 py-2
                              text-[12px] text-amber-700 dark:text-amber-500">
                {d.why}
              </div>
            )}
            <div className="grid gap-2 sm:grid-cols-2">
              <label className="text-[12px] text-muted-foreground">
                Кому
                <input value={to} onChange={(e) => setTo(e.target.value)}
                  placeholder="адрес контрагента"
                  className="mt-1 h-8 w-full rounded-md border border-border bg-background
                             px-2.5 text-[13px] text-foreground outline-none" />
              </label>
              <label className="text-[12px] text-muted-foreground">
                От кого
                <input value={d.mailbox?.address ?? 'ящик не настроен'} readOnly
                  className="mt-1 h-8 w-full rounded-md border border-border bg-muted/40
                             px-2.5 text-[13px] text-muted-foreground outline-none" />
              </label>
            </div>
            <label className="block text-[12px] text-muted-foreground">
              Тема
              <input value={subject} onChange={(e) => setSubject(e.target.value)}
                className="mt-1 h-8 w-full rounded-md border border-border bg-background
                           px-2.5 text-[13px] text-foreground outline-none" />
            </label>
            <label className="block text-[12px] text-muted-foreground">
              Текст
              <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={11}
                className="mt-1 w-full rounded-md border border-border bg-background
                           px-2.5 py-2 text-[13px] text-foreground outline-none" />
            </label>

            {d.escalations.length > 0 && (
              <div className="text-[11px] text-muted-foreground">
                Уже обращались: {d.escalations.length} раз ·
                последнее {d.escalations[d.escalations.length - 1].at.slice(0, 10)}
              </div>
            )}

            <div className="flex justify-end gap-2 pt-1">
              <button onClick={onClose}
                className="h-8 rounded-md border border-border px-3 text-[13px] hover:bg-accent">
                Отмена
              </button>
              <button onClick={() => send.mutate()}
                disabled={!d.canSend || !to.trim() || send.isPending}
                className="h-8 rounded-md bg-primary px-3 text-[13px] text-primary-foreground
                           hover:bg-primary/90 disabled:opacity-40">
                {send.isPending ? 'Отправляем…' : 'Отправить'}
              </button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
