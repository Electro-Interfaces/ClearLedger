/**
 * «Периметр» → «Наличные» — расчёты мимо кассы компании.
 *
 * Четвёртая грань периметра и единственная, где считаются деньги. У предпринимателя
 * часть расчётов идёт наличными: оплатили работу частного лица, дали знакомому в долг,
 * вложили свои средства в закупку, забрали выручку на личные нужды. В бухгалтерии этих
 * движений нет, а помнить о них надо — прежде всего кто кому остался должен.
 *
 * Главное правило экранов: **долг человека — это не «выдано минус получено»**. Оплата
 * выполненной работы долгом не становится, сколько её ни выдай. Должен человек ровно на
 * непогашенные займы, и возврат привязывается к своей выдаче, а не уменьшает общий счёт.
 */
import { Fragment, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, Plus, Trash2 } from 'lucide-react'

import { useFilters } from '@/contexts/FilterContext'
import { toast } from 'sonner'

import { QueryError } from '@/components/common/QueryError'
import { Card, CardContent } from '@/components/ui/card'
import { MetricTile } from '@/components/ui/metric-tile'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { ConfirmActionDialog } from '@/components/common/ConfirmActionDialog'
import { cn } from '@/lib/utils'
import {
  checkCash, createCash, deleteCash, getCashDicts, getCashJournal, getCashLoans,
  getCashPapers, getCommitments, getPerimeterPeople,
  parseQuick, updateCash,
  type CashDicts, type CashIn, type CashMove,
} from '@/services/perimeterService'
import { PerimeterExport } from './perimeterShared'
import { Loading, TableCard, Th } from './OfficePanels'
import { SearchInput, Tabs, money, num , Td } from './officeShared'

/** Пустое подтверждение — не придирка: у такого расчёта нет ни доказательства, ни защиты. */
const proofTone = (proof: string) =>
  proof === 'none' ? 'text-amber-700 dark:text-amber-400' : 'text-muted-foreground'

const today = () => new Date().toISOString().slice(0, 10)

/** Виды, которые смотрят чаще прочих: они и остаются табами. */
const QUICK_KINDS_TABS = ['work', 'advance', 'loan', 'bonus']

/** Виды, закрывающие ранее выданное: каждый обязан назвать, что именно закрывает. */
const CLOSING = ['repayment', 'report', 'offset', 'writeoff']

const EMPTY_CASH = (): CashIn => ({
  personName: '', amount: 0, happenedOn: today(), direction: 'out', kind: 'work',
  proof: 'none', purse: 'owner', personKind: 'individual', formalized: false,
})

/* ────────────────────────────────────────────────────────────── */
/*                           Журнал                               */
/* ────────────────────────────────────────────────────────────── */

