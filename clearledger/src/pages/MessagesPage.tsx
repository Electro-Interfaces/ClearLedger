/**
 * Приложение «Чаты» — управление чатами пространства. Вход только администраторам.
 *
 * Зачем отдельный экран, если чат уже открывается доком и модалкой: те отвечают на
 * вопрос «мои разговоры» — показывают комнаты, где ты сам участник. Здесь другой
 * вопрос: что вообще происходит в пространстве. Кто владелец канала, сколько в группе
 * людей партнёра и какого, к какому приложению привязан чат, где месяц не писали.
 *
 * Раньше по этому адресу жил полностраничный мессенджер на Matrix — второй, никем не
 * использованный чат-контур (в пилоте ГИГ: ни одной комнаты, одна служебная учётка и
 * «Не удалось подключиться к чату» на экране). Основным чатом решением МАГа остаётся
 * свой контур `/api/chat`, поэтому адрес занят тем, чего действительно не хватало.
 * Прежняя версия сохранена рядом как `MessagesPage.tsx.matrix-bak`.
 */

import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  Archive, ArchiveRestore, Crown, Hash, Loader2, Megaphone, MessagesSquare,
  Search, Shield, ShieldAlert, Trash2, User as UserIcon, Users,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { CreateRoomDialog } from '@/components/chat/CreateRoomDialog'
import { PartyBadge } from '@/components/chat/PartyBadge'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cn } from '@/lib/utils'
import { useSupportContext } from '@/contexts/SupportContext'
import * as chat from '@/services/chatService'
import * as admin from '@/services/chatAdminService'
import { SPACE_PRODUCTS } from '@/config/spaceProducts'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const dmy = (iso: string | null) =>
  (iso ? new Date(iso).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit' }) : '—')
/** Дни тишины — главный признак заброшенного чата. */
const silentDays = (iso: string | null) =>
  (iso ? Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000) : null)

const TYPES = {
  channel: { label: 'Канал', icon: Megaphone, hint: 'односторонний: пишут владелец и админы' },
  group: { label: 'Группа', icon: Users, hint: 'пишут все участники' },
  direct: { label: 'Личный', icon: UserIcon, hint: 'разговор двоих' },
  company: { label: 'Системный', icon: Hash, hint: 'комната пространства' },
} as const

/**
 * Вид чата по его роли в пространстве, а не по полю в базе: «Объявления» и «Обновления
 * платформы» — каналы, «Общий чат» и группы приложений — группы. Базовый набор заводится
 * сам (`ensure_company_rooms`), и в таблице он должен читаться так же, как созданный
 * руками, иначе администратор ищет в списке «системное» вместо канала.
 */
function typeOf(r: admin.AdminRoom) {
  if (r.kind === 'news' || r.kind === 'platform') return TYPES.channel
  if (r.kind === 'general' || r.kind?.startsWith('app:')) return TYPES.group
  return TYPES[r.type as keyof typeof TYPES] ?? TYPES.group
}

function Stat({ label, value, sub, tone }: {
  label: string; value: string; sub?: string; tone?: 'warn' | 'info'
}) {
  return (
    <div className="min-w-0 border-r border-border/70 px-4 py-3 last:border-r-0">
      <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className={cn('mt-1 truncate text-lg font-semibold tabular-nums',
        tone === 'warn' && 'text-amber-600 dark:text-amber-400',
        tone === 'info' && 'text-sky-600 dark:text-sky-400')}>{value}</div>
      {sub && <div className="mt-0.5 truncate text-[11px] text-muted-foreground">{sub}</div>}
    </div>
  )
}

