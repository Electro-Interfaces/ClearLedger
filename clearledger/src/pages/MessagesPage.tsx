/**
 * Чат экосистемы (Matrix) — модель Ангара (группы=комнаты, папки, личка) + ТЕМЫ (треды).
 * Полностраничный мессенджер: слева комнаты+папки, в центре лента+композер, справа — панель темы.
 * Данные Matrix — через matrixClient (matrix-js-sdk); провижининг/списки — /api/mchat/*.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  Loader2, Send, MessagesSquare, Users, Hash, User as UserIcon, Plus, Reply,
  MessageSquare, X, CornerDownRight, Search, Globe, LifeBuoy,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { PartyBadge, type PartyInfo } from '@/components/chat/PartyBadge'
import { isApiEnabled } from '@/services/apiClient'
import * as mc from '@/services/matrix/matrixClient'
import * as api from '@/services/matrix/mchatApi'
import type { ChatMessage, ChatRoom, ChatThread } from '@/services/matrix/types'

const QUICK = ['👍', '❤️', '🔥', '😂', '😮', '👏']
const FOLDER_ALL = 'all'

export function MessagesPage() {
  const [ready, setReady] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [rooms, setRooms] = useState<ChatRoom[]>([])
  const [active, setActive] = useState<string | null>(null)
  const [tick, setTick] = useState(0)   // форс-рефреш по realtime
  const [folder, setFolder] = useState<string>(FOLDER_ALL)
  const [dialog, setDialog] = useState<null | 'group' | 'dm' | 'public'>(null)
  const [thread, setThread] = useState<string | null>(null)   // открытая тема (root event id)

  const foldersQ = useQuery({ queryKey: ['mchat-folders'], queryFn: api.listFolders, enabled: ready })
  const [supportBusy, setSupportBusy] = useState(false)

  /** Открыть канал поддержки платформы: создаётся один раз, дальше просто открывается. */
  async function openSupport() {
    if (supportBusy) return
    setSupportBusy(true)
    try {
      const r = await api.openSupportChannel()
      setRooms(mc.getChatRooms())
      setActive(r.roomId)
      setThread(null)
      if (r.vendors === 0) {
        toast.warning('Канал создан, но инженеры поддержки не назначены', {
          description: 'В Центре управления отметьте участников поддержки платформы',
        })
      }
    } catch (e) {
      const msg = (e as Error).message || ''
      toast.error(/503|не настроен/i.test(msg) ? 'Чат не настроен' : 'Не удалось открыть канал поддержки')
    } finally {
      setSupportBusy(false)
    }
  }

  // инициализация Matrix
  useEffect(() => {
    let off: (() => void) | undefined
    if (!isApiEnabled()) { setErr('API выключен'); return }
    mc.ensureClient()
      .then(async () => {
        setReady(true)
        setRooms(mc.getChatRooms())
        off = await mc.subscribeChat(() => setTick((t) => t + 1))
      })
      .catch((e) => setErr(/503|не настроен/i.test((e as Error).message) ? 'Чат не настроен' : 'Не удалось подключиться к чату'))
    return () => { off?.() }
  }, [])

  // рефреш списка комнат по realtime
  useEffect(() => { if (ready) setRooms(mc.getChatRooms()) }, [ready, tick])

  const folders = foldersQ.data ?? []
  const filtered = useMemo(() => {
    if (folder === FOLDER_ALL) return rooms
    if (folder === 'auto:unread') return rooms.filter((r) => r.unread_count > 0)
    if (folder === 'auto:direct') return rooms.filter((r) => r.type === 'direct')
    if (folder === 'auto:group') return rooms.filter((r) => r.type !== 'direct')
    const f = folders.find((x) => x.id === folder)
    return f ? rooms.filter((r) => f.roomIds.includes(r.id)) : rooms
  }, [rooms, folder, folders])

  if (err) {
    return <div className="flex flex-col items-center justify-center h-[70vh] gap-2 text-muted-foreground">
      <MessagesSquare className="h-8 w-8" /><p>{err}</p></div>
  }
  if (!ready) {
    return <div className="flex items-center justify-center h-[70vh] gap-2 text-muted-foreground">
      <Loader2 className="h-5 w-5 animate-spin" /> Подключение к чату…</div>
  }

  return (
    <div className="flex h-[calc(100vh-var(--header-height)-2rem)] gap-3 min-h-0">
      {/* ── список комнат + папки ── */}
      <aside className="w-72 shrink-0 flex flex-col rounded-xl border bg-card min-h-0">
        <div className="flex items-center gap-1.5 p-2 border-b">
          <span className="text-sm font-semibold px-1 flex-1">Чаты</span>
          <Button size="icon" variant="ghost" className="h-8 w-8" title="Публичные" onClick={() => setDialog('public')}><Globe className="h-4 w-4" /></Button>
          <Button size="icon" variant="ghost" className="h-8 w-8" title="Личный чат" onClick={() => setDialog('dm')}><UserIcon className="h-4 w-4" /></Button>
          <Button size="icon" variant="ghost" className="h-8 w-8" title="Группа" onClick={() => setDialog('group')}><Plus className="h-4 w-4" /></Button>
          {/* Канал разработчика платформы: у заказчика должен быть штатный способ дойти
              до тех, кто эту экосистему делает, — теми же средствами, не через почту. */}
          <Button size="icon" variant="ghost" className="h-8 w-8 text-sky-600 dark:text-sky-400"
            title="Поддержка платформы" disabled={supportBusy} onClick={openSupport}>
            {supportBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <LifeBuoy className="h-4 w-4" />}
          </Button>
        </div>
        {/* папки */}
        <div className="flex gap-1 p-1.5 overflow-x-auto border-b text-xs">
          {[[FOLDER_ALL, 'Все'], ['auto:unread', 'Непроч.'], ['auto:direct', 'Личные'], ['auto:group', 'Группы']].map(([k, l]) => (
            <button key={k} onClick={() => setFolder(k)}
              className={`px-2 py-1 rounded-md whitespace-nowrap ${folder === k ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'}`}>{l}</button>
          ))}
          {folders.map((f) => (
            <button key={f.id} onClick={() => setFolder(f.id)}
              className={`px-2 py-1 rounded-md whitespace-nowrap ${folder === f.id ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'}`}>{f.name}</button>
          ))}
        </div>
        <div className="flex-1 overflow-y-auto min-h-0">
          {filtered.length === 0 && <div className="p-4 text-center text-xs text-muted-foreground">Нет чатов</div>}
          {filtered.map((r) => (
            <button key={r.id} onClick={() => { setActive(r.id); setThread(null) }}
              className={`w-full text-left px-3 py-2 border-b hover:bg-muted/50 ${active === r.id ? 'bg-muted' : ''}`}>
              <div className="flex items-center gap-2">
                {r.type === 'direct' ? <UserIcon className="h-4 w-4 text-muted-foreground shrink-0" />
                  : r.type === 'channel' ? <Hash className="h-4 w-4 text-muted-foreground shrink-0" />
                  : <Users className="h-4 w-4 text-muted-foreground shrink-0" />}
                <span className="text-sm font-medium truncate flex-1">{r.name || 'Личный чат'}</span>
                {r.unread_count > 0 && <Badge className="h-5 min-w-5 px-1 text-[10px]">{r.unread_count}</Badge>}
              </div>
              {r.last_message && <div className="text-xs text-muted-foreground truncate mt-0.5 pl-6">{r.last_message}</div>}
            </button>
          ))}
        </div>
      </aside>

      {/* ── лента комнаты ── */}
      <main className="flex-1 flex flex-col rounded-xl border bg-card min-h-0">
        {active ? (
          <RoomView key={active} roomId={active} tick={tick} onOpenThread={setThread} />
        ) : (
          <div className="flex-1 flex items-center justify-center text-muted-foreground gap-2">
            <MessagesSquare className="h-6 w-6" /> Выберите чат
          </div>
        )}
      </main>

      {/* ── панель темы (тред) ── */}
      {active && thread && (
        <ThreadPanel key={thread} roomId={active} rootId={thread} tick={tick} onClose={() => setThread(null)} />
      )}

      {dialog && <NewChatDialog kind={dialog} onClose={() => setDialog(null)}
        onOpened={async (roomId) => { setDialog(null); await mc.waitForRoom(roomId); setRooms(mc.getChatRooms()); setActive(roomId); setThread(null) }} />}
    </div>
  )
}