export function CashJournalScreen({ companyId }: { companyId: string }) {
  const qc = useQueryClient()
  const { period } = useFilters()
  const [kind, setKind] = useState('')
  const [search, setSearch] = useState('')
  const [edit, setEdit] = useState<{ id: string | null; body: CashIn } | null>(null)
  // Быстрый ввод: строка вместо формы. Трение записи — главная причина, по которой
  // такие реестры бросают, поэтому обычный путь начинается здесь.
  const [quick, setQuick] = useState('')
  const parse = useMutation({
    mutationFn: (line: string) => parseQuick(companyId, line),
    onSuccess: (draft) => {
      const { understood: _u, missing: _m, kindLabel: _k, ...body } = draft
      setEdit({ id: null, body: body as CashIn })
      setQuick('')
      if (draft.understood.length) toast.info(`Понял: ${draft.understood.join(', ')}`)
    },
    onError: (e: Error) => toast.error(e.message),
  })

  const dicts = useQuery({
    queryKey: ['perimeter', 'cash-dicts', companyId],
    queryFn: () => getCashDicts(companyId),
    enabled: !!companyId,
  })
  const q = useQuery({
    queryKey: ['perimeter', 'cash', companyId, period.from, period.to, kind],
    queryFn: () => getCashJournal(companyId, {
      from: period.from, to: period.to, kind: kind || undefined,
    }),
    enabled: !!companyId,
  })
  const loans = useQuery({
    queryKey: ['perimeter', 'cash-loans', companyId],
    queryFn: () => getCashLoans(companyId),
    enabled: !!companyId,
  })
  // Подсказка имён: список наполняется сам, карточка заводится при первом расчёте.
  const people = useQuery({
    queryKey: ['perimeter', 'people', companyId],
    queryFn: () => getPerimeterPeople(companyId),
    enabled: !!companyId,
  })
  const commitments = useQuery({
    queryKey: ['perimeter', 'commitments', companyId],
    queryFn: () => getCommitments(companyId),
    enabled: !!companyId,
  })

  const save = useMutation({
    mutationFn: (v: { id: string | null; body: CashIn }) =>
      v.id ? updateCash(companyId, v.id, v.body) : createCash(companyId, v.body),
    onSuccess: () => {
      setEdit(null)
      qc.invalidateQueries({ queryKey: ['perimeter'] })
    },
  })
  const remove = useMutation({
    mutationFn: (id: string) => deleteCash(companyId, id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['perimeter'] }),
    onError: (e: Error) => toast.error(e.message),
  })

  const rows = useMemo(() => {
    const all = q.data?.rows ?? []
    const s = search.trim().toLowerCase()
    if (!s) return all
    return all.filter((r) => `${r.person} ${r.purpose ?? ''} ${r.note ?? ''}`
      .toLowerCase().includes(s))
  }, [q.data, search])

  if (q.isError) {
    return <div className="p-4">
      <QueryError message="Не удалось загрузить журнал наличных" onRetry={() => q.refetch()} />
    </div>
  }
  const d = q.data

  return (
    <div className="p-4 space-y-4">
      {d && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <MetricTile label="Выдано за период" value={`${money.format(d.out)} ₽`}
            hint={`${num.format(d.count)} операций`} />
          <MetricTile label="Получено за период" value={`${money.format(d.in)} ₽`}
            hint="возвраты, взносы, поступления" />
          <MetricTile label="Из личных средств" value={`${money.format(d.ownerOut)} ₽`}
            hint={d.ownerIn ? `вернулось ${money.format(d.ownerIn)} ₽` : 'вложено собственником'} />
          <MetricTile label="Выдано сотрудникам" value={`${money.format(d.employeeOut)} ₽`}
            hint="подотчёт, проезд, премии" />
          <MetricTile label="Ждёт документов" value={`${money.format(d.awaitsPapers)} ₽`}
            hint={`${num.format(d.awaitsPapersCount)} операций без документов`}
            tone={d.awaitsPapersCount ? 'warning' : undefined} />
          <MetricTile label="Без подтверждения" value={`${money.format(d.noProof)} ₽`}
            hint={`${num.format(d.noProofCount)} операций без бумаги`}
            tone={d.noProofCount ? 'warning' : undefined} />
        </div>
      )}

      <Card>
        <CardContent className="p-3">
          <div className="flex flex-wrap items-center gap-2">
            <input
              className="flex-1 min-w-64 rounded-md border bg-background px-3 py-2 text-sm"
              value={quick} aria-label="Быстрый ввод операции одной строкой"
              placeholder="5000 Иванову за монтаж наличными"
              onChange={(e) => setQuick(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && quick.trim()) parse.mutate(quick)
              }} />
            <Button size="sm" variant="outline" disabled={!quick.trim() || parse.isPending}
              onClick={() => parse.mutate(quick)}>
              {parse.isPending ? 'Разбираем…' : 'Разобрать'}
            </Button>
          </div>
          <p className="text-[11px] text-muted-foreground mt-1.5">
            Одной строкой: сумма, кому, за что. Понимает «вчера», «в долг», «под отчёт»,
            «из кассы», дату вида 12.08. Разобранное открывается формой — вы проверяете и
            сохраняете.
          </p>
        </CardContent>
      </Card>

      <div className="flex flex-wrap items-center gap-2 justify-between">
        {/* Видов операций одиннадцать — табами они встают в две строки и шумят.
            Часто нужны три-четыре, остальные выбираются списком. */}
        <div className="flex items-center gap-2">
          <Tabs value={QUICK_KINDS_TABS.includes(kind) ? kind : ''} onChange={setKind}
            label="разрез журнала" items={[
              { key: '', label: 'Все' },
              ...(dicts.data?.kinds ?? [])
                .filter((k) => QUICK_KINDS_TABS.includes(k.key))
                .map((k) => ({ key: k.key, label: k.label })),
            ]} />
          <select className="rounded-md border bg-background px-2.5 py-1.5 text-sm"
            aria-label="Другие виды операций"
            value={QUICK_KINDS_TABS.includes(kind) ? '' : kind}
            onChange={(e) => setKind(e.target.value)}>
            <option value="">Другие виды…</option>
            {(dicts.data?.kinds ?? [])
              .filter((k) => !QUICK_KINDS_TABS.includes(k.key))
              .map((k) => <option key={k.key} value={k.key}>{k.label}</option>)}
          </select>
        </div>
        <div className="flex items-center gap-2">
          <SearchInput value={search} onChange={setSearch} label="Поиск по операциям"
            placeholder="Кто или за что" />
          <PerimeterExport companyId={companyId} title="Наличные расчёты"
            columns={[
              { header: 'Дата', key: 'happenedOn', width: 13 },
              { header: 'Направление', key: 'directionLabel', width: 13 },
              { header: 'Вид', key: 'kindLabel', width: 24 },
              { header: 'С кем', key: 'person', width: 30 },
              { header: 'За что', key: 'purpose', width: 44 },
              { header: 'Сумма', key: 'amount', width: 16, money: true },
              { header: 'Чьи деньги', key: 'purseLabel', width: 18 },
              { header: 'Подтверждение', key: 'proofLabel', width: 16 },
              { header: 'Осталось', key: 'rest', width: 16, money: true },
            ]}
            rows={rows} />
          <Button size="sm" onClick={() => setEdit({ id: null, body: EMPTY_CASH() })}>
            <Plus className="w-4 h-4 mr-1" />Записать
          </Button>
        </div>
      </div>

      {!d ? <Loading /> : !rows.length ? (
        <Card>
          <CardContent className="p-4 text-sm space-y-2">
            <div className="font-medium">
              {kind || search.trim()
                ? 'Под отбор ничего не подходит'
                : `За период ${period.from} — ${period.to} записей нет`}
            </div>
            {(kind || search.trim()) && (
              <p className="text-muted-foreground">
                Снимите отбор по виду или очистите поиск. Период рабочей области тоже
                сужает список: операции более ранних месяцев видны при его смене.
              </p>
            )}
            <p className="text-muted-foreground">
              Здесь ведут расчёты, которых нет в кассе компании: оплату работ частных лиц,
              займы знакомым и от знакомых, покупки на личные деньги собственника,
              изъятие выручки на личные нужды. У каждой операции видно, чьи это были
              деньги и чем расчёт подтверждён.
            </p>
            <p className="text-muted-foreground">
              Смысл журнала не в отчётности, а в памяти: через полгода никто не вспомнит,
              кому и за что отдали, и особенно — сколько осталось получить обратно.
            </p>
          </CardContent>
        </Card>
      ) : (
        <TableCard note="Период берётся из фильтра рабочей области. «Осталось» показано у займов и подотчёта"
          head={<><Th>Дата</Th><Th>С кем и за что</Th><Th>Вид</Th>
            <Th>Чем подтверждено</Th><Th right>Сумма</Th><Th right>Осталось</Th>
            <Th right> </Th></>}>
          {rows.map((r) => (
            <tr key={r.id} className={cn('border-b last:border-0 hover:bg-muted/40',
              r.overdue && 'bg-destructive/5')}>
              <Td>
                <div className="tabular-nums">{r.happenedOn}</div>
                <div className="text-[11px] text-muted-foreground">{r.directionLabel}</div>
              </Td>
              <Td>
                <button className="text-left hover:underline"
                  onClick={() => setEdit({ id: r.id, body: toCashForm(r) })}>
                  {r.person}
                </button>
                {r.purpose && (
                  <div className="text-[11px] text-muted-foreground">{r.purpose}</div>
                )}
              </Td>
              <Td muted>
                <div>{r.kindLabel}</div>
                <div className="text-[11px]">{r.personKindLabel} · {r.purseLabel}</div>
              </Td>
              <Td>
                <span className={cn('text-sm', proofTone(r.proof))}>{r.proofLabel}</span>
                {r.formalized ? (
                  <div className="text-[11px] text-emerald-700 dark:text-emerald-400">
                    проведено{r.formalizedOn ? ` ${r.formalizedOn}` : ''}
                  </div>
                ) : r.awaitsPapers ? (
                  <div className="text-[11px] text-amber-700 dark:text-amber-400">ждёт документов</div>
                ) : null}
              </Td>
              <Td right>
                <span className={r.direction === 'in' ? 'text-emerald-700 dark:text-emerald-400' : undefined}>
                  {r.direction === 'in' ? '+' : '−'}{money.format(r.amount)} ₽
                </span>
              </Td>
              <Td right>
                {r.rest === null ? '—' : (
                  <>
                    <div>{money.format(r.rest)} ₽</div>
                    {r.dueOn && (
                      <div className={cn('text-[11px] tabular-nums',
                        r.overdue ? 'text-destructive' : 'text-muted-foreground')}>
                        до {r.dueOn}
                      </div>
                    )}
                  </>
                )}
              </Td>
              <Td right>
                <ConfirmActionDialog
                  destructive
                  title="Удалить операцию?"
                  description={<>{r.kindLabel} от {r.happenedOn} — {r.person},{' '}
                    {money.format(r.amount)} ₽. Операция исчезнет насовсем; если по ней
                    есть возвраты или отчёты, сначала удалите их.</>}
                  confirmLabel="Удалить"
                  onConfirm={() => remove.mutate(r.id)}
                  trigger={
                    <Button variant="ghost" size="icon-sm"
                      aria-label={`Удалить операцию: ${r.person}, ${r.amount} ₽`}
                      className="text-muted-foreground hover:text-destructive">
                      <Trash2 className="w-4 h-4" />
                    </Button>
                  } />
              </Td>
            </tr>
          ))}
        </TableCard>
      )}

      {remove.isError && (
        <p className="text-sm text-destructive">
          {String((remove.error as Error).message)}
        </p>
      )}

      {!!d?.byKind.length && (
        <TableCard note="Куда уходили и откуда приходили наличные за период"
          head={<><Th>Вид</Th><Th right>Операций</Th><Th right>Выдано</Th><Th right>Получено</Th></>}>
          {d.byKind.map((k) => (
            <tr key={k.key} className="border-b last:border-0">
              <Td>{k.label}</Td>
              <Td right muted>{num.format(k.count)}</Td>
              <Td right>{k.out ? `${money.format(k.out)} ₽` : '—'}</Td>
              <Td right>{k.in ? `${money.format(k.in)} ₽` : '—'}</Td>
            </tr>
          ))}
        </TableCard>
      )}

      {edit && dicts.data && (
        <CashDialog
          companyId={companyId}
          value={edit.body}
          isNew={!edit.id}
          dicts={dicts.data}
          loans={(loans.data?.rows ?? []).filter((l) => (l.rest ?? 0) > 0.01)}
          people={(people.data?.rows ?? []).filter((p) => p.isActive)}
          commitments={(commitments.data?.rows ?? [])
            .filter((c) => c.status === 'active' && c.form === 'money')}
          saving={save.isPending}
          error={save.error ? String((save.error as Error).message) : null}
          onChange={(body) => setEdit({ ...edit, body })}
          onClose={() => setEdit(null)}
          onSave={() => save.mutate(edit)}
        />
      )}
    </div>
  )
}

