/**
 * «Закрытие месяца» — рабочий стол сотрудника, который собирает документы.
 *
 * Один экран на весь месяц: что мы должны были собрать, что собрали, чем
 * закрыли остальное. Каждая расчётная сумма подписана методом — сумма без
 * пометки происхождения выглядит подтверждённой, и расхождение всплывает,
 * когда период уже отдан в бухгалтерию.
 *
 * Кнопка «Закрыть месяц» гаснет с ПРИЧИНОЙ, а не просто серым: человек должен
 * видеть, чего не хватает, а не гадать.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { AlertTriangle, CalendarClock, Loader2, Lock, RefreshCw } from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import { fmtN } from './balanceCalc'
import { OpsPeriodsScale } from './OpsPeriodsScale'
import { OpsCalendarBlock } from './OpsCalendarBlock'
import { OpsDocDialog } from './OpsDocDialog'
import {
  closeOpsPeriod, correctOpsCharge, getOpsClosing,
  type OpsCharge, type OpsChargeBasis, type OpsClosing, type OpsPeriodStatus,
} from '@/services/opsService'

/** Откуда цифра. Метка стоит рядом с суммой, иначе расчётная неотличима от факта. */
const BASIS_META: Record<OpsChargeBasis, { label: string; hint: string; tone: string }> = {
  document:    { label: 'док',     hint: 'Сумма из документа контрагента', tone: 'text-emerald-600 dark:text-emerald-400' },
  contract:    { label: 'договор', hint: 'Постоянная сумма по условию договора', tone: 'text-foreground/70' },
  metered:     { label: 'счётчик', hint: 'Объём по прибору учёта × тариф', tone: 'text-foreground/70' },
  metered_prev:{ label: 'счётчик~', hint: 'Тариф текущий, объём — последний известный: реестр закупки заполняется с лагом', tone: 'text-amber-600 dark:text-amber-400' },
  prev_period: { label: 'пр. мес', hint: 'Расчёт по сумме предыдущего месяца', tone: 'text-amber-600 dark:text-amber-400' },
  average:     { label: 'среднее', hint: 'Расчёт по среднему за 3 закрытых месяца', tone: 'text-amber-600 dark:text-amber-400' },
  correction:  { label: 'коррект', hint: 'Корректировка за прошлый закрытый период', tone: 'text-blue-600 dark:text-blue-400' },
  manual:      { label: 'вручную', hint: 'Сумма введена человеком', tone: 'text-foreground/70' },
  none:        { label: 'нет базы', hint: 'Ни суммы в договоре, ни истории для расчёта', tone: 'text-red-600 dark:text-red-400' },
}

const STATUS_META: Record<OpsPeriodStatus, { label: string; hint: string }> = {
  open:       { label: 'Месяц идёт',   hint: 'Период ещё не кончился, ожидания разворачиваются' },
  collecting: { label: 'Сбор',         hint: 'Месяц кончился, ждём документы от контрагентов' },
  review:     { label: 'Разбор',       hint: 'Срок предоставления вышел — разобрать оставшееся' },
  closed:     { label: 'Закрыт',       hint: 'Суммы зафиксированы, поздний документ идёт корректировкой' },
  reopened:   { label: 'Открыт заново', hint: 'Период открыт повторно, причина сохранена' },
}

const CHARGE_STATUS_LABEL: Record<string, string> = {
  expected: 'ждём документ', received: 'документ получен', matched: 'закрыто документом',
  disputed: 'оспаривается', accrued: 'закрыто расчётом', corrected: 'скорректировано',
  waived: 'не начисляем',
}

const money = (v: number | null | undefined) =>
  v === null || v === undefined ? '—' : fmtN(Math.round(v))

