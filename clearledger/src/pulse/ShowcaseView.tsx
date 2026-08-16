/**
 * Показ витрины — то, что видит получатель.
 *
 * Он не работает в пространстве: у него нет рабочих мест, разрезов и фильтров. Ему
 * нужно за минуту понять, в каком состоянии дело и что от него нужно. Поэтому здесь
 * нет ни одного элемента управления, кроме выбора витрины: всё, что можно нажать,
 * рождает вопрос «а что будет, если нажму», и на витрине это лишнее.
 *
 * Подпись обязательна: кто отвечает за цифры и на какую дату они верны. «Данные из
 * системы» — не ответ, когда картину показывают наружу.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ArrowLeft, MessageSquare, ShieldCheck } from 'lucide-react'

import { Card, CardContent } from '@/components/ui/card'
import { MetricTile } from '@/components/ui/metric-tile'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import { useCompany } from '@/contexts/CompanyContext'
import {
  getPulseMyViews, getPulseViewData, replyPulseRequest, sendPulseFeedback,
  type PulseViewData,
} from './pulseService'
import { PulseError, PulseLoading } from './parts'

/** Сетка блоков: то же полотно, что у витрины, но без её рамки.
 *
 * Экраны «Бизнеса» в бухгалтерском пространстве показывают ровно эти карточки:
 * данные считает одна ручка, а второй набор вёрстки разошёлся бы с первым.
 */