const toCashForm = (r: CashMove): CashIn => ({
  personName: r.person, amount: r.amount, happenedOn: r.happenedOn,
  direction: r.direction, kind: r.kind, purpose: r.purpose, proof: r.proof,
  purse: r.purse, parentId: r.parentId, recordId: r.recordId,
  commitmentId: r.commitmentId, dueOn: r.dueOn,
  acknowledgedOn: r.acknowledgedOn, acknowledgedBy: r.acknowledgedBy,
  note: r.note, counterpartyId: r.counterpartyId,
  // Эти три поля терялись при правке: «кто это» сбрасывалось на частное лицо, а
  // проведённая премия возвращалась в очередь на оформление. Форма отправляет весь
  // объект целиком, поэтому пропущенное поле означает не «не менять», а «стереть».
  personKind: r.personKind, formalized: r.formalized,
  formalizedOn: r.formalizedOn, formalizedBy: r.formalizedBy,
})

function Field({ label, hint, children }: {
  label: string; hint?: string; children: React.ReactNode
}) {
  return (
    <label className="block space-y-1">
      <span className="text-[11px] uppercase tracking-wider text-muted-foreground">{label}</span>
      {children}
      {hint && <span className="block text-[11px] text-muted-foreground">{hint}</span>}
    </label>
  )
}

