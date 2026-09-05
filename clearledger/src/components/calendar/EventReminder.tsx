import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bell } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import * as workService from '@/services/workService'
import type { CalendarEvent } from '@/services/workService'

const dateTime = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' })

export function EventReminder({ companyId, event }: { companyId: string; event: CalendarEvent }) {
  const qc = useQueryClient()
  const [minutes, setMinutes] = useState(15)
  const targetRef = 'event:' + event.id
  const query = useQuery({
    queryKey: ['reminders', companyId, targetRef],
    queryFn: () => workService.listReminders(companyId, { targetRef }),
  })
  const reminders = query.data?.items ?? []
  const save = useMutation({
    mutationFn: () => {
      const remindAt = new Date(new Date(event.starts_at).getTime() - minutes * 60_000).toISOString()
      const existing = reminders.find(row => !row.fired_at)
      return existing
        ? workService.reminderAction(companyId, existing.id, { remindAt })
        : workService.createReminder(companyId, { targetRef, remindAt, note: event.title })
    },
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['reminders'] }); toast.success('Личное напоминание сохранено') },
    onError: (error: Error) => toast.error(error.message || 'Не удалось сохранить напоминание'),
  })
  const remove = useMutation({
    mutationFn: (id: string) => workService.reminderAction(companyId, id, { done: true }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['reminders'] }); toast.success('Напоминание снято') },
    onError: (error: Error) => toast.error(error.message || 'Не удалось снять напоминание'),
  })
  const future = new Date(event.starts_at).getTime() - minutes * 60_000 > Date.now()
  return <section aria-label="Личное напоминание" className="space-y-2 border-t border-border pt-3">
    <p className="flex items-center gap-2 text-sm font-medium"><Bell className="h-4 w-4" />Напомнить мне</p>
    {query.isError ? <div role="alert" className="text-sm">Не удалось проверить ваши напоминания. <Button variant="ghost" size="sm" onClick={() => void query.refetch()}>Повторить</Button></div> : <>
      <div className="flex flex-wrap items-center gap-2">
        <select aria-label="Когда напомнить о встрече" value={minutes} onChange={e => setMinutes(Number(e.target.value))} className="h-10 rounded-md border border-input bg-background px-3 text-base sm:text-sm">
          {[5, 15, 30, 60, 1440].map(value => <option key={value} value={value}>{value === 1440 ? 'За день' : `За ${value} мин`}</option>)}
        </select>
        <Button variant="outline" disabled={!future || query.isFetching || save.isPending || remove.isPending} onClick={() => save.mutate()}>{reminders.some(row => !row.fired_at) ? 'Изменить напоминание' : 'Поставить напоминание'}</Button>
      </div>
      {!future && <p className="text-sm text-muted-foreground">Это время уже прошло. Выберите более позднее напоминание.</p>}
      {reminders.map(row => <div key={row.id} className="flex flex-wrap items-center gap-2 text-sm">
        <span className="flex-1">{dateTime.format(new Date(row.remind_at))}{row.fired_at ? ' · уже сработало' : ''}</span>
        <Button variant="ghost" size="sm" disabled={remove.isPending || save.isPending} onClick={() => remove.mutate(row.id)}>Снять</Button>
      </div>)}
      <p className="text-sm text-muted-foreground">Напоминание только для вас, на указанную дату и время. При переносе встречи его можно изменить здесь.</p>
    </>}
  </section>
}