// ── лента одной комнаты ──
function RoomView({ roomId, tick, onOpenThread }: { roomId: string; tick: number; onOpenThread: (id: string) => void }) {
  const directory = useChatDirectory()
  const [msgs, setMsgs] = useState<ChatMessage[]>([])
  const [threads, setThreads] = useState<ChatThread[]>([])
  const [text, setText] = useState('')
  const [reply, setReply] = useState<ChatMessage | null>(null)
  const [showThreads, setShowThreads] = useState(false)
  const endRef = useRef<HTMLDivElement>(null)

  const load = useCallback(() => {
    mc.getChatMessages(roomId).then(setMsgs)
    mc.getThreads(roomId).then(setThreads)
    mc.markChatRead(roomId).catch(() => {})
  }, [roomId])

  useEffect(() => { load() }, [load, tick])
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [msgs.length])

  async function send() {
    const t = text.trim()
    if (!t) return
    setText('')
    try { await mc.sendChatMessage(roomId, t, { replyTo: reply?.id }); setReply(null) }
    catch { toast.error('Не удалось отправить') }
  }

  return (
    <>
      <div className="flex items-center gap-2 px-3 py-2 border-b">
        <MessagesSquare className="h-4 w-4 text-primary" />
        <span className="text-sm font-semibold flex-1 truncate">{mc.getChatRooms().find((r) => r.id === roomId)?.name || 'Чат'}</span>
        <Button size="sm" variant={showThreads ? 'default' : 'ghost'} className="gap-1.5 h-8" onClick={() => setShowThreads((v) => !v)}>
          <MessageSquare className="h-4 w-4" /> Темы {threads.length > 0 && <Badge variant="secondary" className="h-4 px-1 text-[10px]">{threads.length}</Badge>}
        </Button>
      </div>

      {showThreads && (
        <div className="border-b bg-muted/30 max-h-40 overflow-y-auto">
          {threads.length === 0 && <div className="p-3 text-xs text-muted-foreground">Тем пока нет. Ответьте в тему на любом сообщении, чтобы создать тему.</div>}
          {threads.map((t) => (
            <button key={t.root_id} onClick={() => onOpenThread(t.root_id)}
              className="w-full text-left px-3 py-2 border-b hover:bg-muted/50 flex items-center gap-2">
              <MessageSquare className="h-3.5 w-3.5 text-primary shrink-0" />
              <span className="text-sm truncate flex-1">{t.root_preview || 'Тема'}</span>
              <Badge variant="secondary" className="h-4 px-1 text-[10px]">{t.reply_count}</Badge>
            </button>
          ))}
        </div>
      )}

      <div className="flex-1 overflow-y-auto min-h-0 p-3 space-y-2">
        {msgs.map((m) => (
          <Bubble key={m.id} m={m} roomId={roomId} party={directory.get(m.user_id)}
            onReply={() => setReply(m)} onThread={() => onOpenThread(m.thread_root_id || m.id)} />
        ))}
        <div ref={endRef} />
      </div>

      {reply && (
        <div className="flex items-center gap-2 px-3 py-1.5 border-t bg-muted/40 text-xs">
          <Reply className="h-3.5 w-3.5 text-primary" />
          <span className="flex-1 truncate text-muted-foreground">Ответ: {reply.content}</span>
          <button onClick={() => setReply(null)}><X className="h-3.5 w-3.5" /></button>
        </div>
      )}
      <div className="flex items-center gap-2 p-2 border-t">
        <Input value={text} onChange={(e) => setText(e.target.value)} placeholder="Сообщение…"
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }} />
        <Button size="icon" onClick={send} disabled={!text.trim()}><Send className="h-4 w-4" /></Button>
      </div>
    </>
  )
}