const inputCls = 'w-full rounded-md border bg-background px-2.5 py-1.5 text-sm'

function CashDialog({
  companyId, value, isNew, dicts, loans, people, commitments, saving, error, onChange,
  onClose, onSave,
}: {
  companyId: string
  value: CashIn
  isNew: boolean
  dicts: CashDicts
  /** Непогашенные займы и выдачи: к ним привязывается возврат или отчёт. */
  loans: CashMove[]
  /** Кого уже знаем: подсказка, а не ограничение — новое имя вводится свободно. */
  people: { name: string; kindLabel: string; role: string | null }[]
  /** Денежные регулярные обязательства: выплата по ним закроет период отметкой. */
  commitments: {
    id: string; person: string; title: string; amount: number | null
    periods: { periodStart: string; label: string; outcome: string }[]
  }[]
  saving: boolean
  error: string | null
  onChange: (v: CashIn) => void
  onClose: () => void
  onSave: () => void
}) {
  const set = (patch: Partial<CashIn>) => onChange({ ...value, ...patch })
  const parentDirection = loans.find((l) => l.id === value.parentId)?.direction ?? 'out'
  // Предупреждения считает сервер: пороги живут в настройках компании, и вторая копия
  // правил во фронте разошлась бы с ними молча.
  const warn = useQuery({
    queryKey: ['perimeter', 'cash-check', companyId, value.kind, value.amount,
               value.proof, value.dueOn, value.personKind],
    queryFn: () => checkCash(companyId, value),
    enabled: !!value.amount,
  })
  // Закрывающие виды: каждый из них гасит конкретную выдачу и обязан её назвать.
  // «Списание» и «Взаимозачёт» стояли в списке видов, но выбор выдачи для них не
  // показывался, а привязка обнулялась при переключении — сохранить их было нельзя.
  const isClosing = CLOSING.includes(value.kind)
  const isRepayment = isClosing
  const isLoan = value.kind === 'loan'
  // Остаток есть у займа и подотчёта: и то и другое чем-то закрывается.
  const isOpen = isLoan || value.kind === 'advance'
  // Что учёт в принципе принимает документами. Оплату частнику наличными и заём
  // знакомому он не примет, и предлагать отметку «проведено» там незачем.
  const canFormalize = ['advance', 'travel', 'bonus'].includes(value.kind)
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{isNew ? 'Новая операция' : 'Операция с наличными'}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 max-h-[70vh] overflow-y-auto pr-1">
          <div className="grid gap-3 sm:grid-cols-3">
            {/* У отчёта, зачёта и списания направление не выбирают: денег не
                движется, а сторону задаёт сама выдача. Пока переключатель стоял здесь,
                форма открывалась на «Выдали», никто его не трогал — и мост изменения
                долга показывал расхождение на ровном месте. */}
            <Field label="Направление"
              hint={isClosing && value.kind !== 'repayment'
                ? 'Задаётся выдачей: закрытие всегда идёт ей навстречу' : undefined}>
              {isClosing && value.kind !== 'repayment' ? (
                <div className={`${inputCls} text-muted-foreground`}>
                  {parentDirection === 'out' ? 'Закрывает выданное' : 'Закрывает полученное'}
                </div>
              ) : (
                <select className={inputCls} value={value.direction}
                  onChange={(e) => set({ direction: e.target.value })}>
                  {dicts.directions.map((k) => <option key={k.key} value={k.key}>{k.label}</option>)}
                </select>
              )}
            </Field>
            <Field label="Сумма, ₽">
              <input className={inputCls} type="number" step="0.01" min="0"
                value={value.amount || ''}
                onChange={(e) => set({ amount: Number(e.target.value) })} />
            </Field>
            <Field label="Когда">
              <input className={inputCls} type="date" value={value.happenedOn}
                onChange={(e) => set({ happenedOn: e.target.value })} />
            </Field>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="С кем рассчитались"
              hint="Новое имя вводится свободно: карточка человека заведётся сама">
              <input className={inputCls} value={value.personName} autoFocus
                list="perimeter-people"
                onChange={(e) => set({ personName: e.target.value })} />
              <datalist id="perimeter-people">
                {people.map((p) => (
                  <option key={p.name} value={p.name}>
                    {[p.kindLabel, p.role].filter(Boolean).join(' · ')}
                  </option>
                ))}
              </datalist>
            </Field>
            <Field label="Кто это" hint="От этого зависит, примет ли учёт эту выдачу">
              <select className={inputCls} value={value.personKind}
                onChange={(e) => set({ personKind: e.target.value })}>
                {dicts.personKinds.map((k) => (
                  <option key={k.key} value={k.key}>{k.label}</option>
                ))}
              </select>
            </Field>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Вид">
              <select className={inputCls} value={value.kind}
                onChange={(e) => {
                  const k = e.target.value
                  // Поля, которых у нового вида нет, сбрасываются вместе с ним:
                  // скрытый флажок «проведено» иначе уходил на сервер незамеченным.
                  set({
                    kind: k,
                    dueOn: ['loan', 'advance'].includes(k) ? value.dueOn : null,
                    parentId: CLOSING.includes(k) ? value.parentId : null,
                    formalized: ['advance', 'travel', 'bonus'].includes(k)
                      ? value.formalized : false,
                    formalizedOn: ['advance', 'travel', 'bonus'].includes(k)
                      ? value.formalizedOn : null,
                    formalizedBy: ['advance', 'travel', 'bonus'].includes(k)
                      ? value.formalizedBy : null,
                  })
                }}>
                {dicts.kinds.map((k) => <option key={k.key} value={k.key}>{k.label}</option>)}
              </select>
            </Field>
            <Field label="Чьи деньги" hint="Из личных средств или из наличных компании">
              <select className={inputCls} value={value.purse}
                onChange={(e) => set({ purse: e.target.value })}>
                {dicts.purse.map((k) => <option key={k.key} value={k.key}>{k.label}</option>)}
              </select>
            </Field>
          </div>

          {isClosing && (
            <Field label="Что закрываем"
              hint="Без привязки выданное осталось бы незакрытым: остаток считается по цепочке">
              <select className={inputCls} value={value.parentId ?? ''}
                onChange={(e) => set({ parentId: e.target.value || null })}>
                <option value="">— выберите заём —</option>
                {loans.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.happenedOn} · {l.person} · осталось{' '}
                    {money.format(l.rest ?? 0)} ₽
                  </option>
                ))}
              </select>
            </Field>
          )}

          {value.kind === 'writeoff' && (
            <Field label="Почему списываем"
              hint="Долг не исчезает: по правилам учёта он уходит на забалансовый счёт 007 и числится там ещё пять лет">
              <select className={inputCls} value={value.writeoffReason ?? ''}
                onChange={(e) => set({ writeoffReason: e.target.value || null })}>
                <option value="">— выберите причину —</option>
                <option value="forgiven">Простили</option>
                <option value="hopeless">Взыскать не с кого</option>
                <option value="expired">Истёк срок давности</option>
              </select>
            </Field>
          )}

          {isOpen && (
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label={isLoan ? 'Срок возврата' : 'Отчитаться до'}
                hint="Пусто, если договорились без срока">
                <input className={inputCls} type="date" value={value.dueOn ?? ''}
                  onChange={(e) => set({ dueOn: e.target.value || null })} />
              </Field>
              <Field label="Долг признан"
                hint="Частичная оплата, акт сверки, просьба об отсрочке — они прерывают срок давности, и он течёт заново">
                <input className={inputCls} type="date" value={value.acknowledgedOn ?? ''}
                  onChange={(e) => set({ acknowledgedOn: e.target.value || null })} />
              </Field>
              <Field label="Чем признан">
                <input className={inputCls} value={value.acknowledgedBy ?? ''}
                  placeholder="акт сверки" disabled={!value.acknowledgedOn}
                  onChange={(e) => set({ acknowledgedBy: e.target.value })} />
              </Field>
            </div>
          )}

          {!!commitments.length && value.direction === 'out' && (
            <Field label="По регулярному обязательству"
              hint="Период закроется отметкой сам — по дате операции, а не по текущему месяцу">
              <select className={inputCls} value={value.commitmentId ?? ''}
                onChange={(e) => {
                  const id = e.target.value || null
                  const c = commitments.find((x) => x.id === id)
                  // Подставляем ожидаемые имя, сумму и период: чаще всего платят как
                  // договорились и за самый старый незакрытый период.
                  const open = c?.periods.filter((p) => p.outcome !== 'done') ?? []
                  set({
                    commitmentId: id,
                    commitmentPeriod: open[0]?.periodStart ?? null,
                    personName: c && !value.personName ? c.person : value.personName,
                    amount: c && !value.amount ? (c.amount ?? value.amount) : value.amount,
                  })
                }}>
                <option value="">— разовая операция —</option>
                {commitments.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.person} · {c.title}
                    {c.amount ? ` · ${money.format(c.amount)} ₽` : ''}
                  </option>
                ))}
              </select>
            </Field>
          )}

          {!!value.commitmentId && (
            <Field label="За какой период"
              hint="Доплату за август обычно выдают в сентябре — период выбирают, а не берут по дате операции">
              <select className={inputCls} value={value.commitmentPeriod ?? ''}
                onChange={(e) => set({ commitmentPeriod: e.target.value || null })}>
                <option value="">— период даты операции —</option>
                {(commitments.find((c) => c.id === value.commitmentId)?.periods ?? [])
                  .slice().reverse().map((p) => (
                    <option key={p.periodStart} value={p.periodStart}>
                      {p.label}{p.outcome === 'done' ? ' (уже закрыт)' : ''}
                    </option>
                  ))}
              </select>
            </Field>
          )}

          <Field label="За что" hint="«Монтаж стеллажей на складе», «в долг до зарплаты»">
            <textarea className={inputCls} rows={2} value={value.purpose ?? ''}
              onChange={(e) => set({ purpose: e.target.value })} />
          </Field>

          <Field label="Чем подтверждено"
            hint="Для займа расписка — единственное, чем он доказуем">
            <select className={inputCls} value={value.proof}
              onChange={(e) => set({ proof: e.target.value })}>
              {dicts.proof.map((k) => <option key={k.key} value={k.key}>{k.label}</option>)}
            </select>
          </Field>

          {canFormalize && (
            <div className="rounded-md border p-3 space-y-3">
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={value.formalized}
                  onChange={(e) => set({ formalized: e.target.checked })} />
                Бухгалтерия провела документами
              </label>
              <p className="text-[11px] text-muted-foreground">
                Выдачу под отчёт закрывает авансовый отчёт, премию — ведомость,
                компенсацию проезда — приказ и чеки. Пока отметки нет, операция стоит
                в очереди на оформление.
              </p>
              {value.formalized && (
                <div className="grid gap-3 sm:grid-cols-2">
                  <Field label="Когда провели">
                    <input className={inputCls} type="date" value={value.formalizedOn ?? ''}
                      onChange={(e) => set({ formalizedOn: e.target.value || null })} />
                  </Field>
                  <Field label="Чем" hint="«Авансовый отчёт № 12», «ведомость за август»">
                    <input className={inputCls} value={value.formalizedBy ?? ''}
                      onChange={(e) => set({ formalizedBy: e.target.value })} />
                  </Field>
                </div>
              )}
            </div>
          )}

          <Field label="Заметка">
            <textarea className={inputCls} rows={2} value={value.note ?? ''}
              onChange={(e) => set({ note: e.target.value })} />
          </Field>

          {!!warn.data?.warnings.length && (
            <div className="rounded-md border border-amber-500/50 bg-amber-500/5 p-3
                space-y-1.5">
              {warn.data.warnings.map((w) => (
                <p key={w.key} className="text-[11px] text-muted-foreground">{w.text}</p>
              ))}
            </div>
          )}

          {error && <div className="text-sm text-destructive">{error}</div>}
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2 pt-2">
          {(!value.personName.trim() || !value.amount
            || (isRepayment && !value.parentId)) && (
            <span className="text-[11px] text-muted-foreground mr-auto">
              Заполните: {[!value.personName.trim() && 'с кем',
                           !value.amount && 'сумма',
                           isRepayment && !value.parentId && 'к какой выдаче']
                .filter(Boolean).join(', ')}
            </span>
          )}
          <Button variant="outline" size="sm" onClick={onClose}>Отмена</Button>
          <Button size="sm" onClick={onSave}
            disabled={saving || !value.personName.trim() || !value.amount
              || (isRepayment && !value.parentId)}>
            {saving ? 'Сохраняем…' : 'Сохранить'}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

