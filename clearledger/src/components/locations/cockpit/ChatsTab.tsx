/**
 * «Чаты» предмета — обсуждения, привязанные к объекту (`scope_object_id`) или к
 * любому другому предмету пространства (`scope_ref`: `site:<uuid>` и прочие).
 *
 * Смысл двусторонний: в чате видно, при чём идёт разговор, а из карточки — какие
 * обсуждения по нему живут и что в них решали. Открытие — той же панелью чата
 * (док/окно): `openInteraction('chat', 'room:<id>')` доносит комнату.
 *
 * Один компонент на оба случая намеренно. Второй список чатов, отличающийся
 * только полем привязки, разошёлся бы с первым на ближайшей правке — а вопрос
 * «что по нему обсуждали» у станции и у проекта один и тот же.
 */
import { useState } from 'react'
import { openContextChat, resolveWorkContext } from '@/services/workContextService'
import { useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Loader2, MessageCircle, Plus, Users } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useSupportContext } from '@/contexts/SupportContext'
import * as chat from '@/services/chatService'
import type { ServiceLocation } from '@/types/location'
import { Placeholder, ScrollTab } from './shared'

const fmt = (iso?: string | null) => iso
  ? new Date(iso).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
  : null

export function ChatsTab({ location, subject, plain, companyId }: {
  /** Карточка объекта сети: привязка идёт по `scope_object_id`. */
  location?: ServiceLocation
  /** Любой другой предмет пространства: проект, договор. `product` — приложение,
   *  в контексте которого живёт разговор (чтобы он был в его правой рельсе). */
  subject?: { ref: string; title: string; product?: string | null }
  companyId?: string
  plain?: boolean
}) {
  const { openInteraction } = useSupportContext()
  const scopeRef = subject?.ref ?? null
  const objectId = subject ? null : location?.id ?? null
  const q = useQuery({
    queryKey: ['chat-rooms-scope', scopeRef ?? objectId],
    queryFn: () => chat.getRooms(false, null, objectId, scopeRef),
    enabled: !!(scopeRef || objectId),
  })
  const [opening, setOpening] = useState(false)
  const rooms = q.data ?? []
  const what = 'этому предмету работы'

  const openMain = async () => {
    if (!companyId || !scopeRef) return
    setOpening(true)
    try {
      const context = await resolveWorkContext(companyId, scopeRef)
      const room = await openContextChat(companyId, scopeRef, { purpose: 'main', audience: 'internal', participant_ids: context.suggested_people?.map((p) => p.id) })
      openInteraction('chat', `room:${room.room_id}`); void q.refetch()
    }
    catch (e) { toast.error((e as Error).message) }
    finally { setOpening(false) }
  }
  const createGroup = () => {
    const title = subject?.title || location?.name || 'Группа'
    chat.createRoom('group', [], title, subject?.product ?? null, objectId, scopeRef)
      .then((room) => {
        q.refetch()
        openInteraction('chat', `room:${room.id}`)
        toast.success('Группа создана — добавьте участников в её составе')
      })
      .catch((e: Error) => toast.error(e.message || 'Не удалось создать группу'))
  }

  return (
    <ScrollTab plain={plain}>
      {companyId && scopeRef && <Button className="mb-3" size="sm" disabled={opening} onClick={() => void openMain()}>Основная группа</Button>}
      <div className="mb-3 flex items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">
          Обсуждения, привязанные к {what}: решения по нему остаются при нём.
        </p>
        <Button size="sm" variant="outline" className="h-8 shrink-0 gap-1.5" onClick={createGroup}>
          <Plus className="size-4" /> {subject ? 'Дополнительная группа' : 'Группа объекта'}
        </Button>
      </div>

      {q.isLoading && (
        <div className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" /> Загрузка…
        </div>
      )}
      {q.isError && <div role="alert" className="mb-3 text-sm"><p>Не удалось загрузить обсуждения.</p><Button variant="outline" onClick={() => void q.refetch()}>Повторить</Button></div>}
      {!q.isLoading && !q.isError && rooms.length === 0 && (
        <Placeholder icon={MessageCircle}
          title="Обсуждений пока нет"
          text={subject
            ? 'Создайте группу проекта — переписка с собственником и сетевой останется при нём.'
            : 'Создайте группу объекта — или привяжите существующую в её свойствах (строка «Объект»).'} />
      )}

      <div className="space-y-1.5">
        {rooms.map((r) => (
          <button key={r.id} type="button"
            onClick={() => openInteraction('chat', `room:${r.id}`)}
            className="flex w-full items-center gap-3 rounded-lg border border-border px-3 py-2.5 text-left transition-colors hover:bg-accent/40">
            <div className="flex size-9 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
              <MessageCircle className="size-4" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline justify-between gap-2">
                <span className="min-w-0 truncate text-sm font-medium">{r.name || 'Группа'}</span>
                <span className="shrink-0 text-[11px] text-muted-foreground">{fmt(r.lastMessageAt) ?? 'нет сообщений'}</span>
              </div>
              <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                <span className="inline-flex items-center gap-0.5"><Users className="size-3" />{r.participantCount}</span>
                <span className="min-w-0 truncate">{r.lastMessage || 'Переписка не начата'}</span>
                {(r.unreadCount ?? 0) > 0 && (
                  <span className="ml-auto shrink-0 rounded-full bg-primary px-1.5 text-[10px] font-bold text-primary-foreground">
                    {r.unreadCount}
                  </span>
                )}
              </div>
            </div>
          </button>
        ))}
      </div>
    </ScrollTab>
  )
}
