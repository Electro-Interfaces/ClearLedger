/**
 * Клиент управления чатами пространства (`/api/chat/admin/*`) — приложение «Чаты».
 *
 * Отдельно от `chatService`: тот отвечает на «мои разговоры» (комнаты, где человек
 * участник), эти ручки — на «что происходит в пространстве»: все каналы и группы,
 * владельцы, состав, где сидят люди партнёров, что заброшено. Бэкенд пускает сюда
 * только администраторов пространства.
 */
import { get, patch, post, del } from './apiClient'

export interface AdminRoom {
  id: string
  type: 'company' | 'channel' | 'group' | 'direct'
  /** Системный вид: general | news | platform | app:<код приложения>; null — обычный чат. */
  kind: string | null
  name: string | null
  /** Приложение, к которому привязан чат; null — чат всего пространства. */
  scopeProduct: string | null
  isArchived: boolean
  ownerName: string | null
  participantCount: number
  /** Сколько в чате людей компаний-партнёров. */
  externalCount: number
  messageCount: number
  lastMessageAt: string | null
  createdAt: string | null
}

export interface RoomPatch {
  name?: string
  /** Пустая строка снимает привязку к приложению. */
  scopeProduct?: string
}

export const getRooms = (archived = false) =>
  get<AdminRoom[]>('/api/chat/admin/rooms', { archived: String(archived) })

export const patchRoom = (roomId: string, body: RoomPatch) =>
  patch<AdminRoom>(`/api/chat/admin/rooms/${roomId}`, body)

/** Роль в чате: owner (владелец, один на чат), admin (пишет в канал), member. */
export const setRole = (roomId: string, userId: string, role: string) =>
  patch<void>(`/api/chat/admin/rooms/${roomId}/participants/${userId}`, { role })

export const removeParticipant = (roomId: string, userId: string) =>
  del<void>(`/api/chat/admin/rooms/${roomId}/participants/${userId}`)

/** Добавить человека в чат (ручка общая с панелью переписки). */
export const addParticipant = (roomId: string, userId: string) =>
  post<void>(`/api/chat/rooms/${roomId}/participants`, { userId })

/** Человек пространства — для выбора владельца и состава. */
export interface SpacePerson {
  userId: string
  name: string
  email: string | null
  /** Сотрудник компании-партнёра: в пространстве по членству, компания другая. */
  isExternal: boolean
  companyName: string | null
  /** vendor — разработчик платформы, internal — свой, partner — сторонний. */
  partyType?: 'vendor' | 'internal' | 'partner'
}

export const getPeople = () => get<SpacePerson[]>('/api/chat/admin/people')

export interface CreateRoomBody {
  type: 'channel' | 'group'
  name: string
  /** Кто ведёт чат; не задан — создатель. */
  ownerId?: string
  participantIds?: string[]
  /** Заселить всех людей пространства (канал новостей, общая группа). */
  everyone?: boolean
  scopeProduct?: string
}

export const createRoom = (body: CreateRoomBody) =>
  post<AdminRoom>('/api/chat/admin/rooms', body)

/** Добрать состав списком — на канал в тридцать человек по одному запросу не набирают. */
export const addPeople = (roomId: string, body: { userIds?: string[]; everyone?: boolean }) =>
  post<void>(`/api/chat/admin/rooms/${roomId}/participants`, body)
