/**
 * Опрос времени: организатор предлагает варианты, участники голосуют.
 *
 * Опрос — не отдельная сущность рядом со встречей, а её состояние. Поэтому
 * гости, материалы, файл для чужого календаря и отмена продолжают работать тем
 * же кодом: выбрав вариант, организатор не создаёт встречу из опроса, а
 * проставляет ей время.
 *
 * Пока идёт опрос, встреча НЕ считается занятостью: шесть предложенных
 * вариантов заняли бы всем участникам полнедели, и подбор времени перестал бы
 * находить что-либо вовсе.
 *
 * Три-шесть вариантов — то, что человек способен сравнить. Двадцать означают,
 * что организатор не выбирал, а свалил выбор на других.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, ListChecks, Plus, X } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import * as workService from '@/services/workService'
import { cn } from '@/lib/utils'

const ГОЛОСА = [
  { key: 'yes', label: 'Подходит' },
  { key: 'maybe', label: 'Возможно' },
  { key: 'no', label: 'Не подходит' },
] as const

const когда = new Intl.DateTimeFormat('ru-RU', {
  weekday: 'short', day: 'numeric', month: 'short',
  hour: '2-digit', minute: '2-digit',
})

const localInput = (d: Date) =>
  new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 16)

export function PollPanel({ companyId, eventId, isOrganizer, durationMinutes = 60,
  onChanged }: {
  companyId: string
  eventId: string
  isOrganizer: boolean
  durationMinutes?: number
  onChanged: () => void
}) {
  const qc = useQueryClient()
  const [черновик, setЧерновик] = useState<string[]>([])

  const q = useQuery({
    queryKey: ['poll', companyId, eventId],
    queryFn: () => workService.readPoll(companyId, eventId),
    enabled: !!eventId,
  })
  const обновить = () => {
    void qc.invalidateQueries({ queryKey: ['poll', companyId, eventId] })
    onChanged()
  }

  const открыть = useMutation({
    mutationFn: () => workService.openPoll(companyId, eventId,
      черновик.filter(Boolean).map((с) => {
        const н = new Date(с)
        return {
          starts_at: н.toISOString(),
          ends_at: new Date(н.getTime() + durationMinutes * 60_000).toISOString(),
        }
      })),
    onSuccess: () => { setЧерновик([]); toast.success('Опрос открыт'); обновить() },
    onError: (e: Error) => toast.error(e.message || 'Опрос не открылся'),
  })

  const голос = useMutation({
    mutationFn: (v: { optionId: string; vote: 'yes' | 'maybe' | 'no' }) =>
      workService.votePoll(companyId, eventId, v.optionId, v.vote),
    onSuccess: обновить,
    onError: (e: Error) => toast.error(e.message || 'Голос не принят'),
  })

  const выбрать = useMutation({
    mutationFn: (optionId: string) => workService.pickPoll(companyId, eventId, optionId),
    onSuccess: () => {
      toast.success('Время выбрано. Согласия обнулены — участникам придёт вопрос заново')
      обновить()
    },
    onError: (e: Error) => toast.error(e.message || 'Не выбралось'),
  })

  const идёт = q.data?.status === 'poll'
  const варианты = q.data?.options ?? []

  return (
    <div className="space-y-2 rounded-md border border-border p-3">
      <h3 className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        <ListChecks className="h-3.5 w-3.5" />Опрос времени
      </h3>

      {идёт && варианты.length > 0 && (
        <ul className="space-y-1.5">
          {варианты.map((o) => (
            <li key={o.id} className="flex flex-wrap items-center gap-2 text-xs">
              <span className="min-w-[9rem] flex-1 tabular-nums">
                {когда.format(new Date(o.starts_at))}
              </span>
              <span className="text-muted-foreground">
                {o.votes.yes} за · {o.votes.maybe} может · {o.votes.no} нет
              </span>
              <span className="flex items-center gap-0.5">
                {ГОЛОСА.map((г) => (
                  <Button key={г.key} size="sm" variant="ghost"
                    disabled={голос.isPending}
                    className={cn('h-7 px-1.5 text-xs',
                      o.my_vote === г.key && 'bg-accent font-medium text-foreground')}
                    onClick={() => голос.mutate({ optionId: o.id, vote: г.key })}>
                    {г.label}
                  </Button>
                ))}
              </span>
              {isOrganizer && (
                <Button size="sm" variant="outline" className="h-7 px-2 text-xs"
                  disabled={выбрать.isPending}
                  onClick={() => выбрать.mutate(o.id)}>
                  <Check className="mr-1 h-3.5 w-3.5" />Выбрать
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}

      {!идёт && isOrganizer && (
        <div className="space-y-1.5">
          <p className="text-xs text-muted-foreground">
            Предложите 2–6 вариантов. Пока идёт опрос, встреча не занимает время
            в календарях: иначе варианты заняли бы всем полнедели.
          </p>
          {черновик.map((с, i) => (
            <div key={i} className="flex items-center gap-1.5">
              <Input type="datetime-local" value={с} className="h-8 w-[210px] text-xs"
                onChange={(e) => setЧерновик((v) =>
                  v.map((x, j) => (j === i ? e.target.value : x)))} />
              <Button size="sm" variant="ghost" className="h-8 px-1.5"
                onClick={() => setЧерновик((v) => v.filter((_, j) => j !== i))}>
                <X className="h-3.5 w-3.5" />
              </Button>
            </div>
          ))}
          <div className="flex items-center gap-1.5">
            <Button size="sm" variant="ghost" className="h-8 px-2 text-xs"
              disabled={черновик.length >= 8}
              onClick={() => setЧерновик((v) => {
                const база = new Date()
                база.setDate(база.getDate() + v.length + 1)
                база.setHours(10, 0, 0, 0)
                return [...v, localInput(база)]
              })}>
              <Plus className="mr-1 h-3.5 w-3.5" />Вариант
            </Button>
            {черновик.filter(Boolean).length >= 2 && (
              <Button size="sm" className="h-8 px-2 text-xs"
                disabled={открыть.isPending}
                onClick={() => открыть.mutate()}>Открыть опрос</Button>
            )}
          </div>
        </div>
      )}

      {!идёт && !isOrganizer && (
        <p className="text-xs text-muted-foreground">Опрос не открыт</p>
      )}
    </div>
  )
}

export default PollPanel
