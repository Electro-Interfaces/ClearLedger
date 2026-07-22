/**
 * Браузерный Matrix-клиент чата экосистемы (matrix-js-sdk). Модель Ангара + ТЕМЫ (threads).
 * SDK импортируется динамически (тяжёлый, отдельный чанк, грузится при открытии чата).
 * Токен берётся с backend (/api/mchat/session), в localStorage НЕ хранится, без crypto.
 */
/* eslint-disable @typescript-eslint/no-explicit-any */
import { getSession } from './mchatApi'
import type { ChatMessage, ChatRoom, ChatThread } from './types'

let sdk: any = null
let client: any = null
let myUserId = ''
let initPromise: Promise<any> | null = null

const DEVICE_KEY = 'clearledger:chatDeviceId'
function getOrCreateDeviceId(): string {
  let d = localStorage.getItem(DEVICE_KEY)
  if (!d) { d = 'CL' + Math.random().toString(36).slice(2, 12).toUpperCase(); localStorage.setItem(DEVICE_KEY, d) }
  return d
}

async function doInit(): Promise<any> {
  sdk = await import('matrix-js-sdk')
  const s = await getSession()
  myUserId = s.userId
  client = sdk.createClient({
    baseUrl: s.homeserver,
    accessToken: s.accessToken,
    userId: s.userId,
    deviceId: getOrCreateDeviceId(),
  })
  client.on(sdk.HttpApiEvent.SessionLoggedOut, () => teardownChat())
  await client.startClient({ initialSyncLimit: 50 })
  await new Promise<void>((resolve, reject) => {
    const t = setTimeout(() => reject(new Error('Matrix sync timeout')), 30000)
    client.once(sdk.ClientEvent.Sync, function onSync(state: string) {
      if (state === 'PREPARED') { clearTimeout(t); resolve() }
      else if (state === 'ERROR') { clearTimeout(t); reject(new Error('Matrix sync error')) }
      else client.once(sdk.ClientEvent.Sync, onSync)
    })
  })
  return client
}

export async function ensureClient(): Promise<any> {
  if (client) return client
  if (!initPromise) {
    initPromise = doInit().catch((e) => { initPromise = null; teardownChat(); throw e })
  }
  return initPromise
}

export function teardownChat(): void {
  try { client?.stopClient() } catch { /* ignore */ }
  client = null; myUserId = ''; initPromise = null
}

export function getMyId(): string { return myUserId }

// ── комнаты ──

function roomType(room: any): ChatRoom['type'] {
  const named = Boolean(room.name)
  const topicEv = room.currentState?.getStateEvents('m.room.topic', '')
  const topic = topicEv?.getContent?.()?.topic || ''
  if (typeof topic === 'string' && topic.startsWith('Чат канала')) return 'channel'
  return named ? 'group' : 'direct'
}

function lastEventPreview(room: any): { text: string; at?: string; by?: string } {
  const events = room.getLiveTimeline().getEvents()
  for (let i = events.length - 1; i >= 0; i--) {
    const ev = events[i]
    if (ev.getType() !== 'm.room.message' || ev.isRedacted()) continue
    const c = ev.getContent()
    let text = c.body || ''
    if (c.msgtype === 'm.image') text = '📷 Фото'
    else if (c.msgtype === 'm.video') text = '🎬 Видео'
    else if (c.msgtype === 'm.file') text = '📎 ' + (c.body || 'файл')
    return { text, at: new Date(ev.getTs()).toISOString(), by: ev.getSender() }
  }
  return { text: '' }
}

export function getChatRooms(): ChatRoom[] {
  if (!client) return []
  return client.getRooms()
    .filter((r: any) => r.getMyMembership() === 'join')
    .map((room: any): ChatRoom => {
      const prev = lastEventPreview(room)
      return {
        id: room.roomId,
        type: roomType(room),
        name: room.name || undefined,
        unread_count: room.getUnreadNotificationCount?.() ?? 0,
        last_message: prev.text,
        last_message_at: prev.at,
        last_message_by: prev.by,
        created_at: new Date(room.getLastActiveTimestamp?.() || Date.now()).toISOString(),
        updated_at: prev.at || new Date().toISOString(),
      }
    })
    .sort((a: ChatRoom, b: ChatRoom) => (b.last_message_at || '').localeCompare(a.last_message_at || ''))
}

