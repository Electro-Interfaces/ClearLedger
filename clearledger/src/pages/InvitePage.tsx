/**
 * Страница приглашения для того, у кого нет учётной записи.
 *
 * У гостя нет календаря — у него есть эта страница. Он видит одну встречу,
 * отвечает, предлагает другое время и забирает файл для своего календаря.
 * Состав встречи ему не показывается: кто ещё позван — сведение о компании, а
 * не о его участии.
 *
 * Материалы — только те, что открыли явно, и каждый по своей ссылке: приглашение
 * само по себе не даёт доступа ни к чему.
 */
import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarDays, Check, Clock3, Download, MapPin, Video } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { get, post } from '@/services/apiClient'
import * as workService from '@/services/workService'
import { cn } from '@/lib/utils'

interface Приглашение {
  title: string
  description: string | null
  starts_at: string
  ends_at: string
  all_day: boolean
  tz: string
  location: string | null
  conference_url: string | null
  cancelled: boolean
  cancel_reason: string | null
  organizer: string | null
  you: {
    name: string | null
    email: string
    response: 'pending' | 'accepted' | 'declined' | 'tentative'
    comment: string | null
    proposed_starts_at: string | null
    proposed_ends_at: string | null
  }
  materials: { title: string; url: string }[]
}

const ОТВЕТЫ = [
  { key: 'accepted', label: 'Буду' },
  { key: 'tentative', label: 'Может быть' },
  { key: 'declined', label: 'Не буду' },
] as const

const когда = new Intl.DateTimeFormat('ru-RU', {
  weekday: 'long', day: 'numeric', month: 'long',
  hour: '2-digit', minute: '2-digit',
})

/** Местное значение для `datetime-local`: через `toISOString` оно уехало бы на
 *  величину часового пояса. */
const localInput = (d: Date) =>
  new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 16)

