/**
 * Клиент REST /api/chat/* — внутренний чат (порт ядра TSupport, Telegram-like).
 * WebSocket-часть — в hooks/useChatWs.ts. Вложения — через /api/intake + /api/files.
 */
import { get, post, patch, del, upload } from './apiClient'

export interface ChatReaction {
  emoji: string
  count: number
  mine: boolean
  /** Кто поставил: «Вы» первым, дальше имена участников. */
  users?: string[]
}

export interface ChatPinned { id: string; content: string; userName: string | null }

export interface ChatRoom {
  id: string
  /** channel — односторонний (новости, рассылка): пишут владелец и админы канала. */
  type: 'company' | 'direct' | 'group' | 'channel'
  /** Системный чат пространства: общий, канал компании, канал платформы.
      Значения задаёт chat_router (SYSTEM_ROOMS); null — обычная группа. */
  kind: 'general' | 'news' | 'platform' | null
  /** Приложение, к которому привязан чат; null — чат всего пространства. */
  scopeProduct?: string | null
  name: string | null
  isArchived: boolean
  participantCount: number
  unreadCount: number
  directPeerId: string | null
  lastMessage: string | null
  lastMessageAt: string | null
  createdBy: string | null
  pinnedMessage: ChatPinned | null
  /** Моя роль в этом чате: owner | admin | member. В канале пишут первые двое. */
  myRole?: string | null
  /** Аватар чата (/api/files/<id>); null — иконка по типу комнаты. */
  avatarUrl?: string | null
  /** «Без звука» до этого момента: не шлём push и не красим общий счётчик. */
  mutedUntil?: string | null
  /** Чат закреплён вверху МОЕГО списка (личная настройка). */
  isPinned?: boolean
  /** Могу ли я здесь писать — решает сервер, фронт не выводит это сам. */
  canWrite?: boolean
  /** Объект пространства, при котором живёт чат («группа по станции»). */
  scopeObjectId?: string | null
  scopeObjectName?: string | null
  /** Чат заявки: скрыт из общего списка, открывается из её карточки. */
  scopeTicketId?: string | null
}

/** Чат сейчас «без звука»? (9999 год = навсегда) */
export const isMuted = (r: Pick<ChatRoom, 'mutedUntil'>): boolean =>
  !!r.mutedUntil && Date.parse(r.mutedUntil) > Date.now()

/** Кто это в пространстве: инженер разработчика платформы, свой сотрудник, партнёр. */
export type PartyType = 'vendor' | 'internal' | 'partner'

export interface ChatParticipant {
  userId: string
  name: string
  /** Роль в комнате: owner — создатель, admin — назначенный им, member — остальные. */
  role: string
  online: boolean
  /** true — человек компании-партнёра, а не наш сотрудник. */
  isExternal?: boolean
  /** Компания партнёра: в смешанной группе надо видеть, при ком идёт разговор. */
  companyName?: string | null
  /** vendor | internal | partner — та же категория, что в Центре управления. */
  partyType?: PartyType
  /** Фото человека (/api/files/<id>); нет — генеративный кружок с инициалами. */
  avatarUrl?: string | null
  /** Участник живёт в своей почте: сообщения уходят ему письмом, ответ — в ленту. */
  mailOnly?: boolean
  /** Адрес почтового участника — показываем, куда именно уходит разговор. */
  email?: string | null
}

export interface ChatRoomDetail extends ChatRoom {
  participants: ChatParticipant[]
}

export interface ChatMessage {
  id: string
  roomId: string
  userId: string | null
  userName: string | null
  type: string          // text | image | video | file | system
  content: string
  fileUrl: string | null
  fileName: string | null
  fileSize: number | null
  replyTo: string | null
  replyPreview: string | null
  replyAuthor: string | null
  isEdited: boolean
  isDeleted: boolean
  readCount: number
  reactions: ChatReaction[]
  createdAt: string
  /** Кто написал: разработчик платформы, свой сотрудник или человек партнёра. */
  authorParty?: PartyType | null
  /** Пересланное: имя автора оригинала («Переслано от …»). */
  forwardedFrom?: string | null
  /** 'email' — сообщение пришло письмом от участника, живущего в своей почте. */
  externalSource?: string | null
  /** Опрос, если сообщение — опрос (type='poll'). */
  poll?: ChatPoll | null
}