export async function waitForRoom(roomId: string, timeoutMs = 8000): Promise<void> {
  const c = await ensureClient()
  if (c.getRoom(roomId)) return
  await new Promise<void>((resolve) => {
    const t = setTimeout(resolve, timeoutMs)
    const h = (room: any) => { if (room.roomId === roomId) { clearTimeout(t); c.off(sdk.ClientEvent.Room, h); resolve() } }
    c.on(sdk.ClientEvent.Room, h)
  })
}

export async function leaveRoom(roomId: string): Promise<void> {
  const c = await ensureClient()
  await c.leave(roomId)
}

// ── сообщения (главная лента, без тред-ответов) ──

function eventToMessage(ev: any, room: any): ChatMessage {
  const c = ev.getContent()
  const relates = c['m.relates_to'] || {}
  const isThread = relates.rel_type === 'm.thread'
  let type: ChatMessage['type'] = 'text'
  if (c.msgtype === 'm.image') type = 'image'
  else if (c.msgtype === 'm.video') type = 'video'
  else if (c.msgtype === 'm.file') type = 'file'
  const replyTo = relates['m.in_reply_to']?.event_id
  const member = room.getMember?.(ev.getSender())
  // реакции
  const reactions = aggregateReactions(room, ev.getId())
  return {
    id: ev.getId(),
    room_id: room.roomId,
    user_id: ev.getSender(),
    user_name: member?.name || ev.getSender(),
    type,
    content: (ev.replacingEvent()?.getContent()?.['m.new_content']?.body) ?? c.body ?? '',
    file_name: type !== 'text' ? c.body : undefined,
    file_size: c.info?.size,
    file_mime: c.info?.mimetype,
    reply_to: !isThread ? replyTo : undefined,
    reactions: reactions.length ? reactions : undefined,
    is_edited: Boolean(ev.replacingEvent()),
    thread_root_id: isThread ? relates.event_id : undefined,
    created_at: new Date(ev.getTs()).toISOString(),
  }
}

function aggregateReactions(room: any, eventId: string): { key: string; count: number; mine: boolean }[] {
  const map = new Map<string, { count: number; mine: boolean }>()
  const rels = room.getUnfilteredTimelineSet?.().relations?.getChildEventsForEvent?.(eventId, 'm.annotation', 'm.reaction')
  const evs = rels?.getRelations?.() || []
  for (const r of evs) {
    if (r.isRedacted()) continue
    const key = r.getContent()['m.relates_to']?.key
    if (!key) continue
    const cur = map.get(key) || { count: 0, mine: false }
    cur.count++
    if (r.getSender() === myUserId) cur.mine = true
    map.set(key, cur)
  }
  return [...map.entries()].map(([key, v]) => ({ key, ...v }))
}

export async function getChatMessages(roomId: string): Promise<ChatMessage[]> {
  const c = await ensureClient()
  const room = c.getRoom(roomId)
  if (!room) return []
  const tl = room.getLiveTimeline()
  if (tl.getEvents().length < 20) { try { await c.scrollback(room, 50) } catch { /* ignore */ } }
  return tl.getEvents()
    .filter((ev: any) => ev.getType() === 'm.room.message' && ev.getContent()['m.relates_to']?.rel_type !== 'm.replace')
    .filter((ev: any) => ev.getContent()['m.relates_to']?.rel_type !== 'm.thread') // тред-ответы — не в главной ленте
    .map((ev: any) => eventToMessage(ev, room))
}

// ── ТЕМЫ (Matrix threads) ──

export async function getThreads(roomId: string): Promise<ChatThread[]> {
  const c = await ensureClient()
  const room = c.getRoom(roomId)
  if (!room) return []
  let threads: any[] = []
  try { threads = room.getThreads?.() || [] } catch { threads = [] }
  return threads.map((t: any): ChatThread => {
    const root = t.rootEvent
    const rc = root?.getContent?.() || {}
    return {
      root_id: t.id || root?.getId(),
      root_preview: rc.body || '',
      root_user_name: room.getMember?.(root?.getSender())?.name || root?.getSender() || '',
      reply_count: t.length ?? (t.replyCount ?? 0),
      latest_at: t.replyToEvent ? new Date(t.replyToEvent.getTs()).toISOString() : undefined,
    }
  }).sort((a, b) => (b.latest_at || '').localeCompare(a.latest_at || ''))
}