/**
 * Справочник участников: mxid → «кто это». Matrix присылает автора как mxid, поэтому без
 * этой карты подписать сообщение «внешний · ООО Подрядчик» нечем. Кого в карте нет
 * (гость, бот) — остаётся без подписи, а не помечается своим.
 */
function useChatDirectory() {
  const q = useQuery({
    queryKey: ['mchat-directory'],
    queryFn: api.chatDirectory,
    staleTime: 60_000,
    // Присутствие живёт минутами — иначе точки «в сети» устаревали бы на глазах.
    refetchInterval: 60_000,
    retry: false,
  })
  return useMemo(() => {
    const map = new Map<string, PartyInfo>()
    for (const p of q.data ?? []) {
      map.set(p.mxid, {
        partyType: p.partyType, role: p.role, orgName: p.orgName,
        position: p.position, online: p.online, lastSeenAt: p.lastSeenAt,
      })
    }
    return map
  }, [q.data])
}

// ── сообщение ──
function Bubble({ m, roomId, party, onReply, onThread }: {
  m: ChatMessage; roomId: string; party?: PartyInfo; onReply: () => void; onThread: () => void
}) {
  const mine = m.user_id === mc.getMyId()
  return (
    <div className={`group flex flex-col ${mine ? 'items-end' : 'items-start'}`}>
      <div className={`max-w-[75%] rounded-2xl px-3 py-1.5 ${mine ? 'bg-primary text-primary-foreground' : 'bg-muted'}`}>
        {/* Автора подписываем вместе с принадлежностью: в общей комнате важно видеть,
            свой это сотрудник или внешний подрядчик. */}
        {!mine && (
          <div className="mb-0.5 flex items-center gap-1.5">
            {party?.online && (
              <span className="size-1.5 rounded-full bg-emerald-500" title="В системе сейчас" />
            )}
            <span className="text-[11px] font-medium opacity-70">{m.user_name}</span>
            <PartyBadge party={party} withIcon={false} />
          </div>
        )}
        <div className="text-sm whitespace-pre-wrap break-words">{m.content}{m.is_edited && <span className="opacity-50 text-[10px]"> (изм.)</span>}</div>
      </div>
      <div className="flex items-center gap-1 mt-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
        {QUICK.slice(0, 3).map((e) => (
          <button key={e} className="text-xs hover:scale-125 transition-transform" onClick={() => mc.toggleReaction(roomId, m.id, e).catch(() => {})}>{e}</button>
        ))}
        <button className="text-muted-foreground hover:text-foreground" title="Ответить" onClick={onReply}><Reply className="h-3.5 w-3.5" /></button>
        <button className="text-muted-foreground hover:text-foreground" title="Ответить в тему" onClick={onThread}><CornerDownRight className="h-3.5 w-3.5" /></button>
        {mine && <button className="text-muted-foreground hover:text-destructive" title="Удалить" onClick={() => mc.deleteChatMessage(roomId, m.id).catch(() => {})}><X className="h-3.5 w-3.5" /></button>}
      </div>
      {m.reactions && m.reactions.length > 0 && (
        <div className={`flex gap-1 mt-0.5 ${mine ? 'justify-end' : ''}`}>
          {m.reactions.map((r) => (
            <button key={r.key} onClick={() => mc.toggleReaction(roomId, m.id, r.key).catch(() => {})}
              className={`text-[11px] px-1.5 rounded-full border ${r.mine ? 'bg-primary/15 border-primary/40' : 'bg-muted border-border'}`}>{r.key} {r.count}</button>
          ))}
        </div>
      )}
    </div>
  )
}