/** Состав чата: роли, метки партнёров, действия администратора. */
function RoomMembers({ roomId }: { roomId: string }) {
  const qc = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ['chat-room-detail', roomId],
    queryFn: () => chat.getRoom(roomId),
  })
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['chat-room-detail', roomId] })
    qc.invalidateQueries({ queryKey: ['chat-admin-rooms'] })
  }
  const setRole = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: string }) =>
      admin.setRole(roomId, userId, role),
    onSuccess: () => { refresh(); toast.success('Роль изменена') },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Не удалось изменить роль'),
  })
  const remove = useMutation({
    mutationFn: (userId: string) => admin.removeParticipant(roomId, userId),
    onSuccess: () => { refresh(); toast.success('Участник выведен из чата') },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Не удалось вывести участника'),
  })
  // Добор состава: канал новостей набирают «всем пространством», группу — человеком.
  const people = useQuery({
    queryKey: ['chat-admin-people'], queryFn: admin.getPeople, staleTime: 5 * 60_000,
  })
  const addPeople = useMutation({
    mutationFn: (body: { userIds?: string[]; everyone?: boolean }) => admin.addPeople(roomId, body),
    onSuccess: () => { refresh(); toast.success('Состав пополнен') },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Не удалось добавить'),
  })

  if (isLoading) {
    return <div className="flex justify-center py-6"><Loader2 className="size-4 animate-spin text-muted-foreground" /></div>
  }
  const parts = data?.participants ?? []
  return (
    <div className="space-y-0.5 px-4 pb-3 pt-2">
      <div className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">
        Состав · {nf0.format(parts.length)}
      </div>
      {parts.map((p) => (
        <div key={p.userId} className="flex items-center gap-2 rounded-md px-2 py-1.5 text-xs hover:bg-muted/40">
          <span className="truncate font-medium">{p.name}</span>
          <PartyBadge party={{
            partyType: p.partyType ?? (p.isExternal ? 'partner' : 'internal'),
            orgName: p.companyName,
          }} />
          <span className="ml-auto shrink-0 text-[10px] text-muted-foreground">
            {p.role === 'owner' ? 'владелец' : p.role === 'admin' ? 'админ' : 'участник'}
          </span>
          {p.role !== 'owner' && (
            <>
              <button type="button" title="Сделать владельцем"
                onClick={() => setRole.mutate({ userId: p.userId, role: 'owner' })}
                className="shrink-0 rounded p-1 text-muted-foreground hover:text-foreground">
                <Crown className="size-3.5" />
              </button>
              <button type="button" title={p.role === 'admin' ? 'Снять права админа' : 'Сделать админом'}
                onClick={() => setRole.mutate({ userId: p.userId, role: p.role === 'admin' ? 'member' : 'admin' })}
                className={cn('shrink-0 rounded p-1 hover:text-foreground',
                  p.role === 'admin' ? 'text-sky-500' : 'text-muted-foreground')}>
                <Shield className="size-3.5" />
              </button>
              <button type="button" title="Вывести из чата"
                onClick={() => remove.mutate(p.userId)}
                className="shrink-0 rounded p-1 text-muted-foreground hover:text-rose-500">
                <Trash2 className="size-3.5" />
              </button>
            </>
          )}
        </div>
      ))}
      <div className="mt-2 flex flex-wrap items-center gap-2 border-t border-border/60 pt-2">
        <Select value="" onValueChange={(v) => addPeople.mutate({ userIds: [v] })}>
          <SelectTrigger className="h-7 w-[220px] text-xs">
            <SelectValue placeholder="Добавить человека…" />
          </SelectTrigger>
          <SelectContent>
            {(people.data ?? [])
              .filter((x) => !parts.some((p) => p.userId === x.userId))
              .map((x) => (
                <SelectItem key={x.userId} value={x.userId} className="text-xs">
                  {x.name}{x.companyName ? ` · ${x.companyName}` : ''}
                </SelectItem>
              ))}
          </SelectContent>
        </Select>
        <Button size="sm" variant="outline" className="h-7 text-xs"
          disabled={addPeople.isPending}
          onClick={() => addPeople.mutate({ everyone: true })}>
          {addPeople.isPending && <Loader2 className="mr-1.5 size-3 animate-spin" />}
          Добавить всё пространство
        </Button>
      </div>
    </div>
  )
}

