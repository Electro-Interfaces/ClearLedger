/**
 * WhatsApp Chat Parser — извлечение данных из экспорта чата (.txt).
 *
 * Форматы строк:
 *   [DD.MM.YYYY, HH:MM:SS] Имя: текст
 *   DD.MM.YYYY, HH:MM - Имя: текст
 *   DD/MM/YYYY, HH:MM - Имя: текст
 *
 * Системные сообщения (без двоеточия после имени) — пропускаются.
 * Вложения: «<Медиа отсутствует>», «image omitted», имя_файла.pdf (attached)
 */

import type { ExtractResult } from '../extract'

interface ChatMessage {
  date: string
  time: string
  sender: string
  text: string
}

export interface WhatsAppParseResult extends ExtractResult {
  messages: ChatMessage[]
}

// Паттерны начала строки WhatsApp (разные локали)
const LINE_PATTERNS = [
  // [12.01.2024, 14:30:45] Имя Фамилия: текст
  /^\[(\d{1,2}\.\d{1,2}\.\d{2,4}),\s*(\d{1,2}:\d{2}(?::\d{2})?)\]\s+([^:]+?):\s(.+)/,
  // 12.01.2024, 14:30 - Имя Фамилия: текст
  /^(\d{1,2}[.\/]\d{1,2}[.\/]\d{2,4}),?\s*(\d{1,2}:\d{2}(?::\d{2})?)\s*[-–]\s*([^:]+?):\s(.+)/,
]

// Системные сообщения (без sender: text)
const SYSTEM_LINE = /^(?:\[?\d{1,2}[.\/]\d{1,2}[.\/]\d{2,4})/

// Вложения
const ATTACHMENT_PATTERNS = [
  /<Медиа отсутствует>/i,
  /\(file attached\)/i,
  /image omitted/i,
  /video omitted/i,
  /audio omitted/i,
  /document omitted/i,
  /sticker omitted/i,
  /\.(pdf|jpg|jpeg|png|doc|docx|xls|xlsx)\s*\(file attached\)/i,
]

export async function parseWhatsApp(file: File): Promise<WhatsAppParseResult> {
  const raw = await file.text()
  const lines = raw.split(/\r?\n/)

  const messages: ChatMessage[] = []
  let currentMsg: ChatMessage | null = null

  for (const line of lines) {
    let matched = false

    for (const pattern of LINE_PATTERNS) {
      const m = line.match(pattern)
      if (m) {
        // Сохраняем предыдущее сообщение
        if (currentMsg) messages.push(currentMsg)
        currentMsg = {
          date: m[1],
          time: m[2],
          sender: m[3].trim(),
          text: m[4],
        }
        matched = true
        break
      }
    }

    if (!matched && currentMsg) {
      // Продолжение многострочного сообщения
      if (line.trim() && !SYSTEM_LINE.test(line)) {
        currentMsg.text += '\n' + line
      }
    }
  }
  if (currentMsg) messages.push(currentMsg)

  // Метаданные
  const metadata: Record<string, string> = {}
  const senders = [...new Set(messages.map((m) => m.sender))]
  metadata['_chat.type'] = 'whatsapp'
  metadata['_chat.participants'] = senders.join(', ')
  metadata['_chat.participantCount'] = String(senders.length)
  metadata['_chat.messageCount'] = String(messages.length)

  if (messages.length > 0) {
    metadata['_chat.dateFrom'] = messages[0].date
    metadata['_chat.dateTo'] = messages[messages.length - 1].date
  }

  // Считаем вложения
  let attachmentCount = 0
  const attachmentNames: string[] = []
  for (const msg of messages) {
    for (const pattern of ATTACHMENT_PATTERNS) {
      if (pattern.test(msg.text)) {
        attachmentCount++
        const fileMatch = msg.text.match(/([^\s<>]+\.\w{2,5})\s*\(file attached\)/i)
        if (fileMatch) attachmentNames.push(fileMatch[1])
        break
      }
    }
  }
  if (attachmentCount > 0) {
    metadata['_chat.attachments'] = String(attachmentCount)
    if (attachmentNames.length > 0) {
      metadata['_chat.attachmentNames'] = attachmentNames.join(', ')
    }
  }

  // Собираем текст для classify
  const textParts: string[] = []
  textParts.push(`Чат WhatsApp: ${senders.length} участников, ${messages.length} сообщений`)
  if (metadata['_chat.dateFrom']) {
    textParts.push(`Период: ${metadata['_chat.dateFrom']} — ${metadata['_chat.dateTo']}`)
  }
  textParts.push(`Участники: ${senders.join(', ')}`)
  textParts.push('')

  // Последние 100 сообщений (для classify)
  const recentMessages = messages.slice(-100)
  for (const msg of recentMessages) {
    textParts.push(`[${msg.date} ${msg.time}] ${msg.sender}: ${msg.text}`)
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