const prevMonth = () => {
  const d = new Date()
  d.setDate(1)
  d.setMonth(d.getMonth() - 1)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`
}

const monthLabel = (period: string) => {
  const names = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь',
    'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь']
  return `${names[Number(period.slice(5, 7)) - 1]} ${period.slice(0, 4)}`
}

export function OpsClosingPanel() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const [period, setPeriod] = useState(prevMonth)
  const [scope, setScope] = useState<'location' | 'company' | 'all'>('location')
  const [onlyOpen, setOnlyOpen] = useState(false)

  const q = useQuery({
    queryKey: ['ops-closing', companyId, period, scope],
    queryFn: () => getOpsClosing(companyId!, period, scope),
    enabled: !!companyId,
  })

  const close = useMutation({
    mutationFn: (force: boolean) => closeOpsPeriod(companyId!, period, force),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['ops-closing', companyId] }),
  })

  const correct = useMutation({
    mutationFn: (chargeId: string) => correctOpsCharge(companyId!, chargeId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['ops-closing', companyId] }),
  })

  if (q.isLoading) {
    return <div className="flex justify-center py-16">
      <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
    </div>
  }
  if (q.isError) {
    return <div className="p-6 text-sm text-red-600 dark:text-red-400">
      Не удалось загрузить реестр закрытия. Обновите страницу или смените период.
    </div>
  }

  const d = q.data as OpsClosing
  const rows = onlyOpen
    ? d.charges.filter((c) => c.status === 'expected' || c.varianceClass === 'material')
    : d.charges
  const isClosed = d.status === 'closed'
  // Причина, по которой закрывать рано. Гасим кнопку с текстом, а не молча.
  const blockReason = d.counters.noBasis > 0
    ? `${d.counters.noBasis} строк нечем закрыть: нет ни суммы в договоре, ни истории`
    : null

  return (
    <div className="space-y-4 p-4">
      {/* Состояние ВСЕХ периодов сразу: договоры переходящие, и один месяц в
          отрыве от соседних не отвечает на вопрос «где у меня дыры». */}
      <OpsPeriodsScale current={period} onPick={setPeriod} />

      <PeriodBar period={period} onPeriod={setPeriod} status={d.status}
        closedAt={d.closedAt} isClosed={isClosed}
        blockReason={blockReason}
        pending={close.isPending}
        onClose={(force) => close.mutate(force)}
        onRefresh={() => qc.invalidateQueries({ queryKey: ['ops-closing', companyId] })} />

      {close.data && !close.data.ok && (
        <Card className="border-amber-500/40">
          <CardContent className="space-y-1 pt-4 text-sm">
            <div className="flex items-center gap-2 font-medium text-amber-600 dark:text-amber-400">
              <AlertTriangle className="h-4 w-4" />Месяц не закрыт
            </div>
            <p className="text-muted-foreground">{close.data.message}</p>
            <p className="text-xs text-muted-foreground/80">
              Заполните суммы в условиях договоров либо закройте месяц принудительно —
              тогда эти строки уйдут как «не начисляем», а не нулём.
            </p>
          </CardContent>
        </Card>
      )}

      <Counters data={d} />

      <div className="flex flex-wrap items-center gap-2">
        <Segmented value={scope} onChange={setScope} options={[
          { v: 'location', label: 'По объектам' },
          { v: 'company', label: 'Общие затраты' },
          { v: 'all', label: 'Всё вместе' },
        ]} />
        <label className="ml-auto flex cursor-pointer items-center gap-2 text-sm text-muted-foreground">
          <input type="checkbox" checked={onlyOpen} onChange={(e) => setOnlyOpen(e.target.checked)}
            className="h-4 w-4 rounded border-border" />
          только незакрытое и существенные расхождения
        </label>
      </div>

      <ChargesTable rows={rows} isClosed={isClosed} period={period}
        onCorrect={(id) => correct.mutate(id)} correcting={correct.isPending} />

      <div className="space-y-2">
        <div className="text-sm font-medium">Что предстоит собрать</div>
        <OpsCalendarBlock />
      </div>

      <Gaps blocked={d.blocked} contracts={d.contractsWithoutTerms} />
    </div>
  )
}

/* ── Шапка периода ─────────────────────────────────────────────────────── */

function PeriodBar({ period, onPeriod, status, closedAt, isClosed, blockReason,
  pending, onClose, onRefresh }: {
  period: string; onPeriod: (v: string) => void; status: OpsPeriodStatus
  closedAt: string | null; isClosed: boolean; blockReason: string | null
  pending: boolean; onClose: (force: boolean) => void; onRefresh: () => void
}) {
  const meta = STATUS_META[status] ?? STATUS_META.open
  return (
    <div data-zone="Период и его состояние"
      className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-card px-3 py-2">
      <CalendarClock className="h-4 w-4 text-primary" />
      <input type="month" value={period.slice(0, 7)}
        onChange={(e) => onPeriod(`${e.target.value}-01`)}
        className="h-9 rounded-md border border-border bg-background px-2 text-sm" />
      <span className="text-sm font-medium">{monthLabel(period)}</span>
      <Badge variant="outline" title={meta.hint} className="text-xs">{meta.label}</Badge>
      {closedAt && (
        <span className="text-xs text-muted-foreground">закрыт {closedAt.slice(0, 10)}</span>
      )}
      <div className="ml-auto flex items-center gap-2">
        <Button variant="ghost" size="sm" onClick={onRefresh} title="Пересобрать ожидания">
          <RefreshCw className="h-3.5 w-3.5" />
        </Button>
        {isClosed ? (
          <span className="inline-flex items-center gap-1.5 text-sm text-muted-foreground">
            <Lock className="h-3.5 w-3.5" />месяц закрыт
          </span>
        ) : (
          <>
            {blockReason && (
              <span className="max-w-md text-xs text-amber-600 dark:text-amber-400">{blockReason}</span>
            )}
            <Button size="sm" disabled={pending || !!blockReason}
              title={blockReason ?? 'Незакрытое будет доведено расчётом'}
              onClick={() => onClose(false)}>
              {pending && <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />}Закрыть месяц
            </Button>
            {blockReason && (
              <Button size="sm" variant="outline" disabled={pending}
                title="Строки без базы уйдут как «не начисляем» — не нулём"
                onClick={() => onClose(true)}>Закрыть всё равно</Button>
            )}
          </>
        )}
      </div>
    </div>
  )
}

/* ── Четыре счётчика ───────────────────────────────────────────────────── */

function Counters({ data }: { data: OpsClosing }) {
  const c = data.counters
  const cells = [
    { label: 'Ждём документ', count: c.expected.count, gross: c.expected.gross,
      tone: c.expected.count ? 'text-amber-600 dark:text-amber-400' : '' },
    { label: 'Закрыто документами', count: c.received.count, gross: c.received.gross,
      tone: 'text-emerald-600 dark:text-emerald-400' },
    { label: 'Закрыто расчётом', count: c.estimated.count, gross: c.estimated.gross,
      tone: c.estimated.count ? 'text-amber-600 dark:text-amber-400' : '' },
    { label: 'Расхождения', count: c.variance.count, gross: c.variance.gross,
      tone: c.variance.count ? 'text-red-600 dark:text-red-400' : '' },
  ]
  return (
    <div data-zone="Итоги месяца" className="grid grid-cols-2 gap-3 md:grid-cols-4">
      {cells.map((x) => (
        <Card key={x.label}><CardContent className="pt-4">
          <div className="text-xs text-muted-foreground">{x.label}</div>
          <div className={`text-xl font-semibold tabular-nums ${x.tone}`}>{fmtN(x.count)}</div>
          <div className="text-xs tabular-nums text-muted-foreground">{money(x.gross)} ₽</div>
        </CardContent></Card>
      ))}
    </div>
  )
}

/* ── Реестр строк ──────────────────────────────────────────────────────── */

function ChargesTable({ rows, isClosed, period, onCorrect, correcting }: {
  rows: OpsCharge[]; isClosed: boolean; period: string
  onCorrect: (id: string) => void; correcting: boolean
}) {
  if (rows.length === 0) {
    return <Card><CardContent className="py-10 text-center text-sm text-muted-foreground">
      За этот месяц ожиданий нет. Либо условия договоров ещё не заведены, либо
      период вне сроков их действия.
    </CardContent></Card>
  }
  return (
    <Card><CardContent className="p-0">
      {/* Узкий экран: карточки. Таблица на 10 колонок в телефон не помещается,
          а горизонтальная прокрутка прячет ровно то, ради чего пришли — сумму. */}
      <div className="divide-y divide-border sm:hidden">
        {rows.map((r) => (
          <div key={r.id} className="space-y-1 p-3 text-sm">
            <div className="flex items-start justify-between gap-2">
              <span className="font-medium">{r.locationName ?? 'Общая затрата компании'}</span>
              <span className="shrink-0 tabular-nums">{money(r.expectedGross)} ₽</span>
            </div>
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
              <span>{r.costItemLabel}</span>
              {r.counterpartyName && <span>· {r.counterpartyName}</span>}
              <BasisTag basis={r.expectedBasis} />
              <StatusTag row={r} />
              {!r.docId && (
                <OpsDocDialog charge={r} period={period}>
                  <button type="button" className="ml-auto rounded border border-border px-2 py-1 text-xs">
                    Документ
                  </button>
                </OpsDocDialog>
              )}
            </div>
          </div>
        ))}
      </div>

      <div className="hidden sm:block">
        <Table>
          <TableHeader><TableRow>
            <TableHead>Объект</TableHead>
            <TableHead>Статья</TableHead>
            <TableHead>Контрагент</TableHead>
            <TableHead className="text-right">Ожидали</TableHead>
            <TableHead>Чем</TableHead>
            <TableHead className="text-right">Документ</TableHead>
            <TableHead className="text-right">Расхождение</TableHead>
            <TableHead>Срок</TableHead>
            <TableHead>Состояние</TableHead>
            <TableHead />
          </TableRow></TableHeader>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.id} className={r.seq > 0 ? 'bg-blue-500/5' : undefined}>
                <TableCell className="max-w-[220px] truncate font-medium"
                  title={r.locationName ?? undefined}>
                  {r.locationName ?? <span className="text-muted-foreground">вся компания</span>}
                </TableCell>
                <TableCell className="whitespace-nowrap">
                  {r.costItemLabel}
                  {r.seq > 0 && (
                    <span className="ml-1 text-xs text-blue-600 dark:text-blue-400"
                      title={r.correctionReason ?? undefined}>корректировка</span>
                  )}
                </TableCell>
                <TableCell className="max-w-[200px] truncate"
                  title={r.counterpartyName ?? undefined}>
                  {r.counterpartyName ?? '—'}
                </TableCell>
                <TableCell className="text-right tabular-nums">{money(r.expectedGross)}</TableCell>
                <TableCell><BasisTag basis={r.expectedBasis} /></TableCell>
                <TableCell className="text-right tabular-nums">{money(r.actualGross)}</TableCell>
                <TableCell className={`text-right tabular-nums ${
                  r.varianceClass === 'material' ? 'text-red-600 dark:text-red-400'
                    : r.varianceClass === 'minor' ? 'text-amber-600 dark:text-amber-400' : ''}`}>
                  {r.variance ? money(r.variance) : '—'}
                </TableCell>
                <TableCell className={`whitespace-nowrap text-xs ${
                  r.overdue ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground'}`}>
                  {r.docDueOn ?? '—'}
                  {r.overdue && ' · просрочен'}
                </TableCell>
                <TableCell className="whitespace-nowrap text-xs"><StatusTag row={r} /></TableCell>
                <TableCell className="text-right">
                  <div className="flex items-center justify-end gap-1">
                    {/* Документа нет — главное действие строки: завести и закрыть
                        им ожидание. Всё остальное вторично. */}
                    {!r.docId && (
                      <OpsDocDialog charge={r} period={period}>
                        <Button size="sm" variant="outline" className="h-7 text-xs"
                          title="Завести документ контрагента и закрыть им ожидание">
                          Документ
                        </Button>
                      </OpsDocDialog>
                    )}
                    {/* Корректировку предлагаем только там, где она нужна: закрытый
                        период и расхождение сверх округления. */}
                    {isClosed && (r.varianceClass === 'minor' || r.varianceClass === 'material')
                      && r.status !== 'corrected' && (
                      <Button size="sm" variant="outline" className="h-7 text-xs" disabled={correcting}
                        title="Провести разницу отдельной строкой в текущем открытом месяце"
                        onClick={() => onCorrect(r.id)}>Корректировка</Button>
                    )}
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </CardContent></Card>
  )
}

