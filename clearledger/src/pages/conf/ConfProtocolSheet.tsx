/**
 * Расшифровка записи и протокол по ней — «дешифратор + протокол с
 * распределением задач» (РусГидро, «ТЗ по СРМ», п. 6).
 *
 * Запись после конференции сама уходит в распознавание речи пространства;
 * сервер собирает по тексту черновик: решения и поручения, исполнителя — по
 * имени участника, прозвучавшему в фразе, срок — по «до пятницы», «20.10».
 * Черновик правит человек: распределение предлагает машина, ставит — он.
 * «Поставить поручения» заводит задачи «Трека» обычным путём (маршрут, письмо
 * исполнителю, след у встречи), «Разослать» кладёт протокол в личный чат
 * каждому участнику.
 */
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { CheckCircle2, Loader2, Plus, Send, Trash2 } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import * as conf from '@/services/confService'
import { createTask } from '@/services/tasksService'
import { refHref } from '@/services/workService'
import { cn } from '@/lib/utils'

const мс = (sec?: number | null) => {
  if (sec == null) return ''
  const s = Math.floor(sec)
  const ч = Math.floor(s / 3600), м = Math.floor((s % 3600) / 60), с = s % 60
  return `${ч ? `${ч}:` : ''}${String(м).padStart(ч ? 2 : 1, '0')}:${String(с).padStart(2, '0')}`
}

