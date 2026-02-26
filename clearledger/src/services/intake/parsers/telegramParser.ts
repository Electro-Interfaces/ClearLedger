/**
 * Telegram Chat Parser — извлечение данных из экспорта чата (result.json).
 *
 * Telegram Desktop экспортирует чат как JSON:
 * {
 *   name: "Имя чата",
 *   type: "personal_chat" | "private_group" | "private_supergroup",
 *   messages: [{ id, type, date, from, text, ... }]
 * }
 *
 * text может быть строкой или массивом объектов:
 *   "простой текст"
 *   [{ type: "text_link", text: "...", href: "..." }, "обычный текст"]
 */

import type { ExtractResult } from '../extract'

interface TelegramMessage {
  date: string
  sender: string
  text: string
  type: string
  hasMedia: boolean
  mediaType?: string
}

export interface TelegramParseResult extends ExtractResult {
  messages: TelegramMessage[]
}

interface TgRawMessage {
  id?: number
  type?: string
  date?: string
  date_unixtime?: string
  from?: string
  from_id?: string
  text?: string | TgTextEntity[]
  text_entities?: TgTextEntity[]
  photo?: string
  file?: string
  media_type?: string
  mime_type?: string
  forwarded_from?: string
  reply_to_message_id?: number
}

interface TgTextEntity {
  type?: string
  text?: string
  href?: string
}

interface TgExport {
  name?: string
  type?: string
  id?: number
  messages?: TgRawMessage[]
}

export async function parseTelegram(file: File): Promise<TelegramParseResult> {
  const raw = await file.text()
  let data: TgExport

  try {
    data = JSON.parse(raw) as TgExport
  } catch {
    return {
      text: raw,
      metadata: { _extractError: 'Не удалось разобрать Telegram JSON' },
      messages: [],
    }
  }

  // Проверяем что это Telegram export
  if (!data.messages || !Array.isArray(data.messages)) {
    return {
      text: raw.slice(0, 5000),
      metadata: { _extractError: 'JSON не содержит массив messages (не Telegram export)' },
      messages: [],
    }
  }

  const messages: TelegramMessage[] = []

  for (const msg of data.messages) {
    if (msg.type === 'service') continue // пропускаем системные

    const text = extractText(msg.text)
    if (!text && !msg.photo && !msg.file) continue

    const hasMedia = !!(msg.photo || msg.file || msg.media_type)

    messages.push({
      date: msg.date ?? '',
      sender: msg.from ?? msg.from_id ?? '',
      text: text || (hasMedia ? `[${msg.media_type ?? 'media'}]` : ''),
      type: msg.type ?? 'message',
      hasMedia,
      mediaType: msg.media_type ?? msg.mime_type,
    })
  }

  // Метаданные
  const metadata: Record<string, string> = {}
  const senders = [...new Set(messages.map((m) => m.sender).filter(Boolean))]
  metadata['_chat.type'] = 'telegram'
  metadata['_chat.name'] = data.name ?? ''
  metadata['_chat.chatType'] = data.type ?? ''
  metadata['_chat.participants'] = senders.join(', ')
  metadata['_chat.participantCount'] = String(senders.length)
  metadata['_chat.messageCount'] = String(messages.length)

  if (messages.length > 0) {
    metadata['_chat.dateFrom'] = messages[0].date
    metadata['_chat.dateTo'] = messages[messages.length - 1].date
  }

  const mediaMessages = messages.filter((m) => m.hasMedia)
  if (mediaMessages.length > 0) {
    metadata['_chat.mediaCount'] = String(mediaMessages.length)
  }

  // Собираем текст для classify
  const textParts: string[] = []
  textParts.push(`Чат Telegram: ${data.name ?? 'без имени'}`)
  textParts.push(`${senders.length} участников, ${messages.length} сообщений`)
  if (metadata['_chat.dateFrom']) {
    textParts.push(`Период: ${metadata['_chat.dateFrom']} — ${metadata['_chat.dateTo']}`)
  }
  textParts.push(`Участники: ${senders.join(', ')}`)
  textParts.push('')

  // Последние 100 сообщений
  const recentMessages = messages.slice(-100)
  for (const msg of recentMessages) {
    const dateStr = msg.date ? `[${msg.date}]` : ''
    textParts.push(`${dateStr} ${msg.sender}: ${msg.text}`)
  }

  if (messages.length > 100) {
    textParts.unshift(`... ещё ${messages.length - 100} сообщений выше`)
  }

  return {
    text: textParts.join('\n'),
    metadata,
    messages,
  }
}

/** Извлечь текст из Telegram text field (строка или массив объектов) */
function extractText(text: string | TgTextEntity[] | undefined): string {
  if (!text) return ''
  if (typeof text === 'string') return text

  return text
    .map((entity) => {
      if (typeof entity === 'string') return entity
      return entity.text ?? ''
    })
    .join('')
}
