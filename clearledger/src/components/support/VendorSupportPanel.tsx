/**
 * Разговор с технической поддержкой поставщика программы — из своего пространства.
 *
 * Замысел МАГа: наши инженеры заведены у клиента и работают внутри его контура,
 * но когда клиент ПИШЕТ нам, разговор обязан идти в нашем пространстве — там
 * очередь дежурных и история по всем клиентам. Отсюда мост: человек пишет здесь,
 * реплика уезжает к нам и встаёт в очередь оператора рядом со звонками, ответ
 * возвращается в это же обращение.
 *
 * Единица разговора — ОБРАЩЕНИЕ, а не поток сообщений (docs/BRIDGE.md §4.1).
 * Плоская лента отвечала «что писали», но не отвечала «сколько у меня открытых
 * вопросов и чей сейчас ход»; номер и состояние приходят с той стороны, где
 * работа и делается.
 *
 * Панель показывается только когда связь включена (адрес и ключ на месте). Не
 * включена — остаётся прежний выход: чат приложения и телефон куратора, потому
 * что «написать некому» человек должен узнать до того, как напишет.
 */
import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, ArrowLeft, Loader2, LifeBuoy, Plus, Send } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { formatDateTime } from '@/lib/formatDate'
import {
  listTopics, openTopic, partnerFeed, sendToTopic, topicFeed,
  TOPIC_STATE_NAME, type PartnerMessage, type PartnerSpaceRef, type TopicState,
} from '@/services/partnerSpaceService'

/** Ответ приходит мостом, а не веб-сокетом: опрос — честная цена за то, что у
 *  поддержки и у клиента разные контейнеры и общей шины между ними нет. */
const POLL_MS = 20_000

const STATE_STYLE: Record<TopicState, string> = {
  new: 'border-border/60 bg-secondary/60 text-muted-foreground',
  in_progress: 'border-primary/30 bg-primary/10 text-primary',
  waiting: 'border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-400',
  resolved: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400',
  closed: 'border-border/60 bg-secondary/60 text-muted-foreground',
}

function StateBadge({ state }: { state: TopicState }) {
  return (
    <span className={`shrink-0 rounded-md border px-1.5 py-0.5 text-[11px] ${STATE_STYLE[state]}`}>
      {TOPIC_STATE_NAME[state]}
    </span>
  )
}

function Header({ back, title, hint }: {
  back?: () => void; title: string; hint: string
}) {
  return (
    <div className="flex items-center gap-2 border-b border-border/60 px-4 py-2.5">
      {back ? (
        <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0" onClick={back}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
      ) : (
        <LifeBuoy className="h-4 w-4 shrink-0 text-primary" />
      )}
      <div className="min-w-0">
        <div className="truncate text-sm font-medium text-foreground">{title}</div>
        <div className="truncate text-xs text-muted-foreground">{hint}</div>
      </div>
    </div>
  )
}

function Feed({ messages, vendor, loading }: {
  messages: PartnerMessage[]; vendor: PartnerSpaceRef; loading: boolean
}) {
  const bottom = useRef<HTMLDivElement>(null)
  useEffect(() => { bottom.current?.scrollIntoView({ block: 'end' }) }, [messages.length])

  if (loading) {
    return (
      <div className="flex items-center gap-2 px-4 py-6 text-xs text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />Открываю переписку…
      </div>
    )
  }
  return (
    <div className="min-h-0 flex-1 space-y-2 overflow-y-auto px-4 py-3">
      {messages.map((m) => (
        <div key={m.id} className={m.direction === 'out' ? 'flex justify-end' : 'flex justify-start'}>
          <div className={`max-w-[85%] rounded-xl border px-3 py-2 text-sm ${
            m.direction === 'out'
              ? 'border-primary/30 bg-primary/10 dark:bg-primary/20'
              : 'border-border/60 bg-secondary/50'}`}>
            <div className="mb-0.5 flex items-baseline gap-2 text-[11px] text-muted-foreground">
              <span className="font-medium text-foreground/80">
                {m.direction === 'out' ? (m.authorName || 'Вы') : (m.authorName || vendor.name)}
              </span>
              {m.createdAt && <span>{formatDateTime(m.createdAt)}</span>}
            </div>
            <div className="whitespace-pre-wrap break-words text-foreground">{m.body}</div>
            {/* Не дошедшее видно сразу: реплика осталась у нас, и человек должен
                знать это, а не думать, что поддержка молчит. */}
            {m.direction === 'out' && !m.delivered && (
              <div className="mt-1 flex items-start gap-1 text-[11px] text-amber-600 dark:text-amber-400">
                <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
                <span>{m.error || 'Не доставлено, попробуйте отправить ещё раз'}</span>
              </div>
            )}
          </div>
        </div>
      ))}
      <div ref={bottom} />
    </div>
  )
}

