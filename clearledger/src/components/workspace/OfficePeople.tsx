/**
 * «Периметр» → «Люди» — с кем компания имеет дело помимо штата и договоров.
 *
 * Это НЕ зарплатный контур и не второй справочник контрагентов. Здесь монтажник,
 * приезжающий на разовые работы; водитель, возящий товар за наличные; сотрудник,
 * которому выдают под отчёт; знакомый, взявший в долг; представитель поставщика, с
 * которым договорились устно. Часть из них в штате, часть в справочнике контрагентов,
 * часть не заведена нигде — и ради последних список существует: через полгода «Сергей
 * с гидравликой» не восстанавливается ничем, а расчёты с ним остались.
 *
 * Карточка заводится САМА при первом расчёте в журнале наличных. Здесь её дополняют
 * ролью, телефоном и связью с контрагентом.
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2 } from 'lucide-react'

import { QueryError } from '@/components/common/QueryError'
import { Card, CardContent } from '@/components/ui/card'
import { MetricTile } from '@/components/ui/metric-tile'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { ConfirmActionDialog } from '@/components/common/ConfirmActionDialog'
import { cn } from '@/lib/utils'
import {
  createPerson, deletePerson, getPerimeterPeople, updatePerson,
  type PerimeterPerson, type PersonIn,
} from '@/services/perimeterService'
import { PersonCardDialog } from './OfficePersonCard'
import { PerimeterExport } from './perimeterShared'
import { Loading, TableCard, Th } from './OfficePanels'
import { SearchInput, Tabs, money, num , Td } from './officeShared'

const EMPTY_PERSON: PersonIn = { name: '', kind: 'individual', isActive: true }
const inputCls = 'w-full rounded-md border bg-background px-2.5 py-1.5 text-sm'

export function PerimeterPeopleScreen({ companyId }: { companyId: string }) {
  const qc = useQueryClient()
  const [kind, setKind] = useState('')
  const [search, setSearch] = useState('')
  const [edit, setEdit] = useState<{ id: string | null; body: PersonIn } | null>(null)
  const [card, setCard] = useState<string | null>(null)

  const q = useQuery({
    queryKey: ['perimeter', 'people', companyId],
    queryFn: () => getPerimeterPeople(companyId),
    enabled: !!companyId,
  })
  const save = useMutation({
    mutationFn: (v: { id: string | null; body: PersonIn }) =>
      v.id ? updatePerson(companyId, v.id, v.body) : createPerson(companyId, v.body),
    onSuccess: () => {
      setEdit(null)
      qc.invalidateQueries({ queryKey: ['perimeter'] })
    },
  })
  const remove = useMutation({
    mutationFn: (id: string) => deletePerson(companyId, id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['perimeter'] }),
  })

  const rows = useMemo(() => {
    let all = q.data?.rows ?? []
    if (kind) all = all.filter((p) => p.kind === kind)
    const s = search.trim().toLowerCase()
    if (!s) return all
    return all.filter((p) => `${p.name} ${p.role ?? ''} ${p.note ?? ''} ${p.phone ?? ''}`
      .toLowerCase().includes(s))
  }, [q.data, kind, search])

  if (q.isError) {
    return <div className="p-4">
      <QueryError message="Не удалось загрузить список" onRetry={() => q.refetch()} />
    </div>
  }
  if (!q.data) return <Loading />
  const d = q.data
  const withDebt = d.rows.filter((p) => Math.abs(p.rest) > 0.01)

  return (
    <div className="p-4 space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <MetricTile label="Людей в списке" value={num.format(d.count)}
          hint="сотрудники и не сотрудники" />
        <MetricTile label="Сотрудников"
          value={num.format(d.byKind.find((k) => k.key === 'employee')?.count ?? 0)}
          hint="свои, с подотчётом и премиями" />
        <MetricTile label="Людей с незакрытым" value={num.format(withDebt.length)}
          hint="за ними займы или подотчёт"
          tone={withDebt.length ? 'warning' : undefined} />
        <MetricTile label="Ждёт документов"
          value={num.format(d.rows.reduce((s, p) => s + p.awaits, 0))}
          hint="операций без оформления"
          tone={d.rows.some((p) => p.awaits) ? 'warning' : undefined} />
      </div>

      <div className="flex flex-wrap items-center gap-2 justify-between">
        <Tabs value={kind} onChange={setKind} items={[
          { key: '', label: 'Все' },
          ...d.kinds.map((k) => ({ key: k.key, label: k.label })),
        ]} />
        <div className="flex items-center gap-2">
          <SearchInput value={search} onChange={setSearch} label="Поиск по людям"
            placeholder="Имя, роль, телефон" />
          {!!rows.length && (
            <PerimeterExport companyId={companyId} title="Люди периметра"
            columns={[
              { header: 'Имя', key: 'name', width: 34 },
              { header: 'Кто это', key: 'kindLabel', width: 24 },
              { header: 'Роль', key: 'role', width: 26 },
              { header: 'Телефон', key: 'phone', width: 18 },
              { header: 'Операций', key: 'operations', width: 12 },
              { header: 'Выдано', key: 'out', width: 16, money: true },
              { header: 'Осталось', key: 'rest', width: 16, money: true },
              { header: 'Договорённостей', key: 'records', width: 16 },
              { header: 'Заметка', key: 'note', width: 40 },
            ]}
            rows={rows} />
          )}
          <Button size="sm" onClick={() => setEdit({ id: null, body: { ...EMPTY_PERSON } })}>
            <Plus className="w-4 h-4 mr-1" />Добавить
          </Button>
        </div>
      </div>

      {!rows.length ? (
        <Card>
          <CardContent className="p-4 text-sm space-y-2">
            <div className="font-medium">
              {d.count ? 'Никто не подходит под отбор' : 'Список пуст'}
            </div>
            {!d.count && (
              <>
                <p className="text-muted-foreground">
                  Здесь собираются люди, с которыми компания имеет дело помимо штатного
                  расписания и договоров: монтажник на разовые работы, водитель за
                  наличные, сотрудник с подотчётом, знакомый с займом, представитель
                  поставщика из устной договорённости.
                </p>
                <p className="text-muted-foreground">
                  Заводить вручную не обязательно: карточка появится сама, как только в
                  журнале наличных запишут первый расчёт с человеком. Здесь её
                  дополняют ролью, телефоном и связью с контрагентом.
                </p>
              </>
            )}
          </CardContent>
        </Card>
      ) : (
        <TableCard note="«Осталось» — займы и подотчёт: плюс за человеком, минус за нами. Оплата работы и премия долгом не становятся"
          head={<><Th>Имя</Th><Th>Кто это</Th><Th>Телефон</Th>
            <Th right>Операций</Th><Th right>Выдано</Th><Th right>Осталось</Th>
            <Th right> </Th></>}>
          {rows.map((p) => (
            <tr key={p.id} className={cn('border-b last:border-0 hover:bg-muted/40',
              !p.isActive && 'opacity-60')}>
              <Td>
                {/* Имя ведёт к сверке, карандаш — к правке карточки: чаще нужно
                    первое, а карточка человека правится редко. */}
                <button className="text-left hover:underline"
                  onClick={() => setCard(p.name)}>
                  {p.name}
                </button>
                <button className="ml-2 text-[11px] text-muted-foreground hover:underline"
                  onClick={() => setEdit({ id: p.id, body: toForm(p) })}>
                  править
                </button>
                {p.role && (
                  <div className="text-[11px] text-muted-foreground">{p.role}</div>
                )}
                {!p.isActive && (
                  <div className="text-[11px] text-muted-foreground">не в работе</div>
                )}
              </Td>
              <Td muted>
                <div>{p.kindLabel}</div>
                {!!p.records && (
                  <div className="text-[11px]">
                    договорённостей: {num.format(p.records)}
                  </div>
                )}
              </Td>
              <Td muted>{p.phone ?? '—'}</Td>
              <Td right muted>
                {p.operations ? num.format(p.operations) : '—'}
                {!!p.awaits && (
                  <div className="text-[11px] text-amber-700 dark:text-amber-400">
                    {num.format(p.awaits)} без документов
                  </div>
                )}
              </Td>
              <Td right>{p.out ? `${money.format(p.out)} ₽` : '—'}</Td>
              <Td right>
                {Math.abs(p.rest) < 0.01 ? '—' : (
                  <>
                    <div>{money.format(Math.abs(p.rest))} ₽</div>
                    <div className="text-[11px] text-muted-foreground">
                      {p.rest > 0 ? 'за человеком' : 'за нами'}
                    </div>
                  </>
                )}
              </Td>
              <Td right>
                {p.operations ? (
                  <Button variant="ghost" size="icon-sm" disabled
                    aria-label={`Удалить ${p.name} нельзя: есть расчёты`}
                    title="За человеком есть расчёты: снимите отметку «в работе»"
                    className="text-muted-foreground">
                    <Trash2 className="w-4 h-4" />
                  </Button>
                ) : (
                  <ConfirmActionDialog
                    destructive
                    title="Удалить из списка?"
                    description={<>Карточка «{p.name}» исчезнет из списка людей.
                      Расчётов за человеком нет, поэтому история не пострадает.</>}
                    confirmLabel="Удалить"
                    onConfirm={() => remove.mutate(p.id)}
                    trigger={
                      <Button variant="ghost" size="icon-sm"
                        aria-label={`Удалить ${p.name} из списка`}
                        className="text-muted-foreground hover:text-destructive">
                        <Trash2 className="w-4 h-4" />
                      </Button>
                    } />
                )}
              </Td>
            </tr>
          ))}
        </TableCard>
      )}

      {remove.isError && (
        <p className="text-sm text-destructive">{String((remove.error as Error).message)}</p>
      )}

      {!!d.orphans.length && (
        <Card>
          <CardContent className="p-4 text-sm space-y-1">
            <div className="font-medium">Имена из расчётов без карточки</div>
            <p className="text-muted-foreground">
              {d.orphans.join(', ')}
            </p>
            <p className="text-[11px] text-muted-foreground">
              Такое бывает у записей, сделанных до появления списка. Заведите карточку с
              тем же написанием — расчёты подтянутся к ней.
            </p>
          </CardContent>
        </Card>
      )}

      {edit && (
        <PersonDialog
          value={edit.body}
          isNew={!edit.id}
          kinds={d.kinds}
          saving={save.isPending}
          error={save.error ? String((save.error as Error).message) : null}
          onChange={(body) => setEdit({ ...edit, body })}
          onClose={() => setEdit(null)}
          onSave={() => save.mutate(edit)}
        />
      )}

      {card && (
        <PersonCardDialog companyId={companyId} person={card}
          onClose={() => setCard(null)} />
      )}
    </div>
  )
}