/* ────────────────────────────────────────────────────────────── */
/*                      Расчёты по людям                          */
/* ────────────────────────────────────────────────────────────── */

/* ────────────────────────────────────────────────────────────── */
/*                            Займы                               */
/* ────────────────────────────────────────────────────────────── */

export function CashLoansScreen({ companyId }: { companyId: string }) {
  const [open, setOpen] = useState<Set<string>>(new Set())
  const q = useQuery({
    queryKey: ['perimeter', 'cash-loans', companyId],
    queryFn: () => getCashLoans(companyId),
    enabled: !!companyId,
  })
  if (q.isError) {
    return <div className="p-4">
      <QueryError message="Не удалось загрузить займы и подотчёт"
        onRetry={() => q.refetch()} />
    </div>
  }
  if (!q.data) return <Loading />
  const d = q.data
  if (!d.rows.length) {
    return (
      <div className="p-4">
        <Card>
          <CardContent className="p-4 text-sm text-muted-foreground">
            Ни займов, ни выданного под отчёт. Заём заводится в журнале видом «Заём»,
            выдача сотруднику — видом «Выдано под отчёт»; закрываются они «Возвратом
            займа» или «Отчётом по выданному» со ссылкой на выдачу. Тогда остаток
            считается сам.
          </CardContent>
        </Card>
      </div>
    )
  }
  const toggle = (id: string) => setOpen((prev) => {
    const next = new Set(prev)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    return next
  })

  return (
    <div className="p-4 space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <MetricTile label="Осталось за людьми" value={`${money.format(d.givenRest)} ₽`}
          hint="выданные займы и подотчёт" />
        <MetricTile label="Осталось за нами" value={`${money.format(d.takenRest)} ₽`}
          hint="полученные займы" />
        <MetricTile label="Просрочено" value={num.format(d.overdue)}
          hint="срок прошёл, остаток не погашен"
          tone={d.overdue ? 'danger' : undefined} />
      </div>

      <TableCard note="Выданные и полученные не сворачиваются в одну цифру: долг знакомого не гасит наш долг перед другим"
        head={<><Th>Дата</Th><Th>С кем и за что</Th><Th right>Сумма</Th>
          <Th right>Возвращено</Th><Th right>Осталось</Th><Th>Срок</Th></>}>
        {d.rows.map((l) => (
          <Fragment key={l.id}>
            <tr className={cn('border-b last:border-0',
              l.overdue && 'bg-destructive/5')}>
              <Td>
                <button className="flex items-center gap-1 hover:underline"
                  onClick={() => toggle(l.id)}>
                  {(l.payments?.length ?? 0) > 0
                    ? (open.has(l.id) ? <ChevronDown className="w-3.5 h-3.5" />
                                      : <ChevronRight className="w-3.5 h-3.5" />)
                    : <span className="w-3.5" />}
                  <span className="tabular-nums">{l.happenedOn}</span>
                </button>
                <div className="text-[11px] text-muted-foreground pl-4.5">
                  {l.kindLabel.toLowerCase()}
                </div>
              </Td>
              <Td>
                <div>{l.person}</div>
                <div className="text-[11px] text-muted-foreground">
                  {l.purpose ?? '—'} · {l.personKindLabel.toLowerCase()}
                  {' · '}{l.proofLabel.toLowerCase()}
                </div>
              </Td>
              <Td right>{money.format(l.amount)} ₽</Td>
              <Td right muted>{l.repaid ? `${money.format(l.repaid)} ₽` : '—'}</Td>
              <Td right>
                <span className={(l.rest ?? 0) < 0.01 ? 'text-muted-foreground' : undefined}>
                  {money.format(l.rest ?? 0)} ₽
                </span>
              </Td>
              <Td muted>
                <span className={cn('tabular-nums', l.overdue && 'text-destructive')}>
                  {l.dueOn ?? 'без срока'}
                </span>
              </Td>
            </tr>
            {open.has(l.id) && (l.payments ?? []).map((p) => (
              <tr key={p.id} className="border-b last:border-0 bg-muted/30">
                <Td muted><span className="tabular-nums pl-4">{p.happenedOn}</span></Td>
                <Td muted>
                  {(p.kindLabel ?? 'возврат').toLowerCase()}{p.note ? ` · ${p.note}` : ''}
                </Td>
                <Td right muted>—</Td>
                <Td right>{money.format(p.amount)} ₽</Td>
                <Td right muted>—</Td>
                <Td muted>—</Td>
              </tr>
            ))}
          </Fragment>
        ))}
      </TableCard>
    </div>
  )
}