function Composer({ onSend, pending, error, placeholder }: {
  onSend: (text: string) => void; pending: boolean; error?: string; placeholder: string
}) {
  const [text, setText] = useState('')
  const submit = () => { const t = text.trim(); if (t) { onSend(t); setText('') } }
  return (
    <div className="border-t border-border/60 p-3">
      <Textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={placeholder}
        rows={3}
        className="resize-none text-sm"
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) submit()
        }}
      />
      <div className="mt-2 flex items-center justify-between gap-2">
        <span className="text-[11px] text-muted-foreground">Ctrl + Enter — отправить</span>
        <Button size="sm" className="gap-2" disabled={!text.trim() || pending} onClick={submit}>
          {pending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
          Отправить
        </Button>
      </div>
      {error && <p className="mt-2 text-xs text-red-600 dark:text-red-400">{error}</p>}
    </div>
  )
}

/** Открытое обращение: лента и ответ в ту же ветку. */
function TopicView({ vendor, companyId, topicCode, back }: {
  vendor: PartnerSpaceRef; companyId: string; topicCode: string; back: () => void
}) {
  const qc = useQueryClient()
  const feed = useQuery({
    queryKey: ['partner-topic', vendor.code, topicCode, companyId],
    queryFn: () => topicFeed(vendor.code, topicCode, companyId),
    refetchInterval: POLL_MS,
  })
  const send = useMutation({
    mutationFn: (body: string) => sendToTopic(vendor.code, topicCode, companyId, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['partner-topic', vendor.code, topicCode, companyId] })
      qc.invalidateQueries({ queryKey: ['partner-topics', vendor.code, companyId] })
    },
  })
  const topic = feed.data?.topic

  return (
    <div className="flex h-full min-h-0 flex-col">
      <Header
        back={back}
        title={topic?.title || 'Обращение'}
        hint={[
          topic?.number ? `№ ${topic.number}` : null,
          topic ? TOPIC_STATE_NAME[topic.state] : null,
          topic?.subjectLabel,
        ].filter(Boolean).join(' · ') || vendor.name}
      />
      <Feed messages={feed.data?.messages || []} vendor={vendor} loading={feed.isLoading} />
      <Composer
        onSend={(t) => send.mutate(t)} pending={send.isPending}
        error={send.isError ? ((send.error as Error).message || 'Не удалось отправить') : undefined}
        placeholder="Дополнить обращение"
      />
    </div>
  )
}

/** Прежняя переписка «обо всём» — до появления обращений. Только чтение: новое
 *  пишется обращением, у которого есть тема и состояние. */
function GeneralView({ vendor, companyId, back }: {
  vendor: PartnerSpaceRef; companyId: string; back: () => void
}) {
  const feed = useQuery({
    queryKey: ['partner-feed', vendor.code, companyId],
    queryFn: () => partnerFeed(vendor.code, companyId),
    refetchInterval: POLL_MS,
  })
  return (
    <div className="flex h-full min-h-0 flex-col">
      <Header back={back} title="Прежняя переписка"
        hint="История до появления обращений — только для чтения" />
      <Feed messages={feed.data?.messages || []} vendor={vendor} loading={feed.isLoading} />
    </div>
  )
}

