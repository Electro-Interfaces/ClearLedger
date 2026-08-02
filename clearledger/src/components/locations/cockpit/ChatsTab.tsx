/**
 * «Чаты» станции — обсуждения, привязанные к этому объекту (`chat_rooms.scope_object_id`).
 *
 * Смысл двусторонний: в чате видно, при каком объекте идёт разговор, а из карточки
 * объекта — какие обсуждения по нему живут и что в них решали. Открытие — той же
 * панелью чата (док/окно): `openInteraction('chat', 'room:<id>')` доносит комнату.
 */
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

export function ChatsTab({ location }: { location: ServiceLocation }) {
  const { openInteraction } = useSupportContext()
  const q = useQuery({
    queryKey: ['chat-rooms-object', location.id],
    queryFn: () => chat.getRooms(false, null, location.id),
  })
  const rooms = q.data ?? []

  const createGroup = () => {
    chat.createRoom('group', [], location.name, null, location.id)
      .then((room) => {
        q.refetch()
        openInteraction('chat', `room:${room.id}`)
        toast.success('Группа объекта создана — добавьте участников в её составе')
      })
      .catch((e: Error) => toast.error(e.message || 'Не удалось создать группу'))
  }

  return (
    <ScrollTab>
      <div className="mb-3 flex items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">
          Обсуждения, привязанные к этому объекту: решения по нему остаются при нём.
        </p>
        <Button size="sm" variant="outline" className="h-8 shrink-0 gap-1.5" onClick={createGroup}>
          <Plus className="size-4" /> Группа объекта
        </Button>
      </div>

      {q.isLoading && (
        <div className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" /> Загрузка…
        </div>
      )}
      {!q.isLoading && rooms.length === 0 && (
        <Placeholder icon={MessageCircle}
          title="Обсуждений пока нет"
          text="Создайте группу объекта — или привяжите существующую в её свойствах (строка «Объект»)." />
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