const toForm = (p: PerimeterPerson): PersonIn => ({
  name: p.name, kind: p.kind, role: p.role, phone: p.phone,
  payoutPhone: p.payoutPhone, payoutBank: p.payoutBank, payoutNote: p.payoutNote,
  counterpartyId: p.counterpartyId, note: p.note, isActive: p.isActive,
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

function PersonDialog({ value, isNew, kinds, saving, error, onChange, onClose, onSave }: {
  value: PersonIn
  isNew: boolean
  kinds: { key: string; label: string }[]
  saving: boolean
  error: string | null
  onChange: (v: PersonIn) => void
  onClose: () => void
  onSave: () => void
}) {
  const set = (patch: Partial<PersonIn>) => onChange({ ...value, ...patch })
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{isNew ? 'Новый человек' : 'Карточка человека'}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <Field label="Имя"
            hint="Так, как его называют в разговоре: по этому имени расчёты и найдутся">
            <input className={inputCls} value={value.name} autoFocus
              onChange={(e) => set({ name: e.target.value })} />
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Кто это">
              <select className={inputCls} value={value.kind}
                onChange={(e) => set({ kind: e.target.value })}>
                {kinds.map((k) => <option key={k.key} value={k.key}>{k.label}</option>)}
              </select>
            </Field>
            <Field label="Роль" hint="«Монтажник», «водитель», «прораб у подрядчика»">
              <input className={inputCls} value={value.role ?? ''}
                onChange={(e) => set({ role: e.target.value })} />
            </Field>
          </div>
          <Field label="Телефон"
            hint="Из данных физического лица храним только номер">
            <input className={inputCls} value={value.phone ?? ''}
              onChange={(e) => set({ phone: e.target.value })} />
          </Field>
          <div className="rounded-md border p-3 space-y-3">
            <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
              Как вернуть деньги
            </div>
            <p className="text-[11px] text-muted-foreground">
              Долг зафиксирован, а действие «верни» упирается в поиск реквизитов по
              переписке — пусть лежат там же, где сальдо.
            </p>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Телефон для перевода">
                <input className={inputCls} value={value.payoutPhone ?? ''}
                  onChange={(e) => set({ payoutPhone: e.target.value })} />
              </Field>
              <Field label="Банк">
                <input className={inputCls} value={value.payoutBank ?? ''}
                  onChange={(e) => set({ payoutBank: e.target.value })} />
              </Field>
            </div>
            <Field label="Иначе" hint="«наличными в офисе», «переводом от жены»">
              <input className={inputCls} value={value.payoutNote ?? ''}
                onChange={(e) => set({ payoutNote: e.target.value })} />
            </Field>
          </div>

          <Field label="Заметка">
            <textarea className={inputCls} rows={3} value={value.note ?? ''}
              onChange={(e) => set({ note: e.target.value })} />
          </Field>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={value.isActive}
              onChange={(e) => set({ isActive: e.target.checked })} />
            В работе
          </label>
          <p className="text-[11px] text-muted-foreground">
            Ушедших не удаляют: за ними остаётся история расчётов. Снятая отметка убирает
            человека из подсказок, но сохраняет всё, что с ним связано.
          </p>
          {error && <div className="text-sm text-destructive">{error}</div>}
        </div>
        <div className="flex items-center justify-end gap-2 pt-2">
          {!value.name.trim() && (
            <span className="mr-auto text-[11px] text-muted-foreground">
              Заполните: имя
            </span>
          )}
          <Button variant="outline" size="sm" onClick={onClose}>Отмена</Button>
          <Button size="sm" disabled={!value.name.trim() || saving} onClick={onSave}>
            {saving ? 'Сохраняем…' : 'Сохранить'}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
