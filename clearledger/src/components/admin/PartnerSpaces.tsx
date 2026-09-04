/**
 * Пространства-соседи: кого мы обслуживаем и кто обслуживает нас.
 *
 * Не путать с разделом «Компании»: там сторонние организации, ДОПУЩЕННЫЕ в это
 * пространство своими людьми. Здесь — другие пространства целиком, со своим
 * Ядром, людьми и данными; общего у нас с ними ровно два канала: разговор
 * поддержки и пропуск инженера.
 *
 * Уровень контейнера, а не организации: связь между пространствами заводит тот,
 * кто владеет обоими концами, — он же держит ключи.
 */
import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  ExternalLink, ListChecks, Loader2, MessagesSquare, Network, ShieldCheck,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { useCompany } from '@/contexts/CompanyContext'
import { formatDateTime } from '@/lib/formatDate'
import {
  listPartnerSpaces, listTopics, openTopic, partnerFeed, sendToTopic,
  TOPIC_STATE_NAME, visitPartnerSpace,
} from '@/services/partnerSpaceService'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import * as tasksService from '@/services/tasksService'

export function PartnerSpaces() {
  const { companyId } = useCompany()
  const [openFeed, setOpenFeed] = useState<string | null>(null)
  const [openTopics, setOpenTopics] = useState<string | null>(null)
  // Разговор может начать и поддержка: предупредить о работах, вернуться к
  // старому случаю, попросить сведения. До этого первое слово было только за
  // клиентом, и написать ему из своего пространства было нечем.
  const [writeTo, setWriteTo] = useState<string | null>(null)
  const [draft, setDraft] = useState({ title: '', body: '' })
  const [replyTo, setReplyTo] = useState<{ partner: string; topic: string } | null>(null)
  const [reply, setReply] = useState('')

  const spaces = useQuery({
    queryKey: ['partner-spaces', companyId],
    queryFn: () => listPartnerSpaces(companyId),
    enabled: !!companyId,
  })
  const feed = useQuery({
    queryKey: ['partner-feed', openFeed, companyId],
    queryFn: () => partnerFeed(openFeed!, companyId),
    enabled: !!openFeed && !!companyId,
  })
  const topics = useQuery({
    queryKey: ['partner-topics', openTopics, companyId],
    queryFn: () => listTopics(openTopics!, companyId),
    enabled: !!openTopics && !!companyId,
  })
  // Задача по обращению — наша работа, но со ссылкой на разговор: из неё
  // исполнитель спрашивает клиента, не выходя из задачи (docs/BRIDGE.md §4.4).
  const makeTask = useMutation({
    mutationFn: (t: { id: string; title: string }) => tasksService.createTask({
      companyId, title: t.title.slice(0, 300),
      subjectRef: `partner_topic:${t.id}`,
    }),
    onSuccess: (task) => toast.success(`Задача №${task.number} поставлена`),
    onError: (e: Error) => toast.error(e.message || 'Задача не поставлена'),
  })
  const write = useMutation({
    mutationFn: (code: string) => openTopic(code, companyId,
      { title: draft.title.trim(), body: draft.body.trim() }),
    onSuccess: (res) => {
      setDraft({ title: '', body: '' })
      setWriteTo(null)
      if (res.error) toast.warning(`Записано, но не доставлено: ${res.error}`)
      else toast.success('Обращение отправлено в пространство клиента')
      topics.refetch()
    },
    onError: (e: Error) => toast.error(e.message || 'Не отправлено'),
  })
  const answer = useMutation({
    mutationFn: (v: { partner: string; topic: string; body: string }) =>
      sendToTopic(v.partner, v.topic, companyId, v.body),
    onSuccess: (res) => {
      setReply('')
      setReplyTo(null)
      if (res.error) toast.warning(`Записано, но не доставлено: ${res.error}`)
      else toast.success('Ответ ушёл клиенту')
      topics.refetch()
    },
    onError: (e: Error) => toast.error(e.message || 'Не отправлено'),
  })
  const visit = useMutation({
    mutationFn: (code: string) => visitPartnerSpace(code, companyId),
    // Пропуск живёт две минуты — открываем сразу, а не даём ссылку «на потом».
    onSuccess: (res) => window.open(res.url, '_blank', 'noopener'),
  })

  const items = spaces.data?.items || []

  return (
    <div className="space-y-4 p-4">
      <div className="flex items-start gap-3">
        <Network className="mt-0.5 h-5 w-5 shrink-0 text-primary" />
        <div>
          <h2 className="text-base font-semibold text-foreground">Пространства</h2>
          <p className="text-sm text-muted-foreground">
            Соседние пространства экосистемы: чьи обращения приходят к нам и куда
            наши инженеры входят своей учётной записью.
          </p>
        </div>
      </div>

      {spaces.isLoading ? (
        <div className="flex items-center gap-2 p-4 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />Читаю реестр…
        </div>
      ) : items.length === 0 ? (
        <p className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">
          Связей нет. Пространства соединяются парой записей — по одной с каждой
          стороны — и ключом, который живёт в окружении стека, а не в базе.
        </p>
      ) : items.map((p) => (
        <div key={p.code} className="rounded-lg border border-border bg-card p-3">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="font-medium text-foreground">{p.name}</span>
            <span className="rounded bg-secondary px-1.5 py-0.5 text-xs text-muted-foreground">
              {p.role === 'client' ? 'наш клиент' : 'наш поставщик'}
            </span>
            {p.linked ? (
              <span className="inline-flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400">
                <ShieldCheck className="h-3.5 w-3.5" />связь включена
              </span>
            ) : (
              <span className="text-xs text-amber-600 dark:text-amber-400">нет адреса или ключа</span>
            )}
            {p.lastSeenAt && (
              <span className="text-xs text-muted-foreground">последний обмен {formatDateTime(p.lastSeenAt)}</span>
            )}
            <div className="ml-auto flex gap-2">
              <Button size="sm" variant="outline" className="gap-1.5"
                onClick={() => setOpenTopics(openTopics === p.code ? null : p.code)}>
                <ListChecks className="h-4 w-4" />Обращения
              </Button>
              <Button size="sm" variant="outline" className="gap-1.5" disabled={!p.linked}
                onClick={() => { setWriteTo(writeTo === p.code ? null : p.code); setOpenTopics(null) }}>
                <MessagesSquare className="h-4 w-4" />Написать
              </Button>
              <Button size="sm" variant="outline" className="gap-1.5"
                onClick={() => setOpenFeed(openFeed === p.code ? null : p.code)}>
                <MessagesSquare className="h-4 w-4" />Переписка
              </Button>
              {/* Входим только к клиенту: у поставщика своё пространство, и наш
                  пропуск там ничего не значит — он выписан нашим ключом. */}
              {p.role === 'client' && (
                <Button size="sm" className="gap-1.5" disabled={!p.linked || visit.isPending}
                  onClick={() => visit.mutate(p.code)}>
                  {visit.isPending ? <Loader2 className="h-4 w-4 animate-spin" />
                    : <ExternalLink className="h-4 w-4" />}
                  Войти
                </Button>
              )}
            </div>
          </div>

          {writeTo === p.code && (
            <div className="mt-3 space-y-2 border-t border-border/60 pt-3">
              <Input value={draft.title} maxLength={300}
                onChange={(e) => setDraft({ ...draft, title: e.target.value })}
                placeholder="Тема: коротко, её увидит клиент" className="text-sm" />
              <Textarea value={draft.body} rows={4} className="resize-none text-sm"
                onChange={(e) => setDraft({ ...draft, body: e.target.value })}
                placeholder="Что сообщить клиенту" />
              <div className="flex justify-end">
                <Button size="sm" disabled={!draft.title.trim() || !draft.body.trim() || write.isPending}
                  onClick={() => write.mutate(p.code)}>
                  {write.isPending ? 'Отправляю…' : 'Отправить'}
                </Button>
              </div>
            </div>
          )}

          {openTopics === p.code && (
            <div className="mt-3 space-y-1.5 border-t border-border/60 pt-3">
              {topics.isLoading ? (
                <div className="text-xs text-muted-foreground">Читаю обращения…</div>
              ) : topics.data?.items.length ? topics.data.items.map((t) => (
                <div key={t.code} className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
                  <span className="text-foreground">{t.title}</span>
                  <span className="rounded bg-secondary px-1.5 py-0.5 text-xs text-muted-foreground">
                    {TOPIC_STATE_NAME[t.state]}
                  </span>
                  {t.number && <span className="text-xs text-muted-foreground">№ {t.number}</span>}
                  {t.subjectLabel && (
                    <span className="text-xs text-muted-foreground">· {t.subjectLabel}</span>
                  )}
                  {t.lastMessageAt && (
                    <span className="text-xs text-muted-foreground">
                      · {formatDateTime(t.lastMessageAt)}
                    </span>
                  )}
                  <Button size="sm" variant="ghost" className="ml-auto h-7 px-2 text-xs"
                    onClick={() => setReplyTo(replyTo?.topic === t.code ? null
                      : { partner: p.code, topic: t.code })}>
                    Ответить
                  </Button>
                  <Button size="sm" variant="ghost" className="h-7 px-2 text-xs"
                    disabled={makeTask.isPending}
                    onClick={() => makeTask.mutate({ id: t.id, title: t.title })}>
                    Поставить задачу
                  </Button>
                  {replyTo?.topic === t.code && (
                    <div className="w-full space-y-2 pt-1">
                      <Textarea value={reply} rows={3} className="resize-none text-sm"
                        onChange={(e) => setReply(e.target.value)}
                        placeholder="Ответ клиенту — уйдёт в это обращение" />
                      <div className="flex justify-end">
                        <Button size="sm" disabled={!reply.trim() || answer.isPending}
                          onClick={() => answer.mutate({ partner: p.code, topic: t.code, body: reply.trim() })}>
                          {answer.isPending ? 'Отправляю…' : 'Ответить'}
                        </Button>
                      </div>
                    </div>
                  )}
                </div>
              )) : <div className="text-xs text-muted-foreground">Обращений ещё не было.</div>}
            </div>
          )}

          {openFeed === p.code && (
            <div className="mt-3 space-y-2 border-t border-border/60 pt-3">
              {feed.isLoading ? (
                <div className="text-xs text-muted-foreground">Открываю переписку…</div>
              ) : (feed.data?.messages.length ? feed.data.messages.map((m) => (
                <div key={m.id} className="text-sm">
                  <span className="text-xs text-muted-foreground">
                    {m.direction === 'out' ? 'мы' : 'они'} · {m.authorName || '—'}
                    {m.createdAt ? ` · ${formatDateTime(m.createdAt)}` : ''}
                  </span>
                  <div className="text-foreground">{m.body}</div>
                </div>
              )) : <div className="text-xs text-muted-foreground">Разговора ещё не было.</div>)}
            </div>
          )}
        </div>
      ))}

      {visit.isError && (
        <p className="text-sm text-red-600 dark:text-red-400">
          {(visit.error as Error).message || 'Пропуск не выписан'}
        </p>
      )}
    </div>
  )
}

export default PartnerSpaces