function BasisTag({ basis }: { basis: OpsChargeBasis | null }) {
  const meta = BASIS_META[basis ?? 'none']
  return <span className={`text-xs ${meta.tone}`} title={meta.hint}>{meta.label}</span>
}

function StatusTag({ row }: { row: OpsCharge }) {
  const label = CHARGE_STATUS_LABEL[row.status] ?? row.status
  const tone = row.status === 'matched' ? 'text-emerald-600 dark:text-emerald-400'
    : row.status === 'waived' ? 'text-muted-foreground'
    : row.overdue ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground'
  return <span className={`text-xs ${tone}`}>{label}</span>
}

/* ── Чего система ещё не знает ─────────────────────────────────────────── */

function Gaps({ blocked, contracts }: {
  blocked: OpsClosing['blocked']; contracts: OpsClosing['contractsWithoutTerms']
}) {
  if (blocked.length === 0 && contracts.length === 0) return null
  return (
    <Card className="border-amber-500/30">
      <CardContent className="space-y-2 pt-4">
        <div className="flex items-center gap-2 text-sm font-medium">
          <AlertTriangle className="h-4 w-4 text-amber-500" />
          Обязательства, которых нет в реестре
        </div>
        <p className="text-xs text-muted-foreground">
          Реестр выше отвечает, чего не прислали по известным обязательствам. Это —
          вторая половина правды: договоры, о которых система ещё не знает, и потому
          молчит о них вдвойне.
        </p>
        {blocked.length > 0 && (
          <p className="text-sm">
            Условий развёрнуто не полностью: <b>{blocked.length}</b>
            {' '}— {blocked[0].reason}.
          </p>
        )}
        {contracts.length > 0 && (
          <p className="text-sm">
            Действующих договоров аренды и энергоснабжения без условий начисления:
            {' '}<b>{contracts.length}</b>.
          </p>
        )}
      </CardContent>
    </Card>
  )
}

function Segmented<T extends string>({ value, onChange, options }: {
  value: T; onChange: (v: T) => void; options: Array<{ v: T; label: string }>
}) {
  return (
    <div className="inline-flex rounded-md border border-border bg-muted/60 p-0.5">
      {options.map((o) => (
        <button key={o.v} type="button" onClick={() => onChange(o.v)}
          className={`rounded-[5px] px-3 py-1.5 text-sm transition-colors ${
            value === o.v ? 'bg-primary text-primary-foreground'
              : 'text-muted-foreground hover:text-foreground'}`}>
          {o.label}
        </button>
      ))}
    </div>
  )
}