// ── панель темы (тред) ──
function ThreadPanel({ roomId, rootId, tick, onClose }: { roomId: string; rootId: string; tick: number; onClose: () => void }) {
  const directory = useChatDirectory()
  const [msgs, setMsgs] = useState<ChatMessage[]>([])
  const [text, setText] = useState('')
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => { mc.getThreadMessages(roomId, rootId).then(setMsgs) }, [roomId, rootId, tick])
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [msgs.length])

  async function send() {
    const t = text.trim(); if (!t) return
    setText('')
    try { await mc.sendChatMessage(roomId, t, { threadRootId: rootId }) } catch { toast.error('Не удалось отправить') }
  }

  return (
    <aside className="w-80 shrink-0 flex flex-col rounded-xl border bg-card min-h-0">
      <div className="flex items-center gap-2 px-3 py-2 border-b">
        <MessageSquare className="h-4 w-4 text-primary" />
        <span className="text-sm font-semibold flex-1">Тема</span>
        <button onClick={onClose}><X className="h-4 w-4" /></button>
      </div>
      <div className="flex-1 overflow-y-auto min-h-0 p-3 space-y-2">
        {msgs.map((m) => (
          <Bubble key={m.id} m={m} roomId={roomId} party={directory.get(m.user_id)}
            onReply={() => {}} onThread={() => {}} />
        ))}
        <div ref={endRef} />
      </div>
      <div className="flex items-center gap-2 p-2 border-t">
        <Input value={text} onChange={(e) => setText(e.target.value)} placeholder="Ответить в тему…"
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }} />
        <Button size="icon" onClick={send} disabled={!text.trim()}><Send className="h-4 w-4" /></Button>
      </div>
    </aside>
  )
}

