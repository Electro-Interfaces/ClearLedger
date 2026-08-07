/**
 * Чат задачи — короткое обсуждение внутри самой работы.
 *
 * Смысл ровно такой: на каком-то шаге возникает вопрос, причастные быстро его
 * проговаривают и идут дальше. Поэтому обсуждение живёт ЗДЕСЬ, а не в
 * приложении «Чаты»: уводить человека из задачи ради двух реплик — терять
 * контекст, к которому он и вернётся через минуту.
 *
 * Состав комнаты собирается из самой задачи (автор, исполнитель, наблюдатели) —
 * звать никого не нужно. Комната скрытая: в общем списке чатов её нет, вход
 * только отсюда.
 *
 * Почему это не лента задачи: лента — след работы, по нему потом отвечают на
 * вопрос «почему так вышло». Разговор «а когда сможешь?» в следе только мешает,
 * поэтому у них разные места и разный срок жизни внимания.
 */
import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, Send, Users } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { QueryError } from '@/components/common/QueryError'
import { cn } from '@/lib/utils'
import { ensureTaskRoom, getMessages, sendMessage } from '@/services/chatService'
import { dtT } from './taskWords'
import { useSendMode } from '@/hooks/useSendMode'

export function TaskChat({ taskId, taskNumber, selfName }: {
  taskId: string
  taskNumber: number
  selfName?: string | null
}) {
  const qc = useQueryClient()
  const { shouldSend, hint: sendHint } = useSendMode()
  const [text, setText] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)

  // Комната создаётся при первом заходе во вкладку: заводить чат каждой задаче
  // заранее — плодить пустые комнаты, в которые никто не напишет.
  const roomQ = useQuery({
    queryKey: ['task-room', taskId],
    queryFn: () => ensureTaskRoom(taskId),
    staleTime: 10 * 60 * 1000,
  })
  const roomId = roomQ.data?.id

  const msgQ = useQuery({
    queryKey: ['task-room-messages', roomId],
    queryFn: () => getMessages(roomId!),
    enabled: !!roomId,
    // Короткий разговор идёт минутами: опрос раз в 10 секунд читается как
    // живой, а держать здесь сокет ради двух реплик незачем.
    refetchInterval: 10_000,
  })
  const messages = msgQ.data ?? []

  const send = useMutation({
    mutationFn: () => sendMessage(roomId!, { content: text.trim() }),
    onSuccess: () => {
      setText('')
      qc.invalidateQueries({ queryKey: ['task-room-messages', roomId] })
    },
    onError: (e) => toast.error((e as Error).message),
  })

  // Держим низ: разговор читают с конца.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: 'end' })
  }, [messages.length])

  if (roomQ.isLoading) {
    return (
      <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />Открываем обсуждение…
      </div>
    )
  }
  if (roomQ.isError) {
    return <QueryError message="Не удалось открыть обсуждение задачи"
      onRetry={() => void roomQ.refetch()} />
  }

  const people = roomQ.data?.participants ?? []

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 items-center gap-2 pb-2 text-xs text-muted-foreground">
        <Users className="h-3.5 w-3.5" />
        <span>Обсуждение задачи №{taskNumber}</span>
        {people.length > 0 && (
          <span className="truncate" title={people.map((p) => p.name).join(", ")}>
            · {people.length} участник{people.length === 1 ? '' : people.length < 5 ? 'а' : 'ов'}
          </span>
        )}
        <span className="ml-auto">видно только причастным</span>
      </div>

      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto rounded-lg border bg-muted/20 p-3">
        {msgQ.isLoading ? (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />Загрузка…
          </div>
        ) : messages.length === 0 ? (
          <p className="py-8 text-center text-xs text-muted-foreground">
            Здесь можно быстро проговорить вопрос с теми, кто в задаче.
            Написанное сюда не попадает в след работы.
          </p>
        ) : (
          messages.map((m) => {
            const own = !!selfName && m.userName === selfName
            return (
              <div key={m.id} className={cn('flex', own && 'justify-end')}>
                <div className={cn('max-w-[75%] rounded-lg px-3 py-1.5 text-xs',
                  own ? 'bg-primary/10' : 'bg-muted/60')}>
                  {!own && (
                    <div className="mb-0.5 text-[11px] font-medium text-muted-foreground">
                      {m.userName ?? 'участник'}
                    </div>
                  )}
                  <div className="whitespace-pre-wrap text-foreground/90">{m.content}</div>
                  <div className="mt-0.5 text-right text-[10px] text-muted-foreground">
                    {dtT(m.createdAt)}
                  </div>
                </div>
              </div>
            )
          })
        )}
        <div ref={bottomRef} />
      </div>

      <div className="flex shrink-0 items-end gap-2 pt-2">
        <Textarea value={text} onChange={(e) => setText(e.target.value)} rows={1}
          maxLength={2000} className="min-h-9 resize-none text-sm" title={sendHint}
          placeholder={`Написать участникам задачи. ${sendHint}`}
          onKeyDown={(e) => {
            // Чем отправляется — выбор человека в меню профиля: та же привычка,
            // что и в чате, здесь она не должна меняться.
            if (shouldSend(e) && text.trim() && roomId) {
              e.preventDefault()
              send.mutate()
            }
          }} />
        <Button size="sm" className="h-9" disabled={!text.trim() || send.isPending || !roomId}
          onClick={() => send.mutate()}>
          {send.isPending
            ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
            : <Send className="h-3.5 w-3.5" />}
        </Button>
      </div>
    </div>
  )
}

export default TaskChat
