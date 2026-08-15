/**
 * «Периметр» → «Регулярные» — обязательства, которые надо выполнять каждый период.
 *
 * Разовую договорённость закрывают один раз, регулярную — каждый месяц, и вопрос к ней
 * другой: за какой период рассчитались, а какой пропустили. Доплата водителю, аренда
 * жилья мастеру, обед бригаде по пятницам, обучение раз в квартал.
 *
 * Форма исполнения не обязана быть денежной, поэтому суммы может не быть, а «выполнено»
 * отмечается фактом, а не платежом. Периодичность по умолчанию — месяц: это
 * естественный шаг таких договорённостей.
 *
 * Полоса периодов — главный элемент экрана: по ней сразу видно, где дыры. Пропуск
 * бывает сознательным («в этом месяце договорились не платить»), и отмечать его надо
 * явно, иначе он неотличим от забытого.
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2 } from 'lucide-react'

import { toast } from 'sonner'

import { QueryError } from '@/components/common/QueryError'
import { Card, CardContent } from '@/components/ui/card'
import { MetricTile } from '@/components/ui/metric-tile'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { cn } from '@/lib/utils'
import { exportTable } from '@/services/booksExport'
import {
  createCommitment, deleteCommitment, getCommitments, getPerimeterPeople,
  markCommitment, unmarkCommitment, updateCommitment,
  type Commitment, type CommitmentIn, type CommitmentList,
} from '@/services/perimeterService'
import { Loading } from './OfficePanels'
import { ExportButton, SearchInput, Tabs, money, num } from './officeShared'

const today = () => new Date().toISOString().slice(0, 10)

const EMPTY: CommitmentIn = {
  personName: '', title: '', startedOn: today(), form: 'money', periodicity: 'month',
  status: 'active', confidence: 'spoken', personKind: 'individual',
}

const inputCls = 'w-full rounded-md border bg-background px-2.5 py-1.5 text-sm'

/** Цвет клетки периода: выполнено, сознательно пропущено, пропущено, текущее. */
const PERIOD_TONE: Record<string, string> = {
  done: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400',
  skipped: 'bg-muted text-muted-foreground',
  // Красное — только настоящий пропуск. Идущий период ждёт, а не провален.
  missed: 'bg-destructive/15 text-destructive',
  open: 'bg-muted/50 text-muted-foreground',
  partial: 'bg-muted/50 text-muted-foreground',
}

/** Короткая подпись клетки: «авг», «Q3», «26» — по шагу, а не первым словом подряд. */
const periodChip = (label: string, periodicity: string): string => {
  if (periodicity === 'week') return label.replace('неделя с ', '').slice(0, 5)
  if (periodicity === 'quarter') return `Q${label[0]}`
  if (periodicity === 'halfyear') return `${label[0]}п`
  if (periodicity === 'year') return label.slice(2, 4)
  return label.slice(0, 3)
}