// ── новый чат: группа / личка / публичные ──
function NewChatDialog({ kind, onClose, onOpened }: { kind: 'group' | 'dm' | 'public'; onClose: () => void; onOpened: (roomId: string) => void }) {
  const [q, setQ] = useState('')
  const [title, setTitle] = useState('')
  const [picked, setPicked] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const peopleQ = useQuery({ queryKey: ['mchat-people', q], queryFn: () => api.searchPeople(q), enabled: kind !== 'public' })
  const publicQ = useQuery({ queryKey: ['mchat-public'], queryFn: api.listPublic, enabled: kind === 'public' })

  async function createGroup() {
    setBusy(true)
    try { const g = await api.createGroup(title || 'Группа', Object.keys(picked), false); onOpened(g.roomId) }
    catch { toast.error('Не удалось создать группу'); setBusy(false) }
  }
  async function openDm(userId: string) {
    setBusy(true)
    try { const r = await api.openDm(userId); onOpened(r.roomId) }
    catch { toast.error('Не удалось открыть чат'); setBusy(false) }
  }
  async function join(roomId: string) {
    setBusy(true)
    try { await api.joinRoom(roomId); onOpened(roomId) }
    catch { toast.error('Не удалось вступить'); setBusy(false) }
  }

  return (
    <div className="fixed inset-0 z-[1200] bg-black/40 flex items-center justify-center p-4" onClick={onClose}>
      <div className="w-full max-w-md rounded-xl border bg-card p-4 space-y-3" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2">
          <span className="font-semibold flex-1">{kind === 'group' ? 'Новая группа' : kind === 'dm' ? 'Личный чат' : 'Публичные чаты'}</span>
          <button onClick={onClose}><X className="h-4 w-4" /></button>
        </div>

        {kind === 'group' && <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Название группы" />}

        {kind !== 'public' ? (
          <>
            <div className="relative">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input className="pl-8" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Поиск сотрудника…" />
            </div>
            <div className="max-h-64 overflow-y-auto border rounded-lg divide-y">
              {(peopleQ.data ?? []).map((p) => (
                <button key={p.id} disabled={busy}
                  onClick={() => kind === 'dm' ? openDm(p.id) : setPicked((s) => { const n = { ...s }; if (n[p.id]) delete n[p.id]; else n[p.id] = p.name; return n })}
                  className={`w-full text-left px-3 py-2 hover:bg-muted/50 flex items-center gap-2 ${picked[p.id] ? 'bg-primary/10' : ''}`}>
                  <span className="relative shrink-0">
                    <UserIcon className="h-4 w-4 text-muted-foreground" />
                    {/* Зелёная точка — человек в системе сейчас: видно, дойдёт ли
                        сообщение до живого собеседника или ляжет до утра. */}
                    <span className={`absolute -right-0.5 -bottom-0.5 size-2 rounded-full ring-2 ring-card ${
                      p.online ? 'bg-emerald-500' : 'bg-muted-foreground/30'}`}
                      title={p.online ? 'В системе сейчас' : p.lastSeenAt
                        ? `Был ${new Date(p.lastSeenAt).toLocaleString('ru-RU')}` : 'Ни разу не заходил'} />
                  </span>
                  <span className="text-sm flex-1 min-w-0">
                    <span className="block truncate">{p.name} <span className="text-xs text-muted-foreground">{p.email}</span></span>
                  </span>
                  <PartyBadge party={p} />
                  {kind === 'group' && picked[p.id] && <Badge variant="secondary" className="text-[10px]">выбран</Badge>}
                </button>
              ))}
              {(peopleQ.data ?? []).length === 0 && <div className="p-3 text-center text-xs text-muted-foreground">Никого не найдено</div>}
            </div>
            {kind === 'group' && (
              <Button className="w-full" disabled={busy || Object.keys(picked).length === 0} onClick={createGroup}>
                {busy && <Loader2 className="h-4 w-4 animate-spin mr-1.5" />} Создать группу ({Object.keys(picked).length})
              </Button>
            )}
          </>
        ) : (
          <div className="max-h-72 overflow-y-auto border rounded-lg divide-y">
            {(publicQ.data ?? []).map((r) => (
              <div key={r.roomId} className="px-3 py-2 flex items-center gap-2">
                <Globe className="h-4 w-4 text-muted-foreground" />
                <span className="text-sm flex-1 truncate">{r.title}</span>
                <Button size="sm" variant="outline" disabled={busy} onClick={() => join(r.roomId)}>Вступить</Button>
              </div>
            ))}
            {(publicQ.data ?? []).length === 0 && <div className="p-3 text-center text-xs text-muted-foreground">Публичных чатов нет</div>}
          </div>
        )}
      </div>
    </div>
  )
}

export default MessagesPage