/** Опрос в чате: вопрос, варианты и текущий расклад голосов. */
export interface ChatPoll {
  id: string
  question: string
  options: string[]
  counts: number[]
  /** Кто за что голосовал; null — опрос анонимный. */
  voters: string[][] | null
  multiple: boolean
  anonymous: boolean
  /** Участник может дописать свой вариант. */
  allowCustom: boolean
  myVotes: number[]
  totalVoters: number
  isClosed: boolean
  createdBy: string | null
}

export const createPoll = (roomId: string, body: {
  question: string; options: string[]; multiple: boolean; anonymous: boolean; allowCustom: boolean
}) => post<ChatMessage & { poll: ChatPoll }>(`/api/chat/rooms/${roomId}/polls`, body)

/** Дописать свой вариант и сразу отдать за него голос (если опрос открытый). */
export const addPollOption = (pollId: string, text: string) =>
  post<ChatPoll>(`/api/chat/polls/${pollId}/options`, { text })

/** Отдать голос; пустой список — снять свой выбор. */
export const votePoll = (pollId: string, options: number[]) =>
  post<ChatPoll>(`/api/chat/polls/${pollId}/vote`, { options })

export const closePoll = (pollId: string) =>
  post<ChatPoll>(`/api/chat/polls/${pollId}/close`, {})

export interface ChatUser {
  userId: string; name: string; email: string; online: boolean
  /** Фото человека (/api/files/<id>) — то же, что у участника комнаты. */
  avatarUrl?: string | null
}
export interface ChatPresence { userId: string; name: string; online: boolean }
export interface ChatFolder { id: string; name: string; roomIds: string[]; sortOrder: number }

export interface SendPayload {
  content?: string
  replyTo?: string
  type?: string
  fileUrl?: string
  fileName?: string
  fileSize?: number
  mentions?: string[]
}

// ── комнаты ────────────────────────────────────────────────────────────────
/**
 * Список чатов человека. `product` — код приложения: правая рельса просит чаты своего
 * приложения (к ним всегда добавляются общие чаты пространства), верхняя кнопка
 * параметр не передаёт и получает всё. Один и тот же чат, разные предустановки.
 */
export const getRooms = (archived = false, product?: string | null, objectId?: string | null) =>
  get<ChatRoom[]>('/api/chat/rooms', {
    archived: String(archived),
    ...(product ? { product } : {}),
    ...(objectId ? { object_id: objectId } : {}),
  })

export const getRoom = (roomId: string) =>
  get<ChatRoomDetail>(`/api/chat/rooms/${roomId}`)

export const createRoom = (
  type: 'direct' | 'group' | 'channel',
  participantIds: string[],
  name?: string,
  scopeProduct?: string | null,
  scopeObjectId?: string | null,
) =>
  post<ChatRoomDetail>('/api/chat/rooms', { type, participantIds, name, scopeProduct, scopeObjectId })

export const archiveRoom = (roomId: string) =>
  post<{ ok: boolean; isArchived: boolean }>(`/api/chat/rooms/${roomId}/archive`, {})

export const unarchiveRoom = (roomId: string) =>
  post<{ ok: boolean; isArchived: boolean }>(`/api/chat/rooms/${roomId}/unarchive`, {})

export const addParticipant = (roomId: string, userId: string) =>
  post<{ ok: boolean }>(`/api/chat/rooms/${roomId}/participants`, { userId })

/** Позвать в чат человека, который работает в своей почте и в пространство не заходит.
 * Сообщения комнаты уходят ему письмом, ответ возвращается в ленту. */
export const addMailParticipant = (roomId: string, email: string, name?: string) =>
  post<{ ok: boolean; userId: string; email: string; replyAddress: string | null }>(
    `/api/chat/rooms/${roomId}/participants/mail`, { email, name })

/** Переименовать чат, сменить аватар, привязку к приложению или объекту — владелец
 * или админ чата (у системных — только пространство; '' очищает значение). */
