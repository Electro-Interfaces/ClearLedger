/**
 * DETECT — определение типа входного файла по MIME, расширению и содержимому.
 */

import type { IntakeFileType } from '@/types'

const EXT_MAP: Record<string, IntakeFileType> = {
  pdf: 'pdf',
  jpg: 'image', jpeg: 'image', png: 'image', tiff: 'image', tif: 'image', webp: 'image', bmp: 'image',
  xlsx: 'excel', xls: 'excel',
  csv: 'csv',
  xml: 'xml',
  eml: 'email', msg: 'email',
  txt: 'text',
  json: 'json',
  dbf: 'dbf',
  doc: 'word', docx: 'word',
}

const MIME_MAP: Record<string, IntakeFileType> = {
  'application/pdf': 'pdf',
  'image/jpeg': 'image',
  'image/png': 'image',
  'image/tiff': 'image',
  'image/webp': 'image',
  'image/bmp': 'image',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'excel',
  'application/vnd.ms-excel': 'excel',
  'text/csv': 'csv',
  'application/xml': 'xml',
  'text/xml': 'xml',
  'message/rfc822': 'email',
  'application/vnd.ms-outlook': 'email',
  'text/plain': 'text',
  'application/json': 'json',
  'application/msword': 'word',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'word',
}

/** WhatsApp chat line patterns */
const WHATSAPP_LINE = /^\[?\d{1,2}[.\/]\d{1,2}[.\/]\d{2,4},?\s*\d{1,2}:\d{2}/m

/** Определяет тип файла по MIME и/или расширению */
export function detectFileType(file: File): IntakeFileType {
  // Сначала по расширению — более надёжно
  const ext = file.name.split('.').pop()?.toLowerCase() ?? ''
  if (EXT_MAP[ext]) return EXT_MAP[ext]

  // Потом по MIME
  if (file.type && MIME_MAP[file.type]) return MIME_MAP[file.type]

  return 'unknown'
}

/**
 * Уточняет тип файла по содержимому для неоднозначных форматов.
 * Вызывается после detectFileType для .txt и .json файлов.
 */
export async function refineFileType(file: File, baseType: IntakeFileType): Promise<IntakeFileType> {
  // JSON → проверяем Telegram export
  if (baseType === 'json') {
    try {
      const head = await readHead(file, 2000)
      // Telegram export содержит "messages" массив и "type": "personal_chat"|"private_group"
      if (/"messages"\s*:/.test(head) && (/"type"\s*:\s*"(personal_chat|private_group|private_supergroup|public_supergroup|bot_chat|saved_messages)"/.test(head) || /"from"\s*:/.test(head))) {
        return 'telegram'
      }
    } catch { /* fallback to json */ }
    return 'json'
  }

  // TXT → проверяем WhatsApp export
  if (baseType === 'text') {
    try {
      const head = await readHead(file, 2000)
      // WhatsApp: минимум 3 строки с timestamp-паттерном
      const lines = head.split('\n')
      let matchCount = 0
      for (const line of lines.slice(0, 20)) {
        if (WHATSAPP_LINE.test(line)) matchCount++
        if (matchCount >= 3) return 'whatsapp'
      }
    } catch { /* fallback to text */ }
    return 'text'
  }

  return baseType
}

/** Определяет тип вставленного текста */
export function detectPasteType(text: string): 'email' | 'chat' | 'freetext' {
  // Email: наличие заголовков From: / Subject: / Date:
  const emailHeaders = /^(From|Subject|Date|To|Cc):\s/m
  if (emailHeaders.test(text)) return 'email'

  // WhatsApp / Telegram chat format: timestamp + sender
  if (WHATSAPP_LINE.test(text)) return 'chat'

  return 'freetext'
}

/** Читает первые N байт файла как текст */
async function readHead(file: File, bytes: number): Promise<string> {
  const slice = file.slice(0, bytes)
  return slice.text()
}
