/**
 * «Встречи» — с кем говорят сейчас и что назначено впереди.
 *
 * Идущие стоят наверху отдельным блоком, а не строкой в общем списке: попасть в
 * начавшийся конференция нужно в один клик, и искать его среди завтрашних встреч
 * человек не станет — он позвонит по телефону, и конференция пройдёт мимо нас.
 *
 * Пока не заведено ничего, экран говорит это ОДИН раз. Два пустых блока подряд
 * («никто не созванивается» и «впереди встреч нет») читались как поломка: на
 * первом же скриншоте половина экрана оказалась объяснением пустоты.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, Loader2, Radio, Square, UserPlus, Users, Video } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { useCompany } from '@/contexts/CompanyContext'
import * as conf from '@/services/confService'
import { NewTalkDialog, TalkRow } from './parts'
import { RoomCards } from './RoomCards'
import { EmptyBlock } from './EmptyBlock'
import { длительность, когда, копировать } from './format'

export default function ConfTalksPage() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const [окно, setОкно] = useState(false)

  const live = useQuery({
    queryKey: ['conf-live', companyId],
    queryFn: () => conf.listLive(companyId),
    // Конференция начинается и заканчивается без нашего ведома: список, который
    // не обновляется сам, врёт уже через минуту после открытия.
    refetchInterval: 20_000,
  })
  const впереди = useQuery({
    queryKey: ['conf-meetings', companyId, 'upcoming', ''],
    queryFn: () => conf.listMeetings(companyId, 'upcoming'),
  })

  const обновить = () => {
    void qc.invalidateQueries({ queryKey: ['conf-live'] })
    void qc.invalidateQueries({ queryKey: ['conf-meetings'] })
    void qc.invalidateQueries({ queryKey: ['calendar'] })
    void qc.invalidateQueries({ queryKey: ['pulse-my-meetings'] })
  }

  const войти = useMutation({
    mutationFn: (eventId: string) => conf.joinMeeting(companyId, eventId),
    onSuccess: (m) => { копировать(m.guest_url); обновить() },
    onError: () => toast.error('Не удалось войти в конференцию'),
  })
  // «Завершить» закрывает конференцию целиком: журнал, комнату и запись.
  // Комнату гасит сервер конференций по нашей просьбе — иначе брошенная вкладка
  // держала её часами и всё это время шла запись (случай МАГа 10.09.2026).
  const ответ = useMutation({
    mutationFn: ({ id, что }: { id: string; что: 'accepted' | 'declined' }) =>
      conf.respond(companyId, id, что),
    onSuccess: (_д, { что }) => {
      toast.success(что === 'accepted' ? 'Записал: будете' : 'Записал: не сможете')
      обновить()
    },
    onError: () => toast.error('Не удалось ответить на приглашение'),
  })
  const завершить = useMutation({
    mutationFn: (sessionId: string) => conf.endSession(companyId, sessionId),
    onSuccess: () => {
      toast.success('Конференция закрыта — она в «Истории»', {
        description: 'Комната закрыта для всех, запись остановлена',
      })
      обновить()
    },
    onError: () => toast.error('Не удалось закрыть конференцию'),
  })

  const идут = live.data?.live ?? []
  const все = впереди.data?.meetings ?? []
  // Приглашения без ответа — наверх: это единственное, что здесь требует
  // ответа именно от вас, и искать его среди чужих встреч не должно.
  const зовут = все.filter(в => в.my_response === 'pending' && !в.organizer_is_me && !в.live)
  const встречи = все.filter(в => !зовут.includes(в) && !в.live)
  // Приглашения на уже идущие конференции: ответить на них можно прямо в
  // карточке «Идут сейчас», второй строкой их не дублируем.
  const ответить = new Map(все.filter(в => в.live && в.my_response === 'pending'
    && !в.organizer_is_me).map(в => [в.id, в]))
  const выключено = впереди.data?.enabled === false
  const грузим = live.isLoading || впереди.isLoading
  const пусто = !грузим && !идут.length && !встречи.length && !зовут.length

  return (
    <div className="space-y-5 p-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="mr-auto">
          <h1 className="font-headline text-lg font-semibold">Идут и назначены</h1>
          <p className="mt-0.5 max-w-2xl text-xs text-muted-foreground">
            Конференция живёт в календаре пространства: ссылка у неё одна и та же
            всегда, а после — видно, кто пришёл и о чём договорились.
          </p>
        </div>
        <Button onClick={() => setОкно(true)} disabled={выключено}>
          <Video className="mr-2 h-4 w-4" />Начать конференцию
        </Button>
      </div>

      {выключено && (
        <p role="alert" className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm">
          Видеоконференции в этом пространстве не настроены — обратитесь к администратору.
        </p>
      )}

      <RoomCards />

      {грузим && <p role="status" className="text-sm text-muted-foreground">Загружаем…</p>}

      {пусто && (
        <EmptyBlock иконка={Video} текст="Назначенных конференций нет"
          подсказка="«Начать конференцию» заводит комнату и зовёт участников — в чат пространства, а при желании и письмом. Для короткого разговора без назначения есть постоянные комнаты выше." />
      )}

      {идут.length > 0 && (
        <section className="space-y-2">
          <h2 className="flex items-center gap-2 text-sm font-medium">
            {/* Зелёный, а не красный: идущий конференция — это норма, а не тревога.
                Цвет не единственный признак — рядом стоит слово. */}
            <Radio className="h-4 w-4 animate-pulse text-success" />
            Идут сейчас
            <span className="text-muted-foreground">· {идут.length}</span>
          </h2>
          <p className="text-xs text-muted-foreground">
            «Завершить» закрывает конференцию целиком: комната гасится для всех,
            запись останавливается и уезжает в «Записи», а сама конференция уходит
            в «Историю» с длительностью и составом. Забытую пространство закрывает
            само через полчаса после конца встречи. Записывать можно одну
            конференцию одновременно — сервер записи в пространстве один.
          </p>
          {идут.map(с => (
            <div key={с.id} className="rounded-lg border border-success/40 bg-card p-3">
              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                <span className="font-medium">{с.title}</span>
                <span className="text-xs text-muted-foreground">
                  начали {когда(с.started_at)}
                  {с.seconds ? ` · ${длительность(с.seconds)}` : ''}
                  {с.invited && с.invited > 1 ? ` · звано ${с.invited}` : ''}
                  {с.invited && с.invited > 1 && с.accepted
                    ? `, будут ${с.accepted}` : ''}
                </span>
                <div className="ml-auto flex items-center gap-2">
                  <Button variant="ghost" size="sm" className="h-9 px-2"
                    aria-label="Скопировать ссылку для участников"
                    title="Скопировать ссылку для участников"
                    onClick={() => копировать(с.guest_url)}>
                    <Copy className="h-4 w-4" />
                  </Button>
                  {с.event_id && (
                    <Button size="sm" disabled={войти.isPending}
                      onClick={() => войти.mutate(с.event_id!)}>
                      {войти.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        : <Video className="mr-2 h-4 w-4" />}
                      Присоединиться
                    </Button>
                  )}
                  {/* Гасит разговор тот, кто его собрал: приглашённому кнопка
                      «Завершить» не нужна и опасна — он закрыл бы конференцию
                      всем остальным (проверка интерфейса 11.09.2026). */}
                  {с.organizer_is_me && (
                    <Button size="sm" variant="outline" disabled={завершить.isPending}
                      title="Закрыть конференцию для всех: комната гаснет, запись останавливается"
                      onClick={() => завершить.mutate(с.id)}>
                      <Square className="mr-2 h-3.5 w-3.5" />Завершить
                    </Button>
                  )}
                </div>
              </div>
              {с.came.length > 0 && (
                <p className="mt-1 flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Users className="h-3.5 w-3.5" />{с.came.map(ч => ч.name).join(', ')}
                </p>
              )}
              {с.event_id && ответить.has(с.event_id) && (
                <div className="mt-2 flex flex-wrap items-center gap-2 rounded-md border border-primary/30 bg-primary/5 px-2.5 py-1.5">
                  <UserPlus className="h-3.5 w-3.5 text-primary" />
                  <span className="text-xs">Вас позвали. Придёте?</span>
                  <div className="ml-auto flex gap-1.5">
                    <Button size="sm" variant="outline" className="h-8"
                      disabled={ответ.isPending}
                      onClick={() => ответ.mutate({ id: с.event_id!, что: 'accepted' })}>Буду</Button>
                    <Button size="sm" variant="ghost" className="h-8"
                      disabled={ответ.isPending}
                      onClick={() => ответ.mutate({ id: с.event_id!, что: 'declined' })}>Не смогу</Button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </section>
      )}

      {зовут.length > 0 && (
        <section>
          <h2 className="mb-1 flex items-center gap-2 text-sm font-medium">
            <UserPlus className="h-4 w-4 text-primary" />Вас зовут
            <span className="text-muted-foreground">· {зовут.length}</span>
          </h2>
          {зовут.map(в => (
            <TalkRow key={в.id} meeting={в} companyId={companyId} onChanged={обновить} />
          ))}
        </section>
      )}

      {встречи.length > 0 && (
        <section>
          <h2 className="mb-1 text-sm font-medium">Назначены</h2>
          {встречи.map(в => (
            <TalkRow key={в.id} meeting={в} companyId={companyId} onChanged={обновить} />
          ))}
        </section>
      )}

      {окно && (
        <NewTalkDialog companyId={companyId} onClose={() => setОкно(false)}
          onCreated={() => { setОкно(false); обновить() }} />
      )}
    </div>
  )
}