/* ────────────────────────────────────────────────────────────── */
/*                        К оформлению                            */
/* ────────────────────────────────────────────────────────────── */

/**
 * Что бухгалтерия ещё не провела документами.
 *
 * Часть наличных движений учёт всё-таки принимает: выданное под отчёт закрывается
 * авансовым отчётом, премия проводится ведомостью, компенсация проезда — приказом и
 * чеками. Пока документов нет, операция живёт только в периметре, и владельцу нужен
 * список, а не память.
 *
 * Оплата работы частному лицу и заём знакомому сюда не попадают: учёт их не примет в
 * принципе, и держать их в очереди значило бы делать вид, что когда-нибудь примет.
 */
export function CashPapersScreen({ companyId }: { companyId: string }) {
  const q = useQuery({
    queryKey: ['perimeter', 'cash-papers', companyId],
    queryFn: () => getCashPapers(companyId),
    enabled: !!companyId,
  })
  if (q.isError) {
    return <div className="p-4">
      <QueryError message="Не удалось собрать очередь на оформление"
        onRetry={() => q.refetch()} />
    </div>
  }
  if (!q.data) return <Loading />
  const d = q.data

  return (
    <div className="p-4 space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <MetricTile label="Ждёт документов" value={`${money.format(d.waitingAmount)} ₽`}
          hint={`${num.format(d.waiting.length)} операций`}
          tone={d.waiting.length ? 'warning' : 'success'} />
        <MetricTile label="Уже проведено" value={`${money.format(d.doneAmount)} ₽`}
          hint={`${num.format(d.done.length)} операций`} />
        <MetricTile label="Подотчёт не закрыт"
          value={num.format(d.openAdvances.length)}
          hint="деньги выданы, отчёта нет"
          tone={d.openAdvances.length ? 'warning' : undefined} />
      </div>

      <Card>
        <CardContent className="p-4 space-y-2 text-sm">
          <div className="font-medium">Что здесь</div>
          <p className="text-muted-foreground">
            Выдачи сотрудникам учёт принимает: подотчёт закрывается авансовым отчётом,
            премия проводится ведомостью, компенсация проезда — приказом и чеками. Этот
            экран показывает, что уже оформлено, а что ждёт бухгалтерию. Отметку
            «проведено» ставят в карточке операции, указав чем и когда.
          </p>
          <p className="text-muted-foreground">
            Оплаты частным лицам и займы знакомым в очередь не попадают: их учёт не
            примет, и место им — в журнале и в расчётах с людьми.
          </p>
        </CardContent>
      </Card>

      {!!d.byKind.length && (
        <TableCard note="Из чего состоит очередь"
          head={<><Th>Вид</Th><Th right>Операций</Th><Th right>Сумма</Th></>}>
          {d.byKind.map((k) => (
            <tr key={k.key} className="border-b last:border-0">
              <Td>{k.label}</Td>
              <Td right muted>{num.format(k.count)}</Td>
              <Td right>{money.format(k.amount)} ₽</Td>
            </tr>
          ))}
        </TableCard>
      )}

      {d.waiting.length ? (
        <>
          <div className="flex items-center justify-between">
            <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
              Ждут оформления
            </div>
            <PerimeterExport companyId={companyId} title="К оформлению"
            columns={[
              { header: 'Дата', key: 'happenedOn', width: 13 },
              { header: 'Кому', key: 'person', width: 30 },
              { header: 'Кто это', key: 'personKindLabel', width: 16 },
              { header: 'Вид', key: 'kindLabel', width: 22 },
              { header: 'За что', key: 'purpose', width: 44 },
              { header: 'Сумма', key: 'amount', width: 16, money: true },
              { header: 'Чем подтверждено', key: 'proofLabel', width: 18 },
            ]}
            rows={d.waiting} />
          </div>
          <TableCard note="Отметка о проведении ставится в карточке операции на экране «Журнал»"
            head={<><Th>Дата</Th><Th>Кому и за что</Th><Th>Вид</Th>
              <Th>Чем подтверждено</Th><Th right>Сумма</Th></>}>
            {d.waiting.map((r) => (
              <tr key={r.id} className="border-b last:border-0">
                <Td><span className="tabular-nums">{r.happenedOn}</span></Td>
                <Td>
                  <div>{r.person}</div>
                  <div className="text-[11px] text-muted-foreground">
                    {r.personKindLabel}{r.purpose ? ` · ${r.purpose}` : ''}
                  </div>
                </Td>
                <Td muted>{r.kindLabel}</Td>
                <Td>
                  <span className={cn('text-sm', proofTone(r.proof))}>{r.proofLabel}</span>
                </Td>
                <Td right>{money.format(r.amount)} ₽</Td>
              </tr>
            ))}
          </TableCard>
        </>
      ) : (
        <Card>
          <CardContent className="p-4 text-sm text-muted-foreground">
            Очередь пуста: всё, что учёт принимает, проведено документами.
          </CardContent>
        </Card>
      )}

      {!!d.openAdvances.length && (
        <TableCard note="Выдано под отчёт, а отчёта нет. С точки зрения учёта это долг сотрудника"
          head={<><Th>Дата</Th><Th>Кому</Th><Th right>Выдано</Th>
            <Th right>Отчитался</Th><Th right>Осталось</Th><Th>Срок</Th></>}>
          {d.openAdvances.map((r) => (
            <tr key={r.id} className={cn('border-b last:border-0',
              r.overdue && 'bg-destructive/5')}>
              <Td><span className="tabular-nums">{r.happenedOn}</span></Td>
              <Td>
                <div>{r.person}</div>
                {r.purpose && (
                  <div className="text-[11px] text-muted-foreground">{r.purpose}</div>
                )}
              </Td>
              <Td right>{money.format(r.amount)} ₽</Td>
              <Td right muted>{r.repaid ? `${money.format(r.repaid)} ₽` : '—'}</Td>
              <Td right>{money.format(r.rest ?? 0)} ₽</Td>
              <Td muted>
                <span className={cn('tabular-nums', r.overdue && 'text-destructive')}>
                  {r.dueOn ?? 'без срока'}
                </span>
              </Td>
            </tr>
          ))}
        </TableCard>
      )}
    </div>
  )
}