export const patchRoom = (roomId: string,
  body: { name?: string; avatarUrl?: string; scopeProduct?: string; scopeObjectId?: string }) =>
  patch<{ ok: boolean; name: string | null; avatarUrl: string | null; scopeProduct: string | null; scopeObjectId: string | null }>(
    `/api/chat/rooms/${roomId}`, body)

/** Убрать участника: владелец — любого, админ чата — обычных участников. */
export const removeParticipant = (roomId: string, userId: string) =>
  del(`/api/chat/rooms/${roomId}/participants/${userId}`)

/** Назначить или снять админа чата — только владелец; админов может быть несколько. */
export const setParticipantRole = (roomId: string, userId: string, role: 'admin' | 'member') =>
  patch(`/api/chat/rooms/${roomId}/participants/${userId}`, { role })

/** Выйти из группы самому. Системные чаты и каналы — без выхода. */
export const leaveRoom = (roomId: string) =>
  post(`/api/chat/rooms/${roomId}/leave`, {})

/** Карточка ссылки: заголовок, описание, домен. Пустой объект — превью нет. */
export interface LinkPreview {
  url?: string
  site?: string
  title?: string
  description?: string
  image?: string
}

export const getLinkPreview = (url: string) =>
  get<LinkPreview>('/api/chat/link-preview', { url })

/** Вложения чата: фотографии и файлы одним списком (последние 200). */
export interface ChatMediaItem {
  messageId: string
  fileUrl: string
  fileName: string | null
  fileSize: number | null
  type: string
  userName: string | null
  createdAt: string
}

export const getRoomMedia = (roomId: string) =>
  get<ChatMediaItem[]>(`/api/chat/rooms/${roomId}/media`)

/** Закрепить чат вверху своего списка / открепить (переключатель). */
export const pinRoom = (roomId: string) =>
  post<{ ok: boolean; isPinned: boolean }>(`/api/chat/rooms/${roomId}/pin-room`, {})

/** «Без звука»: until = 'forever' | ISO-время | null (включить уведомления). */

export const muteRoom = (roomId: string, until: 'forever' | string | null) =>
  post<{ mutedUntil: string | null }>(`/api/chat/rooms/${roomId}/mute`, { until })

/** Переслать сообщение в другие чаты (копия несёт имя автора оригинала). */
export const forwardMessage = (messageId: string, toRoomIds: string[]) =>
  post<ChatMessage[]>(`/api/chat/messages/${messageId}/forward`, { toRoomIds })

export interface ChatSearchHit {
  messageId: string
  roomId: string
  roomName: string
  userName: string | null
  preview: string
  createdAt: string
}

/** Глобальный поиск по всем чатам, где человек участник. */
export const searchAllMessages = (q: string, limit = 30) =>
  get<ChatSearchHit[]>('/api/chat/search', { q, limit: String(limit) })

// ── сопряжение с заявками ──────────────────────────────────────────────────
/** Заявка из сообщения: создаётся через эко-канал Поддержки (стадия, SLA, аудит).
 * Объект не задан → объект чата → «Офис» по умолчанию (правило на сервере). */
export const ticketFromMessage = (messageId: string,
  body: { objectId?: string; title?: string; priority?: 'low' | 'medium' | 'high' }) =>
  post<{ ok: boolean; ticketId: string | null; ticketNumber: string | null }>(
    `/api/chat/messages/${messageId}/ticket`, body)

/** Чат заявки (скрытая группа): создаётся при первом обращении из её карточки. */
export const ensureTicketRoom = (ticketId: string) =>
  post<ChatRoomDetail>(`/api/chat/tickets/${ticketId}/room`, {})

// ── Web Push: уведомления при закрытой вкладке ─────────────────────────────
export const getVapidKey = () => get<{ key: string }>('/api/chat/push/vapid')

export const subscribePush = (sub: { endpoint: string; keys: { p256dh: string; auth: string }
                                     showPreview?: boolean }) =>
  post<{ ok: boolean }>('/api/chat/push/subscribe', sub)

export const unsubscribePush = (endpoint: string) =>
  post('/api/chat/push/unsubscribe', { endpoint, keys: {} })

