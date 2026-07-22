// Типы чата экосистемы (Matrix) — без зависимости от matrix-js-sdk, для любого UI-кода.
// Плоская модель Ангара + ТЕМЫ (Matrix threads): у сообщения может быть thread_root_id.

export interface ChatRoom {
  id: string
  type: 'direct' | 'group' | 'channel'
  name?: string
  unread_count: number
  last_message?: string
  last_message_at?: string
  last_message_by?: string
  created_at: string
  updated_at: string
  readonly?: boolean
  pinned?: boolean
  isPublic?: boolean
  participants?: ChatParticipant[]
}

export interface ChatParticipant {
  id: string
  user_id: string
  name: string
  avatar_url?: string
  power?: number
}

export interface ChatMessage {
  id: string
  room_id: string
  user_id: string
  user_name: string
  type: 'text' | 'image' | 'video' | 'file'
  content: string
  file_url?: string
  file_name?: string
  file_size?: number
  file_mime?: string
  reply_to?: string
  reply_to_content?: string
  reply_to_user?: string
  reactions?: { key: string; count: number; mine: boolean }[]
  is_edited: boolean
  is_deleted?: boolean
  read?: boolean
  read_count?: number
  pending?: boolean
  created_at: string
  // ── темы (Matrix threads) ──
  thread_root_id?: string    // сообщение принадлежит теме с этим корнем
  thread_reply_count?: number // для корня темы: сколько ответов
  thread_latest_at?: string
}

/** Тема (тред) внутри комнаты — корневое сообщение + агрегаты. */
export interface ChatThread {
  root_id: string
  root_preview: string
  root_user_name: string
  reply_count: number
  latest_at?: string
}

/** Сессия Matrix для браузера (с backend /api/mchat/session). */
export interface ChatSession {
  homeserver: string
  userId: string
  accessToken: string
}