export function ConfProtocolSheet({ companyId, sessionId, onClose }: {
  companyId: string
  sessionId: string | null
  onClose: () => void
}) {
  const qc = useQueryClient()
  const [вкладка, setВкладка] = useState<'protocol' | 'text'>('protocol')
  const [пункты, setПункты] = useState<conf.ProtocolItem[]>([])
  const [правлено, setПравлено] = useState(false)

  const q = useQuery({
    queryKey: ['conf-transcript', companyId, sessionId],
    queryFn: () => conf.getTranscript(companyId, sessionId!),
    enabled: !!sessionId,
    // Пока идёт распознавание — спрашиваем раз в 10 секунд; готово — перестаём.
    refetchInterval: (query) => {
      const s = query.state.data?.status
      return s === 'queued' || s === 'running' ? 10_000 : false
    },
  })
  const d = q.data

  // Пункты с сервера берём, пока человек их не трогал: опрос статуса не должен
  // затирать то, что он уже поправил.
  useEffect(() => {
    if (d && !правлено) setПункты(d.protocol)
  }, [d, правлено])
  useEffect(() => { setПравлено(false); setВкладка('protocol') }, [sessionId])

  const обновить = () => {
    void qc.invalidateQueries({ queryKey: ['conf-transcript', companyId, sessionId] })
    void qc.invalidateQueries({ queryKey: ['conf-records', companyId] })
  }

  const запустить = useMutation({
    mutationFn: () => conf.transcribe(companyId, sessionId!),
    onSuccess: () => { toast.success('Расшифровка поставлена в очередь'); обновить() },
    onError: (e: Error) => toast.error(e.message || 'Не удалось запустить расшифровку'),
  })

  const сохранить = useMutation({
    mutationFn: (send: boolean) => conf.saveProtocol(companyId, sessionId!, пункты, send),
    onSuccess: (r, send) => {
      setПравлено(false)
      toast.success(send ? `Протокол разослан: ${r.sent}` : 'Протокол сохранён')
      обновить()
    },
    onError: (e: Error) => toast.error(e.message || 'Протокол не сохранился'),
  })

  const к_постановке = пункты.filter(п => п.kind === 'task' && п.assignee_id && !п.task_id && п.text.trim())
  const поставить = useMutation({
    mutationFn: async () => {
      const итог = [...пункты]
      let ok = 0
      for (let i = 0; i < итог.length; i++) {
        const п = итог[i]
        if (п.kind !== 'task' || !п.assignee_id || п.task_id || !п.text.trim()) continue
        const задача = await createTask({
          companyId, title: п.text.trim().slice(0, 300),
          description: `По итогам конференции «${d?.title ?? ''}»`
            + (п.at != null ? `, на ${мс(п.at)} записи` : ''),
          assigneeId: п.assignee_id,
          dueAt: п.due ? new Date(`${п.due}T18:00`).toISOString() : undefined,
          subjectRef: d?.event_id ? `event:${d.event_id}` : undefined,
        })
        итог[i] = { ...п, task_id: задача.id }
        ok++
      }
      // Номера задач сохраняем сразу: повторное нажатие не должно ставить их второй раз.
      await conf.saveProtocol(companyId, sessionId!, итог, false)
      return { итог, ok }
    },
    onSuccess: ({ итог, ok }) => {
      setПункты(итог); setПравлено(false)
      toast.success(`Поставлено поручений: ${ok}`)
      обновить()
    },
    onError: (e: Error) => toast.error(e.message || 'Поручения не поставились'),
  })

  const править = (i: number, patch: Partial<conf.ProtocolItem>) => {
    setПравлено(true)
    setПункты(было => было.map((п, j) => (j === i ? { ...п, ...patch } : п)))
  }
  const добавить = (kind: conf.ProtocolItem['kind']) => {
    setПравлено(true)
    setПункты(было => [...было, { kind, text: '', assignee_id: null, due: null, task_id: null }])
  }
  const занят = сохранить.isPending || поставить.isPending

  return (
    <Sheet open={!!sessionId} onOpenChange={(open) => { if (!open) onClose() }}>
      <SheetContent side="right" className="flex w-full flex-col gap-3 overflow-y-auto sm:max-w-2xl">
        <SheetHeader>
          <SheetTitle>{d?.title ?? 'Расшифровка'}</SheetTitle>
          <SheetDescription>Расшифровка записи и протокол: решения и поручения участникам.</SheetDescription>
        </SheetHeader>

        {q.isLoading && <p role="status" className="text-sm">Загружаем…</p>}
        {q.isError && <p role="alert" className="text-sm text-destructive">Не удалось открыть расшифровку.</p>}

        {d && (d.status === 'queued' || d.status === 'running') && (
          <p role="status" className="flex items-center gap-2 rounded-md border border-border p-3 text-sm">
            <Loader2 className="h-4 w-4 animate-spin" />
            {d.status === 'queued' ? 'Ждёт очереди распознавания…' : 'Распознаём речь…'}
            <span className="text-muted-foreground">Обычно около трети длительности записи.</span>
          </p>
        )}
        {d && (d.status === null || d.status === 'error') && (
          <div className="space-y-2 rounded-md border border-border p-3 text-sm">
            {d.error && <p role="alert" className="text-destructive">{d.error}</p>}
            <Button size="sm" disabled={запустить.isPending} onClick={() => запустить.mutate()}>
              {запустить.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {d.status === 'error' ? 'Расшифровать снова' : 'Расшифровать'}
            </Button>
          </div>
        )}

        {d?.status === 'done' && (
          <>
            <div className="flex gap-1" role="tablist">
              {([['protocol', 'Протокол'], ['text', 'Текст']] as const).map(([k, label]) => (
                <Button key={k} size="sm" role="tab" aria-selected={вкладка === k}
                  variant={вкладка === k ? 'secondary' : 'ghost'} onClick={() => setВкладка(k)}>{label}</Button>
              ))}
            </div>

            {вкладка === 'text' && (
              <div className="space-y-1.5 text-sm">
                {!d.segments.length && <p className="text-muted-foreground">Речь в записи не распознана.</p>}
                {d.segments.map((o, i) => (
                  <p key={i}><span className="mr-2 font-mono text-xs text-muted-foreground">{мс(o.start)}</span>{o.text}</p>
                ))}
              </div>
            )}

            {вкладка === 'protocol' && (
              <div className="space-y-3">
                {d.draft && !правлено && (
                  <p className="rounded-md border border-amber-500/40 bg-amber-500/5 p-2 text-xs text-amber-800 dark:text-amber-300">
                    Черновик собран по расшифровке автоматически: исполнитель — участник, чьё имя прозвучало в фразе,
                    срок — из слов «до пятницы», «20.10». Проверьте перед тем, как ставить поручения.
                  </p>
                )}
                {!пункты.length && <p className="text-sm text-muted-foreground">В разговоре не нашлось решений и поручений — добавьте их сами.</p>}
                {пункты.map((п, i) => (
                  <div key={i} className={cn('space-y-2 rounded-md border p-2.5',
                    п.kind === 'task' ? 'border-border' : 'border-primary/30 bg-primary/5')}>
                    <div className="flex flex-wrap items-center gap-2">
                      <select aria-label="Вид пункта" value={п.kind} disabled={!!п.task_id}
                        onChange={e => править(i, { kind: e.target.value as conf.ProtocolItem['kind'] })}
                        className="h-8 rounded-md border border-input bg-background px-2 text-sm">
                        <option value="decision">Решение</option>
                        <option value="task">Поручение</option>
                      </select>
                      {п.at != null && <span className="font-mono text-xs text-muted-foreground">{мс(п.at)}</span>}
                      {п.task_id && (
                        <Link to={refHref(`task:${п.task_id}`) ?? '/'} className="flex items-center gap-1 text-xs text-emerald-700 hover:underline dark:text-emerald-400">
                          <CheckCircle2 className="h-3.5 w-3.5" />задача поставлена
                        </Link>
                      )}
                      <Button size="sm" variant="ghost" className="ml-auto h-8 px-2" aria-label="Убрать пункт"
                        onClick={() => { setПравлено(true); setПункты(было => было.filter((_, j) => j !== i)) }}>
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                    <Textarea aria-label="Текст пункта" value={п.text} rows={2} disabled={!!п.task_id}
                      onChange={e => править(i, { text: e.target.value })} />
                    {п.kind === 'task' && (
                      <div className="flex flex-wrap items-center gap-2">
                        <select aria-label="Исполнитель" value={п.assignee_id ?? ''} disabled={!!п.task_id}
                          onChange={e => править(i, { assignee_id: e.target.value || null })}
                          className={cn('h-8 min-w-48 rounded-md border bg-background px-2 text-sm',
                            п.assignee_id ? 'border-input' : 'border-amber-500/60')}>
                          <option value="">Исполнитель не назначен</option>
                          {d.people.map(ч => <option key={ч.id} value={ч.id}>{ч.name}</option>)}
                        </select>
                        <Input type="date" aria-label="Срок" value={п.due ?? ''} disabled={!!п.task_id}
                          onChange={e => править(i, { due: e.target.value || null })} className="h-8 w-40" />
                      </div>
                    )}
                  </div>
                ))}
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" variant="outline" onClick={() => добавить('decision')}><Plus className="mr-1 h-4 w-4" />Решение</Button>
                  <Button size="sm" variant="outline" onClick={() => добавить('task')}><Plus className="mr-1 h-4 w-4" />Поручение</Button>
                </div>
                <div className="flex flex-wrap gap-2 border-t border-border pt-3">
                  <Button size="sm" variant="outline" disabled={занят} onClick={() => сохранить.mutate(false)}>
                    {сохранить.isPending && !сохранить.variables && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Сохранить
                  </Button>
                  <Button size="sm" disabled={занят || !к_постановке.length} onClick={() => поставить.mutate()}
                    title="Задачи «Трека» исполнителям: со сроком, письмом и ссылкой на встречу">
                    {поставить.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                    Поставить поручения{к_постановке.length ? ` (${к_постановке.length})` : ''}
                  </Button>
                  <Button size="sm" variant="outline" disabled={занят || !пункты.length} onClick={() => сохранить.mutate(true)}
                    title="Протокол текстом — каждому участнику в личный чат">
                    <Send className="mr-1 h-4 w-4" />Разослать участникам
                  </Button>
                </div>
              </div>
            )}
          </>
        )}
      </SheetContent>
    </Sheet>
  )
}