export function InvitePage() {
  const { token = '' } = useParams()
  const qc = useQueryClient()
  const [comment, setComment] = useState('')
  const [предлагаю, setПредлагаю] = useState(false)
  const [с, setС] = useState('')
  const [по, setПо] = useState('')

  const q = useQuery({
    queryKey: ['invite', token],
    queryFn: () => get<Приглашение>(`/api/invite/${token}`),
    enabled: !!token,
    retry: false,
  })

  const обновить = () => qc.invalidateQueries({ queryKey: ['invite', token] })

  const ответить = useMutation({
    mutationFn: (response: string) =>
      post(`/api/invite/${token}/respond`, { response, comment: comment || undefined }),
    onSuccess: () => { toast.success('Ответ принят'); void обновить() },
    onError: (e: Error) => toast.error(e.message || 'Не получилось ответить'),
  })

  const предложить = useMutation({
    mutationFn: () => post(`/api/invite/${token}/propose`, {
      starts_at: new Date(с).toISOString(),
      ends_at: new Date(по).toISOString(),
      comment: comment || undefined,
    }),
    onSuccess: () => {
      setПредлагаю(false)
      toast.success('Предложение отправлено организатору')
      void обновить()
    },
    onError: (e: Error) => toast.error(e.message || 'Не отправилось'),
  })

  const опрос = useQuery({
    queryKey: ['invite-poll', token],
    queryFn: () => workService.invitePoll(token),
    enabled: !!token,
    retry: false,
  })
  const голос = useMutation({
    mutationFn: (v: { optionId: string; vote: 'yes' | 'maybe' | 'no' }) =>
      workService.inviteVote(token, v.optionId, v.vote),
    onSuccess: () => {
      toast.success('Голос принят')
      void qc.invalidateQueries({ queryKey: ['invite-poll', token] })
    },
    onError: (e: Error) => toast.error(e.message || 'Голос не принят'),
  })

  if (q.isLoading) {
    return <Обёртка><p className="text-sm text-muted-foreground">Открываю…</p></Обёртка>
  }
  if (q.isError || !q.data) {
    // На «нет», «отозвана» и «истекла» ответ одинаковый: подсказывать, что
    // ссылка когда-то существовала, незачем.
    return (
      <Обёртка>
        <h1 className="text-lg font-semibold">Приглашение недоступно</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Ссылка не найдена или отозвана. Запросите новую у организатора.
        </p>
      </Обёртка>
    )
  }

  const и = q.data
  const начало = new Date(и.starts_at)
  const конец = new Date(и.ends_at)

  return (
    <Обёртка>
      <header className="space-y-1">
        <h1 className={cn('text-xl font-semibold',
          и.cancelled && 'text-muted-foreground line-through')}>
          {и.title}
        </h1>
        {и.cancelled && (
          <p className="text-sm text-red-600 dark:text-red-400">
            Встреча отменена{и.cancel_reason ? `: ${и.cancel_reason}` : ''}
          </p>
        )}
        {и.organizer && (
          <p className="text-sm text-muted-foreground">Собирает: {и.organizer}</p>
        )}
      </header>

      <dl className="space-y-2 rounded-lg border border-border p-3 text-sm">
        <div className="flex items-start gap-2">
          <CalendarDays className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
          <span className="first-letter:uppercase">
            {и.all_day ? когда.format(начало).replace(/,.*$/, '') : когда.format(начало)}
            {!и.all_day && ` — ${new Intl.DateTimeFormat('ru-RU', {
              hour: '2-digit', minute: '2-digit',
            }).format(конец)}`}
          </span>
        </div>
        {и.location && (
          <div className="flex items-start gap-2">
            <MapPin className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
            <span>{и.location}</span>
          </div>
        )}
        {и.conference_url && !и.cancelled && (
          <div className="flex items-start gap-2">
            <Video className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
            <a href={и.conference_url} target="_blank" rel="noreferrer"
              className="text-primary hover:underline">Подключиться</a>
          </div>
        )}
      </dl>

      {и.description && (
        <p className="whitespace-pre-wrap text-sm text-foreground">{и.description}</p>
      )}

      {и.materials.length > 0 && (
        <section className="space-y-1.5">
          <h2 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Материалы
          </h2>
          <ul className="space-y-1">
            {и.materials.map((m) => (
              <li key={m.url}>
                <a href={m.url} className="text-sm text-primary hover:underline">
                  {m.title}
                </a>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Опрос времени. Без него согласование с партнёром теряет смысл ровно
          там, где он нужнее всего: время выбирают с внешним участником, а не
          между своими. */}
      {опрос.data?.status === 'poll' && (опрос.data.options.length > 0) && (
        <section className="space-y-1.5">
          <h2 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Выберите удобное время
          </h2>
          <ul className="space-y-1.5">
            {опрос.data.options.map((o) => (
              <li key={o.id} className="flex flex-wrap items-center gap-2 text-sm">
                <span className="min-w-[10rem] flex-1 tabular-nums">
                  {когда.format(new Date(o.starts_at))}
                </span>
                <span className="flex items-center gap-1">
                  {([['yes', 'Подходит'], ['maybe', 'Возможно'],
                     ['no', 'Не подходит']] as const).map(([k, л]) => (
                    <Button key={k} size="sm" variant={o.my_vote === k ? 'default' : 'outline'}
                      disabled={голос.isPending}
                      onClick={() => голос.mutate({ optionId: o.id, vote: k })}>
                      {л}
                    </Button>
                  ))}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {!и.cancelled && опрос.data?.status !== 'poll' && (
        <section className="space-y-2">
          <div className="flex flex-wrap items-center gap-1.5">
            {ОТВЕТЫ.map((r) => (
              <Button key={r.key} size="sm" disabled={ответить.isPending}
                variant={и.you.response === r.key ? 'default' : 'outline'}
                onClick={() => ответить.mutate(r.key)}>
                {и.you.response === r.key && <Check className="mr-1 h-3.5 w-3.5" />}
                {r.label}
              </Button>
            ))}
            <Button size="sm" variant="ghost"
              onClick={() => {
                setС(localInput(начало))
                setПо(localInput(конец))
                setПредлагаю((v) => !v)
              }}>
              <Clock3 className="mr-1 h-3.5 w-3.5" />Предложить другое время
            </Button>
          </div>

          {и.you.proposed_starts_at && (
            <p className="text-xs text-amber-600 dark:text-amber-400">
              Вы предложили {когда.format(new Date(и.you.proposed_starts_at))}.
              Организатор решит, переносить ли встречу.
            </p>
          )}

          {предлагаю && (
            <div className="flex flex-wrap items-end gap-2 rounded-lg border border-border p-3">
              <label className="space-y-1 text-xs text-muted-foreground">
                Начало
                <Input type="datetime-local" value={с}
                  onChange={(e) => setС(e.target.value)} className="w-[210px]" />
              </label>
              <label className="space-y-1 text-xs text-muted-foreground">
                Конец
                <Input type="datetime-local" value={по}
                  onChange={(e) => setПо(e.target.value)} className="w-[210px]" />
              </label>
              <Button size="sm" disabled={!с || !по || предложить.isPending}
                onClick={() => предложить.mutate()}>Отправить</Button>
            </div>
          )}

          <Textarea value={comment} rows={2}
            onChange={(e) => setComment(e.target.value)}
            placeholder="Комментарий организатору — необязательно"
            className="text-sm" />
        </section>
      )}

      <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
        {/* Файл для своего календаря: без него человек прочтёт письмо и в нужный
            час будет занят другим. */}
        <a href={`/api/invite/${token}/ics`}
          className="inline-flex items-center gap-1.5 text-sm text-primary hover:underline">
          <Download className="h-3.5 w-3.5" />В свой календарь
        </a>
        <span className="ml-auto text-xs text-muted-foreground">{и.you.email}</span>
      </div>
    </Обёртка>
  )
}

function Обёртка({ children }: { children: React.ReactNode }) {
  return (
    <div className="mx-auto flex min-h-screen w-full max-w-2xl flex-col gap-4 p-6">
      {children}
    </div>
  )
}

export default InvitePage