export async function getThreadMessages(roomId: string, threadRootId: string): Promise<ChatMessage[]> {
  const c = await ensureClient()
  const room = c.getRoom(roomId)
  if (!room) return []
  const thread = room.getThread?.(threadRootId)
  const events: any[] = thread?.timeline || []
  // корень + ответы
  const rootEv = room.findEventById?.(threadRootId)
  const all = rootEv ? [rootEv, ...events.filter((e: any) => e.getId() !== threadRootId)] : events
  return all
    .filter((ev: any) => ev.getType() === 'm.room.message' && ev.getContent()['m.relates_to']?.rel_type !== 'm.replace')
    .map((ev: any) => eventToMessage(ev, room))
}

// ── отправка (текст / ответ / в тему) ──

export async function sendChatMessage(
  roomId: string, content: string, opts?: { replyTo?: string; threadRootId?: string },
): Promise<void> {
  const c = await ensureClient()
  const body: any = { msgtype: 'm.text', body: content }
  if (opts?.threadRootId) {
    body['m.relates_to'] = { rel_type: 'm.thread', event_id: opts.threadRootId, is_falling_back: true }
    if (opts.replyTo) body['m.relates_to']['m.in_reply_to'] = { event_id: opts.replyTo }
  } else if (opts?.replyTo) {
    body['m.relates_to'] = { 'm.in_reply_to': { event_id: opts.replyTo } }
  }
  await c.sendEvent(roomId, 'm.room.message', body)
}

export async function editChatMessage(roomId: string, eventId: string, content: string): Promise<void> {
  const c = await ensureClient()
  await c.sendEvent(roomId, 'm.room.message', {
    msgtype: 'm.text', body: '* ' + content,
    'm.new_content': { msgtype: 'm.text', body: content },
    'm.relates_to': { rel_type: 'm.replace', event_id: eventId },
  })
}

export async function deleteChatMessage(roomId: string, eventId: string): Promise<void> {
  const c = await ensureClient()
  await c.redactEvent(roomId, eventId)
}

export async function toggleReaction(roomId: string, eventId: string, key: string): Promise<void> {
  const c = await ensureClient()
  const room = c.getRoom(roomId)
  const rels = room?.getUnfilteredTimelineSet?.().relations?.getChildEventsForEvent?.(eventId, 'm.annotation', 'm.reaction')
  const mine = (rels?.getRelations?.() || []).find((r: any) =>
    r.getSender() === myUserId && r.getContent()['m.relates_to']?.key === key && !r.isRedacted())
  if (mine) { await c.redactEvent(roomId, mine.getId()); return }
  await c.sendEvent(roomId, 'm.reaction', { 'm.relates_to': { rel_type: 'm.annotation', event_id: eventId, key } })
}

// ── непрочитанное / прочтение ──

export async function markChatRead(roomId: string): Promise<void> {
  const c = await ensureClient()
  const room = c.getRoom(roomId)
  const events = room?.getLiveTimeline().getEvents() || []
  const last = events[events.length - 1]
  if (last) await c.sendReadReceipt(last)
}

export function getChatUnread(): number {
  if (!client) return 0
  return client.getRooms()
    .filter((r: any) => r.getMyMembership() === 'join')
    .reduce((sum: number, r: any) => sum + (r.getUnreadNotificationCount?.() ?? 0), 0)
}

// ── realtime ──

export async function subscribeChat(handler: () => void): Promise<() => void> {
  const c = await ensureClient()
  const h = () => handler()
  c.on(sdk.RoomEvent.Timeline, h)
  c.on(sdk.RoomEvent.Receipt, h)
  return () => { c.off(sdk.RoomEvent.Timeline, h); c.off(sdk.RoomEvent.Receipt, h) }
}

export async function subscribeTyping(roomId: string, handler: (names: string[]) => void): Promise<() => void> {
  const c = await ensureClient()
  const h = (_ev: any, member: any) => {
    if (member.roomId !== roomId) return
    const room = c.getRoom(roomId)
    const typing = (room?.currentState?.getStateEvents('m.typing', '')?.getContent?.()?.user_ids) || []
    handler(typing.filter((u: string) => u !== myUserId).map((u: string) => room?.getMember?.(u)?.name || u))
  }
  c.on(sdk.RoomMemberEvent.Typing, h)
  return () => c.off(sdk.RoomMemberEvent.Typing, h)
}

export async function sendTyping(roomId: string, typing: boolean): Promise<void> {
  const c = await ensureClient()
  try { await c.sendTyping(roomId, typing, typing ? 5000 : undefined) } catch { /* ignore */ }
}
