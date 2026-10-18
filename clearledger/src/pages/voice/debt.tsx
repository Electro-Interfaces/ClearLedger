/**
 * Долг перезвона (волна 7, Р2): кому поручить и форма «завести» из завершённого звонка.
 *
 * Исполнитель — контакт-центр (узел отдаёт ему непрозрачную задачу, номер остаётся у
 * узла) или сотрудник заказчика: он звонит сам и отмечает попытки в «Нужен контакт».
 * Сотрудник выбирается из людей пространства; имени нет в списке — можно вписать.
 */
import { useId, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { PhoneForwarded } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useCompany } from '@/contexts/CompanyContext'
import { cn } from '@/lib/utils'
import * as voice from '@/services/voiceService'
import { listTaskPeople } from '@/services/tasksService'

/** Выбор исполнителя: КЦ или сотрудник. `value` — то, что уйдёт узлу. */
export function AssigneePicker({ value, onChange, ccOff }: {
  value: voice.Assignee
  onChange: (a: voice.Assignee) => void
  /** КЦ не подключён: передать ему нельзя (узел ответит cc_unavailable) */
  ccOff?: boolean
}) {
  const { companyId } = useCompany()
  const id = useId()
  const люди = useQuery({
    queryKey: ['voice-debt-people', companyId],
    queryFn: async () => (await listTaskPeople(companyId)).people.filter(p => p.partyType !== 'partner' && p.partyType !== 'vendor'),
    staleTime: 5 * 60_000,
  })
  const имя = value.kind === 'staff' ? value.name ?? '' : ''
  return (
    <div className="space-y-2">
      <div role="radiogroup" aria-label="Кому" className="flex flex-wrap gap-1 rounded-md border border-border p-0.5">
        {([['cc', 'Контакт-центру'], ['staff', 'Сотруднику']] as const).map(([k, т]) => (
          <button key={k} type="button" role="radio" aria-checked={value.kind === k}
            onClick={() => onChange(k === 'cc' ? { kind: 'cc' } : { kind: 'staff', id: null, name: имя || null })}
            className={cn('min-h-8 flex-1 rounded px-3 text-sm transition-colors',
              value.kind === k ? 'bg-primary/10 font-medium text-primary' : 'hover:bg-accent/50')}>
            {т}
          </button>
        ))}
      </div>
      {value.kind === 'cc' && ccOff && (
        <p className="text-xs text-muted-foreground">Контакт-центр не подключён: задача останется не назначенной, пока его не подключат.</p>
      )}
      {value.kind === 'staff' && (
        <div className="space-y-1">
          <Input value={имя} list={id} aria-label="Сотрудник" placeholder="Кто перезвонит"
            onChange={e => {
              const p = люди.data?.find(x => x.name === e.target.value)
              onChange({ kind: 'staff', id: p?.id ?? null, name: e.target.value || null })
            }} className="h-9" />
          <datalist id={id}>{люди.data?.map(p => <option key={p.id} value={p.name} />)}</datalist>
          <p className="text-xs text-muted-foreground">Узел не звонит сам: сотрудник отмечает попытки в «Нужен контакт».</p>
        </div>
      )}
    </div>
  )
}

/** «Нужен контакт» в карточке звонка: завести долг или увидеть уже заведённый. */
export function DebtFromCall({ к }: { к: voice.CallCard }) {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const [открыта, setОткрыта] = useState(false)
  const [кому, setКому] = useState<voice.Assignee>({ kind: 'cc' })
  const [срок, setСрок] = useState('')
  const [заметка, setЗаметка] = useState('')
  const [идёт, setИдёт] = useState(false)
  const долги = useQuery({
    queryKey: ['voice-callbacks', companyId, 'by-contact', к.contactId],
    queryFn: () => voice.callbacks(companyId, { contactId: к.contactId, limit: 5 }),
  })
  const открытый = долги.data?.items.find(x => !x.result && (x.state === 'scheduled' || x.state === 'dialing'))
  const завершён = !!к.endedAt && к.outcome != null
  if (к.direction === 'callback') return null

  async function завести(e: React.FormEvent) {
    e.preventDefault()
    if (кому.kind === 'staff' && !кому.name?.trim()) return
    setИдёт(true)
    try {
      const r = await voice.createCallback(companyId, {
        contactId: к.contactId, assignee: кому,
        dueAt: срок ? new Date(срок).toISOString() : undefined, note: заметка.trim() || undefined,
      })
      toast.success(r.merged ? `Номер уже ждёт контакта: звонок присоединён к долгу (обращений: ${r.callback.missedCalls ?? 2})`
        : 'Долг перезвона заведён')
      setОткрыта(false)
      await qc.invalidateQueries({ queryKey: ['voice-callbacks', companyId] })
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Узел не завёл долг')
    } finally {
      setИдёт(false)
    }
  }

  return (
    <section aria-label="Нужен контакт" className="space-y-2">
      <h2 className="text-sm font-medium">Нужен контакт</h2>
      {открытый ? (
        <p className="flex flex-wrap items-center gap-2 text-sm">
          <PhoneForwarded className="size-4 text-primary" />
          Номер ждёт контакта{открытый.missedCalls && открытый.missedCalls > 1 ? ` · обращений: ${открытый.missedCalls}` : ''}
          <Link to={`/voice/contact?id=${encodeURIComponent(открытый.id)}`} className="text-primary underline-offset-4 hover:underline">
            Открыть долг
          </Link>
        </p>
      ) : !завершён ? (
        <p className="text-xs text-muted-foreground">Звонок ещё идёт: в разговоре перезвон ставит оператор.</p>
      ) : !открыта ? (
        <Button variant="outline" size="sm" onClick={() => setОткрыта(true)}><PhoneForwarded />Завести перезвон</Button>
      ) : (
        <form onSubmit={завести} className="space-y-2 rounded-lg border border-border p-2.5">
          <AssigneePicker value={кому} onChange={setКому} />
          <label className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            не раньше
            <Input type="datetime-local" value={срок} onChange={e => setСрок(e.target.value)} className="h-9 w-56" aria-label="Не раньше" />
            <span>пусто — сразу</span>
          </label>
          <Input value={заметка} onChange={e => setЗаметка(e.target.value)} maxLength={500} aria-label="Заметка"
            placeholder="Что важно знать тому, кто перезвонит (без номера)" className="h-9" />
          <p className="text-xs text-muted-foreground">
            Если у этого номера на линии уже есть открытый долг, новой задачи не будет: звонок присоединится к нему.
          </p>
          <div className="flex gap-2">
            <Button type="submit" size="sm" disabled={идёт || (кому.kind === 'staff' && !кому.name?.trim())}>
              {идёт ? 'Заводим…' : 'Завести'}
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={() => setОткрыта(false)}>Отмена</Button>
          </div>
        </form>
      )}
    </section>
  )
}
