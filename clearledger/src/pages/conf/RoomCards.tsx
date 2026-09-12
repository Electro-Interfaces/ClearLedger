/**
 * Постоянные комнаты пространства — карточками наверху раздела.
 *
 * Комната это МЕСТО, а не событие: «Оперативка», «Переговорная», «Дежурная».
 * Половина разговоров в компании такие — зашли, поговорили, вышли, — и заводить
 * под них встречу в календаре значит просить человека провести обряд ради
 * трёхминутного вопроса. Кто в комнате сейчас, видно до входа: заходить в
 * пустую переговорную и ждать там в одиночестве никто не станет.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { DoorOpen, Loader2, Plus, Users, X } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { useCompany } from '@/contexts/CompanyContext'
import * as conf from '@/services/confService'
import { cn } from '@/lib/utils'
import { копировать } from './format'

export function RoomCards() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const [окно, setОкно] = useState(false)

  const список = useQuery({
    queryKey: ['conf-rooms', companyId],
    queryFn: () => conf.listRooms(companyId),
    // Кто внутри — то, ради чего на карточку смотрят: список должен обновляться
    // сам, иначе «пусто» на экране означает «было пусто минуту назад».
    refetchInterval: 20_000,
  })
  const обновить = () => {
    void qc.invalidateQueries({ queryKey: ['conf-rooms'] })
    void qc.invalidateQueries({ queryKey: ['conf-live'] })
  }

  const войти = useMutation({
    mutationFn: (roomId: string) => conf.joinRoom(companyId, roomId),
    onSuccess: () => обновить(),
    onError: (e: Error) => toast.error(/503|не настроен/i.test(e.message || '')
      ? 'Конференции не настроены' : 'Не удалось войти в комнату'),
  })
  const убрать = useMutation({
    mutationFn: (roomId: string) => conf.archiveRoom(companyId, roomId),
    onSuccess: () => { toast.success('Комната убрана из списка'); обновить() },
    onError: () => toast.error('Не удалось убрать комнату'),
  })

  const комнаты = список.data?.rooms ?? []
  const можно = список.data?.can_manage ?? false
  if (!комнаты.length && !можно) return null

  return (
    <section className="space-y-2">
      <div className="flex items-center gap-2">
        <h2 className="flex items-center gap-2 text-sm font-medium">
          <DoorOpen className="h-4 w-4 text-muted-foreground" />Постоянные комнаты
        </h2>
        {можно && (
          <Button variant="ghost" size="sm" className="ml-auto h-8"
            onClick={() => setОкно(true)}>
            <Plus className="mr-1.5 h-3.5 w-3.5" />Добавить
          </Button>
        )}
      </div>
      <p className="text-xs text-muted-foreground">
        Место для короткой конференции без назначения встречи: зашли, обсудили, вышли.
        Ссылка у комнаты постоянная — её можно раздать один раз.
      </p>

      {!комнаты.length && (
        <p className="text-sm text-muted-foreground">
          Комнат пока нет. Заведите «Оперативку» или «Переговорную» — в них
          заходят без приглашения.
        </p>
      )}

      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {комнаты.map(к => (
          <div key={к.id}
            className={cn('rounded-lg border p-3',
              к.live ? 'border-success/40 bg-card' : 'border-border bg-card')}>
            <div className="flex items-start gap-2">
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium">{к.name}</p>
                {к.purpose && (
                  <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{к.purpose}</p>
                )}
              </div>
              {можно && (
                <button type="button" onClick={() => убрать.mutate(к.id)}
                  title="Убрать комнату из списка" aria-label={`Убрать комнату ${к.name}`}
                  className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-accent/50 hover:text-foreground">
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </div>

            <p className="mt-2 flex items-center gap-1.5 text-xs">
              {к.live ? (
                <>
                  <Users className="h-3.5 w-3.5 text-success" />
                  <span className="text-success">разговаривают</span>
                  <span className="min-w-0 truncate text-muted-foreground">
                    · {к.inside.map(ч => ч.name).join(', ') || 'кто-то'}
                  </span>
                </>
              ) : (
                <span className="text-muted-foreground">свободна</span>
              )}
            </p>

            <div className="mt-2 flex gap-2">
              <Button size="sm" className="h-9 flex-1"
                variant={к.live ? 'default' : 'outline'}
                disabled={войти.isPending} onClick={() => войти.mutate(к.id)}>
                {войти.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  : <DoorOpen className="mr-2 h-4 w-4" />}
                {к.live ? 'Присоединиться' : 'Войти'}
              </Button>
              <Button size="sm" variant="ghost" className="h-9 px-2"
                title="Скопировать ссылку на комнату"
                aria-label={`Скопировать ссылку на комнату ${к.name}`}
                onClick={() => копировать(к.guest_url)}>
                ссылка
              </Button>
            </div>
          </div>
        ))}
      </div>

      {окно && <NewRoomDialog companyId={companyId} onClose={() => setОкно(false)}
        onCreated={() => { setОкно(false); обновить() }} />}
    </section>
  )
}

function NewRoomDialog({ companyId, onClose, onCreated }: {
  companyId: string
  onClose: () => void
  onCreated: () => void
}) {
  const [имя, setИмя] = useState('')
  const [зачем, setЗачем] = useState('')

  const создать = useMutation({
    mutationFn: () => conf.createRoom(companyId, имя.trim(), зачем.trim()),
    onSuccess: () => { toast.success('Комната заведена'); onCreated() },
    onError: (e: Error) => toast.error(/403/.test(e.message || '')
      ? 'Заводить комнаты может администратор пространства'
      : 'Не удалось завести комнату'),
  })

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="sm:max-w-md" aria-describedby="room-help">
        <DialogHeader>
          <DialogTitle>Постоянная комната</DialogTitle>
          <DialogDescription id="room-help">
            Место для конференции без назначения встречи: ссылка постоянная, вход
            без приглашения.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="room-name">Название</Label>
            <Input id="room-name" value={имя} onChange={e => setИмя(e.target.value)}
              placeholder="Оперативка, Переговорная, Дежурная"
              className="text-base sm:text-sm" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="room-purpose">Для чего</Label>
            <Input id="room-purpose" value={зачем} onChange={e => setЗачем(e.target.value)}
              placeholder="Кому и о чём сюда заходить"
              className="text-base sm:text-sm" />
            <p className="text-xs text-muted-foreground">
              Строка объясняет, туда ли человек заходит, до того как он войдёт и
              увидит незнакомые лица.
            </p>
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>Отмена</Button>
          <Button disabled={!имя.trim() || создать.isPending} onClick={() => создать.mutate()}>
            {создать.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Завести
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