export function MessagesPage() {
  const qc = useQueryClient()
  // Раздел живёт в АДРЕСЕ (?view=), а не в локальном состоянии: его задаёт левое меню
  // приложения, и оно же подсвечивает активный пункт. Селектор вида и переключатель
  // архива меняют тот же параметр — иначе меню и экран показывали бы разное.
  const [params, setParams] = useSearchParams()
  const view = params.get('view') || 'all'
  const archived = view === 'archive'
  const kind = view === 'channel' ? 'Канал' : view === 'group' ? 'Группа'
    : view === 'direct' ? 'Личный' : 'all'
  const setView = (v: string) => {
    const next = new URLSearchParams(params)
    if (v === 'all') next.delete('view')
    else next.set('view', v)
    setParams(next, { replace: true })
  }
  const [q, setQ] = useState('')
  const [open, setOpen] = useState<string | null>(null)
  // Открыть саму переписку (не админ-состав): та же панель чата, что у «Чат» в
  // шапке, наведённая на комнату — как в мессенджере, клик по чату входит в него.
  const { openInteraction } = useSupportContext()
  const [create, setCreate] = useState<'channel' | 'group' | null>(null)

  const { data, isLoading, error } = useQuery({
    queryKey: ['chat-admin-rooms', archived],
    queryFn: () => admin.getRooms(archived),
  })

  const patchRoom = useMutation({
    mutationFn: ({ id, body }: { id: string; body: admin.RoomPatch }) => admin.patchRoom(id, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['chat-admin-rooms'] })
      toast.success('Чат обновлён')
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Не удалось обновить чат'),
  })
  const archiveRoom = useMutation({
    mutationFn: ({ id, on }: { id: string; on: boolean }) =>
      (on ? chat.archiveRoom(id) : chat.unarchiveRoom(id)),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['chat-admin-rooms'] }); toast.success('Готово') },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Не удалось изменить архив'),
  })

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return (data ?? []).filter((r) => {
      if (kind !== 'all' && typeOf(r).label !== kind) return false
      if (!needle) return true
      return (r.name ?? '').toLowerCase().includes(needle)
        || (r.ownerName ?? '').toLowerCase().includes(needle)
    })
  }, [data, q, kind])

  const totals = useMemo(() => (data ?? []).reduce((a, r) => ({
    channels: a.channels + (typeOf(r).label === 'Канал' ? 1 : 0),
    groups: a.groups + (typeOf(r).label === 'Группа' ? 1 : 0),
    direct: a.direct + (r.type === 'direct' ? 1 : 0),
    external: a.external + r.externalCount,
    silent: a.silent + ((silentDays(r.lastMessageAt) ?? 9999) > 30 ? 1 : 0),
  }), { channels: 0, groups: 0, direct: 0, external: 0, silent: 0 }), [data])

  // 403 — не администратор: экран объясняет, почему закрыт, а не показывает пустоту.
  const forbidden = error instanceof Error && /403|администратор/i.test(error.message)

  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-base font-semibold">
            <MessagesSquare className="size-4 text-blue-600 dark:text-blue-400" />Чаты пространства
          </h1>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Каналы, группы и личные переписки компании: состав, владельцы, привязка к
            приложению. Управление доступно администраторам пространства.
          </p>
        </div>
        <div className="flex items-center gap-2">
        <Button size="sm" variant="outline" className="h-7 gap-1.5 text-xs"
          onClick={() => setCreate('channel')}>
          <Megaphone className="size-3.5" />Канал
        </Button>
        <Button size="sm" variant="outline" className="h-7 gap-1.5 text-xs"
          onClick={() => setCreate('group')}>
          <Users className="size-3.5" />Группа
        </Button>
        <div className="inline-flex rounded-md border border-border p-0.5">
          {[{ v: false, l: 'Активные' }, { v: true, l: 'Архив' }].map((o) => (
            <button key={String(o.v)} type="button" onClick={() => setView(o.v ? 'archive' : 'all')}
              className={cn('rounded-[5px] px-2.5 py-1 text-xs transition-colors',
                archived === o.v ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:text-foreground')}>
              {o.l}
            </button>
          ))}
        </div>
        </div>
      </div>

      {create && (
        <CreateRoomDialog type={create} open onOpenChange={(v) => { if (!v) setCreate(null) }} />
      )}

      {forbidden ? (
        <div className="rounded-lg border border-dashed p-8 text-center">
          <ShieldAlert className="mx-auto size-6 text-amber-500" />
          <div className="mt-2 text-sm font-medium">Управление чатами закрыто</div>
          <div className="mt-1 text-xs text-muted-foreground">
            Экран доступен администраторам пространства. Свои чаты открываются кнопкой
            «Чат» в шапке и панелью справа.
          </div>
        </div>
      ) : isLoading ? (
        <div className="flex justify-center py-16"><Loader2 className="size-5 animate-spin text-muted-foreground" /></div>
      ) : error ? (
        <div className="rounded-lg border border-dashed p-8 text-center text-sm">
          <div className="text-red-400/90">Список чатов не загрузился</div>
          <div className="mt-1 text-xs text-muted-foreground">
            {error instanceof Error ? error.message : 'неизвестная ошибка'}
          </div>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 rounded-lg border md:grid-cols-5">
            <Stat label="Каналы" value={nf0.format(totals.channels)} sub="односторонние" />
            <Stat label="Группы" value={nf0.format(totals.groups)} sub="обсуждения" />
            <Stat label="Личные" value={nf0.format(totals.direct)} sub="переписки двоих" />
            <Stat label="Людей партнёров" value={nf0.format(totals.external)}
              sub="участий в чатах" tone={totals.external ? 'info' : undefined} />
            <Stat label="Молчат месяц" value={nf0.format(totals.silent)}
              sub="ни одного сообщения" tone={totals.silent ? 'warn' : undefined} />
          </div>

          <div className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-muted/30 px-3 py-2.5">
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
              Вид:
              <Select value={archived ? 'archive' : view} onValueChange={setView}>
                <SelectTrigger className="h-7 w-[150px] text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all" className="text-xs">Все виды</SelectItem>
                  <SelectItem value="channel" className="text-xs">Каналы</SelectItem>
                  <SelectItem value="group" className="text-xs">Группы</SelectItem>
                  <SelectItem value="direct" className="text-xs">Личные</SelectItem>
                </SelectContent>
              </Select>
            </label>
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Search className="size-3.5" />
              <Input value={q} onChange={(e) => setQ(e.target.value)}
                placeholder="Название или владелец" className="h-7 w-[200px] text-xs" />
            </label>
            <span className="ml-auto text-xs tabular-nums text-muted-foreground">
              {nf0.format(rows.length)} из {nf0.format(data?.length ?? 0)}
            </span>
          </div>

          {rows.length === 0 ? (
            <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
              {data?.length ? 'Под фильтр не подошёл ни один чат' : 'В пространстве пока нет чатов'}
            </div>
          ) : (
            <div className="overflow-x-auto rounded-lg border">
              <table className="w-full min-w-[900px] text-xs">
                <thead>
                  <tr className="border-b bg-muted/35 text-muted-foreground">
                    <th className="p-2 text-left font-medium">Чат</th>
                    <th className="p-2 text-left font-medium">Вид</th>
                    <th className="p-2 text-left font-medium">Владелец</th>
                    <th className="p-2 text-right font-medium">Участников</th>
                    <th className="p-2 text-right font-medium">Сообщений</th>
                    <th className="p-2 text-right font-medium">Последнее</th>
                    <th className="p-2 text-left font-medium">Приложение</th>
                    <th className="p-2" />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => {
                    const meta = typeOf(r)
                    const Ico = meta.icon
                    const days = silentDays(r.lastMessageAt)
                    const isOpen = open === r.id
                    return [
                      <tr key={r.id}
                        className={cn('border-b border-border/40 hover:bg-muted/25', isOpen && 'bg-muted/30')}>
                        <td className="p-2">
                          <button type="button" onClick={() => openInteraction('chat', `room:${r.id}`)}
                            className="text-left font-medium hover:text-primary hover:underline"
                            title="Открыть переписку">
                            {r.name ?? 'Личный чат'}
                          </button>
                        </td>
                        <td className="p-2 whitespace-nowrap text-muted-foreground" title={meta.hint}>
                          <Ico className="mr-1 inline size-3.5 align-[-2px]" />{meta.label}
                        </td>
                        <td className="max-w-[180px] truncate p-2 text-muted-foreground">{r.ownerName ?? '—'}</td>
                        <td className="p-2 text-right tabular-nums">
                          <button type="button" onClick={() => setOpen(isOpen ? null : r.id)}
                            className="tabular-nums hover:underline"
                            title={isOpen ? 'Скрыть состав' : 'Показать состав участников'}>
                            {nf0.format(r.participantCount)}
                          </button>
                          {r.externalCount > 0 && (
                            <span className="ml-1 text-[10px] text-amber-600 dark:text-amber-400"
                              title={`${r.externalCount} из компаний-партнёров`}>+{r.externalCount}</span>
                          )}
                        </td>
                        <td className="p-2 text-right tabular-nums text-muted-foreground">
                          {nf0.format(r.messageCount)}
                        </td>
                        <td className={cn('p-2 text-right whitespace-nowrap tabular-nums',
                          days != null && days > 30 ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground')}>
                          {r.lastMessageAt ? dmy(r.lastMessageAt) : 'нет сообщений'}
                        </td>
                        <td className="p-2">
                          {/* Привязка к приложению: чат остаётся в контексте, из которого его
                              завели, — правая рельса покажет его именно в этом приложении. */}
                          <Select value={r.scopeProduct ?? 'none'}
                            onValueChange={(v) => patchRoom.mutate({
                              id: r.id, body: { scopeProduct: v === 'none' ? '' : v },
                            })}>
                            <SelectTrigger className="h-7 w-[160px] text-xs"><SelectValue /></SelectTrigger>
                            <SelectContent>
                              <SelectItem value="none" className="text-xs">Всё пространство</SelectItem>
                              {SPACE_PRODUCTS.map((p) => (
                                <SelectItem key={p.code} value={p.code} className="text-xs">{p.label}</SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </td>
                        <td className="p-2 text-right">
                          <button type="button" title={r.isArchived ? 'Вернуть из архива' : 'В архив'}
                            onClick={() => archiveRoom.mutate({ id: r.id, on: !r.isArchived })}
                            className="rounded p-1 text-muted-foreground hover:text-foreground">
                            {r.isArchived ? <ArchiveRestore className="size-3.5" /> : <Archive className="size-3.5" />}
                          </button>
                        </td>
                      </tr>,
                      isOpen ? (
                        <tr key={`${r.id}-members`} className="border-b border-border/40 bg-muted/15">
                          <td colSpan={8} className="p-0"><RoomMembers roomId={r.id} /></td>
                        </tr>
                      ) : null,
                    ]
                  })}
                </tbody>
              </table>
            </div>
          )}

          <div className="space-y-2 rounded-lg border border-dashed px-4 py-3 text-xs leading-relaxed text-muted-foreground">
            <div>
              <span className="font-medium text-foreground">Что есть в пространстве сразу.</span>{' '}
              «Обновления платформы» — канал разработчика платформы: что вышло в продуктах и
              когда регламентные работы; пространство его читает. «Объявления» — канал
              компании: слово руководства сотрудникам, владельца назначаете вы. «Общий
              чат» — группа со всеми людьми пространства. Больше пространство само ничего
              не заводит: группы под работу создают сами люди.
            </div>
            <div>
              <span className="font-medium text-foreground">Что заводите вы.</span>{' '}
              Канал — когда нужно говорить, а не обсуждать (кадры, безопасность, рассылка):
              пишут в нём владелец и назначенные им админы. Группа — под задачу, объект или
              партнёра. Привязка к приложению делает чат контекстным: он сам открывается в
              рельсе того рабочего места. Владелец в чате один — назначая нового, прежний
              становится админом. Сотрудники компаний-партнёров чаты не создают, но
              участвуют в них и помечены в составе.
            </div>
          </div>
        </>
      )}
    </div>
  )
}

export default MessagesPage