/** Новое обращение: тема отдельно от текста — по ней его различают обе стороны. */
function NewTopicForm({ vendor, companyId, done }: {
  vendor: PartnerSpaceRef; companyId: string; done: (code: string) => void
}) {
  const qc = useQueryClient()
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const open = useMutation({
    mutationFn: () => openTopic(vendor.code, companyId, { title: title.trim(), body: body.trim() }),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ['partner-topics', vendor.code, companyId] })
      done(res.code)
    },
  })
  return (
    <div className="flex h-full min-h-0 flex-col">
      <Header back={() => done('')} title="Новое обращение"
        hint={`Уйдёт в ${vendor.name}`} />
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">Тема</label>
          <Input value={title} onChange={(e) => setTitle(e.target.value)}
            placeholder="Коротко: что не работает" className="text-sm" />
        </div>
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">Что случилось</label>
          <Textarea value={body} onChange={(e) => setBody(e.target.value)} rows={6}
            className="resize-none text-sm"
            placeholder="Экран, шаги и время — по ним поддержка найдёт событие быстрее, чем по одному «не работает»." />
        </div>
        <Button className="w-full gap-2" disabled={!title.trim() || !body.trim() || open.isPending}
          onClick={() => open.mutate()}>
          {open.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
          Отправить обращение
        </Button>
        {open.isError && (
          <p className="text-xs text-red-600 dark:text-red-400">
            {(open.error as Error).message || 'Не удалось отправить'}
          </p>
        )}
      </div>
    </div>
  )
}

export function VendorSupportPanel({ vendor, companyId }: { vendor: PartnerSpaceRef; companyId: string }) {
  // '' — список, 'general' — прежняя переписка, 'new' — форма, иначе код обращения.
  const [view, setView] = useState('')

  const topics = useQuery({
    queryKey: ['partner-topics', vendor.code, companyId],
    queryFn: () => listTopics(vendor.code, companyId),
    refetchInterval: POLL_MS,
  })

  if (view === 'new') {
    return <NewTopicForm vendor={vendor} companyId={companyId} done={(code) => setView(code)} />
  }
  if (view === 'general') {
    return <GeneralView vendor={vendor} companyId={companyId} back={() => setView('')} />
  }
  if (view) {
    return <TopicView vendor={vendor} companyId={companyId} topicCode={view} back={() => setView('')} />
  }

  const items = topics.data?.items || []
  return (
    <div className="flex h-full min-h-0 flex-col">
      <Header title={vendor.name}
        hint="Вопросы и ошибки по работе программы — сюда. Ответ придёт в обращение." />

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
        {topics.isLoading ? (
          <div className="flex items-center gap-2 py-6 text-xs text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />Открываю обращения…
          </div>
        ) : items.length === 0 ? (
          <p className="px-1 py-6 text-center text-sm text-muted-foreground">
            Обращений пока нет. Опишите, что случилось: экран, шаги и время — по ним
            поддержка найдёт событие быстрее, чем по одному «не работает».
          </p>
        ) : (
          <div className="space-y-1.5">
            {items.map((t) => (
              <button key={t.code} onClick={() => setView(t.code)}
                className="flex w-full items-start gap-2 rounded-xl border border-border/60 bg-secondary/40 px-3 py-2.5 text-left transition-colors hover:border-primary/40 hover:bg-accent">
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium text-foreground">{t.title}</div>
                  <div className="truncate text-[11px] text-muted-foreground">
                    {[t.number ? `№ ${t.number}` : null, t.subjectLabel,
                      t.lastMessageAt ? formatDateTime(t.lastMessageAt) : null]
                      .filter(Boolean).join(' · ')}
                  </div>
                </div>
                <StateBadge state={t.state} />
              </button>
            ))}
          </div>
        )}

        {/* История до обращений не пропадает — но и не мешает: пункт появляется,
            только если такая переписка была. */}
        {(topics.data?.general || 0) > 0 && (
          <button onClick={() => setView('general')}
            className="mt-2 w-full rounded-xl border border-dashed border-border/60 px-3 py-2 text-left text-xs text-muted-foreground hover:border-primary/40 hover:text-foreground">
            Прежняя переписка · {topics.data?.general}
          </button>
        )}
      </div>

      <div className="border-t border-border/60 p-3">
        <Button className="w-full gap-2" onClick={() => setView('new')}>
          <Plus className="h-4 w-4" />Новое обращение
        </Button>
      </div>
    </div>
  )
}
