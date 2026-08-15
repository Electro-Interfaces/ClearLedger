/**
 * «Периметр» → «Разбор недели» — короткий еженедельный просмотр вместо дисциплины.
 *
 * Реестры такого рода умирают не от нехватки возможностей, а от нерегулярности: записи
 * заводят неделю, потом бросают, и через полгода им не верят. Ежедневная проверка здесь
 * не нужна — событий мало; ежемесячная приходит поздно. Рабочий ритм — десять минут раз
 * в неделю.
 *
 * Экран отвечает на три вопроса и ни на один сверх: что появилось, что требует решения
 * сейчас, и всё ли просмотрено. Стриков и баллов нет намеренно: соревнование за объём
 * записей о неоформленных расчётах — плохая мысль и как стимул, и как факт. Отметка о
 * разборе нужна не для отчёта наверх, а как след регулярности — вместе со снимком
 * счётчиков, иначе через год не отличить пустую неделю от недели с семью просрочками.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, ChevronLeft, ChevronRight } from 'lucide-react'
import { toast } from 'sonner'

import { useWorkspace } from '@/contexts/WorkspaceContext'
import { QueryError } from '@/components/common/QueryError'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import {
  getDigest, getReviewHistory, getWeekReview, markWeekReview, sendDigest,
} from '@/services/perimeterService'
import { Loading } from './OfficePanels'
import { dayLabel, money, num } from './officeShared'

/** Сдвиг недели без часовых поясов: всё в UTC, иначе граница уезжает на день. */
const shiftWeek = (iso: string, weeks: number) => {
  const d = new Date(`${iso}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + weeks * 7)
  return d.toISOString().slice(0, 10)
}


export function WeekReviewScreen({ companyId }: { companyId: string }) {
  const qc = useQueryClient()
  const { setCoreMode } = useWorkspace()
  const [week, setWeek] = useState<string | null>(null)
  const [note, setNote] = useState('')
  // Сводка в чат: текст готовит сервер, отправляет — человек. Рассылки по таймеру
  // здесь нет намеренно: в тексте имена и суммы неоформленных расчётов, и решение,
  // кому это показать, за человеком, а не за расписанием.
  const [digestOpen, setDigestOpen] = useState(false)
  const [room, setRoom] = useState('')
  const [digestText, setDigestText] = useState('')

  const q = useQuery({
    queryKey: ['perimeter', 'review', companyId, week],
    queryFn: () => getWeekReview(companyId, week ?? undefined),
    enabled: !!companyId,
  })
  const history = useQuery({
    queryKey: ['perimeter', 'reviews', companyId],
    queryFn: () => getReviewHistory(companyId),
    enabled: !!companyId,
  })
  const digest = useQuery({
    queryKey: ['perimeter', 'digest', companyId, week],
    queryFn: () => getDigest(companyId, week ?? undefined),
    enabled: !!companyId && digestOpen,
  })
  const send = useMutation({
    mutationFn: () => sendDigest(companyId, { roomId: room, text: digestText }),
    onSuccess: () => {
      toast.success('Сводка отправлена в чат')
      setDigestOpen(false)
    },
    onError: (e: Error) => toast.error(e.message),
  })

  const done = useMutation({
    mutationFn: (v: { weekStart: string; note: string | null }) =>
      markWeekReview(companyId, v),
    onSuccess: () => {
      toast.success('Неделя отмечена разобранной')
      setNote('')
      qc.invalidateQueries({ queryKey: ['perimeter'] })
    },
    onError: (e: Error) => toast.error(e.message),
  })

  if (q.isError) {
    return <div className="p-4">
      <QueryError message="Не удалось собрать разбор" onRetry={() => q.refetch()} />
    </div>
  }
  if (!q.data) return <Loading />
  const d = q.data

  return (
    <div className="p-4 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" aria-label="Предыдущая неделя"
            onClick={() => setWeek(shiftWeek(d.weekStart, -1))}>
            <ChevronLeft className="w-4 h-4" />
          </Button>
          <div className="text-base font-medium tabular-nums">
            {dayLabel(d.weekStart)} — {dayLabel(d.weekEnd)}
            {d.isCurrent && (
              <span className="ml-2 text-[11px] text-muted-foreground">текущая</span>
            )}
          </div>
          <Button variant="outline" size="sm" disabled={d.isCurrent}
            aria-label="Следующая неделя"
            onClick={() => setWeek(shiftWeek(d.weekStart, 1))}>
            <ChevronRight className="w-4 h-4" />
          </Button>
        </div>
        {d.reviewed && (
          <span className="inline-flex items-center gap-1.5 text-sm text-emerald-700 dark:text-emerald-400">
            <CheckCircle2 className="w-4 h-4" />
            разобрана {d.reviewedAt?.slice(0, 10)}
          </span>
        )}
      </div>

      {/* Что требует решения — впереди: ради этого экран и открывают */}
      {d.todo.length ? (
        <div className="space-y-3">
          {d.todo.map((t) => (
            <Card key={t.key}>
              <CardContent className="p-4 space-y-2">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <div className="text-sm font-medium">{t.title}</div>
                    <div className="text-[11px] text-muted-foreground">{t.hint}</div>
                  </div>
                  <span className="text-lg tabular-nums shrink-0">{num.format(t.count)}</span>
                </div>
                <ul className="text-[11px] text-muted-foreground space-y-0.5">
                  {t.items.map((i) => (
                    <li key={i.id} className="flex justify-between gap-3">
                      <span className="truncate">{i.text}</span>
                      <span className="tabular-nums shrink-0">{i.note}</span>
                    </li>
                  ))}
                  {t.count > t.items.length && (
                    <li>…и ещё {num.format(t.count - t.items.length)}</li>
                  )}
                </ul>
                <Button variant="outline" size="sm"
                  onClick={() => setCoreMode(t.mode as never, t.sub)}>
                  Перейти и разобрать
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : (
        <Card>
          <CardContent className="p-4 text-sm">
            <div className="font-medium">Ничего не требует решения</div>
            <p className="text-muted-foreground mt-1">
              Сроки не прошли, периоды отмечены, подотчёт закрыт, очередь на оформление
              пуста. Просмотрите, что появилось за неделю, и отметьте разбор.
            </p>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent className="p-4 space-y-3">
          <div>
            <div className="text-sm font-medium">Что появилось за неделю</div>
            <div className="text-[11px] text-muted-foreground">
              {d.added.cash
                ? `${num.format(d.added.cash)} операций, выдано ${money.format(d.added.cashOut)} ₽`
                : 'операций с наличными не было'}
              {d.added.records ? ` · ${num.format(d.added.records)} новых договорённостей` : ''}
            </div>
          </div>

          {!!d.added.rows.length && (
            <ul className="text-[11px] text-muted-foreground space-y-0.5">
              {d.added.rows.map((r) => (
                <li key={r.id} className="flex justify-between gap-3">
                  <span className="truncate">
                    <span className="tabular-nums">{dayLabel(r.date)}</span> · {r.person} · {r.kind}
                  </span>
                  <span className="tabular-nums shrink-0">
                    {r.direction === 'in' ? '+' : '−'}{money.format(r.amount)} ₽ · {r.proof.toLowerCase()}
                  </span>
                </li>
              ))}
            </ul>
          )}

          {!!d.added.recordRows.length && (
            <ul className="text-[11px] text-muted-foreground space-y-0.5">
              {d.added.recordRows.map((r) => (
                <li key={r.id} className="flex justify-between gap-3">
                  <span className="truncate">{r.counterparty ?? '—'}: {r.title}</span>
                  <span className="shrink-0">{r.confidence.toLowerCase()}</span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-4 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="text-sm font-medium">Сводка в чат</div>
            <Button variant="outline" size="sm"
              onClick={() => setDigestOpen((v) => !v)}>
              {digestOpen ? 'Свернуть' : 'Подготовить сводку'}
            </Button>
          </div>
          {digestOpen && (
            digest.isPending ? <div className="text-sm text-muted-foreground">Собираем…</div>
            : digest.isError ? (
              <p className="text-sm text-destructive">
                {String((digest.error as Error).message)}
              </p>
            ) : digest.data ? (
              <div className="space-y-2">
                <textarea
                  className="w-full rounded-md border bg-background px-2.5 py-2 text-sm
                    font-mono"
                  aria-label="Текст сводки"
                  rows={Math.min(14, digest.data.text.split('\n').length + 1)}
                  value={digestText || digest.data.text}
                  onChange={(e) => setDigestText(e.target.value)} />
                <p className="text-[11px] text-muted-foreground">
                  Текст можно поправить перед отправкой. В нём имена и суммы
                  неоформленных расчётов — выбирайте комнату осознанно.
                </p>
                <div className="flex flex-wrap items-center gap-2">
                  <select className="rounded-md border bg-background px-2.5 py-1.5 text-sm"
                    aria-label="Куда отправить сводку"
                    value={room} onChange={(e) => setRoom(e.target.value)}>
                    <option value="">— выберите чат —</option>
                    {digest.data.rooms.map((r) => (
                      <option key={r.id} value={r.id}>{r.title}</option>
                    ))}
                  </select>
                  <Button size="sm" disabled={!room || send.isPending}
                    onClick={() => {
                      if (!digestText) setDigestText(digest.data!.text)
                      send.mutate()
                    }}>
                    {send.isPending ? 'Отправляем…' : 'Отправить'}
                  </Button>
                  {!digest.data.rooms.length && (
                    <span className="text-[11px] text-muted-foreground">
                      Вы не состоите ни в одном чате пространства
                    </span>
                  )}
                </div>

                {!!digest.data.personal.length && (
                  <div className="pt-2 space-y-1">
                    <div className="text-[11px] uppercase tracking-wider
                        text-muted-foreground">
                      Напоминания людям — текстом, без рассылки
                    </div>
                    <ul className="text-[11px] text-muted-foreground space-y-1">
                      {digest.data.personal.slice(0, 6).map((p) => (
                        <li key={p.person}>{p.text}</li>
                      ))}
                    </ul>
                    <p className="text-[11px] text-muted-foreground">
                      Продукт их не отправляет: долг с именем и суммой уходит человеку
                      только по вашему решению и вашими словами.
                    </p>
                  </div>
                )}
              </div>
            ) : null
          )}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-4 space-y-3">
          <div className="text-sm font-medium">
            {d.reviewed ? 'Неделя разобрана' : 'Отметить разбор'}
          </div>
          {d.reviewed && d.reviewNote && (
            <p className="text-sm text-muted-foreground whitespace-pre-wrap">
              {d.reviewNote}
            </p>
          )}
          {!d.reviewed && (
            <p className="text-[11px] text-muted-foreground">
              Отметка сохраняет снимок счётчиков: сколько записей появилось и сколько
              требовало решения на этот момент. Через год это отличает разобранную пустую
              неделю от разобранной тяжёлой.
            </p>
          )}
          <textarea className="w-full rounded-md border bg-background px-2.5 py-2 text-sm"
            rows={2} value={note} onChange={(e) => setNote(e.target.value)}
            aria-label="Что решили по итогам недели"
            placeholder="Что решили по итогам недели (не обязательно)" />
          <div className="flex justify-end">
            <Button size="sm" disabled={done.isPending}
              onClick={() => done.mutate({ weekStart: d.weekStart, note: note || null })}>
              {done.isPending ? 'Сохраняем…'
                : d.reviewed ? 'Обновить отметку' : 'Неделя разобрана'}
            </Button>
          </div>
        </CardContent>
      </Card>

      {!!history.data?.rows.length && (
        <Card>
          <CardContent className="p-4 space-y-2">
            <div className="flex items-center justify-between">
              <div className="text-sm font-medium">Прошлые разборы</div>
              {!!history.data.weeksInRow && (
                <span className="text-[11px] text-muted-foreground">
                  недель подряд без пропуска: {num.format(history.data.weeksInRow)}
                </span>
              )}
            </div>
            <ul className="text-[11px] text-muted-foreground space-y-0.5">
              {history.data.rows.slice(0, 12).map((r) => (
                <li key={r.weekStart} className="flex justify-between gap-3">
                  <button className="hover:underline tabular-nums"
                    onClick={() => setWeek(r.weekStart)}>
                    неделя с {dayLabel(r.weekStart)}
                  </button>
                  <span className={cn('shrink-0 tabular-nums',
                    r.todoTotal ? '' : 'text-emerald-700 dark:text-emerald-400')}>
                    {r.todoTotal ? `${num.format(r.todoTotal)} к решению` : 'чисто'}
                    {r.by ? ` · ${r.by}` : ''}
                  </span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