export function CommitmentsScreen({ companyId }: { companyId: string }) {
  const qc = useQueryClient()
  const [status, setStatus] = useState('active')
  const [search, setSearch] = useState('')
  const [edit, setEdit] = useState<{ id: string | null; body: CommitmentIn } | null>(null)
  const [mark, setMark] = useState<{ c: Commitment; period: string; label: string } | null>(null)

  const q = useQuery({
    queryKey: ['perimeter', 'commitments', companyId],
    queryFn: () => getCommitments(companyId),
    enabled: !!companyId,
  })
  const people = useQuery({
    queryKey: ['perimeter', 'people', companyId],
    queryFn: () => getPerimeterPeople(companyId),
    enabled: !!companyId,
  })

  const save = useMutation({
    mutationFn: (v: { id: string | null; body: CommitmentIn }) =>
      v.id ? updateCommitment(companyId, v.id, v.body)
           : createCommitment(companyId, v.body),
    onSuccess: () => {
      setEdit(null)
      qc.invalidateQueries({ queryKey: ['perimeter'] })
    },
  })
  const remove = useMutation({
    mutationFn: (id: string) => deleteCommitment(companyId, id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['perimeter'] }),
    onError: (e: Error) => toast.error(e.message),
  })
  const doMark = useMutation({
    mutationFn: (v: {
      id: string; periodStart: string; outcome: string; amount?: number | null
      note?: string | null
    }) => markCommitment(companyId, v.id, {
      periodStart: v.periodStart, outcome: v.outcome, amount: v.amount, note: v.note,
    }),
    onSuccess: () => {
      setMark(null)
      qc.invalidateQueries({ queryKey: ['perimeter'] })
    },
    // Отметка периода — главное действие экрана: её отказ обязан быть виден.
    onError: (e: Error) => toast.error(e.message),
  })
  const undoMark = useMutation({
    mutationFn: (v: { id: string; markId: string }) =>
      unmarkCommitment(companyId, v.id, v.markId),
    onSuccess: () => {
      setMark(null)
      qc.invalidateQueries({ queryKey: ['perimeter'] })
    },
    onError: (e: Error) => toast.error(e.message),
  })

  const rows = useMemo(() => {
    let all = q.data?.rows ?? []
    if (status) all = all.filter((c) => c.status === status)
    const s = search.trim().toLowerCase()
    if (!s) return all
    return all.filter((c) => `${c.person} ${c.title} ${c.note ?? ''}`
      .toLowerCase().includes(s))
  }, [q.data, status, search])

  if (q.isError) {
    return <div className="p-4">
      <QueryError message="Не удалось загрузить обязательства" onRetry={() => q.refetch()} />
    </div>
  }
  if (!q.data) return <Loading />
  const d: CommitmentList = q.data

  return (
    <div className="p-4 space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <MetricTile label="Действующих" value={num.format(d.activeCount)}
          hint={`перед ${num.format(d.peopleCount)} людьми`} />
        <MetricTile label="В месяц деньгами" value={`${money.format(d.monthlyMoney)} ₽`}
          hint="регулярные выплаты, приведённые к месяцу" />
        <MetricTile label="Периодов пропущено" value={num.format(d.missedTotal)}
          hint="не выполнено и не отмечено"
          tone={d.missedTotal ? 'danger' : 'success'} />
        <MetricTile label="Всего записей" value={num.format(d.rows.length)}
          hint="включая приостановленные и прекращённые" />
      </div>

      <div className="flex flex-wrap items-center gap-2 justify-between">
        <Tabs value={status} onChange={setStatus} items={[
          { key: 'active', label: 'Действующие' },
          { key: '', label: 'Все' },
          { key: 'paused', label: 'Приостановленные' },
          { key: 'ended', label: 'Прекращённые' },
        ]} />
        <div className="flex items-center gap-2">
          <SearchInput value={search} onChange={setSearch} placeholder="Кто или что" />
          {!!rows.length && (
            <ExportButton onClick={() => exportTable('Регулярные обязательства', [
              { header: 'Перед кем', key: 'person', width: 30 },
              { header: 'Что', key: 'title', width: 44 },
              { header: 'Форма', key: 'formLabel', width: 22 },
              { header: 'Сумма за период', key: 'amount', width: 18, money: true },
              { header: 'Периодичность', key: 'periodicityLabel', width: 20 },
              { header: 'С какого дня', key: 'startedOn', width: 14 },
              { header: 'Выполнено', key: 'doneCount', width: 12 },
              { header: 'Пропущено', key: 'missedCount', width: 12 },
              { header: 'Статус', key: 'statusLabel', width: 18 },
            ], rows)} />
          )}
          <Button size="sm" onClick={() => setEdit({ id: null, body: { ...EMPTY } })}>
            <Plus className="w-4 h-4 mr-1" />Записать
          </Button>
        </div>
      </div>

      {!rows.length ? (
        <Card>
          <CardContent className="p-4 text-sm space-y-2">
            <div className="font-medium">
              {d.rows.length ? 'Ничего не подходит под отбор' : 'Регулярных обязательств нет'}
            </div>
            {!d.rows.length && (
              <>
                <p className="text-muted-foreground">
                  Сюда заносят то, что обещано делать не один раз, а каждый период:
                  ежемесячная доплата водителю сверх ведомости, компенсация съёмного
                  жилья мастеру, обед бригаде по пятницам, обучение раз в квартал.
                  Форма любая — деньгами, работой или вещами.
                </p>
                <p className="text-muted-foreground">
                  Смысл в том, чтобы видеть пропуски. Разовое обещание помнят, а
                  регулярное незаметно перестаёт выполняться — и узнают об этом от
                  обиженного человека, а не из записи.
                </p>
              </>
            )}
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {rows.map((c) => (
            <Card key={c.id}>
              <CardContent className="p-4 space-y-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <button className="text-base font-medium hover:underline text-left"
                      onClick={() => setEdit({ id: c.id, body: toForm(c) })}>
                      {c.title}
                    </button>
                    <div className="text-sm text-muted-foreground">
                      {c.person} · {c.periodicityLabel.toLowerCase()}
                      {c.dueDay ? `, к ${c.dueDay} числу` : ''} · {c.formLabel.toLowerCase()}
                      {c.amount ? ` · ${money.format(c.amount)} ₽ за период` : ''}
                    </div>
                    {c.details && (
                      <div className="text-[11px] text-muted-foreground mt-0.5">
                        {c.details}
                      </div>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] text-muted-foreground">
                      {c.statusLabel} · {c.confidenceLabel.toLowerCase()}
                    </span>
                    <button className="text-muted-foreground hover:text-destructive"
                      title="Удалить обязательство" onClick={() => remove.mutate(c.id)}>
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>

                {/* Полоса периодов: клик по клетке открывает отметку */}
                <div className="flex flex-wrap gap-1">
                  {c.periods.map((p) => (
                    <button key={p.periodStart} title={`${p.label}: ${
                      p.outcome === 'done' ? 'выполнено'
                      : p.outcome === 'skipped' ? 'пропущено сознательно'
                      : p.outcome === 'partial' ? 'неполный первый период'
                      : p.outcome === 'open' ? 'период идёт'
                      : 'не отмечено'}`}
                      onClick={() => setMark({ c, period: p.periodStart, label: p.label })}
                      className={cn('h-6 min-w-8 px-1.5 rounded text-[10px] tabular-nums',
                        PERIOD_TONE[p.outcome] ?? 'bg-muted',
                        p.isCurrent && 'ring-2 ring-offset-1 ring-foreground/30')}>
                      {periodChip(p.label, c.periodicity)}
                    </button>
                  ))}
                </div>

                <div className="flex flex-wrap gap-3 text-[11px] text-muted-foreground">
                  {([['done', 'выполнено'], ['skipped', 'пропущено сознательно'],
                     ['missed', 'не отмечено'], ['open', 'период идёт']] as const)
                    .map(([key, label]) => (
                      <span key={key} className="inline-flex items-center gap-1">
                        <span className={cn('w-3 h-3 rounded', PERIOD_TONE[key])} />
                        {label}
                      </span>
                    ))}
                </div>

                <div className="flex flex-wrap gap-x-6 gap-y-1 text-[11px] text-muted-foreground">
                  <span>Выполнено: {num.format(c.doneCount)} из {num.format(c.periodsTotal)}</span>
                  {!!c.skippedCount && <span>пропущено сознательно: {num.format(c.skippedCount)}</span>}
                  {!!c.missedCount && (
                    <span className="text-destructive">
                      не отмечено: {num.format(c.missedCount)}
                      {c.missedPeriods.length ? ` (${c.missedPeriods.join(', ')})` : ''}
                      {c.missedAmount ? ` — ${money.format(c.missedAmount)} ₽` : ''}
                    </span>
                  )}
                  {c.paidTotal !== null && <span>выплачено всего: {money.format(c.paidTotal)} ₽</span>}
                  {c.nextPeriod && <span>следующий период: {c.nextPeriod}</span>}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {edit && (
        <CommitmentDialog
          value={edit.body}
          isNew={!edit.id}
          dicts={d.dictionaries}
          people={(people.data?.rows ?? []).filter((p) => p.isActive)}
          saving={save.isPending}
          error={save.error ? String((save.error as Error).message) : null}
          onChange={(body) => setEdit({ ...edit, body })}
          onClose={() => setEdit(null)}
          onSave={() => save.mutate(edit)}
        />
      )}

      {mark && (
        <MarkDialog
          commitment={mark.c}
          periodStart={mark.period}
          label={mark.label}
          saving={doMark.isPending || undoMark.isPending}
          onClose={() => setMark(null)}
          onSave={(outcome, amount, note) => doMark.mutate({
            id: mark.c.id, periodStart: mark.period, outcome, amount, note,
          })}
          onUndo={(markId) => undoMark.mutate({ id: mark.c.id, markId })}
        />
      )}
    </div>
  )
}

const toForm = (c: Commitment): CommitmentIn => ({
  personName: c.person, title: c.title, startedOn: c.startedOn, form: c.form,
  amount: c.amount, periodicity: c.periodicity, dueDay: c.dueDay, endsOn: c.endsOn,
  status: c.status, confidence: c.confidence, details: c.details, note: c.note,
  personKind: 'individual',
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

function CommitmentDialog({
  value, isNew, dicts, people, saving, error, onChange, onClose, onSave,
}: {
  value: CommitmentIn
  isNew: boolean
  dicts: CommitmentList['dictionaries']
  people: { name: string; kindLabel: string; role: string | null }[]
  saving: boolean
  error: string | null
  onChange: (v: CommitmentIn) => void
  onClose: () => void
  onSave: () => void
}) {
  const set = (patch: Partial<CommitmentIn>) => onChange({ ...value, ...patch })
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {isNew ? 'Новое регулярное обязательство' : 'Регулярное обязательство'}
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3 max-h-[70vh] overflow-y-auto pr-1">
          <Field label="Что обязаны делать"
            hint="«Доплата сверх ведомости», «компенсация съёмного жилья», «обед бригаде»">
            <input className={inputCls} value={value.title} autoFocus
              onChange={(e) => set({ title: e.target.value })} />
          </Field>

          <Field label="Перед кем" hint="Новое имя вводится свободно: карточка заведётся сама">
            <input className={inputCls} value={value.personName} list="commitment-people"
              onChange={(e) => set({ personName: e.target.value })} />
            <datalist id="commitment-people">
              {people.map((p) => (
                <option key={p.name} value={p.name}>
                  {[p.kindLabel, p.role].filter(Boolean).join(' · ')}
                </option>
              ))}
            </datalist>
          </Field>

          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="Как выполняется">
              <select className={inputCls} value={value.form}
                onChange={(e) => set({
                  form: e.target.value,
                  amount: e.target.value === 'money' ? value.amount : null,
                })}>
                {dicts.forms.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
              </select>
            </Field>
            <Field label="Сумма за период, ₽"
              hint={value.form === 'money' ? 'Пусто, если сумма плавает' : 'Только для выплат'}>
              <input className={inputCls} type="number" step="0.01"
                disabled={value.form !== 'money'} value={value.amount ?? ''}
                onChange={(e) => set({
                  amount: e.target.value === '' ? null : Number(e.target.value),
                })} />
            </Field>
            <Field label="Периодичность">
              <select className={inputCls} value={value.periodicity}
                onChange={(e) => set({ periodicity: e.target.value })}>
                {dicts.periodicity.map((p) => (
                  <option key={p.key} value={p.key}>{p.label}</option>
                ))}
              </select>
            </Field>
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="С какого дня">
              <input className={inputCls} type="date" value={value.startedOn}
                onChange={(e) => set({ startedOn: e.target.value })} />
            </Field>
            <Field label="До какого" hint="Пусто — бессрочно">
              <input className={inputCls} type="date" value={value.endsOn ?? ''}
                onChange={(e) => set({ endsOn: e.target.value || null })} />
            </Field>
            <Field label="К какому числу" hint="Пусто — в течение периода">
              <input className={inputCls} type="number" min="1" max="31"
                value={value.dueDay ?? ''}
                onChange={(e) => set({
                  dueDay: e.target.value === '' ? null : Number(e.target.value),
                })} />
            </Field>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Статус">
              <select className={inputCls} value={value.status}
                onChange={(e) => set({ status: e.target.value })}>
                {dicts.statuses.map((st) => (
                  <option key={st.key} value={st.key}>{st.label}</option>
                ))}
              </select>
            </Field>
            <Field label="Чем подтверждено">
              <select className={inputCls} value={value.confidence}
                onChange={(e) => set({ confidence: e.target.value })}>
                {dicts.confidence.map((cf) => (
                  <option key={cf.key} value={cf.key}>{cf.label}</option>
                ))}
              </select>
            </Field>
          </div>

          <Field label="Подробности">
            <textarea className={inputCls} rows={2} value={value.details ?? ''}
              onChange={(e) => set({ details: e.target.value })} />
          </Field>

          <p className="text-[11px] text-muted-foreground">
            Приостановленное обязательство пропусков не копит: договорились, что пока не
            выполняем. Периодичность у записи с отметками не меняется — заведите новое
            обязательство и прекратите старое.
          </p>

          {error && <div className="text-sm text-destructive">{error}</div>}
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="outline" size="sm" onClick={onClose}>Отмена</Button>
          <Button size="sm" onClick={onSave}
            disabled={saving || !value.title.trim() || !value.personName.trim()}>
            {saving ? 'Сохраняем…' : 'Сохранить'}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

/** Отметка периода: выполнено, сознательно пропущено или снять отметку. */
function MarkDialog({ commitment, periodStart, label, saving, onClose, onSave, onUndo }: {
  commitment: Commitment
  periodStart: string
  label: string
  saving: boolean
  onClose: () => void
  onSave: (outcome: string, amount: number | null, note: string | null) => void
  onUndo: (markId: string) => void
}) {
  const period = commitment.periods.find((p) => p.periodStart === periodStart)
  const [amount, setAmount] = useState<number | null>(
    period?.amount ?? (commitment.form === 'money' ? commitment.amount : null))
  const [note, setNote] = useState(period?.note ?? '')

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{label}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <p className="text-sm text-muted-foreground">
            {commitment.title} · {commitment.person}
          </p>
          {commitment.form === 'money' && (
            <Field label="Сколько выплачено, ₽"
              hint="Подставлена сумма за период — исправьте, если платили другую">
              <input className={inputCls} type="number" step="0.01" value={amount ?? ''}
                onChange={(e) => setAmount(e.target.value === '' ? null
                  : Number(e.target.value))} />
            </Field>
          )}
          <Field label="Заметка">
            <textarea className={inputCls} rows={2} value={note}
              onChange={(e) => setNote(e.target.value)} />
          </Field>
          <p className="text-[11px] text-muted-foreground">
            «Пропущено» ставят, когда договорились в этом периоде не выполнять: иначе
            пропуск неотличим от забытого.
          </p>
        </div>
        <div className="flex flex-wrap justify-end gap-2 pt-2">
          {period?.markId && (
            <Button variant="outline" size="sm" disabled={saving}
              onClick={() => onUndo(period.markId!)}>
              Снять отметку
            </Button>
          )}
          <Button variant="outline" size="sm" disabled={saving}
            onClick={() => onSave('skipped', null, note || null)}>
            Пропущено
          </Button>
          <Button size="sm" disabled={saving}
            onClick={() => onSave('done', amount, note || null)}>
            {saving ? 'Сохраняем…' : 'Выполнено'}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
