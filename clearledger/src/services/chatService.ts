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
  kind: 'general' | 'news' | null
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
  /** Приложение, к которому привязан чат; null — чат всего пространства. */
  scopeProduct?: string | null
}

/** Кто это в пространстве: инженер разработчика платформы, свой сотрудник, партнёр. */
export type PartyType = 'vendor' | 'internal' | 'partner'

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
}

export interface ChatUser { userId: string; name: string; email: string; online: boolean }
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
export const getRooms = (archived = false, product?: string | null) =>
  get<ChatRoom[]>('/api/chat/rooms', {
    archived: String(archived),
    ...(product ? { product } : {}),
  })

export const getRoom = (roomId: string) =>
  get<ChatRoomDetail>(`/api/chat/rooms/${roomId}`)

export const createRoom = (
  type: 'direct' | 'group' | 'channel',
  participantIds: string[],
  name?: string,
  scopeProduct?: string | null,
) =>
  post<ChatRoomDetail>('/api/chat/rooms', { type, participantIds, name, scopeProduct })

export const archiveRoom = (roomId: string) =>
  post<{ ok: boolean; isArchived: boolean }>(`/api/chat/rooms/${roomId}/archive`, {})

export const unarchiveRoom = (roomId: string) =>
  post<{ ok: boolean; isArchived: boolean }>(`/api/chat/rooms/${roomId}/unarchive`, {})

export const addParticipant = (roomId: string, userId: string) =>
  post<{ ok: boolean }>(`/api/chat/rooms/${roomId}/participants`, { userId })

export const pinMessage = (roomId: string, messageId: string | null) =>
  post<{ roomId: string; pinnedMessage: ChatPinned | null }>(`/api/chat/rooms/${roomId}/pin`, { messageId })

// ── сообщения ──────────────────────────────────────────────────────────────
export const getMessages = (roomId: string, search?: string) =>
  get<ChatMessage[]>(`/api/chat/rooms/${roomId}/messages`, search ? { search } : undefined)

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