/** «Кто это» по клику на человека: то, что о нём знает пространство. */
export interface ChatUserProfile {
  userId: string
  name: string
  email: string
  position?: string | null
  /** Уровень в организации: admin | user. */
  role?: string | null
  partyType?: PartyType
  organizationName?: string | null
  lastSeenAt?: string | null
  /** Фото человека (/api/files/<id>). */
  avatarUrl?: string | null
  /** Живёт в своей почте: в пространство не заходит, разговор идёт письмами. */
  mailOnly?: boolean
}

/** Своё имя и фото — то, что человек меняет о себе сам. */
export const updateMe = (body: { name?: string; avatarUrl?: string }) =>
  patch<{ ok: boolean; name: string; avatarUrl: string | null }>('/api/chat/me', body)

export const getUserProfile = (userId: string) =>
  get<ChatUserProfile>(`/api/chat/users/${userId}/profile`)

export const pinMessage = (roomId: string, messageId: string | null) =>
  post<{ roomId: string; pinnedMessage: ChatPinned | null }>(`/api/chat/rooms/${roomId}/pin`, { messageId })

// ── сообщения ──────────────────────────────────────────────────────────────
/** Страница ленты. `before` — ISO-время самого раннего показанного сообщения:
 *  сервер отдаёт то, что было ДО него (догрузка истории вверх). */
export const getMessages = (roomId: string, search?: string, before?: string) =>
  get<ChatMessage[]>(`/api/chat/rooms/${roomId}/messages`,
    search || before ? { ...(search ? { search } : {}), ...(before ? { before } : {}) } : undefined)

export const sendMessage = (roomId: string, payload: SendPayload) =>
  post<ChatMessage>(`/api/chat/rooms/${roomId}/messages`, payload)

export const editMessage = (roomId: string, messageId: string, content: string) =>
  patch<ChatMessage>(`/api/chat/rooms/${roomId}/messages/${messageId}`, { content })

export const deleteMessage = (roomId: string, messageId: string) =>
  del<{ ok: boolean }>(`/api/chat/rooms/${roomId}/messages/${messageId}`)

export const reactMessage = (roomId: string, messageId: string, emoji: string) =>
  post<{ messageId: string; reactions: ChatReaction[] }>(
    `/api/chat/rooms/${roomId}/messages/${messageId}/react`, { emoji })

export const markRead = (roomId: string) =>
  post<{ ok: boolean }>(`/api/chat/rooms/${roomId}/read`, {})

// ── папки (группировки) ────────────────────────────────────────────────────
export const getFolders = () => get<ChatFolder[]>('/api/chat/folders')

export const createFolder = (name: string, roomIds: string[] = []) =>
  post<ChatFolder>('/api/chat/folders', { name, roomIds })

export const updateFolder = (folderId: string, name: string, roomIds: string[]) =>
  patch<ChatFolder>(`/api/chat/folders/${folderId}`, { name, roomIds })

export const deleteFolder = (folderId: string) =>
  del<{ ok: boolean }>(`/api/chat/folders/${folderId}`)

export const reorderFolders = (folderIds: string[]) =>
  post<{ ok: boolean }>('/api/chat/folders/reorder', { folderIds })

// ── прочее ─────────────────────────────────────────────────────────────────
export const searchUsers = (q: string) =>
  get<ChatUser[]>('/api/chat/users/search', { q })

export const getPresence = () =>
  get<ChatPresence[]>('/api/chat/presence')

/**
 * Загрузить вложение чата. Файл кладём в компанию чата (companyId — дефолтная
 * компания пользователя), чтобы все участники получили доступ через /api/files.
 * Возвращает fileUrl для сообщения (относительный путь GET-эндпоинта).
 */
export async function uploadAttachment(
  file: File, companyId?: string | null,
): Promise<{ fileUrl: string; fileName: string; fileSize: number }> {
  const fd = new FormData()
  fd.append('file', file)
  const q = companyId ? `?company_id=${encodeURIComponent(companyId)}` : ''
  const res = await upload<{ source_id: string }>(`/api/intake${q}`, fd)
  return { fileUrl: `/api/files/${res.source_id}`, fileName: file.name, fileSize: file.size }
}