export function BlockGrid({ blocks, onReply }: {
  blocks: PulseViewData['blocks']
  onReply?: (requestId: string) => React.ReactNode
}) {
  return (
      <div className="grid gap-3 md:grid-cols-2">
          {blocks.map((b) => (
            <Card key={b.key}>
              <CardContent className="p-3 space-y-2">
                <div className="text-sm font-medium">{b.title}</div>
                {b.hint && <div className="text-[11px] text-muted-foreground">{b.hint}</div>}
  
                {b.metrics.length > 0 && (
                  <div className="grid gap-2 sm:grid-cols-2">
                    {b.metrics.map((m) => (
                      <MetricTile key={m.label} label={m.label} value={m.value}
                        tone={m.tone ?? undefined} hint={m.delta?.text} />
                    ))}
                  </div>
                )}
  
                {b.items.length > 0 && (
                  <div className="divide-y divide-border/60">
                    {b.items.map((it, i) => (
                      <div key={i} className="flex flex-wrap items-start justify-between gap-2 py-1.5">
                        <div className="min-w-0 flex-1">
                          <div className="text-[13px]">{it.title}</div>
                          {it.detail && (
                            <div className="text-[11px] text-muted-foreground">{it.detail}</div>
                          )}
                        </div>
                        {it.amount && (
                          <div className="shrink-0 text-[13px] tabular-nums">{it.amount}</div>
                        )}
                        {it.requestId && onReply ? onReply(it.requestId) : null}
                      </div>
                    ))}
                  </div>
                )}
  
                {b.note && <div className="text-[11px] text-muted-foreground">{b.note}</div>}
                {b.link && (
                  <a href={b.link.href}
                    className="inline-flex items-center gap-1 text-[12px] text-primary
                               hover:underline">
                    {b.link.title} →
                  </a>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
  )
}

/**
 * Полотно витрины: то, что видит получатель.
 *
 * Отделено от загрузки намеренно — этим же компонентом рисуется публичная страница
 * по ссылке. Пока копий было две, они разошлись: на публичной потерялся тон
 * предупреждения, и одна и та же витрина выглядела спокойнее, чем на самом деле.
 *
 * Действия (ответ по строке, обращение) приходят снаружи: по ссылке их нет —
 * аноним смотрит, но не действует.
 */
export function ShowcaseCanvas({ data, onReply, onRefresh }: {
  data: PulseViewData
  onReply?: (requestId: string) => React.ReactNode
  onRefresh?: () => void
}) {
  const d = data
  return (
    <div className="space-y-3">
      <div>
        <div className="text-base font-semibold">{d.name}</div>
        <div className="text-[12px] text-muted-foreground">
          {d.company}{d.audience ? ` · для: ${d.audience}` : ''}
          {d.periodLabel ? ` · цифры ${d.periodLabel}` : ''}
          {d.owner ? ` · отвечает: ${d.owner}` : ''}
        </div>
      </div>

      <BlockGrid blocks={d.blocks} onReply={onReply} />

      {d.canWrite && onRefresh !== undefined && <FeedbackBox viewId={d.id} />}

      {/* Подпись витрины: дата и ответственный. Цифра без них наружу не идёт. */}
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border
                      px-3 py-2 text-[11px] text-muted-foreground">
        <ShieldCheck className="h-3.5 w-3.5" />
        <span>Данные на {ruDate(d.asOf)}</span>
        {d.owner && <span>· за цифры отвечает: {d.owner}</span>}
        {d.note && <span>· {d.note}</span>}
      </div>
    </div>
  )
}

/** ISO-дата в привычный вид: наружу «15.08.2026», а не «2026-08-15». */
function ruDate(v: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(v ?? '')
  return m ? `${m[3]}.${m[2]}.${m[1]}` : (v ?? '')
}

/** Витрина по id: загрузка + действия. Используется и в предпросмотре. */
export function ShowcaseBody({ viewId, onBack }: { viewId: string; onBack?: () => void }) {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const q = useQuery({
    queryKey: ['pulse-view-data', companyId, viewId],
    queryFn: () => getPulseViewData(companyId, viewId),
  })

  if (q.isError) return <PulseError what="витрину" onRetry={() => q.refetch()} />
  if (!q.data) return <PulseLoading what="витрину" />
  const refresh = () => qc.invalidateQueries({ queryKey: ['pulse-view-data', companyId, viewId] })

  return (
    <div className="space-y-2">
      {onBack && (
        <div className="flex justify-end">
          <Button size="sm" variant="ghost" className="h-7 gap-1" onClick={onBack}>
            <ArrowLeft className="h-3.5 w-3.5" /> К настройке
          </Button>
        </div>
      )}
      <ShowcaseCanvas data={q.data} onRefresh={refresh}
        onReply={(requestId) => (
          <RequestReply viewId={q.data.id} requestId={requestId} onDone={refresh} />
        )} />
    </div>
  )
}

/** Раздел получателя: его витрины и ничего больше. */
export function ShowcaseView() {
  const { companyId } = useCompany()
  const [openId, setOpenId] = useState<string | null>(null)
  const q = useQuery({
    queryKey: ['pulse-my-views', companyId],
    queryFn: () => getPulseMyViews(companyId),
  })

  if (q.isError) return <PulseError what="ваши витрины" onRetry={() => q.refetch()} />
  if (!q.data) return <PulseLoading what="витрин" />
  const views = q.data.views

  if (views.length === 0) {
    return (
      <Card><CardContent className="py-10 text-center text-sm text-muted-foreground">
        Вам пока не назначено ни одной витрины.
      </CardContent></Card>
    )
  }

  // Одна витрина — сразу она: выбор из одного пункта это лишний экран.
  const active = openId ?? (views.length === 1 ? views[0].id : null)

  return (
    // Внешний отступ — на оболочке «Пульса», как у соседних разделов.
    <div className="space-y-3">
      {views.length > 1 && (
        <div className="flex flex-wrap gap-1.5">
          {views.map((v) => (
            <button key={v.id} onClick={() => setOpenId(v.id)}
              className={cn('rounded-md border px-2.5 py-1 text-[13px]',
                active === v.id ? 'border-primary/50 bg-primary/10' : 'border-border hover:bg-accent')}>
              {v.name}
            </button>
          ))}
        </div>
      )}
      {active && <ShowcaseBody viewId={active} />}
    </div>
  )
}

/**
 * Обращение с витрины.
 *
 * Своего ящика витрина не заводит: текст уходит задачей (там исполнитель и срок) и,
 * если задана комната, эхом в чат (там скорость). Получателю об этом знать не нужно —
 * он написал, ему ответили.
 */
function FeedbackBox({ viewId }: { viewId: string }) {
  const { companyId } = useCompany()
  const [text, setText] = useState('')
  const send = useMutation({
    mutationFn: () => sendPulseFeedback(companyId, viewId, { text: text.trim() }),
    onSuccess: (r) => {
      setText('')
      toast.success('Обращение принято',
        { description: r.task ? `Задача № ${r.task.number}` : undefined })
    },
    onError: (e) => toast.error('Не отправилось', { description: (e as Error).message }),
  })

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border px-3 py-2">
      <MessageSquare className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      <Input value={text} onChange={(e) => setText(e.target.value)}
        placeholder="Вопрос, просьба или замечание"
        className="h-8 flex-1 min-w-[200px] text-[13px]" />
      <Button size="sm" className="h-8" disabled={!text.trim() || send.isPending}
        onClick={() => send.mutate()}>Отправить</Button>
    </div>
  )
}

/**
 * Ответ по строке «Чего ждём от вас».
 *
 * Три коротких ответа вместо переписки: «отправил», «пришлю», «не будет». Они идут в
 * само требование — статус и лента, — а не в отдельную ветку обсуждения: два места,
 * где нужно смотреть, означают, что одно из них всегда забывают.
 *
 * Ответ не закрывает требование: закрывает его появление документа в учёте.
 * «Отправил» — обещание, а не факт.
 */
function RequestReply({ viewId, requestId, onDone }: {
  viewId: string; requestId: string; onDone: () => void
}) {
  const { companyId } = useCompany()
  const [open, setOpen] = useState(false)
  const m = useMutation({
    mutationFn: (decision: 'sent' | 'will_send' | 'declined') =>
      replyPulseRequest(companyId, viewId, { requestId, decision }),
    onSuccess: (r) => { toast.success(`Отметили: ${r.answer}`); setOpen(false); onDone() },
    onError: (e) => toast.error('Не вышло', { description: (e as Error).message }),
  })

  if (!open) {
    return (
      <button onClick={() => setOpen(true)}
        className="shrink-0 rounded-md px-2 py-0.5 text-[11px] text-muted-foreground
                   hover:bg-accent hover:text-foreground">
        ответить
      </button>
    )
  }
  return (
    // На узкой строке ответы уходят на свою строку (`w-full`), а не режут название.
    <div className="flex w-full shrink-0 justify-end gap-1 sm:w-auto">
      {([['sent', 'отправил'], ['will_send', 'пришлю'], ['declined', 'не будет']] as const)
        .map(([k, label]) => (
          <button key={k} disabled={m.isPending} onClick={() => m.mutate(k)}
            className="rounded-md border border-border px-1.5 py-0.5 text-[11px]
                       hover:bg-accent">
            {label}
          </button>
        ))}
    </div>
  )
}
