/**
 * «Периметр» → карточка человека: всё, что между нами, на одном листе.
 *
 * Жанр — акт сверки. Именно этим пользуются, когда доходит до разговора: не «журнал
 * за период», а «вот что было между нами, вот что осталось». Сюда же собраны три
 * действия, ради которых карточку и открывают: записать разговор о долге, зачесть
 * встречные требования и выгрузить сверку.
 *
 * Разговор здесь не переписка, а юридическое событие: признание долга прерывает срок
 * исковой давности, и он течёт заново. Поэтому запись разговора двигает срок у самой
 * выдачи — а удаление разговора его возвращает.
 *
 * Взаимозачёт гасит встречные долги «начиная со старых» и только внутри одной пары:
 * переносить долг на третье лицо продукт не станет — перевод долга требует согласия
 * кредитора, а записи «Иванов должен Петрову», которой не было, не существует.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { QueryError } from '@/components/common/QueryError'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { ConfirmActionDialog } from '@/components/common/ConfirmActionDialog'
import { cn } from '@/lib/utils'
import {
  cashOffset, createReminder, deleteReminder, getPersonStatement,
  type PersonStatement,
} from '@/services/perimeterService'
import { Loading, TableCard, Th } from './OfficePanels'
import { PerimeterExport } from './perimeterShared'
import { Td, dayLabel, inputCls, money, num, today } from './officeShared'

export function PersonCardDialog({ companyId, person, onClose }: {
  companyId: string
  person: string
  onClose: () => void
}) {
  const qc = useQueryClient()
  const [talk, setTalk] = useState<{
    happenedOn: string; channel: string; outcome: string
    promisedOn: string | null; note: string; cashId: string | null
  } | null>(null)

  const q = useQuery({
    queryKey: ['perimeter', 'statement', companyId, person],
    queryFn: () => getPersonStatement(companyId, person),
    enabled: !!companyId && !!person,
  })

  const invalidate = () => qc.invalidateQueries({ queryKey: ['perimeter'] })

  const saveTalk = useMutation({
    mutationFn: () => createReminder(companyId, {
      personName: person, happenedOn: talk!.happenedOn,
      channel: talk!.channel, outcome: talk!.outcome,
      promisedOn: talk!.promisedOn, note: talk!.note || null,
      cashId: talk!.cashId,
    }),
    onSuccess: () => { setTalk(null); invalidate() },
    onError: (e: Error) => toast.error(e.message),
  })
  const dropTalk = useMutation({
    mutationFn: (id: string) => deleteReminder(companyId, id),
    onSuccess: invalidate,
    onError: (e: Error) => toast.error(e.message),
  })
  const offset = useMutation({
    mutationFn: (amount: number) => cashOffset(companyId, {
      personName: person, amount, happenedOn: today(),
      note: 'зачёт встречных требований',
    }),
    onSuccess: (r) => {
      toast.success(`Зачтено ${money.format(r.offset)} ₽ по ${r.rows} выдачам`)
      invalidate()
    },
    onError: (e: Error) => toast.error(e.message),
  })

  const d = q.data
  // Встречные: сколько должен он и сколько должны мы. Зачесть можно меньшую сторону.
  const owed = (d?.cash ?? []).filter((c) => c.direction === 'out' && (c.rest ?? 0) > 0)
  const owes = (d?.cash ?? []).filter((c) => c.direction === 'in' && (c.rest ?? 0) > 0)
  const owedSum = owed.reduce((s, c) => s + (c.rest ?? 0), 0)
  const owesSum = owes.reduce((s, c) => s + (c.rest ?? 0), 0)
  const canOffset = owedSum > 0.01 && owesSum > 0.01
  const offsetAmount = Math.min(owedSum, owesSum)

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <DialogTitle>{person}</DialogTitle>
        </DialogHeader>

        {q.isError ? (
          <QueryError message="Не удалось собрать сверку по человеку"
            onRetry={() => q.refetch()} />
        ) : !d ? <Loading /> : (
          <div className="space-y-4 max-h-[72vh] overflow-y-auto pr-1">
            <Summary d={d} />

            <div className="flex flex-wrap items-center gap-2">
              <Button size="sm" variant="outline"
                onClick={() => setTalk({
                  happenedOn: today(), channel: 'talk', outcome: 'promised',
                  promisedOn: null, note: '', cashId: owed[0]?.id ?? null,
                })}>
                Записать разговор
              </Button>
              {canOffset && (
                <ConfirmActionDialog
                  title="Зачесть встречные требования?"
                  description={<>Он должен {money.format(owedSum)} ₽, мы —{' '}
                    {money.format(owesSum)} ₽. Зачёт погасит {money.format(offsetAmount)} ₽
                    с обеих сторон, начиная со старых выдач: в журнале появятся записи
                    «Взаимозачёт», денег при этом не движется.</>}
                  confirmLabel="Зачесть"
                  onConfirm={() => offset.mutate(offsetAmount)}
                  trigger={
                    <Button size="sm" variant="outline" disabled={offset.isPending}>
                      Зачесть встречные · {money.format(offsetAmount)} ₽
                    </Button>
                  } />
              )}
              <div className="ml-auto">
                <PerimeterExport companyId={companyId} title={`Сверка — ${person}`}
                  columns={[
                    { header: 'Дата', key: 'happenedOn', width: 13 },
                    { header: 'Направление', key: 'directionLabel', width: 13 },
                    { header: 'Вид', key: 'kindLabel', width: 24 },
                    { header: 'За что', key: 'purpose', width: 44 },
                    { header: 'Сумма', key: 'amount', width: 16, money: true },
                    { header: 'Осталось', key: 'rest', width: 16, money: true },
                    { header: 'Чем подтверждено', key: 'proofLabel', width: 18 },
                  ]}
                  rows={d.cash} />
              </div>
            </div>

            {!!d.cash.length && (
              <TableCard note="Расчёты между нами по датам. «Осталось» есть только у займов и подотчёта: оплата работы долгом не становится"
                head={<><Th>Когда</Th><Th>Что было</Th><Th right>Сумма</Th>
                  <Th right>Осталось</Th><Th>Право сгорает</Th></>}>
                {d.cash.map((c) => (
                  <tr key={c.id} className="border-b last:border-0">
                    <Td>{dayLabel(c.happenedOn)}</Td>
                    <Td>
                      <div>{c.kindLabel}</div>
                      {c.purpose && (
                        <div className="text-[11px] text-muted-foreground">{c.purpose}</div>
                      )}
                    </Td>
                    <Td right className={c.direction === 'in' ? 'text-emerald-700 dark:text-emerald-400' : undefined}>
                      {c.direction === 'in' ? '+' : '−'}{money.format(c.amount)} ₽
                    </Td>
                    <Td right>{c.rest ? `${money.format(c.rest)} ₽` : '—'}</Td>
                    <Td muted>
                      {c.limitationExpiresOn
                        ? <span className={cn('tabular-nums',
                          (c.limitationDaysLeft ?? 0) < 0 && 'text-destructive')}>
                          {c.limitationExpiresOn}
                        </span>
                        : '—'}
                    </Td>
                  </tr>
                ))}
              </TableCard>
            )}

            <Talks rows={d.reminders} onDrop={(id) => dropTalk.mutate(id)} />

            {!!d.commitments.length && (
              <Block title="Регулярные обязательства перед человеком">
                {d.commitments.map((c) => (
                  <li key={c.id}>
                    {c.title} · {c.periodicityLabel.toLowerCase()}
                    {c.amount ? ` · ${money.format(c.amount)} ₽` : ''}
                    {c.missedCount ? ` · пропущено ${num.format(c.missedCount)}` : ''}
                  </li>
                ))}
              </Block>
            )}

            {!!d.records.length && (
              <Block title="Договорённости">
                {d.records.map((r) => (
                  <li key={r.id}>
                    {r.title} · {r.statusLabel.toLowerCase()}
                    {r.dueOn ? ` · срок ${r.dueOn}` : ''}
                  </li>
                ))}
              </Block>
            )}

            {d.disclaimer && (
              <p className="text-[11px] text-muted-foreground">{d.disclaimer}</p>
            )}
          </div>
        )}

        {talk && (
          <Dialog open onOpenChange={(o) => !o && setTalk(null)}>
            <DialogContent className="max-w-lg">
              <DialogHeader>
                <DialogTitle>Разговор о расчёте</DialogTitle>
              </DialogHeader>
              <div className="space-y-3">
                <p className="text-[11px] text-muted-foreground">
                  Если человек признал долг — обещал вернуть или рассчитался частично —
                  срок исковой давности прерывается и течёт заново с этого дня. Поэтому
                  разговор привязывают к конкретной выдаче.
                </p>
                <div className="grid gap-3 sm:grid-cols-2">
                  <label className="block space-y-1">
                    <span className="block text-[11px] uppercase tracking-wider text-muted-foreground">
                      Когда
                    </span>
                    <input className={inputCls} type="date" value={talk.happenedOn}
                      onChange={(e) => setTalk({ ...talk, happenedOn: e.target.value })} />
                  </label>
                  <label className="block space-y-1">
                    <span className="block text-[11px] uppercase tracking-wider text-muted-foreground">
                      Как
                    </span>
                    <select className={inputCls} value={talk.channel}
                      onChange={(e) => setTalk({ ...talk, channel: e.target.value })}>
                      <option value="talk">Разговор</option>
                      <option value="call">Звонок</option>
                      <option value="chat">Сообщение</option>
                      <option value="mail">Письмо</option>
                      <option value="other">Иначе</option>
                    </select>
                  </label>
                </div>
                <label className="block space-y-1">
                  <span className="block text-[11px] uppercase tracking-wider text-muted-foreground">
                    Чем кончилось
                  </span>
                  <select className={inputCls} value={talk.outcome}
                    onChange={(e) => setTalk({ ...talk, outcome: e.target.value })}>
                    <option value="promised">Обещал вернуть</option>
                    <option value="paid">Рассчитался сразу</option>
                    <option value="refused">Отказал</option>
                    <option value="silent">Не ответил</option>
                  </select>
                </label>
                {!!owed.length && (
                  <label className="block space-y-1">
                    <span className="block text-[11px] uppercase tracking-wider text-muted-foreground">
                      О какой выдаче
                    </span>
                    <select className={inputCls} value={talk.cashId ?? ''}
                      onChange={(e) => setTalk({ ...talk, cashId: e.target.value || null })}>
                      <option value="">— без привязки —</option>
                      {owed.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.happenedOn} · {c.kindLabel} · осталось{' '}
                          {money.format(c.rest ?? 0)} ₽
                        </option>
                      ))}
                    </select>
                    <span className="block text-[11px] text-muted-foreground">
                      Признание долга продлит право требования по этой выдаче
                    </span>
                  </label>
                )}
                {talk.outcome === 'promised' && (
                  <label className="block space-y-1">
                    <span className="block text-[11px] uppercase tracking-wider text-muted-foreground">
                      К какому дню обещал
                    </span>
                    <input className={inputCls} type="date" value={talk.promisedOn ?? ''}
                      onChange={(e) => setTalk({
                        ...talk, promisedOn: e.target.value || null,
                      })} />
                  </label>
                )}
                <label className="block space-y-1">
                  <span className="block text-[11px] uppercase tracking-wider text-muted-foreground">
                    Заметка
                  </span>
                  <textarea className={inputCls} rows={2} value={talk.note}
                    onChange={(e) => setTalk({ ...talk, note: e.target.value })} />
                </label>
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <Button variant="outline" size="sm" onClick={() => setTalk(null)}>
                  Отмена
                </Button>
                <Button size="sm" disabled={saveTalk.isPending}
                  onClick={() => saveTalk.mutate()}>
                  {saveTalk.isPending ? 'Сохраняем…' : 'Записать'}
                </Button>
              </div>
            </DialogContent>
          </Dialog>
        )}
      </DialogContent>
    </Dialog>
  )
}

function Summary({ d }: { d: PersonStatement }) {
  const open = d.totals.open
  return (
    <div className="rounded-md border p-3 text-sm space-y-1">
      <div className="flex flex-wrap gap-x-6 gap-y-1">
        <span>Выдали <b className="tabular-nums">{money.format(d.totals.out)} ₽</b></span>
        <span>Получили <b className="tabular-nums">{money.format(d.totals.in)} ₽</b></span>
        <span>
          {open >= 0 ? 'Должен нам ' : 'Должны мы '}
          <b className={cn('tabular-nums',
            Math.abs(open) > 0.01 && (open > 0 ? 'text-amber-700 dark:text-amber-400'
              : 'text-destructive'))}>
            {money.format(Math.abs(open))} ₽
          </b>
          <span className="text-muted-foreground"> · {num.format(d.totals.openCount)} выдач</span>
        </span>
        {!!d.totals.writtenOff && (
          <span className="text-muted-foreground">
            списано {money.format(d.totals.writtenOff)} ₽
          </span>
        )}
      </div>
      {d.card && (d.card.role || d.card.phone) && (
        <div className="text-[11px] text-muted-foreground">
          {[d.card.role, d.card.phone].filter(Boolean).join(' · ')}
        </div>
      )}
    </div>
  )
}

/** История разговоров: сколько раз напоминали и чем это кончилось. */
function Talks({ rows, onDrop }: {
  rows: PersonStatement['reminders']
  onDrop: (id: string) => void
}) {
  if (!rows.length) {
    return (
      <p className="text-[11px] text-muted-foreground">
        Разговоров о расчёте не записано. Для просроченной выдачи важнее не сумма, а то,
        сколько раз о ней напоминали и что человек отвечал.
      </p>
    )
  }
  return (
    <div className="space-y-1">
      <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
        Разговоры о расчёте
      </div>
      <ul className="text-sm space-y-1">
        {rows.map((r) => (
          <li key={r.id} className="flex items-start gap-2">
            <span className="tabular-nums text-muted-foreground">
              {dayLabel(r.happenedOn)}
            </span>
            <span className="flex-1">
              {r.channelLabel.toLowerCase()} · {r.outcomeLabel.toLowerCase()}
              {r.promisedOn && ` · к ${r.promisedOn}`}
              {r.promiseBroken && (
                <span className="text-amber-700 dark:text-amber-400"> · срок обещания прошёл</span>
              )}
              {r.note && (
                <span className="block text-[11px] text-muted-foreground">{r.note}</span>
              )}
            </span>
            <ConfirmActionDialog
              destructive
              title="Удалить разговор?"
              description={<>Запись от {r.happenedOn} исчезнет. Если этим разговором
                человек признал долг, срок исковой давности вернётся к прежнему
                основанию — праву требования это может стоить трёх лет.</>}
              confirmLabel="Удалить"
              onConfirm={() => onDrop(r.id)}
              trigger={
                <button className="text-[11px] text-muted-foreground hover:text-destructive"
                  aria-label={`Удалить разговор от ${r.happenedOn}`}>
                  удалить
                </button>
              } />
          </li>
        ))}
      </ul>
    </div>
  )
}

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
        {title}
      </div>
      <ul className="text-sm space-y-0.5">{children}</ul>
    </div>
  )
}
